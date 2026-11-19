"""Logika domenowa bonów kaucyjnych DEMO, ważności 100 dni oraz bonu testowego."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final

from kaucjomat.exceptions import EmptyReturnSessionError, InvalidConfigurationError
from kaucjomat.logging_config import get_logger
from kaucjomat.return_domain import format_pln_from_grosze


logger = get_logger("returns")

VOUCHER_VALIDITY_DAYS: Final[int] = 100
EXPIRED_TEST_VOUCHER_CODE: Final[str] = "BON-DEMO-EXP-0001"
EXPIRED_TEST_VOUCHER_SESSION_ID: Final[str] = "DEMO-SEED-EXP0001"


class VoucherStatus(StrEnum):
    """Możliwe statusy bonu kaucyjnego DEMO w cyklu jego życia."""

    ACTIVE = "AKTYWNY"
    REDEEMED = "ZUŻYTY"
    EXPIRED = "WYGASŁY"


@dataclass(frozen=True, slots=True)
class VoucherRecord:
    """Niezmienny rekord bonu kaucyjnego DEMO wraz ze znacznikiem seeda testowego."""

    voucher_code: str
    source_session_id: str
    amount_grosze: int
    amount_formatted: str
    accepted_count: int
    issued_at_iso: str
    expires_at_iso: str
    status: VoucherStatus
    redeemed_at_iso: str | None = None
    is_test_seed: bool = False


def _normalize_utc(moment: datetime, *, field_name: str = "now") -> datetime:
    """Waliduje obecność strefy czasowej i sprowadza znacznik czasu do UTC."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise InvalidConfigurationError(
            f"Znacznik czasu '{field_name}' musi posiadać jawnie określoną strefę czasową (UTC)."
        )
    return moment.astimezone(UTC)


def _parse_utc_iso(iso_timestamp: str, *, field_name: str = "expires_at_iso") -> datetime:
    """Parsuje tekstowy znacznik czasu ISO-8601 ze strefą czasową do obiektu UTC."""
    cleaned = iso_timestamp.strip()
    if not cleaned:
        raise InvalidConfigurationError(
            f"Pole czasu '{field_name}' w rekordzie bonu DEMO nie może być puste."
        )
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise InvalidConfigurationError(
            f"Pole czasu '{field_name}' ma niepoprawny format ISO-8601: {cleaned}."
        ) from exc
    return _normalize_utc(parsed, field_name=field_name)


def resolve_voucher_status(
    stored_status: VoucherStatus,
    expires_at_iso: str,
    *,
    now: datetime | None = None,
) -> VoucherStatus:
    """Wyznacza efektywny status bonu DEMO na podstawie stanu trwałego i czasu ważności."""
    # Status zużycia ma bezwzględny priorytet nad późniejszym upływem terminu ważności.
    if stored_status == VoucherStatus.REDEEMED:
        return VoucherStatus.REDEEMED

    expires_at = _parse_utc_iso(expires_at_iso, field_name="expires_at_iso")
    effective_now = (
        _normalize_utc(now, field_name="now") if now is not None else datetime.now(UTC)
    )
    if effective_now >= expires_at:
        return VoucherStatus.EXPIRED
    return VoucherStatus.ACTIVE


def generate_voucher_code(sequence_no: int, source_session_id: str) -> str:
    """Tworzy deterministyczny numer bonu DEMO w formacie BON-DEMO-NNNN-XXXX."""
    if sequence_no < 1:
        raise InvalidConfigurationError(
            "Numer sekwencyjny bonu DEMO musi być liczbą całkowitą >= 1."
        )
    cleaned_session_id = source_session_id.strip()
    if not cleaned_session_id:
        raise InvalidConfigurationError(
            "Identyfikator sesji źródłowej dla numeru bonu DEMO nie może być pusty."
        )
    alnum_chars = "".join(
        character for character in cleaned_session_id if character.isascii() and character.isalnum()
    ).upper()
    suffix = alnum_chars[-4:].rjust(4, "0")
    return f"BON-DEMO-{sequence_no:04d}-{suffix}"


def create_issued_voucher(
    *,
    sequence_no: int,
    source_session_id: str,
    amount_grosze: int,
    accepted_count: int,
    now: datetime | None = None,
) -> VoucherRecord:
    """Wystawia nowy aktywny bon kaucyjny DEMO ważny dokładnie 100 dni od wystawienia."""
    if sequence_no < 1:
        raise InvalidConfigurationError(
            "Numer sekwencyjny bonu DEMO musi być liczbą całkowitą >= 1."
        )
    cleaned_session_id = source_session_id.strip()
    if not cleaned_session_id:
        raise InvalidConfigurationError(
            "Identyfikator sesji źródłowej bonu DEMO nie może być pusty."
        )
    if amount_grosze <= 0 or accepted_count <= 0:
        raise EmptyReturnSessionError(
            "Nie można wystawić bonu DEMO dla pustej sesji zwrotu o wartości 0,00 zł."
        )

    issued_at = _normalize_utc(now, field_name="now") if now is not None else datetime.now(UTC)
    expires_at = issued_at + timedelta(days=VOUCHER_VALIDITY_DAYS)
    voucher_code = generate_voucher_code(sequence_no, cleaned_session_id)
    amount_formatted = format_pln_from_grosze(amount_grosze)

    logger.info(
        "Utworzono domenowo bon DEMO %s na kwotę %s (%d szt.).",
        voucher_code,
        amount_formatted,
        accepted_count,
    )
    return VoucherRecord(
        voucher_code=voucher_code,
        source_session_id=cleaned_session_id,
        amount_grosze=amount_grosze,
        amount_formatted=amount_formatted,
        accepted_count=accepted_count,
        issued_at_iso=issued_at.isoformat(),
        expires_at_iso=expires_at.isoformat(),
        status=VoucherStatus.ACTIVE,
        redeemed_at_iso=None,
        is_test_seed=False,
    )


def create_expired_test_voucher() -> VoucherRecord:
    """Zwraca predefiniowany testowy bon wygasły DEMO gotowy do demonstracji w kasie."""
    # Stałe daty historyczne (100 dni odstępu) zapewniają status WYGASŁY bez czekania na obronie.
    return VoucherRecord(
        voucher_code=EXPIRED_TEST_VOUCHER_CODE,
        source_session_id=EXPIRED_TEST_VOUCHER_SESSION_ID,
        amount_grosze=150,
        amount_formatted=format_pln_from_grosze(150),
        accepted_count=3,
        issued_at_iso="2026-01-02T10:00:00+00:00",
        expires_at_iso="2026-04-12T10:00:00+00:00",
        status=VoucherStatus.EXPIRED,
        redeemed_at_iso=None,
        is_test_seed=True,
    )
