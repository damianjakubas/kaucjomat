"""Test z prawdziwymi procesami spawn uruchamianymi z serwera WWW (zadanie benchmarku)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kaucjomat.analytics_presets import ANALYTICS_PRESETS, AnalyticsPreset
from kaucjomat.app import create_app

_TINY = AnalyticsPreset("quick", "Mini", "opis", 2, 80, 40, 1, 5, 2)


def _wait(client: TestClient, timeout: float = 120.0) -> dict:
    """Czeka na koniec zadania i zwraca jego migawkę."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get("/api/analytics/jobs/current").json()
        if body["status"] != "running":
            return body
        time.sleep(0.2)
    raise AssertionError("Zadanie nie zakończyło się w limicie czasu.")


def test_benchmark_job_runs_real_spawn_processes_from_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Benchmark z serwera używa procesów spawn i zapisuje PNG oraz JSON w katalogu testu."""
    monkeypatch.setitem(ANALYTICS_PRESETS, "quick", _TINY)
    web_dir = tmp_path / "web"
    app = create_app(state_file=tmp_path / "state.json", analytics_dir=web_dir)
    with TestClient(app) as client:
        for kind in ("generate", "benchmark"):
            assert client.post("/api/analytics/jobs", json={"kind": kind, "preset": "quick"}).status_code == 202
            body = _wait(client)
            assert body["status"] == "succeeded", body

    strategies = body["result"]["strategies"]
    assert [s["strategy_id"] for s in strategies] == ["sequential", "threads", "processes_spawn"]
    # Jednakowa suma kontrolna we wszystkich strategiach potwierdza ten sam wynik obliczeń.
    assert body["result"]["verified_metrics"]["audit_checksum_hex"].startswith("0x")
    png = web_dir / "benchmark" / "gil_benchmark_chart.png"
    saved = json.loads((web_dir / "benchmark" / "gil_benchmark_results.json").read_text("utf-8"))
    assert png.is_file() and png.read_bytes().startswith(b"\x89PNG")
    assert [s["strategy_id"] for s in saved["strategies"]] == [s["strategy_id"] for s in strategies]
