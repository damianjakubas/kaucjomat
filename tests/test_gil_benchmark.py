"""Testy jednostkowe silnika benchmarku GIL i diagnostyki interpretera."""

from __future__ import annotations

from dataclasses import replace
import logging
from pathlib import Path

import pytest

from kaucjomat.batch_generator import generate_batch_log_dataset
from kaucjomat.batch_runner import (
    compute_analytics_multiprocess,
    compute_analytics_sequential,
    read_and_chunk_logs_threaded,
)
from kaucjomat.config import (
    BENCHMARK_CHART_PNG_NAME,
    BENCHMARK_RESULTS_JSON_NAME,
    REFERENCE_BENCHMARK_JSON_NAME,
    REFERENCE_BENCHMARK_PNG_NAME,
    get_default_benchmark_output_dir,
    get_reference_benchmark_dir,
)
from kaucjomat.exceptions import (
    BatchLogAnalysisError,
    GilBenchmarkError,
    InvalidConfigurationError,
)
from kaucjomat.gil_benchmark import (
    collect_gil_environment_info,
    compute_analytics_threaded,
    run_gil_benchmark,
)


def _create_small_dataset(log_dir: Path) -> None:
    """Tworzy niewielki deterministyczny zbiór logów (2 pliki po 80 rekordów)."""
    generate_batch_log_dataset(
        log_dir,
        file_count=2,
        records_per_file=80,
        invalid_ratio=0.05,
        seed=2026,
    )


def test_benchmark_config_paths_and_exception_metadata() -> None:
    """Sprawdza stałe ścieżek benchmarku oraz metadane wyjątku GilBenchmarkError."""
    default_dir = get_default_benchmark_output_dir()
    reference_dir = get_reference_benchmark_dir()

    assert default_dir.parts[-3:] == ("data", "generated", "benchmark")
    assert reference_dir.parts[-3:] == ("kaucjomat", "data", "reference")
    assert BENCHMARK_RESULTS_JSON_NAME == "gil_benchmark_results.json"
    assert BENCHMARK_CHART_PNG_NAME == "gil_benchmark_chart.png"
    assert REFERENCE_BENCHMARK_JSON_NAME == "gil_benchmark_reference.json"
    assert REFERENCE_BENCHMARK_PNG_NAME == "gil_benchmark_reference.png"

    err = GilBenchmarkError("Błąd testowy")
    assert err.error_code == "GIL_BENCHMARK_ERROR"
    assert err.status_code == 400


def test_compute_analytics_threaded_parity_with_seq_and_spawn(tmp_path: Path) -> None:
    """Weryfikuje identyczność metryk między trybem sekwencyjnym, wątkowym i spawn."""
    _create_small_dataset(tmp_path)
    stage_one = read_and_chunk_logs_threaded(tmp_path, chunk_size=40, io_workers=2)
    assert stage_one.total_chunks >= 3

    seq = compute_analytics_sequential(stage_one.chunks, work_iterations=15)
    thr = compute_analytics_threaded(
        stage_one.chunks,
        cpu_workers=2,
        work_iterations=15,
    )
    mp = compute_analytics_multiprocess(
        stage_one.chunks,
        cpu_workers=2,
        work_iterations=15,
    )

    assert thr.execution_mode == "threads_gil"
    assert thr.cpu_workers == 2
    assert seq.metrics == thr.metrics == mp.metrics
    assert thr.metrics.processed_records == stage_one.valid_records
    assert thr.metrics.audit_checksum != 0

    empty_thr = compute_analytics_threaded((), cpu_workers=2, work_iterations=10)
    assert empty_thr.metrics.processed_records == 0


def test_run_gil_benchmark_three_modes_parity_and_speedup(tmp_path: Path) -> None:
    """Sprawdza pełny raport 3 strategii, medianę, speedup i zgodność metryk."""
    _create_small_dataset(tmp_path)
    report = run_gil_benchmark(
        tmp_path,
        repeats=2,
        workers=2,
        chunk_size=40,
        io_workers=2,
        work_iterations=15,
        auto_generate=False,
    )

    assert report.mode_label == "DEMO"
    assert report.auto_generated is False
    assert report.files_processed == 2
    assert report.total_chunks >= 3
    assert report.repeats == 2
    assert report.workers == 2
    assert len(report.strategies) == 3
    assert tuple(item.strategy_id for item in report.strategies) == (
        "sequential",
        "threads",
        "processes_spawn",
    )

    seq_strategy = report.strategies[0]
    assert seq_strategy.workers == 1
    assert seq_strategy.speedup_vs_sequential == 1.0
    assert seq_strategy.relative_to_sequential_pct == 100.0

    for strategy in report.strategies:
        assert len(strategy.runs_ms) == 2
        assert strategy.min_ms <= strategy.median_ms <= strategy.max_ms
        assert strategy.mean_ms >= 0.0
        assert strategy.speedup_vs_sequential > 0.0

    assert report.fastest_strategy_id in {"sequential", "threads", "processes_spawn"}
    assert len(report.conclusions) >= 3
    assert report.verified_metrics.processed_records == report.valid_records


def test_collect_gil_environment_info_and_single_core_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Weryfikuje diagnostykę środowiska GIL oraz ostrzeżenie dla 1 rdzenia CPU."""
    env = collect_gil_environment_info()
    assert env.python_version
    assert env.implementation
    assert env.cpu_count >= 1
    assert env.switch_interval_s > 0.0

    _create_small_dataset(tmp_path)
    monkeypatch.setattr("kaucjomat.gil_benchmark.os.cpu_count", lambda: 1)
    report = run_gil_benchmark(
        tmp_path,
        repeats=1,
        workers=None,
        chunk_size=40,
        io_workers=1,
        work_iterations=10,
        auto_generate=False,
    )

    assert report.environment.cpu_count == 1
    assert report.workers == 2
    assert report.single_core_warning is not None
    assert "jednordzeniowe" in report.single_core_warning
    assert report.single_core_warning in report.conclusions


def test_run_gil_benchmark_emits_logs(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Sprawdza logowanie zdarzeń benchmarku GIL w loggerze kaucjomat.batch."""
    _create_small_dataset(tmp_path)
    with caplog.at_level(logging.INFO, logger="kaucjomat.batch"):
        run_gil_benchmark(
            tmp_path,
            repeats=1,
            workers=2,
            chunk_size=40,
            io_workers=2,
            work_iterations=10,
            auto_generate=False,
        )

    assert any("Benchmark GIL DEMO zakończony" in rec.message for rec in caplog.records)


def test_gil_benchmark_validation_and_mismatch_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sprawdza błędy walidacji, brak rekordów oraz wykrycie rozbieżności metryk."""
    for bad_kwarg in (
        {"repeats": 0},
        {"repeats": True},
        {"workers": 0},
        {"workers": False},
        {"chunk_size": 0},
        {"io_workers": 0},
        {"work_iterations": 0},
        {"work_iterations": True},
    ):
        with pytest.raises(InvalidConfigurationError):
            run_gil_benchmark(tmp_path, **bad_kwarg)

    with pytest.raises(InvalidConfigurationError):
        compute_analytics_threaded((), cpu_workers=0)
    with pytest.raises(InvalidConfigurationError):
        compute_analytics_threaded((), cpu_workers=True)
    with pytest.raises(InvalidConfigurationError):
        compute_analytics_threaded((), work_iterations=0)

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(BatchLogAnalysisError):
        run_gil_benchmark(empty_dir, auto_generate=False)

    invalid_only_dir = tmp_path / "invalid_only"
    invalid_only_dir.mkdir()
    (invalid_only_dir / "bad.log").write_text("TO_NIE_JEST_POPRAWNY_REKORD\n", encoding="utf-8")
    with pytest.raises(GilBenchmarkError):
        run_gil_benchmark(invalid_only_dir, auto_generate=False)

    valid_dir = tmp_path / "valid"
    _create_small_dataset(valid_dir)
    real_threaded = compute_analytics_threaded

    def _corrupted_threaded(*args: object, **kwargs: object) -> object:
        """Zwraca celowo zmienioną sumę kontrolną w celu testu spójności."""
        result = real_threaded(*args, **kwargs)  # type: ignore[arg-type]
        bad_metrics = replace(result.metrics, audit_checksum=result.metrics.audit_checksum ^ 0x1)
        return replace(result, metrics=bad_metrics)

    monkeypatch.setattr("kaucjomat.gil_benchmark.compute_analytics_threaded", _corrupted_threaded)
    with pytest.raises(GilBenchmarkError, match="Niezgodność metryk"):
        run_gil_benchmark(
            valid_dir,
            repeats=1,
            workers=2,
            chunk_size=40,
            io_workers=2,
            work_iterations=10,
            auto_generate=False,
        )
