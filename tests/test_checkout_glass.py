"""Testy kwalifikacji szkła i rozliczenia kaucji wraz z aktywnym bonem DEMO."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from kaucjomat.checkout_catalog import GlassReturnSpec, get_glass_return_spec
from kaucjomat.checkout_domain import (
    DEFAULT_GLASS_VOLUME_ML, GLASS_MAX_VOLUME_ML, GLASS_UNIT_DEPOSIT_GROSZE,
    MAX_GLASS_COUNT, Basket, GlassReturn, RedemptionMode, SettlementResult, VoucherSettlement,
)
from kaucjomat.checkout_exceptions import (
    BasketTooSmallError, InvalidCheckoutRequestError, VoucherAlreadyRedeemedError, VoucherExpiredError,
)
from kaucjomat.checkout_state_codec import settlement_from_dict, settlement_to_dict
from kaucjomat.voucher_domain import VoucherStatus, create_issued_voucher

NOW = datetime(2026, 11, 16, 12, tzinfo=UTC)


def _settlement(amount_grosze: int = 100) -> VoucherSettlement:
    """Tworzy rozliczenie aktywnego bonu w stałym momencie niezależnym od zegara."""
    voucher = create_issued_voucher(
        sequence_no=1, source_session_id="DEMO-GLASS-0001",
        amount_grosze=amount_grosze, accepted_count=2, now=NOW,
    )
    return VoucherSettlement(voucher, NOW)


def test_glass_spec_matches_domain_and_is_immutable() -> None:
    """Kasa udostępnia niezmienne zasady zwrotu szkła zgodne z limitami domeny."""
    spec = get_glass_return_spec()
    assert isinstance(spec, GlassReturnSpec)
    assert "szklana" in spec.title and "wielokrotnego użytku" in spec.title
    assert "1,5 l" in spec.title
    assert spec.unit_deposit_grosze == GLASS_UNIT_DEPOSIT_GROSZE == 100
    assert spec.max_volume_ml == GLASS_MAX_VOLUME_ML == 1500
    assert spec.max_quantity == MAX_GLASS_COUNT == 20
    with pytest.raises(FrozenInstanceError):
        spec.unit_deposit_grosze = 1


@pytest.mark.parametrize("count", [0, 1, 2, 20])
@pytest.mark.parametrize("volume_ml", [1, 500, 1500])
def test_glass_accepts_boundaries_and_calculates_deposit(count: int, volume_ml: int) -> None:
    """Obie drogi tworzenia modelu respektują granice i naliczają 100 gr za sztukę."""
    glass = GlassReturn(count, volume_ml)
    assert GlassReturn.from_count(count, volume_ml=volume_ml) == glass
    assert glass.count == count and glass.volume_ml == volume_ml
    assert glass.total_grosze == count * 100


def test_glass_defaults_and_empty_return_do_not_require_volume() -> None:
    """Domyślny zwrot jest pusty, a bez butelek pojemność nie wpływa na kwalifikację."""
    assert GlassReturn() == GlassReturn.from_count()
    assert GlassReturn().volume_ml == DEFAULT_GLASS_VOLUME_ML == 500
    assert GlassReturn().total_grosze == 0
    assert GlassReturn(0, volume_ml=0).total_grosze == 0


@pytest.mark.parametrize("count", [-1, 21, True, False, 1.0, 1.5, "1", None, [], {}])
def test_glass_rejects_invalid_count(count: Any) -> None:
    """Niepoprawna liczba sztuk daje wyjątek domenowy także bez warstwy HTTP."""
    with pytest.raises(InvalidCheckoutRequestError, match="0–20"):
        GlassReturn(count)
    with pytest.raises(InvalidCheckoutRequestError, match="0–20"):
        GlassReturn.from_count(count)


@pytest.mark.parametrize("volume_ml", [-1, 0, 1501, True, False, 500.0, 1.5, "500", None])
def test_glass_rejects_invalid_volume_for_positive_count(volume_ml: Any) -> None:
    """Dodatni zwrot wymaga całkowitej pojemności najwyżej 1500 ml, bez bool."""
    with pytest.raises(InvalidCheckoutRequestError, match=r"1500 ml.*1,5 l"):
        GlassReturn(1, volume_ml)
    with pytest.raises(InvalidCheckoutRequestError, match=r"1500 ml.*1,5 l"):
        GlassReturn.from_count(1, volume_ml=volume_ml)


def test_glass_return_is_immutable() -> None:
    """Po kwalifikacji nie można nadpisać liczby sztuk ani pojemności butelek."""
    glass = GlassReturn(2, 1500)
    for attribute in ("count", "volume_ml"):
        with pytest.raises(FrozenInstanceError):
            setattr(glass, attribute, 21)


@pytest.mark.parametrize(("voucher_amount", "due"), [(99, 1), (100, 0), (101, None)])
@pytest.mark.parametrize("glass", [2, GlassReturn(2, 1500)])
def test_purchases_with_glass_boundary_to_single_grosz(
    voucher_amount: int, due: int | None, glass: GlassReturn | int,
) -> None:
    """Zakupy wymagają pokrycia sumy bonu i szkła z dokładnością do jednego grosza."""
    settlement = _settlement(voucher_amount)
    basket = Basket.from_items([{"product_id": "apple", "quantity": 2}])
    if due is None:
        with pytest.raises(BasketTooSmallError) as error:
            settlement.settle("purchases", basket, glass)
        assert error.value.error_code == "BASKET_TOO_SMALL"
        assert error.value.status_code == 409
        assert "suma bonu i zwróconego szkła" in error.value.message
        assert "wypłatę gotówki" in error.value.message
    else:
        result = settlement.settle(RedemptionMode.PURCHASES, basket, glass)
        assert result.basket_total_grosze == 300
        assert result.voucher_amount_grosze == voucher_amount
        assert result.amount_due_grosze == due
        assert result.cash_payout_grosze == 0
        assert result.glass_count == 2 and result.glass_return_grosze == 200
    assert settlement.voucher.status == VoucherStatus.ACTIVE
    assert settlement.voucher.redeemed_at_iso is None
    assert basket.total_grosze == 300


@pytest.mark.parametrize("glass", [1, 20, GlassReturn(2, 1500)])
def test_cash_pays_voucher_plus_glass(glass: GlassReturn | int) -> None:
    """Gotówka wypłaca sumę bonu i kaucji za szkło przy pustej liście zakupów."""
    result = _settlement(150).settle("cash", Basket(), glass_return=glass)
    count = glass.count if isinstance(glass, GlassReturn) else glass
    assert result.items == ()
    assert result.basket_total_grosze == result.amount_due_grosze == 0
    assert result.voucher_amount_grosze == 150
    assert result.cash_payout_grosze == 150 + count * 100
    assert result.glass_count == count and result.glass_return_grosze == count * 100
    assert result.voucher_status == VoucherStatus.REDEEMED and result.mode == "DEMO"


def test_cash_with_glass_rejects_nonempty_basket() -> None:
    """Szkło nie umożliwia mieszania zakupów z wypłatą gotówki w jednej operacji."""
    basket = Basket.from_items([{"product_id": "bread-roll", "quantity": 1}])
    with pytest.raises(InvalidCheckoutRequestError, match="pustej listy"):
        _settlement().settle("cash", basket, GlassReturn(2))
    assert basket.total_grosze == 50


@pytest.mark.parametrize("mode", ["purchases", "cash"])
@pytest.mark.parametrize("glass", [-1, 21, True, False, 1.0, 1.5, "1", None, [], {}])
def test_settlement_rejects_invalid_glass_argument(mode: str, glass: Any) -> None:
    """Rozliczenie przyjmuje wyłącznie zwalidowany model szkła lub całkowitą liczbę sztuk."""
    basket = Basket.from_items([{"product_id": "bread", "quantity": 10}]) if mode == "purchases" else Basket()
    with pytest.raises(InvalidCheckoutRequestError):
        _settlement().settle(mode, basket, glass)


@pytest.mark.parametrize("mode", ["purchases", "cash"])
def test_omitted_and_explicit_zero_glass_preserve_existing_settlement(mode: str) -> None:
    """Stare wywołania bez szkła i jawne zero dają jednakowy wynik rozliczenia."""
    basket = Basket.from_items([{"product_id": "apple", "quantity": 1}]) if mode == "purchases" else Basket()
    settlement = _settlement()
    result = settlement.settle(mode, basket)
    assert result == settlement.settle(mode, basket, 0)
    assert result == settlement.settle(mode, basket, GlassReturn())
    assert result.glass_count == result.glass_return_grosze == 0


def test_result_preserves_positional_constructor_compatibility() -> None:
    """Dotychczasowe pozycje statusu i znacznika DEMO nie przesuwają się po dodaniu szkła."""
    result = SettlementResult(
        _settlement().voucher.voucher_code, RedemptionMode.CASH, (), 0, 100, 0, 100,
        NOW.isoformat(), VoucherStatus.REDEEMED, "DEMO",
    )
    assert result.glass_count == result.glass_return_grosze == 0
    assert result.voucher_status == VoucherStatus.REDEEMED and result.mode == "DEMO"


@pytest.mark.parametrize("mode", ["purchases", "cash"])
def test_zero_glass_preserves_current_json_format_and_roundtrip(mode: str) -> None:
    """Rozszerzenie domeny nie zmienia dotychczasowego zapisu ani ponownego odczytu bez szkła."""
    basket = Basket.from_items([{"product_id": "apple", "quantity": 1}]) if mode == "purchases" else Basket()
    result = _settlement().settle(mode, basket)
    payload = settlement_to_dict(result)
    assert "glass_count" not in payload and "glass_return_grosze" not in payload
    assert settlement_from_dict(payload) == result


def test_current_codec_rejects_positive_glass_instead_of_losing_deposit() -> None:
    """Przejściowy kodek odmawia zapisu szkła do czasu wdrożenia pełnego kontraktu historii."""
    result = _settlement().settle("cash", Basket(), GlassReturn(2))
    with pytest.raises(ValueError, match="zapis zwrotu szkła"):
        settlement_to_dict(result)
    assert result.glass_count == 2 and result.glass_return_grosze == 200


def test_glass_settlement_result_is_immutable_and_detached_from_basket() -> None:
    """Migawka ze szkłem nie zmienia się po edycji roboczych zakupów."""
    basket = Basket.from_items([{"product_id": "bread", "quantity": 1}])
    result = _settlement().settle("purchases", basket, GlassReturn(2))
    basket.items[0].quantity = 3
    assert result.basket_total_grosze == result.items[0].line_total_grosze == 400
    assert result.amount_due_grosze == 100
    assert result.glass_count == 2 and result.glass_return_grosze == 200
    for attribute in ("glass_count", "glass_return_grosze"):
        with pytest.raises(FrozenInstanceError):
            setattr(result, attribute, 0)
    with pytest.raises(FrozenInstanceError):
        result.items[0].quantity = 99


@pytest.mark.parametrize("mode", ["purchases", "cash"])
@pytest.mark.parametrize("status", [VoucherStatus.REDEEMED, VoucherStatus.EXPIRED])
def test_glass_requires_active_voucher(mode: str, status: VoucherStatus) -> None:
    """Dodatni zwrot szkła nie omija dekoratora aktywności bonu w żadnym trybie."""
    settlement = _settlement()
    if status == VoucherStatus.REDEEMED:
        settlement = replace(settlement, voucher=replace(settlement.voucher, status=status))
        expected_error = VoucherAlreadyRedeemedError
    else:
        settlement = replace(settlement, now=NOW + timedelta(days=100))
        expected_error = VoucherExpiredError
    basket = Basket.from_items([{"product_id": "bread", "quantity": 1}]) if mode == "purchases" else Basket()
    with pytest.raises(expected_error):
        settlement.settle(mode, basket, GlassReturn(2))
