"""Walidacja i serializacja rekordów bonów kaucjomatowych DEMO do formatu JSON."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from kaucjomat.voucher_domain import VoucherRecord, VoucherStatus, resolve_voucher_status


def require_str(raw: dict[str, Any], key: str, *, non_empty: bool = False) -> str:
    """Wymaga wartości tekstowej typu ``str`` dla wskazanego klucza rekordu."""
    value = raw.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Pole {key} musi być napisem.")
    if non_empty and not value.strip():
        raise ValueError(f"Pole {key} musi być niepustym napisem.")
    return value


def require_optional_str(raw: dict[str, Any], key: str) -> str | None:
    """Wymaga napisu ``str`` albo ``None`` dla opcjonalnego klucza rekordu."""
    value = raw.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"Pole {key} musi być napisem albo null.")
    return value


def require_int(raw: dict[str, Any], key: str, *, minimum: int | None = None) -> int:
    """Wymaga całkowitej liczby ``int`` (z odrzuceniem ``bool``) dla klucza rekordu."""
    value = raw.get(key)
    # W Pythonie bool dziedziczy po int, więc odrzucamy go jawnie przed porównaniem zakresu.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Pole {key} musi być liczbą całkowitą.")
    if minimum is not None and value < minimum:
        raise ValueError(f"Pole {key} musi być >= {minimum}.")
    return value


def require_bool(raw: dict[str, Any], key: str) -> bool:
    """Wymaga ścisłej wartości logicznej ``bool`` dla wskazanego klucza rekordu."""
    value = raw.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"Pole {key} musi być wartością logiczną bool.")
    return value


def require_utc_iso(value: str, key: str) -> str:
    """Waliduje tekstowy znacznik czasu ISO-8601 z jawną strefą czasową UTC."""
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"Pole {key} nie może być pustym znacznikiem czasu.")
    parsed = datetime.fromisoformat(cleaned)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"Pole {key} musi zawierać strefę czasową UTC.")
    return value


def voucher_record_to_dict(record: VoucherRecord) -> dict[str, Any]:
    """Serializuje rekord bonu DEMO do słownika gotowego do zapisu w pliku JSON."""
    return {
        "voucher_code": record.voucher_code,
        "source_session_id": record.source_session_id,
        "amount_grosze": record.amount_grosze,
        "amount_formatted": record.amount_formatted,
        "accepted_count": record.accepted_count,
        "issued_at_iso": record.issued_at_iso,
        "expires_at_iso": record.expires_at_iso,
        "status": record.status.value,
        "redeemed_at_iso": record.redeemed_at_iso,
        "is_test_seed": record.is_test_seed,
    }


def voucher_dict_to_record(
    raw: dict[str, Any],
    *,
    now: datetime | None = None,
) -> VoucherRecord:
    """Waliduje słownik bonu z JSON i wyznacza aktualny status na podstawie czasu UTC."""
    stored_status = VoucherStatus(require_str(raw, "status", non_empty=True))
    issued_at_iso = require_str(raw, "issued_at_iso", non_empty=True)
    expires_at_iso = require_str(raw, "expires_at_iso", non_empty=True)
    # Walidujemy format ISO i strefę UTC znaczników czasu, aby wcześnie wykryć uszkodzony rekord JSON.
    require_utc_iso(issued_at_iso, "issued_at_iso")
    effective_status = resolve_voucher_status(stored_status, expires_at_iso, now=now)
    redeemed_at_iso = require_optional_str(raw, "redeemed_at_iso")
    if redeemed_at_iso is not None:
        require_utc_iso(redeemed_at_iso, "redeemed_at_iso")

    return VoucherRecord(
        voucher_code=require_str(raw, "voucher_code", non_empty=True),
        source_session_id=require_str(raw, "source_session_id", non_empty=True),
        amount_grosze=require_int(raw, "amount_grosze", minimum=0),
        amount_formatted=require_str(raw, "amount_formatted", non_empty=True),
        accepted_count=require_int(raw, "accepted_count", minimum=0),
        issued_at_iso=issued_at_iso,
        expires_at_iso=expires_at_iso,
        status=effective_status,
        redeemed_at_iso=redeemed_at_iso,
        is_test_seed=require_bool(raw, "is_test_seed"),
    )
