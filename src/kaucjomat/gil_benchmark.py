"""Silnik porównawczego benchmarku GIL (sekwencyjnie vs wątki vs procesy spawn)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
import os
from pathlib import Path
import platform
import statistics
import sys
import sysconfig
import time

from kaucjomat.batch_cpu import ChunkAnalysisResult, analyze_record_chunk, merge_chunk_results
from kaucjomat.batch_generator import generate_batch_log_dataset
from kaucjomat.batch_patterns import BatchLogRecord
from kaucjomat.batch_runner import (
    StageOneIoResult, StageTwoCpuResult, compute_analytics_multiprocess,
    compute_analytics_sequential, read_and_chunk_logs_threaded,
)
from kaucjomat.config import get_default_log_dir
from kaucjomat.gil_conclusions import build_conclusions
from kaucjomat.exceptions import BatchLogAnalysisError, GilBenchmarkError, InvalidConfigurationError
from kaucjomat.logging_config import get_logger

_LOGGER = get_logger("kaucjomat.batch")
_STRATEGY_ORDER: tuple[str, ...] = ("sequential", "threads", "processes_spawn")

# Callback postępu: (liczba wykonanych przebiegów, liczba wszystkich przebiegów, strategy_id).
ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True, slots=True)
class GilEnvironmentInfo:
    """Diagnostyka interpretera Pythona, stanu blokady GIL oraz liczby rdzeni CPU."""

    python_version: str
    implementation: str
    platform_summary: str
    cpu_count: int
    gil_enabled: bool
    free_threading_build: bool
    switch_interval_s: float


@dataclass(frozen=True, slots=True)
class BenchmarkStrategyResult:
    """Zestawienie czasów i przyspieszenia dla pojedynczej strategii wykonania CPU."""

    strategy_id: str
    strategy_label: str
    workers: int
    repeats: int
    runs_ms: tuple[float, ...]
    median_ms: float
    mean_ms: float
    min_ms: float
    max_ms: float
    speedup_vs_sequential: float
    relative_to_sequential_pct: float


@dataclass(frozen=True, slots=True)
class GilBenchmarkReport:
    """Kompletny raport z porównawczego benchmarku GIL w trybie DEMO."""

    mode_label: str
    generated_at_iso: str
    log_dir: Path
    auto_generated: bool
    environment: GilEnvironmentInfo
    files_processed: int
    total_chunks: int
    valid_records: int
    invalid_lines: int
    chunk_size: int
    work_iterations: int
    repeats: int
    workers: int
    io_elapsed_ms: float
    total_benchmark_elapsed_ms: float
    strategies: tuple[BenchmarkStrategyResult, ...]
    verified_metrics: ChunkAnalysisResult
    fastest_strategy_id: str
    single_core_warning: str | None
    conclusions: tuple[str, ...]
    json_artifact_path: Path | None = None
    chart_artifact_path: Path | None = None


def _validate_positive_int(value: int | None, name: str, *, allow_none: bool = False) -> None:
    """Weryfikuje, czy parametr liczbowy jest dodatnią liczbą całkowitą (bez bool)."""
    if value is None:
        if allow_none:
            return
        raise InvalidConfigurationError(f"Parametr {name} musi być większy od zera.")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidConfigurationError(
            f"Parametr {name} musi być dodatnią liczbą całkowitą większą od zera."
        )


def _resolve_worker_count(workers: int | None, cpu_count: int) -> int:
    """Wyznacza spójną liczbę pracowników dla wątków oraz procesów benchmarku."""
    return workers if workers is not None else min(8, max(2, cpu_count))


def collect_gil_environment_info() -> GilEnvironmentInfo:
    """Zbiera parametry interpretera Pythona, stan blokady GIL oraz liczbę rdzeni CPU."""
    gil_check = getattr(sys, "_is_gil_enabled", None)
    return GilEnvironmentInfo(
        python_version=platform.python_version(),
        implementation=platform.python_implementation(),
        platform_summary=f"{platform.system()} {platform.release()} ({platform.machine()})",
        cpu_count=os.cpu_count() or 1,
        gil_enabled=bool(gil_check()) if callable(gil_check) else True,
        free_threading_build=bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
        switch_interval_s=round(float(sys.getswitchinterval()), 6),
    )


def compute_analytics_threaded(
    chunks: Sequence[tuple[BatchLogRecord, ...]], *,
    cpu_workers: int | None = None, work_iterations: int = 30,
) -> StageTwoCpuResult:
    """Wykonuje obliczenia CPU-bound na puli wątków (podlegającej blokadzie GIL)."""
    _validate_positive_int(cpu_workers, "cpu_workers", allow_none=True)
    _validate_positive_int(work_iterations, "work_iterations")
    resolved_workers = _resolve_worker_count(cpu_workers, os.cpu_count() or 1)
    started_at = time.perf_counter()
    if not chunks:
        merged = merge_chunk_results(())
    else:
        worker_fn = partial(analyze_record_chunk, work_iterations=work_iterations)
        with ThreadPoolExecutor(max_workers=resolved_workers) as executor:
            merged = merge_chunk_results(list(executor.map(worker_fn, chunks)))
    elapsed_ms = round((time.perf_counter() - started_at) * 1000.0, 3)
    return StageTwoCpuResult(
        execution_mode="threads_gil", cpu_workers=resolved_workers,
        work_iterations=work_iterations, cpu_elapsed_ms=elapsed_ms, metrics=merged,
    )


def _prepare_benchmark_stage_one(
    target_dir: Path, *, chunk_size: int, io_workers: int | None, auto_generate: bool,
) -> tuple[StageOneIoResult, bool]:
    """Przygotowuje opcjonalny zbiór DEMO i jednokrotnie wczytuje porcje do pamięci."""
    auto_generated = False
    try:
        has_logs = target_dir.is_dir() and any(p.is_file() for p in target_dir.glob("*.log"))
    except OSError as exc:
        raise BatchLogAnalysisError(f"Nie można odczytać katalogu {target_dir}: {exc}") from exc
    if not has_logs and auto_generate:
        _LOGGER.info("Brak plików *.log w %s — generuję zbiór DEMO.", target_dir)
        generate_batch_log_dataset(target_dir)
        auto_generated = True
    stage_one = read_and_chunk_logs_threaded(
        target_dir, chunk_size=chunk_size, io_workers=io_workers
    )
    if not stage_one.chunks:
        raise GilBenchmarkError(f"Katalog {target_dir} nie zawiera poprawnych rekordów.")
    return stage_one, auto_generated


def _build_strategy_results(
    runs_by_strategy: dict[str, list[float]], labels: dict[str, str],
    worker_counts: dict[str, int], repeats: int,
) -> tuple[BenchmarkStrategyResult, ...]:
    """Oblicza mediany, średnie oraz przyspieszenie względem strategii sekwencyjnej."""
    seq_median = float(statistics.median(runs_by_strategy["sequential"]))
    results: list[BenchmarkStrategyResult] = []
    for strategy_id in _STRATEGY_ORDER:
        runs = runs_by_strategy[strategy_id]
        median_val = float(statistics.median(runs))
        # Zabezpieczenie przed dzieleniem przez 0.000 ms przy bardzo małych zbiorach testowych.
        speedup = 1.0 if strategy_id == "sequential" else round(seq_median / max(median_val, 0.001), 3)
        relative_pct = (
            100.0 if strategy_id == "sequential"
            else round((median_val / max(seq_median, 0.001)) * 100.0, 1)
        )
        results.append(BenchmarkStrategyResult(
            strategy_id=strategy_id, strategy_label=labels[strategy_id],
            workers=worker_counts[strategy_id], repeats=repeats,
            runs_ms=tuple(round(item, 3) for item in runs), median_ms=round(median_val, 3),
            mean_ms=round(float(statistics.fmean(runs)), 3),
            min_ms=round(min(runs), 3), max_ms=round(max(runs), 3),
            speedup_vs_sequential=speedup, relative_to_sequential_pct=relative_pct,
        ))
    return tuple(results)


def run_gil_benchmark(
    log_dir: Path | None = None, *, repeats: int = 3, workers: int | None = None,
    chunk_size: int = 1000, io_workers: int | None = None,
    work_iterations: int = 30, auto_generate: bool = True,
    on_progress: ProgressCallback | None = None,
) -> GilBenchmarkReport:
    """Przeprowadza porównawczy benchmark GIL dla strategii sekwencyjnej, wątkowej i spawn.

    Opcjonalny ``on_progress`` jest wołany po każdej parze powtórzenie × strategia.
    """
    for value, name, allow_none in (
        (repeats, "repeats", False), (workers, "workers", True),
        (chunk_size, "chunk_size", False), (io_workers, "io_workers", True),
        (work_iterations, "work_iterations", False),
    ):
        _validate_positive_int(value, name, allow_none=allow_none)

    env = collect_gil_environment_info()
    resolved_workers = _resolve_worker_count(workers, env.cpu_count)
    target_dir = log_dir if log_dir is not None else get_default_log_dir()
    started_at = time.perf_counter()
    stage_one, auto_generated = _prepare_benchmark_stage_one(
        target_dir, chunk_size=chunk_size, io_workers=io_workers, auto_generate=auto_generate,
    )

    # Jednolita tabela strategii gwarantuje identyczne dane wejściowe oraz pomiar poza I/O.
    runners: dict[str, tuple[str, int, Callable[[], StageTwoCpuResult]]] = {
        "sequential": ("Sekwencyjnie (1 wątek)", 1,
            partial(compute_analytics_sequential, stage_one.chunks, work_iterations=work_iterations)),
        "threads": (f"Wątki ({resolved_workers} wątków, GIL)", resolved_workers,
            partial(compute_analytics_threaded, stage_one.chunks, cpu_workers=resolved_workers, work_iterations=work_iterations)),
        "processes_spawn": (f"Procesy spawn ({resolved_workers} proc.)", resolved_workers,
            partial(compute_analytics_multiprocess, stage_one.chunks, cpu_workers=resolved_workers, work_iterations=work_iterations)),
    }
    runs_by_strategy: dict[str, list[float]] = {key: [] for key in _STRATEGY_ORDER}
    baseline_metrics: ChunkAnalysisResult | None = None
    total_runs = repeats * len(_STRATEGY_ORDER)
    done_runs = 0
    for repeat_idx in range(1, repeats + 1):
        for strategy_id in _STRATEGY_ORDER:
            try:
                result = runners[strategy_id][2]()
            except (BrokenProcessPool, OSError) as exc:
                raise GilBenchmarkError(f"Awaria strategii '{strategy_id}': {exc}") from exc
            # Równość pełnego ChunkAnalysisResult sprawdzamy poza stoperem każdej strategii.
            if baseline_metrics is None:
                baseline_metrics = result.metrics
            elif result.metrics != baseline_metrics:
                raise GilBenchmarkError(f"Niezgodność metryk w strategii '{strategy_id}' (próba {repeat_idx}).")
            runs_by_strategy[strategy_id].append(result.cpu_elapsed_ms)
            done_runs += 1
            if on_progress is not None:
                on_progress(done_runs, total_runs, strategy_id)

    assert baseline_metrics is not None
    labels = {key: spec[0] for key, spec in runners.items()}
    worker_counts = {key: spec[1] for key, spec in runners.items()}
    strategies = _build_strategy_results(runs_by_strategy, labels, worker_counts, repeats)
    fastest = min(strategies, key=lambda item: item.median_ms).strategy_id
    single_core_warning, conclusions = build_conclusions(env, strategies)
    total_ms = round((time.perf_counter() - started_at) * 1000.0, 3)

    _LOGGER.info(
        "Benchmark GIL DEMO zakończony: cpu=%d, gil=%s, rekordy=%d, porcje=%d, "
        "seq=%.2f ms, thr=%.2f ms, spawn=%.2f ms (speedup=%.2fx), checksum=%s",
        env.cpu_count, env.gil_enabled, stage_one.valid_records, stage_one.total_chunks,
        strategies[0].median_ms, strategies[1].median_ms, strategies[2].median_ms,
        strategies[2].speedup_vs_sequential, hex(baseline_metrics.audit_checksum),
    )
    return GilBenchmarkReport(
        mode_label="DEMO", generated_at_iso=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        log_dir=target_dir, auto_generated=auto_generated, environment=env,
        files_processed=stage_one.files_processed, total_chunks=stage_one.total_chunks,
        valid_records=stage_one.valid_records, invalid_lines=stage_one.invalid_lines,
        chunk_size=chunk_size, work_iterations=work_iterations, repeats=repeats,
        workers=resolved_workers, io_elapsed_ms=stage_one.io_elapsed_ms,
        total_benchmark_elapsed_ms=total_ms, strategies=strategies,
        verified_metrics=baseline_metrics, fastest_strategy_id=fastest,
        single_core_warning=single_core_warning, conclusions=conclusions,
    )
