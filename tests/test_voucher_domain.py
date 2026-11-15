"""Testy jednostkowe domeny bonów kaucyjnych DEMO, ważności 100 dni oraz bonu wygasłego."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kaucjomat.exceptions import EmptyReturnSessionError, InvalidConfigurationError
from kaucjomat.voucher_domain import (
    EXPIRED_TEST_VOUCHER_CODE,
    EXPIRED_TEST_VOUCHER_SESSION_ID,
    VOUCHER_VALIDITY_DAYS,
    VoucherStatus,
    create_expired_test_voucher,
    create_issued_voucher,
    generate_voucher_code,
    resolve_voucher_status,
)


def test_create_issued_voucher_sets_100_day_validity_and_demo_code() -> None:
    """Sprawdza wystawienie bonu DEMO z ważnością dokładnie +100 dni od czasu UTC."""
    issued_now = datetime(2026, 11, 15, 18, 30, 0, tzinfo=UTC)
    voucher = create_issued_voucher(
        sequence_no=1,
        source_session_id="SES-20261115-a7f2",
        amount_grosze=150,
        accepted_count=3,
        now=issued_now,
    )

    issued_at = datetime.fromisoformat(voucher.issued_at_iso)
    expires_at = datetime.fromisoformat(voucher.expires_at_iso)

    assert voucher.voucher_code == "BON-DEMO-0001-A7F2"
    assert voucher.source_session_id == "SES-20261115-a7f2"
    assert voucher.amount_grosze == 150
    assert voucher.amount_formatted == "1,50 zł"
    assert voucher.accepted_count == 3
    assert voucher.status == VoucherStatus.ACTIVE
    assert voucher.redeemed_at_iso is None
    assert voucher.is_test_seed is False
    assert expires_at - issued_at == timedelta(days=VOUCHER_VALIDITY_DAYS)


def test_resolve_voucher_status_boundary_and_redeemed_priority() -> None:
    """Weryfikuje przejście AKTYWNY -> WYGASŁY na granicy terminu oraz priorytet ZUŻYTY."""
    issued_now = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)
    voucher = create_issued_voucher(
        sequence_no=2,
        source_session_id="SES-20261115-009B",
        amount_grosze=100,
        accepted_count=2,
        now=issued_now,
    )
    expires_at = datetime.fromisoformat(voucher.expires_at_iso)

    assert (
        resolve_voucher_status(
            voucher.status,
            voucher.expires_at_iso,
            now=expires_at - timedelta(seconds=1),
        )
        == VoucherStatus.ACTIVE
    )
    assert (
        resolve_voucher_status(
            voucher.status,
            voucher.expires_at_iso,
            now=expires_at,
        )
        == VoucherStatus.EXPIRED
    )
    assert (
        resolve_voucher_status(
            voucher.status,
            voucher.expires_at_iso,
            now=expires_at + timedelta(days=5),
        )
        == VoucherStatus.EXPIRED
    )
    assert (
        resolve_voucher_status(
            VoucherStatus.REDEEMED,
            voucher.expires_at_iso,
            now=expires_at + timedelta(days=5),
        )
        == VoucherStatus.REDEEMED
    )


def test_create_expired_test_voucher_matches_kz13_seed_contract() -> None:
    """Sprawdza deterministyczny testowy bon wygasły (KZ-13) z wyraźnym oznaczeniem DEMO."""
    seed_voucher = create_expired_test_voucher()
    issued_at = datetime.fromisoformat(seed_voucher.issued_at_iso)
    expires_at = datetime.fromisoformat(seed_voucher.expires_at_iso)

    assert seed_voucher.voucher_code == EXPIRED_TEST_VOUCHER_CODE
    assert seed_voucher.voucher_code == "BON-DEMO-EXP-0001"
    assert "DEMO" in seed_voucher.voucher_code
    assert seed_voucher.source_session_id == EXPIRED_TEST_VOUCHER_SESSION_ID
    assert seed_voucher.amount_grosze == 150
    assert seed_voucher.amount_formatted == "1,50 zł"
    assert seed_voucher.accepted_count == 3
    assert seed_voucher.status == VoucherStatus.EXPIRED
    assert seed_voucher.is_test_seed is True
    assert expires_at - issued_at == timedelta(days=VOUCHER_VALIDITY_DAYS)
    assert (
        resolve_voucher_status(
            seed_voucher.status,
            seed_voucher.expires_at_iso,
            now=datetime(2026, 11, 15, 19, 0, 0, tzinfo=UTC),
        )
        == VoucherStatus.EXPIRED
    )


def test_generate_voucher_code_pads_short_session_suffix() -> None:
    """Weryfikuje deterministyczne formatowanie i uzupełnianie krótkiego sufiksu sesji."""
    assert generate_voucher_code(7, "ab-1") == "BON-DEMO-0007-0AB1"
    assert generate_voucher_code(12, "SES-XYZ-9876") == "BON-DEMO-0012-9876"


@pytest.mark.parametrize(
    ("amount_grosze", "accepted_count"),
    [
        (0, 1),
        (-50, 1),
        (50, 0),
        (0, 0),
    ],
)
def test_create_issued_voucher_rejects_empty_or_negative_session(
    amount_grosze: int,
    accepted_count: int,
) -> None:
    """Sprawdza odrzucenie próby wystawienia bonu przy pustej lub zerowej sesji."""
    with pytest.raises(EmptyReturnSessionError):
        create_issued_voucher(
            sequence_no=1,
            source_session_id="SES-EMPTY-0001",
            amount_grosze=amount_grosze,
            accepted_count=accepted_count,
        )


def test_voucher_domain_rejects_invalid_sequence_or_naive_datetime() -> None:
    """Weryfikuje jawne błędy konfiguracji dla złego numeru sekwencyjnego i naiwnego czasu."""
    with pytest.raises(InvalidConfigurationError):
        generate_voucher_code(0, "SES-0001")

    with pytest.raises(InvalidConfigurationError):
        create_issued_voucher(
            sequence_no=1,
            source_session_id="   ",
            amount_grosze=50,
            accepted_count=1,
        )

    with pytest.raises(InvalidConfigurationError):
        create_issued_voucher(
            sequence_no=1,
            source_session_id="SES-0001",
            amount_grosze=50,
            accepted_count=1,
            now=datetime(2026, 11, 15, 12, 0, 0),
        )
