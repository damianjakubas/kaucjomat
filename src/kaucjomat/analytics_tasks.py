"""Zadania domenowe widoku Analityka: generowanie zbioru, analiza dwuetapowa i benchmark GIL."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kaucjomat.analytics_presets import AnalyticsPreset
from kaucjomat.batch_format import batch_report_to_dict, gil_benchmark_report_to_dict
from kaucjomat.batch_generator import generate_batch_log_dataset
from kaucjomat.batch_runner import run_two_stage_batch_analysis
from kaucjomat.config import BENCHMARK_CHART_PNG_NAME, BENCHMARK_RESULTS_JSON_NAME
from kaucjomat.exceptions import AnalyticsDatasetMissingError, BatchLogAnalysisError
from kaucjomat.gil_benchmark import run_gil_benchmark
from kaucjomat.gil_conclusions import build_single_core_warning

if TYPE_CHECKING:
    from kaucjomat.analytics_jobs import AnalyticsJobContext

# Zadanie: (uchwyt postępu, preset, katalog roboczy) -> słownik wyniku gotowy do JSON.
AnalyticsTask = Callable[["AnalyticsJobContext", AnalyticsPreset, Path], dict[str, Any]]

_STRATEGIES_PER_REPEAT: int = 3


def _log_dir(base_dir: Path, preset: AnalyticsPreset) -> Path:
    """Zwraca katalog logów presetu wewnątrz katalogu roboczego widoku."""
    return base_dir / "logs" / preset.preset_id


def _log_label(preset: AnalyticsPreset) -> str:
    """Zwraca względną etykietę katalogu logów, żeby odpowiedź HTTP nie ujawniała ścieżek."""
    return f"logs/{preset.preset_id}"


def _require_dataset(log_dir: Path, preset: AnalyticsPreset) -> None:
    """Zgłasza błąd, gdy katalog presetu nie zawiera wygenerowanych plików ``*.log``."""
    try:
        has_logs = log_dir.is_dir() and any(path.is_file() for path in log_dir.glob("*.log"))
    except OSError as exc:
        raise BatchLogAnalysisError("Nie można odczytać katalogu logów presetu.") from exc
    if not has_logs:
        raise AnalyticsDatasetMissingError(
            f"Najpierw wygeneruj zbiór logów (preset {preset.label})."
        )


def run_generate_task(
    context: AnalyticsJobContext, preset: AnalyticsPreset, base_dir: Path,
) -> dict[str, Any]:
    """Generuje zbiór logów o rozmiarze presetu i zwraca podsumowanie jak CLI ``--json``."""
    context.set_phase("Generowanie zbioru logów")
    summary = generate_batch_log_dataset(
        _log_dir(base_dir, preset), file_count=preset.file_count,
        records_per_file=preset.records_per_file,
    )
    payload = asdict(summary)
    payload["log_dir"] = _log_label(preset)
    payload["file_names"] = list(summary.file_names)
    payload["mode_label"] = "DEMO"
    return payload


def run_analysis_task(
    context: AnalyticsJobContext, preset: AnalyticsPreset, base_dir: Path,
) -> dict[str, Any]:
    """Uruchamia analizę dwuetapową (wątki, potem procesy spawn) na zbiorze presetu."""
    log_dir = _log_dir(base_dir, preset)
    _require_dataset(log_dir, preset)
    context.set_phase("Analiza: odczyt plików (wątki) i obliczenia (procesy spawn)")
    cpu_count = os.cpu_count() or 1
    # auto_generate=False: silnik nie może po cichu wygenerować domyślnego zbioru 8×5000.
    report = run_two_stage_batch_analysis(
        log_dir, chunk_size=preset.chunk_size, cpu_workers=min(preset.max_workers, cpu_count),
        work_iterations=preset.work_iterations, auto_generate=False,
    )
    payload = batch_report_to_dict(report)
    payload["log_dir"] = _log_label(preset)
    payload["single_core_warning"] = build_single_core_warning(report.cpu_count)
    return payload


def run_benchmark_task(
    context: AnalyticsJobContext, preset: AnalyticsPreset, base_dir: Path,
) -> dict[str, Any]:
    """Uruchamia benchmark GIL z postępem, zapisuje wykres i JSON w katalogu roboczym."""
    log_dir = _log_dir(base_dir, preset)
    _require_dataset(log_dir, preset)
    total = preset.repeats * _STRATEGIES_PER_REPEAT
    context.set_phase("Benchmark GIL")
    context.set_progress(0, total)

    def report_progress(done: int, all_runs: int, strategy_id: str) -> None:
        """Przekazuje postęp silnika do kontekstu zadania wraz z nazwą strategii."""
        context.set_phase(f"Benchmark GIL: {strategy_id}")
        context.set_progress(done, all_runs)

    report = run_gil_benchmark(
        log_dir, repeats=preset.repeats, workers=None, chunk_size=preset.chunk_size,
        work_iterations=preset.work_iterations, auto_generate=False, on_progress=report_progress,
    )
    context.set_phase("Zapis wykresu i wyników")
    # Import leniwy: matplotlib spowalnia start serwera, a potrzebny jest dopiero tutaj.
    from kaucjomat.gil_chart import save_gil_benchmark_artifacts

    saved = save_gil_benchmark_artifacts(
        report, output_dir=base_dir / "benchmark", save_reference=False,
    )
    payload = gil_benchmark_report_to_dict(saved)
    payload["log_dir"] = _log_label(preset)
    payload["artifacts"] = {
        "json_path": f"benchmark/{BENCHMARK_RESULTS_JSON_NAME}",
        "chart_png_path": f"benchmark/{BENCHMARK_CHART_PNG_NAME}",
    }
    return payload


TASKS: dict[str, AnalyticsTask] = {
    "generate": run_generate_task,
    "analysis": run_analysis_task,
    "benchmark": run_benchmark_task,
}
