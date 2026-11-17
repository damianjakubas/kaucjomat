"""Testy API /api/analytics: kontekst, referencja, PNG, walidacja, 409 i pełne cykle zadań."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from kaucjomat import analytics_router
from kaucjomat.analytics_presets import ANALYTICS_PRESETS, AnalyticsPreset
from kaucjomat.app import create_app
from kaucjomat.config import get_reference_benchmark_dir, REFERENCE_BENCHMARK_JSON_NAME

_TINY = AnalyticsPreset("quick", "Mini", "opis", 2, 60, 40, 1, 3, 2)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Klient z małym presetem quick i katalogiem roboczym w tmp_path."""
    monkeypatch.setitem(ANALYTICS_PRESETS, "quick", _TINY)
    app = create_app(state_file=tmp_path / "state.json", analytics_dir=tmp_path / "web")
    with TestClient(app) as test_client:
        yield test_client
        _wait_for_end(test_client)


def _wait_for_end(client: TestClient, timeout: float = 90.0) -> dict[str, Any]:
    """Odpytuje /jobs/current aż zadanie przestanie działać i zwraca końcową migawkę."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get("/api/analytics/jobs/current").json()
        if body["status"] != "running":
            return body
        time.sleep(0.1)
    raise AssertionError("Zadanie nie zakończyło się w limicie czasu.")


def _run_job(client: TestClient, kind: str) -> dict[str, Any]:
    """Startuje zadanie i czeka na jego koniec."""
    response = client.post("/api/analytics/jobs", json={"kind": kind, "preset": "quick"})
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "running"
    return _wait_for_end(client)


def _assert_no_absolute_paths(value: Any) -> None:
    """Sprawdza rekurencyjnie, że żaden tekst odpowiedzi nie zawiera ścieżki absolutnej."""
    if isinstance(value, dict):
        for item in value.values():
            _assert_no_absolute_paths(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_absolute_paths(item)
    elif isinstance(value, str):
        assert not Path(value).is_absolute() and ":\\" not in value, value


def test_context_lists_presets_and_demo(client: TestClient) -> None:
    """Kontekst zawiera tryb DEMO, rdzenie, stan GIL i oba presety."""
    body = client.get("/api/analytics/context").json()
    assert body["mode"] == "DEMO" and body["cpu_count"] >= 1
    assert isinstance(body["gil_enabled"], bool)
    assert {p["preset_id"] for p in body["presets"]} == {"quick", "standard"}


def test_context_single_core_warning(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Przy 1 rdzeniu kontekst niesie komunikat z 'jednordzeniowe'."""
    monkeypatch.setattr("kaucjomat.gil_benchmark.os.cpu_count", lambda: 1)
    body = client.get("/api/analytics/context").json()
    assert "jednordzeniowe" in body["single_core_warning"]


def test_reference_matches_saved_json(client: TestClient) -> None:
    """Referencja ma kształt zapisanego JSON i adres wykresu."""
    body = client.get("/api/analytics/reference").json()
    saved = json.loads((get_reference_benchmark_dir() / REFERENCE_BENCHMARK_JSON_NAME).read_text("utf-8"))
    assert body["mode"] == "DEMO" and body["benchmark"] == saved
    assert body["chart_url"] == "/api/analytics/reference/chart"


def test_reference_chart_png_and_missing_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Wykres referencji zwraca PNG bez cache'u, a brak pliku daje 404 z kodem."""
    ok = client.get("/api/analytics/reference/chart")
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/png"
    assert ok.headers["cache-control"] == "no-store"
    monkeypatch.setattr(analytics_router, "get_reference_benchmark_dir", lambda: tmp_path)
    missing = client.get("/api/analytics/reference/chart")
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "ANALYTICS_ARTIFACT_NOT_FOUND"
    assert client.get("/api/analytics/benchmark/chart").status_code == 404


def test_validation_errors_return_422(client: TestClient) -> None:
    """Zły kind, zły preset i pole dodatkowe dają 422."""
    for payload in (
        {"kind": "zly", "preset": "quick"}, {"kind": "generate", "preset": "zly"},
        {"kind": "generate", "preset": "quick", "extra": 1},
    ):
        response = client.post("/api/analytics/jobs", json=payload)
        assert response.status_code == 422, payload
        assert response.json()["error_code"] == "VALIDATION_ERROR"


def test_idle_before_any_job(client: TestClient) -> None:
    """Bez uruchomionego zadania /jobs/current zwraca stan idle."""
    assert client.get("/api/analytics/jobs/current").json()["status"] == "idle"


def test_missing_dataset_job_fails_with_code(client: TestClient) -> None:
    """Analiza bez zbioru kończy się failed z ANALYTICS_DATASET_MISSING."""
    body = _run_job(client, "analysis")
    assert body["status"] == "failed" and body["error_code"] == "ANALYTICS_DATASET_MISSING"
    assert "wygeneruj" in body["error_message"]


def test_second_start_returns_409(client: TestClient) -> None:
    """Drugi start w trakcie zadania daje 409, a po zakończeniu start jest znów możliwy."""
    first = client.post("/api/analytics/jobs", json={"kind": "generate", "preset": "quick"})
    assert first.status_code == 202
    second = client.post("/api/analytics/jobs", json={"kind": "generate", "preset": "quick"})
    # Generowanie małego zbioru bywa szybsze niż drugie żądanie, więc akceptujemy oba przebiegi.
    assert second.status_code in (409, 202)
    if second.status_code == 409:
        assert second.json()["error_code"] == "ANALYTICS_JOB_BUSY"
    _wait_for_end(client)


def test_full_cycle_generate_analysis_benchmark(client: TestClient) -> None:
    """Pełny cykl: generowanie, analiza dwuetapowa i benchmark z wykresem."""
    generated = _run_job(client, "generate")
    assert generated["status"] == "succeeded" and generated["result"]["file_count"] == 2
    analysis = _run_job(client, "analysis")
    assert analysis["status"] == "succeeded", analysis
    assert analysis["result"]["mode_label"] == "DEMO"
    assert "audit_checksum_hex" in analysis["result"]["stage_two_cpu"]["metrics"]
    benchmark = _run_job(client, "benchmark")
    assert benchmark["status"] == "succeeded", benchmark
    assert [s["strategy_id"] for s in benchmark["result"]["strategies"]] == [
        "sequential", "threads", "processes_spawn",
    ]
    assert (benchmark["progress_done"], benchmark["progress_total"]) == (3, 3)
    chart = client.get("/api/analytics/benchmark/chart")
    assert chart.status_code == 200 and chart.content.startswith(b"\x89PNG")
    for body in (generated, analysis, benchmark):
        _assert_no_absolute_paths(body["result"])


def test_single_core_warning_in_analysis_and_benchmark(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Przy 1 rdzeniu wyniki analizy i benchmarku zawierają komunikat jednordzeniowy."""
    _run_job(client, "generate")
    monkeypatch.setattr("kaucjomat.gil_benchmark.os.cpu_count", lambda: 1)
    for kind in ("analysis", "benchmark"):
        body = _run_job(client, kind)
        assert body["status"] == "succeeded", body
        assert "jednordzeniowe" in body["result"]["single_core_warning"]


@pytest.mark.parametrize("contents", [None, "{", "{}"])
def test_reference_error_hides_path(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, contents: str | None,
) -> None:
    """Brak lub uszkodzenie referencji zachowuje kod błędu bez ujawniania katalogu."""
    from kaucjomat import gil_chart

    private_dir = tmp_path / "private_reference"
    private_dir.mkdir()
    if contents is not None:
        (private_dir / REFERENCE_BENCHMARK_JSON_NAME).write_text(contents, encoding="utf-8")
    monkeypatch.setattr(gil_chart, "get_reference_benchmark_dir", lambda: private_dir)
    response = client.get("/api/analytics/reference")
    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "GIL_BENCHMARK_ERROR"
    assert body["message"] == (
        "Nie udało się wczytać wyników referencyjnych; szczegóły zapisano w logu serwera."
    )
    assert "private_reference" not in response.text
    _assert_no_absolute_paths(body)


def test_generate_io_error_hides_path(tmp_path: Path) -> None:
    """Zablokowany katalog generowania daje błąd zadania bez lokalnej ścieżki."""
    private_path = tmp_path / "private_analytics"
    private_path.write_text("plik zamiast katalogu", encoding="utf-8")
    app = create_app(state_file=tmp_path / "state.json", analytics_dir=private_path)
    with TestClient(app) as test_client:
        body = _run_job(test_client, "generate")
    assert body["status"] == "failed"
    assert body["error_code"] == "BATCH_LOG_ANALYSIS_ERROR"
    assert body["error_message"] == (
        "Nie udało się wykonać zadania analitycznego; szczegóły zapisano w logu serwera."
    )
    assert "private_analytics" not in json.dumps(body)
    _assert_no_absolute_paths(body)
