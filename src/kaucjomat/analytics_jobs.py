"""Menedżer zadań w tle widoku Analityka: jeden slot, migawki stanu do odpytywania."""

from __future__ import annotations

import copy
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, Literal

from kaucjomat.analytics_presets import AnalyticsPreset, get_preset
from kaucjomat.analytics_tasks import TASKS, AnalyticsTask
from kaucjomat.config import get_web_analytics_dir
from kaucjomat.exceptions import AnalyticsJobBusyError, InvalidConfigurationError, KaucjomatError
from kaucjomat.logging_config import get_logger, sanitize_for_log

_LOGGER = get_logger("kaucjomat.analytics")
_GENERIC_ERROR_CODE: str = "ANALYTICS_JOB_ERROR"
_GENERIC_ERROR_MESSAGE: str = (
    "Zadanie analityczne zakończyło się nieoczekiwanym błędem; szczegóły zapisano w logu serwera."
)

JobKind = Literal["generate", "analysis", "benchmark"]
JobStatus = Literal["running", "succeeded", "failed"]


@dataclass(frozen=True, slots=True)
class AnalyticsJobSnapshot:
    """Niemutowalna migawka stanu zadania, bezpieczna do przekazania poza blokadę menedżera."""

    job_id: str
    kind: str
    preset_id: str
    status: JobStatus
    phase: str
    progress_done: int | None
    progress_total: int | None
    started_at_iso: str
    finished_at_iso: str | None
    elapsed_ms: float
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None


@dataclass(slots=True)
class _JobState:
    """Zmienny, wewnętrzny stan zadania modyfikowany wyłącznie pod blokadą menedżera."""

    job_id: str
    kind: str
    preset_id: str
    started_at_iso: str
    started_perf: float
    status: JobStatus = "running"
    phase: str = "Uruchamianie zadania"
    progress_done: int | None = None
    progress_total: int | None = None
    finished_at_iso: str | None = None
    elapsed_ms: float = 0.0
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None


class AnalyticsJobContext:
    """Uchwyt przekazywany zadaniu, przez który zgłasza ono fazę i postęp."""

    def __init__(self, update: Callable[..., None]) -> None:
        """Zapamiętuje funkcję aktualizującą stan właściwego zadania."""
        self._update = update

    def set_phase(self, label: str) -> None:
        """Ustawia czytelną etykietę bieżącej fazy zadania."""
        self._update(phase=label)

    def set_progress(self, done: int, total: int) -> None:
        """Zgłasza liczbę wykonanych i wszystkich kroków (np. przebiegów benchmarku)."""
        self._update(progress_done=done, progress_total=total)


class AnalyticsJobManager:
    """Uruchamia jedno zadanie analityczne naraz w wątku w tle i udostępnia jego migawkę."""

    def __init__(
        self, base_dir: Path | None = None, tasks: dict[str, AnalyticsTask] | None = None,
    ) -> None:
        """Ustala katalog roboczy oraz zestaw zadań (testy podstawiają szybkie funkcje)."""
        self._base_dir = Path(base_dir) if base_dir is not None else get_web_analytics_dir()
        self._tasks: dict[str, AnalyticsTask] = dict(tasks) if tasks is not None else dict(TASKS)
        self._lock = threading.Lock()
        self._state: _JobState | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_dir(self) -> Path:
        """Zwraca katalog roboczy przebiegów (logi per preset i wyniki benchmarku)."""
        return self._base_dir

    def start(self, kind: str, preset_id: str) -> AnalyticsJobSnapshot:
        """Zajmuje jedyny slot i uruchamia zadanie; gdy inne trwa, zgłasza błąd 409."""
        if kind not in self._tasks:
            raise InvalidConfigurationError(f"Nieznany rodzaj zadania analityki: '{sanitize_for_log(kind)}'.")
        preset = get_preset(preset_id)
        # Sprawdzenie zajętości i zajęcie slotu to jedna sekcja krytyczna.
        with self._lock:
            if self._state is not None and self._state.status == "running":
                raise AnalyticsJobBusyError("Trwa już inne zadanie analityczne. Poczekaj na jego zakończenie.")
            state = _JobState(
                job_id=uuid.uuid4().hex, kind=kind, preset_id=preset.preset_id,
                started_at_iso=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                started_perf=time.perf_counter(),
            )
            self._state = state
            snapshot = self._snapshot(state)
        thread = threading.Thread(
            target=self._run, args=(state.job_id, kind, preset),
            name=f"analytics-{kind}", daemon=True,
        )
        self._thread = thread
        try:
            thread.start()
        except RuntimeError:
            _LOGGER.exception("Nie udało się uruchomić wątku zadania analityki.")
            self._finish(state.job_id, "failed", None, _GENERIC_ERROR_CODE, _GENERIC_ERROR_MESSAGE)
            raise
        _LOGGER.info("Start zadania analityki: id=%s, kind=%s, preset=%s", state.job_id, kind, preset.preset_id)
        return snapshot

    def current(self) -> AnalyticsJobSnapshot | None:
        """Zwraca migawkę bieżącego lub ostatnio zakończonego zadania albo ``None``."""
        with self._lock:
            return self._snapshot(self._state) if self._state is not None else None

    def wait(self, timeout: float | None = None) -> bool:
        """Czeka na koniec wątku ostatniego zadania; zwraca ``True``, gdy nic już nie działa."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            return not thread.is_alive()
        return True

    def _snapshot(self, state: _JobState) -> AnalyticsJobSnapshot:
        """Buduje niemutowalną kopię stanu; wywoływana wyłącznie pod blokadą."""
        elapsed = (
            (time.perf_counter() - state.started_perf) * 1000.0
            if state.status == "running" else state.elapsed_ms
        )
        return AnalyticsJobSnapshot(
            job_id=state.job_id, kind=state.kind, preset_id=state.preset_id, status=state.status,
            phase=state.phase, progress_done=state.progress_done, progress_total=state.progress_total,
            started_at_iso=state.started_at_iso, finished_at_iso=state.finished_at_iso,
            elapsed_ms=round(elapsed, 1), result=copy.deepcopy(state.result),
            error_code=state.error_code, error_message=state.error_message,
        )

    def _update(self, job_id: str, **fields: Any) -> None:
        """Aktualizuje pola trwającego zadania; zgłoszenia spóźnione lub obce są ignorowane."""
        with self._lock:
            state = self._state
            if state is None or state.job_id != job_id or state.status != "running":
                return
            for name, value in fields.items():
                setattr(state, name, value)

    def _finish(
        self, job_id: str, status: JobStatus, result: dict[str, Any] | None,
        error_code: str | None, error_message: str | None,
    ) -> None:
        """Kończy zadanie i tym samym zwalnia slot; powtórne wywołanie nic nie zmienia."""
        with self._lock:
            state = self._state
            if state is None or state.job_id != job_id or state.status != "running":
                return
            state.status = status
            state.result = result
            state.error_code = error_code
            state.error_message = error_message
            state.finished_at_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
            state.elapsed_ms = (time.perf_counter() - state.started_perf) * 1000.0
        _LOGGER.info("Koniec zadania analityki: id=%s, status=%s, kod=%s", job_id, status, error_code)

    def _run(self, job_id: str, kind: str, preset: AnalyticsPreset) -> None:
        """Wykonuje zadanie w wątku, mapuje błędy na status ``failed`` i zawsze zwalnia slot."""
        context = AnalyticsJobContext(partial(self._update, job_id))
        try:
            result = self._tasks[kind](context, preset, self._base_dir)
        except KaucjomatError as exc:
            _LOGGER.warning(
                "Zadanie analityki %s nieudane [%s]: %s", job_id, exc.error_code,
                sanitize_for_log(exc.message, max_length=200),
            )
            self._finish(job_id, "failed", None, exc.error_code, exc.message)
        except Exception:
            # Szczegóły trafiają wyłącznie do logu; klient dostaje ogólny kod.
            _LOGGER.exception("Nieoczekiwany błąd zadania analityki %s.", job_id)
            self._finish(job_id, "failed", None, _GENERIC_ERROR_CODE, _GENERIC_ERROR_MESSAGE)
        else:
            self._finish(job_id, "succeeded", result, None, None)
        finally:
            self._finish(job_id, "failed", None, _GENERIC_ERROR_CODE, _GENERIC_ERROR_MESSAGE)
