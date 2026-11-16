"""Stały katalog produktów kasy DEMO z cenami wyrażonymi w groszach."""

from dataclasses import dataclass
from typing import Final

from kaucjomat.checkout_exceptions import InvalidCheckoutRequestError


@dataclass(frozen=True, slots=True)
class CheckoutProduct:
    """Niezmienna definicja produktu z demonstracyjną ceną bez dodatkowej kaucji."""

    product_id: str
    name: str
    unit_price_grosze: int


PRODUCTS: Final[tuple[CheckoutProduct, ...]] = (
    CheckoutProduct("bread-roll", "Bułka", 50),
    CheckoutProduct("apple", "Jabłko", 150),
    CheckoutProduct("yogurt", "Jogurt", 250),
    CheckoutProduct("bread", "Chleb", 400),
)


@dataclass(frozen=True, slots=True)
class GlassReturnSpec:
    """Niezmienna specyfikacja szkła wielokrotnego użytku przyjmowanego w kasie DEMO."""

    title: str
    unit_deposit_grosze: int
    max_volume_ml: int
    max_quantity: int


GLASS_RETURN_SPEC: Final[GlassReturnSpec] = GlassReturnSpec(
    title="Butelka szklana wielokrotnego użytku do 1,5 l",
    unit_deposit_grosze=100,
    max_volume_ml=1500,
    max_quantity=20,
)


def get_glass_return_spec() -> GlassReturnSpec:
    """Zwraca stałe zasady przyjmowania zwrotnych butelek szklanych w kasie DEMO."""
    return GLASS_RETURN_SPEC


def get_checkout_products() -> tuple[CheckoutProduct, ...]:
    """Zwraca produkty DEMO w kolejności prezentowanej na półce kasy."""
    return PRODUCTS


def get_checkout_product(product_id: str) -> CheckoutProduct:
    """Wyszukuje produkt po dokładnym identyfikatorze i odrzuca nieznane produkty."""
    if not isinstance(product_id, str) or not 1 <= len(product_id) <= 64:
        raise InvalidCheckoutRequestError(
            "Identyfikator produktu DEMO musi być tekstem o długości 1–64 znaków."
        )
    for product in get_checkout_products():
        if product.product_id == product_id:
            return product
    raise InvalidCheckoutRequestError("Nieznany produkt w koszyku DEMO.")
