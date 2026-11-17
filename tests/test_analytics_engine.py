"""Testy warstwy silnika i kontraktu widoku Analityka: postęp, komunikat 1 rdzenia, presety."""

from __future__ import annotations

from pathlib import Path

import pytest

from kaucjomat.analytics_presets import ANALYTICS_PRESETS, AnalyticsPreset, get_preset
from kaucjomat.batch_generator import generate_batch_log_dataset
from kaucjomat.config import (
    get_project_root,
    get_web_analytics_dir,
    get_web_analytics_log_dir,
    get_web_benchmark_dir,
)
from kaucjomat.exceptions import (
    AnalyticsArtifactNotFoundError,
    AnalyticsDatasetMissingError,
    AnalyticsJobBusyError,
    InvalidConfigurationError,
)
from kaucjomat.gil_benchmark import run_gil_benchmark
from kaucjomat.gil_conclusions import build_single_core_warning


def _run_small_benchmark(log_dir: Path, repeats: int, on_progress=None):  # noqa: ANN001, ANN202
    """Uruchamia szybki benchmark na małym zbiorze z opcjonalnym callbackiem postępu."""
    generate_batch_log_dataset(log_dir, file_count=2, records_per_file=60, seed=7)
    return run_gil_benchmark(
        log_dir, repeats=repeats, workers=2, chunk_size=40, io_workers=1,
        work_iterations=5, auto_generate=False, on_progress=on_progress,
    )


def test_on_progress_called_repeats_times_three_in_order(tmp_path: Path) -> None:
    """Callback postępu wywołany repeats × 3 razy w kolejności strategii."""
    calls: list[tuple[int, int, str]] = []
    _run_small_benchmark(tmp_path, 2, lambda done, total, sid: calls.append((done, total, sid)))

    assert len(calls) == 6
    assert [c[0] for c in calls] == [1, 2, 3, 4, 5, 6]
    assert {c[1] for c in calls} == {6}
    assert [c[2] for c in calls] == ["sequential", "threads", "processes_spawn"] * 2


def test_benchmark_without_callback_still_works(tmp_path: Path) -> None:
    """Wywołanie bez callbacku zachowuje się jak dotąd."""
    report = _run_small_benchmark(tmp_path, 1)
    assert [s.strategy_id for s in report.strategies] == [
        "sequential", "threads", "processes_spawn",
    ]


def test_single_core_warning_contract() -> None:
    """Komunikat 1 rdzenia: None dla 2+ rdzeni, tekst z 'jednordzeniowe' dla 1."""
    assert build_single_core_warning(2) is None
    assert build_single_core_warning(16) is None
    for count in (1, 0):
        text = build_single_core_warning(count)
        assert text is not None
        assert "jednordzeniowe" in text
        assert "GIL" in text


def test_presets_have_bounded_positive_values() -> None:
    """Presety quick i standard mają dodatnie, ograniczone parametry."""
    assert set(ANALYTICS_PRESETS) == {"quick", "standard"}
    for preset_id, preset in ANALYTICS_PRESETS.items():
        assert isinstance(preset, AnalyticsPreset)
        assert preset.preset_id == preset_id
        for value in (preset.file_count, preset.records_per_file, preset.chunk_size,
                      preset.repeats, preset.work_iterations, preset.max_workers):
            assert 0 < value <= 10_000
    assert get_preset("quick").file_count < get_preset("standard").file_count


def test_get_preset_unknown_raises_and_lookup_is_late() -> None:
    """Nieznany preset zgłasza błąd, a podmiana przez monkeypatch jest widoczna."""
    with pytest.raises(InvalidConfigurationError):
        get_preset("nieznany")
    small = AnalyticsPreset("tiny", "Mini", "opis", 1, 10, 5, 1, 1, 2)
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(ANALYTICS_PRESETS, "tiny", small)
        assert get_preset("tiny") is small


def test_web_analytics_paths_are_under_project_root() -> None:
    """Ścieżki robocze widoku leżą w data/generated/web_analytics, osobno od CLI."""
    root = get_web_analytics_dir()
    assert root == get_project_root() / "data" / "generated" / "web_analytics"
    assert get_web_analytics_log_dir("quick") == root / "logs" / "quick"
    assert get_web_benchmark_dir() == root / "benchmark"


def test_analytics_exception_metadata() -> None:
    """Nowe wyjątki mają kody i statusy HTTP zgodne z kontraktem."""
    busy = AnalyticsJobBusyError("zajęte")
    missing = AnalyticsArtifactNotFoundError("brak pliku")
    dataset = AnalyticsDatasetMissingError("brak zbioru")
    assert (busy.error_code, busy.status_code) == ("ANALYTICS_JOB_BUSY", 409)
    assert (missing.error_code, missing.status_code) == ("ANALYTICS_ARTIFACT_NOT_FOUND", 404)
    assert dataset.error_code == "ANALYTICS_DATASET_MISSING"
