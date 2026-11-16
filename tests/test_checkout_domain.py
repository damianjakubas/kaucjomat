"""Testy katalogu, koszyka i czystych obliczeń rozliczenia bonu DEMO."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from kaucjomat import checkout_catalog
from kaucjomat.checkout_catalog import CheckoutProduct, get_checkout_product, get_checkout_products
from kaucjomat.checkout_domain import Basket, BasketItem, RedemptionMode, VoucherSettlement
from kaucjomat.checkout_exceptions import BasketTooSmallError, InvalidCheckoutRequestError
from kaucjomat.voucher_domain import VoucherRecord, VoucherStatus, create_issued_voucher

NOW = datetime(2026, 11, 15, 12, tzinfo=UTC)


def _voucher(amount_grosze: int = 100) -> VoucherRecord:
    """Tworzy aktywny bon ze stałym czasem do testów bez zegara systemowego."""
    return create_issued_voucher(
        sequence_no=1, source_session_id="DEMO-TEST-0001",
        amount_grosze=amount_grosze, accepted_count=2, now=NOW,
    )


def test_catalog_has_agreed_products_and_immutable_prices() -> None:
    """Katalog zawiera dokładnie uzgodnione produkty, nazwy i ceny w groszach."""
    assert [(p.product_id, p.name, p.unit_price_grosze) for p in get_checkout_products()] == [
        ("bread-roll", "Bułka", 50), ("apple", "Jabłko", 150),
        ("yogurt", "Jogurt", 250), ("bread", "Chleb", 400),
    ]
    with pytest.raises(FrozenInstanceError):
        get_checkout_product("bread-roll").unit_price_grosze = 1


def test_basket_uses_catalog_prices_copies_input_and_sorts_items() -> None:
    """Migawka nie zależy od późniejszej edycji wejścia ani kolejności identyfikatorów."""
    raw = [{"product_id": "yogurt", "quantity": 2}, {"product_id": "bread-roll", "quantity": 3}]
    basket = Basket.from_items(raw)
    raw[0]["quantity"] = 99
    raw.clear()
    assert [(p.product_id, p.name, p.unit_price_grosze, p.quantity, p.line_total_grosze)
            for p in basket.items] == [
        ("bread-roll", "Bułka", 50, 3, 150), ("yogurt", "Jogurt", 250, 2, 500),
    ]
    assert basket.total_grosze == 650
    basket.items[0].quantity = 4
    assert basket.total_grosze == 700


def test_existing_basket_preserves_price_when_catalog_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Robocza migawka zachowuje cenę katalogową z momentu budowy koszyka."""
    basket = Basket.from_items([{"product_id": "apple", "quantity": 2}])
    monkeypatch.setattr(checkout_catalog, "PRODUCTS", (CheckoutProduct("apple", "Nowa nazwa", 1),))
    assert basket.items[0].name == "Jabłko"
    assert basket.total_grosze == 300
    assert Basket.from_items([{"product_id": "apple", "quantity": 2}]).total_grosze == 2
    for attribute in ("product_id", "name", "unit_price_grosze"):
        with pytest.raises(AttributeError):
            setattr(basket.items[0], attribute, 1)


@pytest.mark.parametrize("product_id", ["unknown", "APPLE", " apple", "apple ", "", "a" * 65, 1, None])
def test_unknown_or_invalid_product_is_rejected(product_id: Any) -> None:
    """Domena wymaga dokładnego identyfikatora produktu także bez warstwy HTTP."""
    with pytest.raises(InvalidCheckoutRequestError):
        Basket.from_items([{"product_id": product_id, "quantity": 1}])
    with pytest.raises(InvalidCheckoutRequestError):
        BasketItem(product_id, 1)


@pytest.mark.parametrize("quantity", [0, -1, 100, True, False, 1.0, 1.5, "2", None])
def test_invalid_quantity_is_rejected_at_creation(quantity: Any) -> None:
    """Niepoprawne ilości nie przechodzą konstruktora ani metody klasowej."""
    with pytest.raises(InvalidCheckoutRequestError):
        BasketItem("apple", quantity)
    with pytest.raises(InvalidCheckoutRequestError):
        Basket.from_items([{"product_id": "apple", "quantity": quantity}])


@pytest.mark.parametrize("items", [
    None, "apple", {"product_id": "apple", "quantity": 1}, [None], [[]], [{}],
    [{"product_id": "apple"}], [{"quantity": 1}],
    [{"product_id": "apple", "quantity": 1, "unit_price_grosze": 1}],
    [{"product_id": "apple", "quantity": 1, "total_grosze": 1}],
    [{"product_id": "apple", "quantity": 1}] * 2,
    [{"product_id": "apple", "quantity": 1}] * 21,
])
def test_invalid_basket_shape_duplicates_and_forged_prices_are_rejected(items: Any) -> None:
    """Domena odrzuca niepełne pozycje, powtórzenia, nadmiar pozycji i podrobione kwoty."""
    with pytest.raises(InvalidCheckoutRequestError):
        Basket.from_items(items)


def test_direct_basket_constructor_enforces_limits_and_duplicates() -> None:
    """Pominięcie metody klasowej nie umożliwia obejścia reguł koszyka."""
    item = BasketItem("apple", 1)
    for items in ((item, item), (item,) * 21, ({"product_id": "apple"},), None):
        with pytest.raises(InvalidCheckoutRequestError):
            Basket(items=items)


def test_twenty_unique_items_allowed_but_twenty_one_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Limit dwudziestu pozycji działa niezależnie od małego katalogu demonstracyjnego."""
    monkeypatch.setattr(checkout_catalog, "PRODUCTS", tuple(
        CheckoutProduct(f"item-{index}", f"Produkt {index}", 50) for index in range(21)
    ))
    raw = [{"product_id": f"item-{index}", "quantity": 1} for index in range(21)]
    assert Basket.from_items(raw[:20]).total_grosze == 1000
    with pytest.raises(InvalidCheckoutRequestError):
        Basket.from_items(raw)


@pytest.mark.parametrize(("quantity", "due"), [(2, 0), (3, 50)])
def test_purchases_equal_or_above_voucher(quantity: int, due: int) -> None:
    """Bon pokrywa równy koszyk lub pozostawia poprawną kwotę do zapłaty."""
    voucher = _voucher()
    basket = Basket.from_items([{"product_id": "bread-roll", "quantity": quantity}])
    result = VoucherSettlement(voucher, NOW).settle("purchases", basket)
    assert result.basket_total_grosze == quantity * 50
    assert result.voucher_amount_grosze == 100
    assert result.amount_due_grosze == due
    assert result.cash_payout_grosze == 0
    assert result.redemption_mode == RedemptionMode.PURCHASES
    assert result.items[0].quantity == quantity
    assert result.voucher_code == voucher.voucher_code
    assert result.voucher_status == VoucherStatus.REDEEMED
    assert result.redeemed_at_iso == NOW.isoformat()
    assert result.mode == "DEMO"
    assert voucher.status == VoucherStatus.ACTIVE and voucher.redeemed_at_iso is None


@pytest.mark.parametrize(("voucher_amount", "due"), [(99, 1), (100, 0), (101, None)])
def test_purchase_boundary_to_single_grosz(voucher_amount: int, due: int | None) -> None:
    """Porównanie działa co do grosza dla koszyka poniżej, równego i powyżej bonu."""
    settlement = VoucherSettlement(_voucher(voucher_amount), NOW)
    basket = Basket.from_items([{"product_id": "bread-roll", "quantity": 2}])
    if due is None:
        with pytest.raises(BasketTooSmallError) as error:
            settlement.settle("purchases", basket)
        assert error.value.error_code == "BASKET_TOO_SMALL"
        assert error.value.status_code == 409
    else:
        assert settlement.settle("purchases", basket).amount_due_grosze == due


@pytest.mark.parametrize("quantity", [0, 1])
def test_empty_or_small_basket_rejects_purchases(quantity: int) -> None:
    """Poprawny roboczy koszyk może być zbyt mały do rozliczenia zakupów."""
    raw = [{"product_id": "bread-roll", "quantity": quantity}] if quantity else []
    basket = Basket.from_items(raw)
    assert basket.total_grosze == quantity * 50
    with pytest.raises(BasketTooSmallError):
        VoucherSettlement(_voucher(), NOW).settle("purchases", basket)


def test_cash_pays_full_voucher_and_requires_empty_transaction_items() -> None:
    """Gotówka wypłaca pełen bon; roboczy koszyk nie jest częścią operacji kasowej."""
    working_basket = Basket.from_items([{"product_id": "bread", "quantity": 3}])
    settlement = VoucherSettlement(_voucher(150), NOW)
    with pytest.raises(InvalidCheckoutRequestError):
        settlement.settle("cash", working_basket)
    result = settlement.settle(RedemptionMode.CASH, Basket.from_items([]))
    assert result.items == ()
    assert result.basket_total_grosze == result.amount_due_grosze == 0
    assert result.cash_payout_grosze == result.voucher_amount_grosze == 150
    assert result.redemption_mode == RedemptionMode.CASH
    assert working_basket.total_grosze == 1200 and working_basket.items[0].quantity == 3
    assert settlement.voucher.status == VoucherStatus.ACTIVE


def test_result_is_deeply_immutable_and_detached_from_basket() -> None:
    """Wynik i jego pozycje nie zmieniają się po edycji roboczego koszyka."""
    basket = Basket.from_items([{"product_id": "apple", "quantity": 2}])
    result = VoucherSettlement(_voucher(), NOW).settle("purchases", basket)
    basket.items[0].quantity = 10
    assert result.items[0].quantity == 2
    assert result.items[0].name == "Jabłko"
    assert result.items[0].unit_price_grosze == 150
    assert result.items[0].line_total_grosze == result.basket_total_grosze == 300
    assert result.amount_due_grosze == 200
    with pytest.raises(FrozenInstanceError):
        result.amount_due_grosze = 0
    with pytest.raises(FrozenInstanceError):
        result.items[0].quantity = 99
    with pytest.raises(AttributeError):
        result.items.append(result.items[0])


@pytest.mark.parametrize("mode", ["unknown", "CASH", "", None, True, 1])
def test_invalid_redemption_mode_is_rejected(mode: Any) -> None:
    """Nieznany tryb nie może zostać potraktowany jako zakup ani wypłata."""
    with pytest.raises(InvalidCheckoutRequestError):
        VoucherSettlement(_voucher(), NOW).settle(mode, Basket())


@pytest.mark.parametrize("basket", [None, [], {}, "basket"])
def test_invalid_settlement_basket_is_rejected(basket: Any) -> None:
    """Bezpośrednie wywołanie rozliczenia wymaga obiektu zwalidowanego koszyka."""
    with pytest.raises(InvalidCheckoutRequestError):
        VoucherSettlement(_voucher(), NOW).settle("cash", basket)


@pytest.mark.parametrize("amount", [True, False, 1.5, "100", 0, -1])
def test_settlement_rejects_non_positive_or_non_integer_voucher_amount(amount: Any) -> None:
    """Kwota bonu podana bezpośrednio domenie musi być dodatnią liczbą całkowitą."""
    with pytest.raises(InvalidCheckoutRequestError):
        VoucherSettlement(replace(_voucher(), amount_grosze=amount), NOW)


def test_settlement_requires_explicit_timezone_and_normalizes_to_utc() -> None:
    """Jawny czas nie zależy od strefy komputera, a wynik zapisuje równoważną chwilę UTC."""
    with pytest.raises(InvalidCheckoutRequestError):
        VoucherSettlement(_voucher(), NOW.replace(tzinfo=None))
    local = NOW.astimezone(timezone(timedelta(hours=2)))
    result = VoucherSettlement(_voucher(), local).settle("cash", Basket())
    assert result.redeemed_at_iso == NOW.isoformat()
