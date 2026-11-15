"""Walidacja schematu JSON i konwersja rekordów stanu sesji zwrotów DEMO."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import math
from typing import Any, Literal
import uuid

from kaucjomat.return_domain import DepositDecision, format_pln_from_grosze

SCHEMA_VERSION = 1
ALLOWED_SESSION_STATUS = "OPEN"


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


def create_empty_state() -> dict[str, Any]:
    """Tworzy słownik reprezentujący czysty stan początkowy magazynu DEMO."""
    return {
        "schema_version": SCHEMA_VERSION,
        "returned_instance_ids": [],
        "session": {
            "session_id": _generate_session_id(),
            "status": ALLOWED_SESSION_STATUS,
            "accepted_count": 0,
            "redirected_glass_count": 0,
            "rejected_count": 0,
            "total_grosze": 0,
            "attempts": [],
        },
    }


def _require_str(raw: dict[str, Any], key: str) -> str:
    """Wymaga wartości tekstowej typu ``str`` dla wskazanego klucza rekordu."""
    value = raw.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Pole {key} musi być napisem.")
    return value


def _require_optional_str(raw: dict[str, Any], key: str) -> str | None:
    """Wymaga napisu ``str`` albo ``None`` dla opcjonalnego klucza rekordu."""
    value = raw.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"Pole {key} musi być napisem albo null.")
    return value


def _require_int(raw: dict[str, Any], key: str, *, minimum: int | None = None) -> int:
    """Wymaga całkowitej liczby ``int`` (z odrzuceniem ``bool``) dla klucza rekordu."""
    value = raw.get(key)
    # W Pythonie bool dziedziczy po int, więc odrzucamy go jawnie przed porównaniem zakresu.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Pole {key} musi być liczbą całkowitą.")
    if minimum is not None and value < minimum:
        raise ValueError(f"Pole {key} musi być >= {minimum}.")
    return value


def _require_finite_float(raw: dict[str, Any], key: str) -> float:
    """Wymaga skończonej liczby rzeczywistej (bez bool, NaN i Infinity)."""
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Pole {key} musi być liczbą.")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0.0:
        raise ValueError(f"Pole {key} musi być skończoną liczbą nieujemną.")
    return numeric


def attempt_dict_to_record(raw: dict[str, Any]) -> SessionAttemptRecord:
    """Konwertuje i ściśle waliduje pojedynczy wpis historii próby z JSON."""
    return SessionAttemptRecord(
        attempt_no=_require_int(raw, "attempt_no", minimum=1),
        timestamp_iso=_require_str(raw, "timestamp_iso"),
        card_id=_require_optional_str(raw, "card_id"),
        package_code=_require_str(raw, "package_code"),
        title=_require_str(raw, "title"),
        category=_require_str(raw, "category"),
        volume_ml=_require_int(raw, "volume_ml"),
        ean=_require_optional_str(raw, "ean"),
        instance_id=_require_optional_str(raw, "instance_id"),
        status=_require_str(raw, "status"),
        reason_code=_require_optional_str(raw, "reason_code"),
        deposit_grosze=_require_int(raw, "deposit_grosze", minimum=0),
        cashier_suggested_grosze=_require_int(raw, "cashier_suggested_grosze", minimum=0),
        message=_require_str(raw, "message"),
        elapsed_ms=_require_finite_float(raw, "elapsed_ms"),
    )


def validate_state_payload(raw: Any) -> tuple[dict[str, Any], tuple[SessionAttemptRecord, ...]]:
    """Waliduje pełny ładunek JSON stanu zwrotów i zwraca zparsowane rekordy prób."""
    if not isinstance(raw, dict):
        raise ValueError("Główna struktura JSON musi być obiektem.")
    if raw.get("schema_version") != SCHEMA_VERSION:
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
    if session.get("status") != ALLOWED_SESSION_STATUS:
        raise ValueError("Nieobsługiwany status sesji zwrotu.")

    for counter_key in ("accepted_count", "redirected_glass_count", "rejected_count", "total_grosze"):
        _require_int(session, counter_key, minimum=0)

    attempts = session.get("attempts")
    if not isinstance(attempts, list) or not all(isinstance(item, dict) for item in attempts):
        raise ValueError("Pole session.attempts musi być listą obiektów.")

    # Jednokrotne parsowanie rekordów podczas odczytu zapobiega podwójnej konwersji później.
    parsed_attempts = tuple(attempt_dict_to_record(item) for item in attempts)
    return raw, parsed_attempts


def decision_to_attempt_dict(
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


def build_session_snapshot(
    state: dict[str, Any],
    attempts: tuple[SessionAttemptRecord, ...],
) -> ReturnSessionSnapshot:
    """Buduje niemodyfikowalną migawkę sesji gotową do serializacji w API."""
    session = state["session"]
    total_grosze = int(session["total_grosze"])
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
