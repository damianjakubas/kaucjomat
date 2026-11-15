"""Bezpieczny wątkowo magazyn stanu rejestru zwróconych egzemplarzy i sesji DEMO."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from kaucjomat.exceptions import ReturnStateStorageError
from kaucjomat.logging_config import get_logger
from kaucjomat.return_domain import (
    DecisionStatus,
    DepositDecision,
    PackageCandidate,
    evaluate_package_return,
    format_pln_from_grosze,
)

_SCHEMA_VERSION = 1
_ALLOWED_SESSION_STATUS = "OPEN"


@dataclass(frozen=True, slots=True)
class SessionAttemptRecord:
    """Pojedynczy wpis historii wrzutu opakowania w aktywnej sesji DEMO."""

    attempt_no: int
    timestamp_iso: str
    card_id: str | None
    package_code: str
    title: str
    category: str
    volume_ml: int
    ean: str | None
    instance_id: str | None
    status: str
    reason_code: str | None
    deposit_grosze: int
    cashier_suggested_grosze: int
    message: str
    elapsed_ms: float


@dataclass(frozen=True, slots=True)
class ReturnSessionSnapshot:
    """Niemodyfikowalna migawka bieżącej sesji zwrotu oraz rozmiaru rejestru DEMO."""

    session_id: str
    status: Literal["OPEN"]
    accepted_count: int
    redirected_glass_count: int
    rejected_count: int
    total_grosze: int
    total_formatted: str
    returned_registry_size: int
    can_issue_voucher: bool
    attempts: tuple[SessionAttemptRecord, ...]


def _generate_session_id() -> str:
    """Generuje czytelny identyfikator nowej sesji demonstracyjnej."""
    return f"DEMO-{uuid.uuid4().hex[:8].upper()}"


def _create_empty_state() -> dict[str, Any]:
    """Tworzy słownik reprezentujący czysty stan początkowy magazynu DEMO."""
    return {
        "schema_version": _SCHEMA_VERSION,
        "returned_instance_ids": [],
        "session": {
            "session_id": _generate_session_id(),
            "status": _ALLOWED_SESSION_STATUS,
            "accepted_count": 0,
            "redirected_glass_count": 0,
            "rejected_count": 0,
            "total_grosze": 0,
            "attempts": [],
        },
    }


def _validate_state_payload(raw: Any) -> dict[str, Any]:
    """Waliduje strukturę i typy danych wczytanych z pliku JSON stanu zwrotów."""
    if not isinstance(raw, dict):
        raise ValueError("Główna struktura JSON musi być obiektem.")

    if raw.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("Nieobsługiwana wersja schematu pliku stanu.")

    returned_ids = raw.get("returned_instance_ids")
    if not isinstance(returned_ids, list) or not all(isinstance(item, str) for item in returned_ids):
        raise ValueError("Pole returned_instance_ids musi być listą napisów.")

    session = raw.get("session")
    if not isinstance(session, dict):
        raise ValueError("Pole session musi być obiektem.")

    session_id = session.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Pole session.session_id musi być niepustym napisem.")

    if session.get("status") != _ALLOWED_SESSION_STATUS:
        raise ValueError("Nieobsługiwany status sesji zwrotu.")

    for counter_key in ("accepted_count", "redirected_glass_count", "rejected_count", "total_grosze"):
        value = session.get(counter_key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"Licznik {counter_key} musi być nieujemną liczbą całkowitą.")

    attempts = session.get("attempts")
    if not isinstance(attempts, list) or not all(isinstance(item, dict) for item in attempts):
        raise ValueError("Pole session.attempts musi być listą obiektów.")

    return raw


def _attempt_dict_to_record(raw: dict[str, Any]) -> SessionAttemptRecord:
    """Konwertuje pojedynczy słownik historii próby na rekord ``SessionAttemptRecord``."""
    return SessionAttemptRecord(
        attempt_no=int(raw["attempt_no"]),
        timestamp_iso=str(raw["timestamp_iso"]),
        card_id=str(raw["card_id"]) if raw.get("card_id") is not None else None,
        package_code=str(raw["package_code"]),
        title=str(raw["title"]),
        category=str(raw["category"]),
        volume_ml=int(raw["volume_ml"]),
        ean=str(raw["ean"]) if raw.get("ean") is not None else None,
        instance_id=str(raw["instance_id"]) if raw.get("instance_id") is not None else None,
        status=str(raw["status"]),
        reason_code=str(raw["reason_code"]) if raw.get("reason_code") is not None else None,
        deposit_grosze=int(raw["deposit_grosze"]),
        cashier_suggested_grosze=int(raw["cashier_suggested_grosze"]),
        message=str(raw["message"]),
        elapsed_ms=float(raw["elapsed_ms"]),
    )


def _decision_to_attempt_dict(
    attempt_no: int,
    card_id: str | None,
    decision: DepositDecision,
) -> dict[str, Any]:
    """Konwertuje wynik oceny skanera na słownik serializowany do JSON."""
    return {
        "attempt_no": attempt_no,
        "timestamp_iso": datetime.now(UTC).isoformat(timespec="seconds"),
        "card_id": card_id,
        "package_code": decision.package_code,
        "title": decision.title,
        "category": decision.category.value,
        "volume_ml": decision.volume_ml,
        "ean": decision.ean,
        "instance_id": decision.instance_id,
        "status": decision.status.value,
        "reason_code": decision.reason_code.value if decision.reason_code is not None else None,
        "deposit_grosze": decision.deposit_grosze,
        "cashier_suggested_grosze": decision.cashier_suggested_grosze,
        "message": decision.message,
        "elapsed_ms": decision.elapsed_ms,
    }


class ReturnStateStore:
    """Magazyn stanu rejestru zwróconych sztuk i aktywnej sesji DEMO w pliku JSON."""

    def __init__(self, state_file: Path) -> None:
        """Inicjalizuje magazyn ze ścieżką pliku JSON i blokadą wątkową."""
        self._lock = threading.Lock()
        self._state_file = Path(state_file)
        self._logger = get_logger("returns.store")

    def get_session_snapshot(self) -> ReturnSessionSnapshot:
        """Bezpiecznie wątkowo wczytuje lub inicjalizuje stan i zwraca migawkę sesji."""
        with self._lock:
            state, initialized = self._load_state()
            # Zapis początkowego stanu zapewnia niezmienny identyfikator sesji od pierwszego odczytu.
            if initialized:
                self._save_state(state)
            return self._build_snapshot(state)

    def process_deposit(
        self,
        candidate: PackageCandidate,
        card_id: str | None = None,
    ) -> tuple[DepositDecision, ReturnSessionSnapshot]:
        """Ocenia wrzut opakowania, aktualizuje stan pod blokadą i zapisuje plik JSON."""
        with self._lock:
            state, _ = self._load_state()
            returned_ids: set[str] = set(state["returned_instance_ids"])
            decision = evaluate_package_return(candidate, returned_ids)

            session = state["session"]
            if decision.status == DecisionStatus.ACCEPTED:
                session["accepted_count"] += 1
                session["total_grosze"] += decision.deposit_grosze
                if (
                    decision.instance_id is not None
                    and decision.instance_id not in returned_ids
                ):
                    state["returned_instance_ids"].append(decision.instance_id)
            elif decision.status == DecisionStatus.REDIRECT_TO_CASHIER:
                session["redirected_glass_count"] += 1
            else:
                session["rejected_count"] += 1

            attempts: list[dict[str, Any]] = session["attempts"]
            attempt_no = len(attempts) + 1
            # Najnowsza próba trafia na początek listy historii wyświetlanej na panelu DEMO.
            attempts.insert(0, _decision_to_attempt_dict(attempt_no, card_id, decision))

            self._save_state(state)
            return decision, self._build_snapshot(state)

    def reset_demo_state(self) -> ReturnSessionSnapshot:
        """Czyści trwały rejestr zwróconych ID oraz rozpoczyna nową czystą sesję DEMO."""
        with self._lock:
            state = _create_empty_state()
            self._save_state(state)
            self._logger.info(
                "Zresetowano stan rejestru i sesji DEMO (nowa sesja: %s).",
                state["session"]["session_id"],
            )
            return self._build_snapshot(state)

    def _load_state(self) -> tuple[dict[str, Any], bool]:
        """Wczytuje i waliduje stan z pliku JSON lub tworzy czysty stan początkowy."""
        if not self._state_file.exists():
            return _create_empty_state(), True

        try:
            raw_text = self._state_file.read_text(encoding="utf-8")
            parsed = json.loads(raw_text)
            validated = _validate_state_payload(parsed)
            # Weryfikujemy również poprawność pól istniejących wpisów historii.
            for attempt in validated["session"]["attempts"]:
                _attempt_dict_to_record(attempt)
            return validated, False
        except (OSError, json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
            self._logger.error(
                "Nie udało się wczytać pliku stanu zwrotów DEMO.",
                exc_info=True,
            )
            raise ReturnStateStorageError(
                "Nie udało się odczytać zapisanego stanu sesji zwrotów DEMO."
            ) from exc

    def _save_state(self, state: dict[str, Any]) -> None:
        """Zapisuje stan magazynu atomowo przez plik tymczasowy i zamianę ścieżki."""
        tmp_path = self._state_file.with_name(f"{self._state_file.name}.{uuid.uuid4().hex}.tmp")
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            serialized = json.dumps(state, ensure_ascii=False, indent=2)
            tmp_path.write_text(serialized, encoding="utf-8")
            tmp_path.replace(self._state_file)
        except OSError as exc:
            tmp_path.unlink(missing_ok=True)
            self._logger.error(
                "Nie udało się zapisać pliku stanu zwrotów DEMO.",
                exc_info=True,
            )
            raise ReturnStateStorageError(
                "Nie udało się zapisać aktualnego stanu sesji zwrotów DEMO."
            ) from exc

    def _build_snapshot(self, state: dict[str, Any]) -> ReturnSessionSnapshot:
        """Buduje niemodyfikowalną migawkę sesji gotową do serializacji w API."""
        session = state["session"]
        total_grosze = int(session["total_grosze"])
        attempts = tuple(_attempt_dict_to_record(item) for item in session["attempts"])
        return ReturnSessionSnapshot(
            session_id=str(session["session_id"]),
            status="OPEN",
            accepted_count=int(session["accepted_count"]),
            redirected_glass_count=int(session["redirected_glass_count"]),
            rejected_count=int(session["rejected_count"]),
            total_grosze=total_grosze,
            total_formatted=format_pln_from_grosze(total_grosze),
            returned_registry_size=len(state["returned_instance_ids"]),
            can_issue_voucher=total_grosze > 0,
            attempts=attempts,
        )
