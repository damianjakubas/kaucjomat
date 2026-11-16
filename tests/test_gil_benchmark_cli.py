"""Testy wykresu PNG, serializacji artefaktów JSON oraz formatowania raportu benchmarku GIL."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from kaucjomat.batch_format import format_gil_benchmark_report, gil_benchmark_report_to_dict
from kaucjomat.batch_generator import generate_batch_log_dataset
from kaucjomat.config import (
    BENCHMARK_CHART_PNG_NAME,
    BENCHMARK_RESULTS_JSON_NAME,
    REFERENCE_BENCHMARK_JSON_NAME,
    REFERENCE_BENCHMARK_PNG_NAME,
)
from kaucjomat import gil_chart
from kaucjomat.exceptions import GilBenchmarkError
from kaucjomat.gil_benchmark import GilBenchmarkReport, run_gil_benchmark
from kaucjomat.gil_chart import (
    load_reference_gil_benchmark_dict,
    render_gil_benchmark_chart,
    save_gil_benchmark_artifacts,
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(scope="module")
def small_report(tmp_path_factory: pytest.TempPathFactory) -> GilBenchmarkReport:
    """Buduje mały raport benchmarku (2 pliki, 1 powtórzenie) współdzielony przez testy."""
    log_dir = tmp_path_factory.mktemp("logs")
    generate_batch_log_dataset(log_dir, file_count=2, records_per_file=60, seed=7)
    return run_gil_benchmark(
        log_dir, repeats=1, workers=2, chunk_size=30, work_iterations=10, auto_generate=False
    )


def test_render_and_save_gil_benchmark_artifacts_png_and_json(
    small_report: GilBenchmarkReport, tmp_path: Path
) -> None:
    """Sprawdza sygnaturę PNG, kompletność JSON i niepuste ścieżki w sekcji artifacts."""
    saved = save_gil_benchmark_artifacts(small_report, output_dir=tmp_path)

    png_path = tmp_path / BENCHMARK_CHART_PNG_NAME
    json_path = tmp_path / BENCHMARK_RESULTS_JSON_NAME
    assert saved.chart_artifact_path == png_path and saved.json_artifact_path == json_path
    assert png_path.read_bytes().startswith(PNG_SIGNATURE) and png_path.stat().st_size > 5000

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["mode_label"] == "DEMO"
    assert [s["strategy_id"] for s in data["strategies"]] == ["sequential", "threads", "processes_spawn"]
    assert data["strategies"][0]["speedup_vs_sequential"] == 1.0
    assert data["verified_metrics"]["audit_checksum_hex"].startswith("0x")
    assert data["artifacts"]["json_path"] and data["artifacts"]["chart_png_path"]
    assert render_gil_benchmark_chart(small_report, tmp_path / "x" / "chart.png").is_file()


def test_save_reference_uses_isolated_dir_and_loader_validates(
    small_report: GilBenchmarkReport, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zapis referencji trafia do izolowanego katalogu, a loader zwraca poprawny kontrakt."""
    monkeypatch.setattr(gil_chart, "get_reference_benchmark_dir", lambda: tmp_path)
    save_gil_benchmark_artifacts(small_report, save_reference=True)

    assert (tmp_path / REFERENCE_BENCHMARK_PNG_NAME).read_bytes().startswith(PNG_SIGNATURE)
    data = load_reference_gil_benchmark_dict(tmp_path)
    assert len(data["strategies"]) == 3 and data["environment"]["cpu_count"] >= 1
    assert data == gil_benchmark_report_to_dict(
        replace(small_report, json_artifact_path=tmp_path / REFERENCE_BENCHMARK_JSON_NAME,
                          chart_artifact_path=tmp_path / REFERENCE_BENCHMARK_PNG_NAME)
    )


def test_load_reference_errors(tmp_path: Path) -> None:
    """Brak pliku, niepoprawny JSON i niekompletny kontrakt zgłaszają GilBenchmarkError."""
    with pytest.raises(GilBenchmarkError):
        load_reference_gil_benchmark_dict(tmp_path)
    ref = tmp_path / REFERENCE_BENCHMARK_JSON_NAME
    ref.write_text("{nie json", encoding="utf-8")
    with pytest.raises(GilBenchmarkError):
        load_reference_gil_benchmark_dict(tmp_path)
    ref.write_text("[]", encoding="utf-8")
    with pytest.raises(GilBenchmarkError):
        load_reference_gil_benchmark_dict(tmp_path)
    ref.write_text(json.dumps({"mode_label": "DEMO"}), encoding="utf-8")
    with pytest.raises(GilBenchmarkError, match="brakuje kluczy"):
        load_reference_gil_benchmark_dict(tmp_path)


def test_format_gil_benchmark_report_contains_sections(small_report: GilBenchmarkReport) -> None:
    """Raport tekstowy zawiera znacznik DEMO, tabelę strategii, GIL i wnioski."""
    text = format_gil_benchmark_report(small_report)
    assert "DEMO" in text and "Rdzenie CPU" in text and "GIL:" in text
    for label in ("Sekwencyjnie", "Wątki", "Procesy spawn"):
        assert label in text
    assert "Wnioski:" in text and "Suma kontrolna" in text
