"""Koszyk i czyste obliczenia rozliczenia bonu na zakupy lub gotówkę w trybie DEMO."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from kaucjomat.checkout_catalog import get_checkout_product
from kaucjomat.checkout_exceptions import BasketTooSmallError, InvalidCheckoutRequestError
from kaucjomat.checkout_guards import require_active_voucher
from kaucjomat.voucher_domain import VoucherRecord, VoucherStatus

MAX_BASKET_ITEMS: Final[int] = 20
MAX_ITEM_QUANTITY: Final[int] = 99


class RedemptionMode(StrEnum):
    """Dwa sposoby pełnego wykorzystania wartości bonu DEMO."""

    PURCHASES = "purchases"
    CASH = "cash"


class BasketItem:
    """Pozycja koszyka o cenie katalogowej i ilości chronionej setterem."""

    __slots__ = ("_product", "_quantity")

    def __init__(self, product_id: str, quantity: int) -> None:
        """Pobiera produkt z katalogu i ustawia poprawną ilość kupowanych sztuk."""
        self._product = get_checkout_product(product_id)
        self.quantity = quantity

    @property
    def product_id(self) -> str:
        """Zwraca identyfikator produktu, którego nie można zmienić w pozycji."""
        return self._product.product_id

    @property
    def name(self) -> str:
        """Zwraca nazwę produktu zapamiętaną przy tworzeniu pozycji."""
        return self._product.name

    @property
    def unit_price_grosze(self) -> int:
        """Zwraca cenę katalogową sztuki bez możliwości nadpisania przez klienta."""
        return self._product.unit_price_grosze

    @property
    def quantity(self) -> int:
        """Zwraca bieżącą liczbę sztuk produktu."""
        return self._quantity

    @quantity.setter
    def quantity(self, value: int) -> None:
        """Ustawia całkowitą ilość 1–99, zachowując poprzednią wartość przy odmowie."""
        # bool dziedziczy po int; nie dopuszczamy go jako liczby kupowanych sztuk.
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_ITEM_QUANTITY:
            raise InvalidCheckoutRequestError("Ilość produktu DEMO musi być liczbą całkowitą 1–99.")
        self._quantity = value

    @property
    def line_total_grosze(self) -> int:
        """Wylicza wartość pozycji z ceny i aktualnej ilości bez zaokrągleń."""
        return self.unit_price_grosze * self.quantity


@dataclass(frozen=True, slots=True)
class Basket:
    """Koszyk ze stałym zestawem pozycji i sumą wynikającą z ich bieżących ilości."""

    items: tuple[BasketItem, ...] = ()

    def __post_init__(self) -> None:
        """Kontroluje limit i unikalność także przy bezpośrednim tworzeniu koszyka."""
        if not isinstance(self.items, (list, tuple)) or len(self.items) > MAX_BASKET_ITEMS:
            raise InvalidCheckoutRequestError("Koszyk DEMO może zawierać najwyżej 20 pozycji.")
        if not all(isinstance(item, BasketItem) for item in self.items):
            raise InvalidCheckoutRequestError("Koszyk DEMO musi zawierać poprawne pozycje.")
        product_ids = [item.product_id for item in self.items]
        if len(set(product_ids)) != len(product_ids):
            raise InvalidCheckoutRequestError("Produkt nie może występować dwukrotnie w koszyku DEMO.")
        object.__setattr__(self, "items", tuple(sorted(self.items, key=lambda item: item.product_id)))

    @classmethod
    def from_items(cls, items: Sequence[Mapping[str, object]]) -> Basket:
        """Buduje migawkę koszyka z identyfikatorów i ilości, wyceniając pozycje katalogowo."""
        if not isinstance(items, (list, tuple)) or len(items) > MAX_BASKET_ITEMS:
            raise InvalidCheckoutRequestError("Koszyk DEMO wymaga listy najwyżej 20 pozycji.")
        lines: list[BasketItem] = []
        for item in items:
            if not isinstance(item, Mapping) or set(item) != {"product_id", "quantity"}:
                raise InvalidCheckoutRequestError(
                    "Pozycja DEMO musi zawierać wyłącznie product_id i quantity."
                )
            product_id, quantity = item["product_id"], item["quantity"]
            if not isinstance(product_id, str) or not isinstance(quantity, int):
                raise InvalidCheckoutRequestError(
                    "Pozycja DEMO wymaga tekstowego product_id i całkowitej quantity."
                )
            lines.append(BasketItem(product_id=product_id, quantity=quantity))
        return cls(items=tuple(lines))

    @property
    def total_grosze(self) -> int:
        """Oblicza sumę koszyka z aktualnych wartości pozycji."""
        return sum(item.line_total_grosze for item in self.items)


@dataclass(frozen=True, slots=True)
class SettlementItem:
    """Niezmienna migawka produktu, ilości i ceny w zakończonym rozliczeniu DEMO."""

    product_id: str
    name: str
    unit_price_grosze: int
    quantity: int
    line_total_grosze: int


@dataclass(frozen=True, slots=True)
class SettlementResult:
    """Niezmienny wynik symulacji rozliczenia, gotowy do późniejszego trwałego zapisu."""

    voucher_code: str
    redemption_mode: RedemptionMode
    items: tuple[SettlementItem, ...]
    basket_total_grosze: int
    voucher_amount_grosze: int
    amount_due_grosze: int
    cash_payout_grosze: int
    redeemed_at_iso: str
    voucher_status: VoucherStatus = VoucherStatus.REDEEMED
    mode: str = "DEMO"


@dataclass(frozen=True, slots=True)
class VoucherSettlement:
    """Obiekt oceniający jeden bon w jawnym momencie czasu bez zmiany jego rekordu."""

    voucher: VoucherRecord
    now: datetime

    def __post_init__(self) -> None:
        """Wymaga czasu ze strefą oraz dodatniej, całkowitej wartości bonu w groszach."""
        if not isinstance(self.now, datetime) or self.now.tzinfo is None or self.now.utcoffset() is None:
            raise InvalidCheckoutRequestError("Czas rozliczenia DEMO musi zawierać strefę czasową.")
        amount = self.voucher.amount_grosze
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise InvalidCheckoutRequestError("Wartość bonu DEMO musi być dodatnią liczbą groszy.")
        object.__setattr__(self, "now", self.now.astimezone(UTC))

    @require_active_voucher
    def settle(self, redemption_mode: RedemptionMode | str, basket: Basket) -> SettlementResult:
        """Oblicza zakupy lub pełną wypłatę bonu DEMO bez zapisu ani potwierdzania płatności."""
        try:
            mode = RedemptionMode(redemption_mode)
        except (ValueError, TypeError) as exc:
            raise InvalidCheckoutRequestError("Nieznany tryb rozliczenia bonu DEMO.") from exc
        if not isinstance(basket, Basket):
            raise InvalidCheckoutRequestError("Rozliczenie DEMO wymaga poprawnego koszyka.")
        if mode == RedemptionMode.CASH and basket.items:
            raise InvalidCheckoutRequestError("Wypłata gotówki DEMO wymaga pustej listy pozycji.")

        # Kopiujemy wartości, aby późniejsza edycja koszyka nie zmieniała historycznego wyniku.
        items = tuple(
            SettlementItem(item.product_id, item.name, item.unit_price_grosze,
                           item.quantity, item.line_total_grosze)
            for item in basket.items
        )
        total = sum(item.line_total_grosze for item in items)
        amount = self.voucher.amount_grosze
        if mode == RedemptionMode.PURCHASES and total < amount:
            raise BasketTooSmallError("Koszyk DEMO ma wartość mniejszą od bonu; wybierz wypłatę gotówki.")
        return SettlementResult(
            voucher_code=self.voucher.voucher_code,
            redemption_mode=mode,
            items=items,
            basket_total_grosze=total,
            voucher_amount_grosze=amount,
            amount_due_grosze=total - amount if mode == RedemptionMode.PURCHASES else 0,
            cash_payout_grosze=amount if mode == RedemptionMode.CASH else 0,
            redeemed_at_iso=self.now.isoformat(),
        )
