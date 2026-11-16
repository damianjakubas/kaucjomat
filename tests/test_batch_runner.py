"""Testy jednostkowe i współbieżności dla Etapu 1 (I/O) oraz Etapu 2 (CPU spawn)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kaucjomat.cli import main

from kaucjomat.batch_cpu import (
    analyze_record_chunk,
    compute_record_audit_signature,
    merge_chunk_results,
)
from kaucjomat.batch_generator import generate_batch_log_dataset
from kaucjomat.batch_runner import (
    batch_report_to_dict,
    compute_analytics_multiprocess,
    compute_analytics_sequential,
    format_batch_analysis_report,
    format_batch_generation_report,
    read_and_chunk_logs_threaded,
    run_two_stage_batch_analysis,
)
from kaucjomat.exceptions import BatchLogAnalysisError, InvalidConfigurationError


def test_stage_one_io_workers_produce_identical_chunks(tmp_path: Path) -> None:
    """Porównuje wynik Etapu 1 dla 1 wątku i 4 wątków (Lock + Queue)."""
    summary = generate_batch_log_dataset(
        tmp_path,
        file_count=4,
        records_per_file=150,
        invalid_ratio=0.02,
        seed=77,
    )

    single = read_and_chunk_logs_threaded(tmp_path, chunk_size=64, io_workers=1)
    multi = read_and_chunk_logs_threaded(tmp_path, chunk_size=64, io_workers=4)

    assert single.files_processed == 4
    assert single.valid_records == summary.expected_valid_records
    assert single.invalid_lines == summary.expected_invalid_lines
    assert single.valid_records == multi.valid_records
    assert single.invalid_lines == multi.invalid_lines
    assert single.total_chunks == multi.total_chunks
    assert single.file_stats == multi.file_stats
    assert single.chunks == multi.chunks
    assert multi.io_elapsed_ms >= 0.0


def test_stage_two_sequential_vs_multiprocess_spawn_parity(tmp_path: Path) -> None:
    """Sprawdza pełną zgodność obliczeń sekwencyjnych i wieloprocesowych (spawn)."""
    generate_batch_log_dataset(
        tmp_path,
        file_count=3,
        records_per_file=120,
        invalid_ratio=0.01,
        seed=2026,
    )
    stage_one = read_and_chunk_logs_threaded(tmp_path, chunk_size=50, io_workers=2)

    seq = compute_analytics_sequential(stage_one.chunks, work_iterations=30)
    mp = compute_analytics_multiprocess(
        stage_one.chunks,
        cpu_workers=2,
        work_iterations=30,
    )

    assert seq.execution_mode == "sequential"
    assert mp.execution_mode == "multiprocess_spawn"
    assert mp.metrics == seq.metrics
    assert mp.metrics.audit_checksum == seq.metrics.audit_checksum
    assert mp.metrics.accepted_deposit_grosze == seq.metrics.accepted_deposit_grosze
    assert mp.metrics.redirected_glass_grosze == seq.metrics.redirected_glass_grosze
    assert mp.metrics.accepted_deposit_grosze > 0
    assert mp.metrics.redirected_glass_grosze > 0


def test_merge_chunk_results_is_order_independent(tmp_path: Path) -> None:
    """Weryfikuje, że łączenie wyników porcji jest niezależne od kolejności."""
    generate_batch_log_dataset(
        tmp_path,
        file_count=2,
        records_per_file=80,
        invalid_ratio=0.0,
        seed=15,
    )
    stage_one = read_and_chunk_logs_threaded(tmp_path, chunk_size=30, io_workers=2)
    chunk_results = [
        analyze_record_chunk(chunk, work_iterations=15)
        for chunk in stage_one.chunks
    ]

    forward = merge_chunk_results(chunk_results)
    reversed_order = merge_chunk_results(reversed(chunk_results))
    assert forward == reversed_order


def test_validation_and_missing_or_empty_directories(tmp_path: Path) -> None:
    """Sprawdza walidację parametrów oraz reakcję na brakujące i puste katalogi."""
    missing_dir = tmp_path / "brak"
    with pytest.raises(BatchLogAnalysisError):
        read_and_chunk_logs_threaded(missing_dir)

    empty_dir = tmp_path / "pusty"
    empty_dir.mkdir()
    with pytest.raises(BatchLogAnalysisError):
        read_and_chunk_logs_threaded(empty_dir)

    with pytest.raises(InvalidConfigurationError):
        read_and_chunk_logs_threaded(empty_dir, chunk_size=0)
    with pytest.raises(InvalidConfigurationError):
        read_and_chunk_logs_threaded(empty_dir, io_workers=0)
    with pytest.raises(InvalidConfigurationError):
        compute_analytics_sequential((), work_iterations=0)
    with pytest.raises(InvalidConfigurationError):
        compute_analytics_multiprocess((), cpu_workers=0)

    generate_batch_log_dataset(empty_dir, file_count=1, records_per_file=5, seed=9)
    stage_one = read_and_chunk_logs_threaded(empty_dir, chunk_size=10, io_workers=1)
    with pytest.raises(InvalidConfigurationError):
        compute_record_audit_signature(stage_one.chunks[0][0], work_iterations=0)


def test_run_two_stage_batch_analysis_auto_generate_and_logging(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Testuje pełny przebieg z auto-generowaniem, logowaniem i formatowaniem DEMO."""
    caplog.set_level(logging.INFO, logger="kaucjomat.batch")

    report = run_two_stage_batch_analysis(
        tmp_path,
        chunk_size=120,
        io_workers=2,
        cpu_workers=2,
        work_iterations=20,
        auto_generate=True,
    )

    assert report.mode_label == "DEMO"
    assert report.auto_generated is True
    assert report.stage_one_io.io_elapsed_ms > 0.0
    assert report.stage_two_cpu.cpu_elapsed_ms > 0.0
    assert report.total_elapsed_ms >= 0.0
    assert any("Analiza wsadowa DEMO zakończona" in rec.message for rec in caplog.records)

    text_report = format_batch_analysis_report(report)
    assert "DEMO" in text_report
    assert "Etap 1 (I/O - wątki)" in text_report
    assert "Etap 2 (CPU - procesy spawn)" in text_report

    payload = batch_report_to_dict(report)
    assert payload["mode_label"] == "DEMO"
    assert payload["stage_two_cpu"]["metrics"]["audit_checksum"] == report.stage_two_cpu.metrics.audit_checksum

    gen_summary = generate_batch_log_dataset(tmp_path / "gen", file_count=1, records_per_file=10, seed=1)
    assert "DEMO" in format_batch_generation_report(gen_summary)


def test_cli_generate_and_analyze_logs_commands(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Podkomendy generate-logs i analyze-logs działają w trybie tekstowym oraz --json."""
    log_dir = tmp_path / "cli_logs"

    exit_gen = main(
        [
            "generate-logs",
            "--log-dir",
            str(log_dir),
            "--files",
            "2",
            "--records-per-file",
            "50",
            "--invalid-ratio",
            "0.1",
            "--seed",
            "7",
            "--json",
        ]
    )
    gen_out = capsys.readouterr().out
    gen_data = json.loads(gen_out)

    assert exit_gen == 0
    assert gen_data["mode_label"] == "DEMO"
    assert gen_data["file_count"] == 2
    assert gen_data["total_lines"] == 100

    exit_analyze = main(
        [
            "analyze-logs",
            "--log-dir",
            str(log_dir),
            "--chunk-size",
            "25",
            "--io-workers",
            "2",
            "--cpu-workers",
            "2",
            "--work-iterations",
            "15",
            "--no-auto-generate",
            "--json",
        ]
    )
    analyze_out = capsys.readouterr().out
    analyze_data = json.loads(analyze_out)

    assert exit_analyze == 0
    assert analyze_data["mode_label"] == "DEMO"
    assert analyze_data["stage_one_io"]["files_processed"] == 2
    assert analyze_data["stage_two_cpu"]["metrics"]["processed_records"] == (
        analyze_data["stage_one_io"]["valid_records"]
    )


def test_cli_analyze_logs_subprocess_spawn(tmp_path: Path) -> None:
    """Uruchomienie ``python -m kaucjomat analyze-logs`` działa w podprocesie spawn na Windows."""
    log_dir = tmp_path / "spawn_logs"
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "kaucjomat",
            "analyze-logs",
            "--log-dir",
            str(log_dir),
            "--chunk-size",
            "500",
            "--cpu-workers",
            "2",
            "--work-iterations",
            "10",
            "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["mode_label"] == "DEMO"
    assert payload["auto_generated"] is True
    assert payload["stage_two_cpu"]["execution_mode"] == "multiprocess_spawn"
    assert payload["stage_one_io"]["valid_records"] > 0


def test_cli_batch_commands_reject_invalid_arguments(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Błędne argumenty lub pusty katalog przy --no-auto-generate zwracają kod błędu 2."""
    exit_empty = main(
        ["analyze-logs", "--log-dir", str(tmp_path / "empty"), "--no-auto-generate"]
    )
    err_empty = capsys.readouterr().err
    assert exit_empty == 2
    assert "BATCH_LOG_ANALYSIS_ERROR" in err_empty

    exit_bad_files = main(["generate-logs", "--files", "0"])
    err_bad_files = capsys.readouterr().err
    assert exit_bad_files == 2
    assert "INVALID_CONFIGURATION" in err_bad_files
