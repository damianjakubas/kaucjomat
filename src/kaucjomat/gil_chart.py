"""Bezgłowy wykres PNG (matplotlib Agg) oraz zapis i odczyt artefaktów benchmarku GIL."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
from typing import Any

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from kaucjomat.batch_format import gil_benchmark_report_to_dict
from kaucjomat.config import (
    BENCHMARK_CHART_PNG_NAME,
    BENCHMARK_RESULTS_JSON_NAME,
    REFERENCE_BENCHMARK_JSON_NAME,
    REFERENCE_BENCHMARK_PNG_NAME,
    get_default_benchmark_output_dir,
    get_reference_benchmark_dir,
)
from kaucjomat.exceptions import GilBenchmarkError
from kaucjomat.gil_benchmark import GilBenchmarkReport
from kaucjomat.logging_config import get_logger

_LOGGER = get_logger("kaucjomat.batch")
_BAR_COLORS: tuple[str, ...] = ("#6b7280", "#d97706", "#059669")
_REQUIRED_REFERENCE_KEYS: tuple[str, ...] = (
    "mode_label", "environment", "dataset", "benchmark_config",
    "strategies", "verified_metrics", "conclusions",
)


def _draw_time_panel(ax: Any, report: GilBenchmarkReport) -> None:
    """Rysuje lewy panel: mediany czasów Etapu 2 wraz z zakresem min–max prób."""
    labels = [s.strategy_label.replace(" (", "\n(") for s in report.strategies]
    medians = [s.median_ms for s in report.strategies]
    lower = [s.median_ms - s.min_ms for s in report.strategies]
    upper = [s.max_ms - s.median_ms for s in report.strategies]
    bars = ax.bar(labels, medians, color=_BAR_COLORS, yerr=[lower, upper], capsize=5)
    top = max(s.max_ms for s in report.strategies)
    for bar, value in zip(bars, medians):
        ax.text(bar.get_x() + bar.get_width() / 2, value + top * 0.02, f"{value:.0f} ms",
                ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax.set_ylim(0, top * 1.2)
    ax.set_ylabel("Mediana czasu Etapu 2 CPU [ms] (mniej = lepiej)")
    ax.set_title("Czas wykonania (mediana, zakres min–max)", fontsize=11)
    ax.tick_params(axis="x", labelsize=8)
    ax.grid(axis="y", alpha=0.3)


def _draw_speedup_panel(ax: Any, report: GilBenchmarkReport) -> None:
    """Rysuje prawy panel: przyspieszenie względem przebiegu sekwencyjnego."""
    labels = [s.strategy_label.replace(" (", "\n(") for s in report.strategies]
    speedups = [s.speedup_vs_sequential for s in report.strategies]
    bars = ax.bar(labels, speedups, color=_BAR_COLORS)
    ax.axhline(1.0, color="#111827", linestyle="--", linewidth=1, label="1.00x (sekwencyjnie)")
    top = max(speedups + [1.0])
    for bar, value in zip(bars, speedups):
        ax.text(bar.get_x() + bar.get_width() / 2, value + top * 0.02, f"{value:.2f}x",
                ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax.set_ylim(0, top * 1.2)
    ax.set_ylabel("Speedup (x) (więcej = lepiej)")
    ax.set_title("Przyspieszenie względem sekwencyjnego", fontsize=11)
    ax.tick_params(axis="x", labelsize=8)
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(axis="y", alpha=0.3)


def render_gil_benchmark_chart(report: GilBenchmarkReport, output_path: Path) -> Path:
    """Renderuje dwupanelowy wykres PNG (Agg, bez GUI) i zapisuje go pod wskazaną ścieżką."""
    env = report.environment
    gil_state = "aktywny" if env.gil_enabled else "wyłączony"
    fig = Figure(figsize=(10.5, 5.2), dpi=140)
    FigureCanvasAgg(fig)
    ax_time, ax_speedup = fig.subplots(1, 2)
    _draw_time_panel(ax_time, report)
    _draw_speedup_panel(ax_speedup, report)
    fig.suptitle("KaucjaSim DEMO — Benchmark GIL", fontsize=14, fontweight="bold")
    fig.text(
        0.5, 0.01,
        f"DEMO | CPU: {env.cpu_count} rdzeni | Python {env.python_version} | GIL: {gil_state} | "
        f"rekordy: {report.valid_records} | rundy FNV-1a: {report.work_iterations} | "
        f"suma kontrolna: {hex(report.verified_metrics.audit_checksum)}",
        ha="center", fontsize=8, color="#374151",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, format="png")
    except OSError as exc:
        raise GilBenchmarkError(f"Nie można zapisać wykresu {output_path}: {exc}") from exc
    return output_path


def save_gil_benchmark_artifacts(
    report: GilBenchmarkReport, *, output_dir: Path | None = None, save_reference: bool = False,
) -> GilBenchmarkReport:
    """Zapisuje wykres PNG i raport JSON (roboczo lub jako referencję) i zwraca zaktualizowany raport."""
    if save_reference:
        target_dir = output_dir if output_dir is not None else get_reference_benchmark_dir()
        json_name, png_name = REFERENCE_BENCHMARK_JSON_NAME, REFERENCE_BENCHMARK_PNG_NAME
    else:
        target_dir = output_dir if output_dir is not None else get_default_benchmark_output_dir()
        json_name, png_name = BENCHMARK_RESULTS_JSON_NAME, BENCHMARK_CHART_PNG_NAME
    json_path, png_path = target_dir / json_name, target_dir / png_name
    updated = replace(report, json_artifact_path=json_path, chart_artifact_path=png_path)
    # Zapis atomowy: najpierw pliki tymczasowe, potem podmiana obu docelowych plików.
    tmp_png = png_path.with_name(png_path.name + ".tmp")
    tmp_json = json_path.with_name(json_path.name + ".tmp")
    try:
        render_gil_benchmark_chart(updated, tmp_png)
        tmp_json.write_text(
            json.dumps(gil_benchmark_report_to_dict(updated), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp_png, png_path)
        os.replace(tmp_json, json_path)
    except OSError as exc:
        raise GilBenchmarkError(f"Nie można zapisać artefaktów w {target_dir}: {exc}") from exc
    finally:
        tmp_png.unlink(missing_ok=True)
        tmp_json.unlink(missing_ok=True)
    _LOGGER.info("Zapisano artefakty benchmarku GIL DEMO: json=%s, png=%s", json_path, png_path)
    return updated


def load_reference_gil_benchmark_dict(reference_dir: Path | None = None) -> dict[str, Any]:
    """Wczytuje i waliduje referencyjny JSON benchmarku GIL (kontrakt dla widoku webowego)."""
    json_path = (reference_dir or get_reference_benchmark_dir()) / REFERENCE_BENCHMARK_JSON_NAME
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GilBenchmarkError(f"Nie można wczytać wyników referencyjnych {json_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise GilBenchmarkError(f"Plik {json_path} nie zawiera obiektu JSON.")
    missing = [key for key in _REQUIRED_REFERENCE_KEYS if key not in data]
    if missing:
        raise GilBenchmarkError(f"W pliku {json_path} brakuje kluczy: {', '.join(missing)}.")
    if not isinstance(data["strategies"], list) or len(data["strategies"]) != 3:
        raise GilBenchmarkError(f"Plik {json_path} musi zawierać dokładnie 3 strategie.")
    return data
