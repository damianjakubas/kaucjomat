"""Ścisłe żądania i jawne odpowiedzi HTTP kasy sklepowej w trybie DEMO."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from kaucjomat.checkout_domain import (
    MAX_BASKET_ITEMS, MAX_GLASS_COUNT, MAX_ITEM_QUANTITY, RedemptionMode,
)
from kaucjomat.voucher_schemas import VoucherSchema


class CheckoutItemInput(BaseModel):
    """Identyfikator i ilość produktu bez ceny ani sumy narzucanej przez klienta."""

    model_config: ConfigDict = ConfigDict(extra="forbid")
    product_id: str = Field(strict=True, min_length=1, max_length=64)
    quantity: int = Field(strict=True, ge=1, le=MAX_ITEM_QUANTITY)


class CheckoutQuoteRequest(BaseModel):
    """Koszyk do wyceny w konkretnej generacji pokazu DEMO."""

    model_config: ConfigDict = ConfigDict(extra="forbid")
    demo_generation_id: UUID = Field(description="Generacja odczytana z kontekstu kasy DEMO.")
    items: list[CheckoutItemInput] = Field(max_length=MAX_BASKET_ITEMS)
    glass_count: int = Field(default=0, strict=True, ge=0, le=MAX_GLASS_COUNT)


class CheckoutRedemptionRequest(CheckoutQuoteRequest):
    """Niezmienna treść jednej realizacji, możliwa do bezpiecznego ponowienia."""

    operation_id: UUID = Field(description="UUID operacji zachowywany przy ponawianiu żądania.")
    voucher_code: str = Field(strict=True, max_length=64)
    redemption_mode: RedemptionMode = Field(description="Zakupy albo pełna wypłata gotówki DEMO.")


class CheckoutProductSchema(BaseModel):
    """Produkt z nazwą i ceną demonstracyjną ustaloną przez serwer."""

    product_id: str
    name: str
    unit_price_grosze: int
    unit_price_formatted: str


class CheckoutItemSchema(CheckoutProductSchema):
    """Migawka wycenionej pozycji koszyka lub historycznego rozliczenia DEMO."""

    quantity: int
    line_total_grosze: int
    line_total_formatted: str


class CheckoutGlassSpecSchema(BaseModel):
    """Zasady ręcznego przyjęcia szkła zwrotnego w kasie DEMO."""

    title: str
    unit_deposit_grosze: int
    unit_deposit_formatted: str
    max_volume_ml: int
    max_quantity: int


class CheckoutContextResponse(BaseModel):
    """Katalog oraz bony i generacja z jednego odczytu wspólnego magazynu."""

    mode: Literal["DEMO"] = "DEMO"
    demo_generation_id: UUID
    products: list[CheckoutProductSchema]
    vouchers: list[VoucherSchema]
    glass_return_spec: CheckoutGlassSpecSchema


class CheckoutQuoteResponse(BaseModel):
    """Wycena koszyka w groszach i polskim formacie walutowym, bez zużycia bonu."""

    mode: Literal["DEMO"] = "DEMO"
    demo_generation_id: UUID
    items: list[CheckoutItemSchema]
    basket_total_grosze: int
    basket_total_formatted: str
    glass_count: int
    glass_return_grosze: int
    glass_return_formatted: str


class CheckoutSettlementSchema(CheckoutQuoteResponse):
    """Trwały wynik realizacji wraz z identyfikatorami oczekiwanymi przez klienta."""

    operation_id: UUID
    voucher_code: str
    redemption_mode: RedemptionMode
    redeemed_at_iso: str
    voucher_status: Literal["ZUŻYTY"]
    voucher_amount_grosze: int
    voucher_amount_formatted: str
    amount_due_grosze: int
    amount_due_formatted: str
    cash_payout_grosze: int
    cash_payout_formatted: str


class CheckoutRedemptionResponse(BaseModel):
    """Potwierdzenie pierwszej realizacji albo odzyskania tego samego wyniku DEMO."""

    mode: Literal["DEMO"] = "DEMO"
    message: str
    was_idempotent_replay: bool
    settlement: CheckoutSettlementSchema
