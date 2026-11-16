"""Dwuetapowy koordynator analizy wsadowej: wątki I/O (Queue+Lock) oraz procesy CPU (spawn)."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
import multiprocessing
import os
from pathlib import Path
import queue
import threading
import time
from typing import Sequence

from kaucjomat.batch_cpu import (
    ChunkAnalysisResult,
    analyze_record_chunk,
    merge_chunk_results,
)
from kaucjomat.batch_format import (
    batch_report_to_dict as batch_report_to_dict,
    format_batch_analysis_report as format_batch_analysis_report,
    format_batch_generation_report as format_batch_generation_report,
)
from kaucjomat.batch_generator import generate_batch_log_dataset
from kaucjomat.batch_patterns import (
    BatchChunkIterator,
    BatchLogFileStats,
    BatchLogRecord,
    stream_valid_log_records,
)
from kaucjomat.config import get_default_log_dir
from kaucjomat.exceptions import BatchLogAnalysisError, InvalidConfigurationError
from kaucjomat.logging_config import get_logger

_LOGGER = get_logger("kaucjomat.batch")


@dataclass(frozen=True, slots=True)
class StageOneIoResult:
    """Wynik Etapu 1: wielowątkowego odczytu i porcjowania plików logów."""

    files_processed: int
    total_chunks: int
    valid_records: int
    invalid_lines: int
    io_workers: int
    io_elapsed_ms: float
    file_stats: tuple[BatchLogFileStats, ...]
    chunks: tuple[tuple[BatchLogRecord, ...], ...]


@dataclass(frozen=True, slots=True)
class StageTwoCpuResult:
    """Wynik Etapu 2: deterministycznych obliczeń CPU-bound na porcjach rekordów."""

    execution_mode: str
    cpu_workers: int
    work_iterations: int
    cpu_elapsed_ms: float
    metrics: ChunkAnalysisResult


@dataclass(frozen=True, slots=True)
class BatchAnalysisReport:
    """Pełny raport z dwuetapowej analizy wsadowej w trybie DEMO."""

    mode_label: str
    cpu_count: int
    log_dir: Path
    auto_generated: bool
    stage_one_io: StageOneIoResult
    stage_two_cpu: StageTwoCpuResult
    total_elapsed_ms: float


def _validate_positive_int(value: int | None, name: str) -> None:
    """Weryfikuje, czy opcjonalna liczba całkowita jest ściśle dodatnia."""
    if value is not None and value <= 0:
        raise InvalidConfigurationError(f"Parametr {name} musi być większy od zera.")


def read_and_chunk_logs_threaded(
    log_dir: Path,
    *,
    chunk_size: int = 1000,
    io_workers: int | None = None,
) -> StageOneIoResult:
    """Etap 1 (I/O): współbieżnie czyta i porcuje pliki *.log z użyciem Queue i Lock."""
    _validate_positive_int(chunk_size, "chunk_size")
    _validate_positive_int(io_workers, "io_workers")

    if not log_dir.exists() or not log_dir.is_dir():
        raise BatchLogAnalysisError(f"Katalog logów wsadowych nie istnieje: {log_dir}")

    log_files = sorted(path for path in log_dir.glob("*.log") if path.is_file())
    if not log_files:
        raise BatchLogAnalysisError(
            f"Brak plików *.log do analizy w katalogu: {log_dir}"
        )

    cpu_total = os.cpu_count() or 2
    default_io = min(8, max(2, cpu_total))
    resolved_io_workers = io_workers if io_workers is not None else min(default_io, len(log_files))

    chunk_queue: queue.Queue[tuple[int, int, tuple[BatchLogRecord, ...]]] = queue.Queue()
    stats_lock = threading.Lock()
    indexed_stats: list[tuple[int, BatchLogFileStats]] = []
    totals = [0, 0]  # [valid_records, invalid_lines]

    def _process_single_file(file_idx: int, file_path: Path) -> None:
        """Odczytuje jeden plik strumieniowo, kolejkuje porcje i aktualizuje statystyki."""
        invalid_counter = [0]
        file_valid = 0
        iterator = BatchChunkIterator(
            stream_valid_log_records(file_path, invalid_counter),
            chunk_size=chunk_size,
        )
        for chunk_idx, chunk in enumerate(iterator):
            file_valid += len(chunk)
            chunk_queue.put((file_idx, chunk_idx, chunk))

        file_stat = BatchLogFileStats(
            file_name=file_path.name,
            valid_records=file_valid,
            invalid_lines=invalid_counter[0],
        )
        # Sekcja krytyczna chroni współdzieloną listę statystyk oraz sumaryczne liczniki.
        with stats_lock:
            indexed_stats.append((file_idx, file_stat))
            totals[0] += file_valid
            totals[1] += invalid_counter[0]

    started_at = time.perf_counter()
    with ThreadPoolExecutor(max_workers=resolved_io_workers) as executor:
        futures = [
            executor.submit(_process_single_file, idx, path)
            for idx, path in enumerate(log_files)
        ]
        for future in futures:
            future.result()

    collected_chunks: list[tuple[int, int, tuple[BatchLogRecord, ...]]] = []
    while not chunk_queue.empty():
        collected_chunks.append(chunk_queue.get_nowait())

    # Deterministyczne sortowanie porcji i statystyk po indeksie pliku i porcji.
    collected_chunks.sort(key=lambda item: (item[0], item[1]))
    indexed_stats.sort(key=lambda item: item[0])
    elapsed_ms = (time.perf_counter() - started_at) * 1000.0

    return StageOneIoResult(
        files_processed=len(log_files),
        total_chunks=len(collected_chunks),
        valid_records=totals[0],
        invalid_lines=totals[1],
        io_workers=resolved_io_workers,
        io_elapsed_ms=round(elapsed_ms, 3),
        file_stats=tuple(stat for _, stat in indexed_stats),
        chunks=tuple(chunk for _, _, chunk in collected_chunks),
    )


def compute_analytics_sequential(
    chunks: Sequence[tuple[BatchLogRecord, ...]],
    *,
    work_iterations: int = 200,
) -> StageTwoCpuResult:
    """Etap 2 (CPU sekwencyjnie): oblicza metryki i sumę kontrolną w jednym procesie."""
    _validate_positive_int(work_iterations, "work_iterations")
    started_at = time.perf_counter()
    partial_results = [
        analyze_record_chunk(chunk, work_iterations=work_iterations)
        for chunk in chunks
    ]
    merged = merge_chunk_results(partial_results)
    elapsed_ms = (time.perf_counter() - started_at) * 1000.0
    return StageTwoCpuResult(
        execution_mode="sequential",
        cpu_workers=1,
        work_iterations=work_iterations,
        cpu_elapsed_ms=round(elapsed_ms, 3),
        metrics=merged,
    )


def compute_analytics_multiprocess(
    chunks: Sequence[tuple[BatchLogRecord, ...]],
    *,
    cpu_workers: int | None = None,
    work_iterations: int = 200,
) -> StageTwoCpuResult:
    """Etap 2 (CPU wieloprocesowo): przetwarza porcje równolegle w kontekście spawn."""
    _validate_positive_int(cpu_workers, "cpu_workers")
    _validate_positive_int(work_iterations, "work_iterations")

    resolved_cpu_workers = cpu_workers if cpu_workers is not None else (os.cpu_count() or 1)
    started_at = time.perf_counter()
    if not chunks:
        merged = merge_chunk_results(())
    else:
        mp_ctx = multiprocessing.get_context("spawn")
        worker_fn = partial(analyze_record_chunk, work_iterations=work_iterations)
        with ProcessPoolExecutor(
            max_workers=resolved_cpu_workers,
            mp_context=mp_ctx,
        ) as executor:
            partial_results = list(executor.map(worker_fn, chunks))
        merged = merge_chunk_results(partial_results)

    elapsed_ms = (time.perf_counter() - started_at) * 1000.0
    return StageTwoCpuResult(
        execution_mode="multiprocess_spawn",
        cpu_workers=resolved_cpu_workers,
        work_iterations=work_iterations,
        cpu_elapsed_ms=round(elapsed_ms, 3),
        metrics=merged,
    )


def run_two_stage_batch_analysis(
    log_dir: Path | None = None,
    *,
    chunk_size: int = 1000,
    io_workers: int | None = None,
    cpu_workers: int | None = None,
    work_iterations: int = 200,
    auto_generate: bool = True,
) -> BatchAnalysisReport:
    """Uruchamia pełny dwuetapowy potok analizy wsadowej (wątki I/O + procesy CPU)."""
    _validate_positive_int(chunk_size, "chunk_size")
    _validate_positive_int(io_workers, "io_workers")
    _validate_positive_int(cpu_workers, "cpu_workers")
    _validate_positive_int(work_iterations, "work_iterations")

    target_dir = log_dir if log_dir is not None else get_default_log_dir()
    started_at = time.perf_counter()
    auto_generated = False

    has_logs = target_dir.exists() and any(target_dir.glob("*.log"))
    if not has_logs and auto_generate:
        _LOGGER.info("Brak plików *.log w %s — generuję zbiór DEMO.", target_dir)
        generate_batch_log_dataset(target_dir)
        auto_generated = True

    stage_one = read_and_chunk_logs_threaded(
        target_dir,
        chunk_size=chunk_size,
        io_workers=io_workers,
    )
    stage_two = compute_analytics_multiprocess(
        stage_one.chunks,
        cpu_workers=cpu_workers,
        work_iterations=work_iterations,
    )
    total_ms = round((time.perf_counter() - started_at) * 1000.0, 3)

    _LOGGER.info(
        "Analiza wsadowa DEMO zakończona: pliki=%d, rekordy=%d, I/O=%.2f ms, CPU=%.2f ms, checksum=%s",
        stage_one.files_processed,
        stage_one.valid_records,
        stage_one.io_elapsed_ms,
        stage_two.cpu_elapsed_ms,
        hex(stage_two.metrics.audit_checksum),
    )
    return BatchAnalysisReport(
        mode_label="DEMO",
        cpu_count=os.cpu_count() or 1,
        log_dir=target_dir,
        auto_generated=auto_generated,
        stage_one_io=stage_one,
        stage_two_cpu=stage_two,
        total_elapsed_ms=total_ms,
    )
