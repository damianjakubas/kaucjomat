"""Testy dekoratora metody, walidowanego settera i metody klasowej koszyka DEMO."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from inspect import signature
from typing import Any

import pytest

from kaucjomat.checkout_domain import Basket, BasketItem, VoucherSettlement
from kaucjomat.checkout_exceptions import (
    InvalidCheckoutRequestError, VoucherAlreadyRedeemedError, VoucherExpiredError,
)
from kaucjomat.voucher_domain import VoucherStatus, create_issued_voucher

NOW = datetime(2026, 11, 15, 12, tzinfo=UTC)


def _settlement() -> VoucherSettlement:
    """Tworzy niezależny obiekt oceny aktywnego bonu w stałym momencie UTC."""
    voucher = create_issued_voucher(
        sequence_no=1, source_session_id="DEMO-GUARD-0001",
        amount_grosze=100, accepted_count=2, now=NOW,
    )
    return VoucherSettlement(voucher, NOW)


def test_method_guard_preserves_metadata_and_signature() -> None:
    """functools.wraps zachowuje nazwę, opis i sygnaturę dekorowanej metody."""
    method = VoucherSettlement.settle
    original = method.__wrapped__
    assert method.__name__ == original.__name__ == "settle"
    assert method.__doc__ == original.__doc__
    assert method.__doc__
    assert signature(method) == signature(original)


@pytest.mark.parametrize("mode", ["cash", "purchases"])
@pytest.mark.parametrize("offset_us", [-1, 0, 1])
def test_guard_checks_exact_expiry_for_both_modes(mode: str, offset_us: int) -> None:
    """Bon jest aktywny mikrosekundę przed terminem i wygasły dokładnie od jego chwili."""
    voucher = _settlement().voucher
    expiry = datetime.fromisoformat(voucher.expires_at_iso)
    settlement = VoucherSettlement(voucher, expiry + timedelta(microseconds=offset_us))
    basket = Basket.from_items([{"product_id": "apple", "quantity": 1}]) if mode == "purchases" else Basket()
    if offset_us < 0:
        assert settlement.settle(mode, basket).voucher_amount_grosze == 100
    else:
        with pytest.raises(VoucherExpiredError) as error:
            settlement.settle(mode, basket)
        assert error.value.error_code == "VOUCHER_EXPIRED"
        assert error.value.status_code == 409
        assert "DEMO" in error.value.message


@pytest.mark.parametrize("days_after_issue", [1, 101])
@pytest.mark.parametrize("mode", ["cash", "purchases"])
def test_redeemed_status_has_priority_over_expiry(days_after_issue: int, mode: str) -> None:
    """Zużyty bon jest blokowany przed i po terminie z tą samą przyczyną odmowy."""
    used = replace(_settlement().voucher, status=VoucherStatus.REDEEMED, redeemed_at_iso=None)
    settlement = VoucherSettlement(used, NOW + timedelta(days=days_after_issue))
    with pytest.raises(VoucherAlreadyRedeemedError) as error:
        settlement.settle(mode, Basket())
    assert error.value.error_code == "VOUCHER_ALREADY_REDEEMED"
    assert error.value.status_code == 409
    assert "DEMO" in error.value.message


def test_guard_uses_voucher_and_time_of_each_instance() -> None:
    """Przeplatanie wywołań nie przenosi bonu ani czasu między instancjami dekoratora."""
    active = _settlement()
    expired = VoucherSettlement(active.voucher, NOW + timedelta(days=100))
    used = VoucherSettlement(replace(active.voucher, status=VoucherStatus.REDEEMED), NOW)
    for _ in range(2):
        with pytest.raises(VoucherExpiredError):
            expired.settle("cash", Basket())
        assert active.settle("cash", Basket()).cash_payout_grosze == 100
        with pytest.raises(VoucherAlreadyRedeemedError):
            used.settle("cash", Basket())
    assert active.voucher.status == VoucherStatus.ACTIVE


@pytest.mark.parametrize("quantity", [0, -1, 100, True, False, "3", 3.0, 1.5, None])
def test_setter_rejection_preserves_quantity_and_total(quantity: Any) -> None:
    """Nieudana edycja ilości nie pozostawia częściowo zmienionej pozycji lub sumy."""
    item = BasketItem("apple", 2)
    basket = Basket((item,))
    with pytest.raises(InvalidCheckoutRequestError):
        item.quantity = quantity
    assert item.quantity == 2
    assert item.line_total_grosze == basket.total_grosze == 300


@pytest.mark.parametrize("quantity", [1, 99])
def test_setter_accepts_quantity_boundaries(quantity: int) -> None:
    """Obie granice ilości można ustawić już po zbudowaniu koszyka."""
    basket = Basket.from_items([{"product_id": "bread-roll", "quantity": 2}])
    basket.items[0].quantity = quantity
    assert basket.total_grosze == quantity * 50


def test_classmethod_uses_cls_and_builds_independent_baskets() -> None:
    """Metoda klasowa tworzy właściwą klasę i niezależne pozycje dla kolejnych koszyków."""
    class DemoBasket(Basket):
        """Wariant koszyka potwierdzający użycie klasy wywołującej metodę."""

    raw = [{"product_id": "apple", "quantity": 2}]
    first, second = DemoBasket.from_items(raw), DemoBasket.from_items(raw)
    assert isinstance(first, DemoBasket) and isinstance(second, DemoBasket)
    first.items[0].quantity = 3
    assert first.total_grosze == 450
    assert second.total_grosze == 300
    assert raw[0]["quantity"] == 2
