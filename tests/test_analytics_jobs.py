"""Testy menedżera zadań w tle: slot „jedno naraz”, mapowanie błędów, migawki."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from kaucjomat.analytics_jobs import AnalyticsJobContext, AnalyticsJobManager
from kaucjomat.analytics_presets import ANALYTICS_PRESETS, AnalyticsPreset
from kaucjomat.analytics_tasks import run_analysis_task, run_benchmark_task
from kaucjomat.exceptions import (
    AnalyticsDatasetMissingError,
    AnalyticsJobBusyError,
    GilBenchmarkError,
    InvalidConfigurationError,
)

_TINY = AnalyticsPreset("quick", "Mini", "opis", 1, 40, 20, 1, 3, 2)


def _quick_task(context: AnalyticsJobContext, preset: AnalyticsPreset, base_dir: Path) -> dict[str, Any]:
    """Szybkie zadanie testowe zgłaszające fazę i postęp."""
    context.set_phase("Faza testowa")
    context.set_progress(1, 2)
    return {"ok": True}


def _manager(tmp_path: Path, **tasks: Any) -> AnalyticsJobManager:
    """Tworzy menedżer z podstawionymi zadaniami i katalogiem tymczasowym."""
    return AnalyticsJobManager(tmp_path, tasks=tasks)


@pytest.fixture(autouse=True)
def _tiny_quick_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Podmienia preset quick na minimalny, żeby testy nie generowały dużych zbiorów."""
    monkeypatch.setitem(ANALYTICS_PRESETS, "quick", _TINY)


def test_successful_job_snapshot(tmp_path: Path) -> None:
    """Udane zadanie kończy się statusem succeeded z wynikiem, fazą i postępem."""
    manager = _manager(tmp_path, generate=_quick_task)
    assert manager.current() is None
    started = manager.start("generate", "quick")
    assert started.status == "running"
    assert manager.wait(5)
    done = manager.current()
    assert done is not None
    assert (done.status, done.result, done.phase) == ("succeeded", {"ok": True}, "Faza testowa")
    assert (done.progress_done, done.progress_total) == (1, 2)
    assert done.finished_at_iso is not None and done.error_code is None


def test_second_start_while_running_raises_busy(tmp_path: Path) -> None:
    """Drugi start podczas trwania zadania zgłasza AnalyticsJobBusyError, a slot się zwalnia."""
    gate = threading.Event()

    def blocking(context: AnalyticsJobContext, preset: AnalyticsPreset, base_dir: Path) -> dict[str, Any]:
        """Zadanie czekające na sygnał z testu."""
        gate.wait(5)
        return {}

    manager = _manager(tmp_path, generate=blocking)
    manager.start("generate", "quick")
    with pytest.raises(AnalyticsJobBusyError):
        manager.start("generate", "quick")
    gate.set()
    assert manager.wait(5)
    assert manager.start("generate", "quick").status == "running"
    assert manager.wait(5)


def test_domain_error_maps_to_failed_with_code(tmp_path: Path) -> None:
    """Błąd domenowy zachowuje kod, ukrywa szczegóły w komunikacie i zwalnia slot."""
    def failing(context: AnalyticsJobContext, preset: AnalyticsPreset, base_dir: Path) -> dict[str, Any]:
        """Zadanie zgłaszające błąd silnika."""
        raise GilBenchmarkError("Awaria testowa: C:/private/benchmark.json")

    manager = _manager(tmp_path, benchmark=failing, generate=_quick_task)
    manager.start("benchmark", "quick")
    assert manager.wait(5)
    snap = manager.current()
    assert snap is not None
    assert (snap.status, snap.error_code, snap.error_message) == (
        "failed", "GIL_BENCHMARK_ERROR",
        "Nie udało się wykonać zadania analitycznego; szczegóły zapisano w logu serwera.",
    )
    manager.start("generate", "quick")
    assert manager.wait(5)


def test_non_domain_error_hides_details(tmp_path: Path) -> None:
    """Wyjątek niedomenowy daje ogólny kod bez treści wyjątku."""
    def crashing(context: AnalyticsJobContext, preset: AnalyticsPreset, base_dir: Path) -> dict[str, Any]:
        """Zadanie rzucające wyjątek z wrażliwą treścią."""
        raise RuntimeError("C:\\sekretna\\sciezka")

    manager = _manager(tmp_path, generate=crashing)
    manager.start("generate", "quick")
    assert manager.wait(5)
    snap = manager.current()
    assert snap is not None
    assert snap.status == "failed" and snap.error_code == "ANALYTICS_JOB_ERROR"
    assert "sekretna" not in (snap.error_message or "")


@pytest.mark.parametrize("task", [run_analysis_task, run_benchmark_task])
def test_missing_dataset_fails_without_generating(tmp_path: Path, task: Any) -> None:
    """Analiza i benchmark bez wygenerowanego zbioru kończą się ANALYTICS_DATASET_MISSING."""
    manager = _manager(tmp_path, analysis=task, benchmark=task)
    kind = "analysis" if task is run_analysis_task else "benchmark"
    manager.start(kind, "quick")
    assert manager.wait(10)
    snap = manager.current()
    assert snap is not None
    assert (snap.status, snap.error_code) == ("failed", AnalyticsDatasetMissingError.error_code)
    assert not (tmp_path / "logs").exists()


def test_snapshot_is_immutable_copy(tmp_path: Path) -> None:
    """Zmiana słownika wyniku w migawce nie wpływa na stan menedżera."""
    manager = _manager(tmp_path, generate=_quick_task)
    manager.start("generate", "quick")
    assert manager.wait(5)
    first = manager.current()
    assert first is not None and first.result is not None
    first.result["ok"] = False
    with pytest.raises(AttributeError):
        first.status = "running"  # type: ignore[misc]
    second = manager.current()
    assert second is not None and second.result == {"ok": True}


def test_invalid_kind_and_preset_rejected_before_slot(tmp_path: Path) -> None:
    """Nieznany rodzaj lub preset zgłasza błąd konfiguracji i nie zajmuje slotu."""
    manager = _manager(tmp_path, generate=_quick_task)
    with pytest.raises(InvalidConfigurationError):
        manager.start("nieznany", "quick")
    with pytest.raises(InvalidConfigurationError):
        manager.start("generate", "nieznany")
    assert manager.current() is None
