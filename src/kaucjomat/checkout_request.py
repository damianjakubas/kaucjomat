"""Kanoniczna treść operacji kasy, niezależna od aktualnych cen i dostępności produktów."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from kaucjomat.checkout_domain import MAX_BASKET_ITEMS, MAX_GLASS_COUNT, MAX_ITEM_QUANTITY, RedemptionMode
from kaucjomat.checkout_exceptions import InvalidCheckoutRequestError


def canonical_uuid(value: str, field: str) -> str:
    """Waliduje tekstowy UUID i zwraca jego kanoniczną postać z myślnikami."""
    try:
        if not isinstance(value, str):
            raise ValueError
        return str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise InvalidCheckoutRequestError(f"Pole {field} musi zawierać UUID.") from exc


def normalize_voucher_code(value: str) -> str:
    """Sprawdza długość kodu i usuwa skrajne odstępy oraz różnice wielkości liter."""
    if not isinstance(value, str) or len(value) > 64 or not value.strip():
        raise InvalidCheckoutRequestError("Kod bonu DEMO wymaga niepustego tekstu do 64 znaków.")
    code = value.strip().upper()
    if len(code) > 64:
        raise InvalidCheckoutRequestError("Znormalizowany kod bonu DEMO przekracza 64 znaki.")
    return code


def canonical_items(items: Sequence[Mapping[str, object]]) -> list[dict[str, Any]]:
    """Kopiuje, sortuje i waliduje identyfikatory oraz ilości bez sprawdzania katalogu."""
    if not isinstance(items, (list, tuple)) or len(items) > MAX_BASKET_ITEMS:
        raise InvalidCheckoutRequestError("Koszyk DEMO wymaga listy najwyżej 20 pozycji.")
    lines: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping) or set(item) != {"product_id", "quantity"}:
            raise InvalidCheckoutRequestError("Pozycja DEMO wymaga tylko product_id i quantity.")
        product, quantity = item["product_id"], item["quantity"]
        if not isinstance(product, str) or not 1 <= len(product) <= 64 or product in seen:
            raise InvalidCheckoutRequestError("Niepoprawny lub powtórzony identyfikator produktu DEMO.")
        if type(quantity) is not int or not 1 <= quantity <= MAX_ITEM_QUANTITY:
            raise InvalidCheckoutRequestError("Ilość produktu DEMO musi być liczbą całkowitą 1–99.")
        seen.add(product)
        lines.append({"product_id": product, "quantity": quantity})
    return sorted(lines, key=lambda item: item["product_id"])


def canonical_glass_count(value: object) -> int:
    """Wymaga całkowitej liczby zwracanych butelek 0–20, odrzucając także bool."""
    if type(value) is not int or not 0 <= value <= MAX_GLASS_COUNT:
        raise InvalidCheckoutRequestError(
            "Liczba butelek szklanych DEMO musi być liczbą całkowitą 0–20."
        )
    return value


def canonical_request(
    demo_generation_id: str,
    voucher_code: str,
    redemption_mode: RedemptionMode | str,
    items: Sequence[Mapping[str, object]],
    glass_count: int = 0,
) -> dict[str, Any]:
    """Kopiuje i waliduje treść żądania bez odczytu katalogu potrzebnego dopiero nowej operacji."""
    generation = canonical_uuid(demo_generation_id, "demo_generation_id")
    code = normalize_voucher_code(voucher_code)
    try:
        mode = RedemptionMode(redemption_mode)
    except (TypeError, ValueError) as exc:
        raise InvalidCheckoutRequestError("Nieznany tryb rozliczenia bonu DEMO.") from exc
    lines = canonical_items(items)
    if mode == RedemptionMode.CASH and lines:
        raise InvalidCheckoutRequestError("Wypłata gotówki DEMO wymaga pustej listy pozycji.")
    return {
        "demo_generation_id": generation,
        "voucher_code": code,
        "redemption_mode": mode.value,
        "items": lines,
        "glass_count": canonical_glass_count(glass_count),
    }
