"""Synchroniczne endpointy kontekstu, wyceny i trwałej realizacji bonów DEMO."""

from fastapi import APIRouter

from kaucjomat.checkout_catalog import get_checkout_products
from kaucjomat.checkout_domain import Basket, BasketItem, SettlementItem
from kaucjomat.checkout_exceptions import DemoGenerationConflictError
from kaucjomat.checkout_schemas import (
    CheckoutContextResponse,
    CheckoutItemSchema,
    CheckoutProductSchema,
    CheckoutQuoteRequest,
    CheckoutQuoteResponse,
    CheckoutRedemptionRequest,
    CheckoutRedemptionResponse,
    CheckoutSettlementSchema,
)
from kaucjomat.return_domain import format_pln_from_grosze
from kaucjomat.return_store import ReturnStateStore
from kaucjomat.schemas import ErrorResponse
from kaucjomat.voucher_schemas import to_voucher_schema


def _to_item_schema(item: BasketItem | SettlementItem) -> CheckoutItemSchema:
    """Formatuje przekazaną migawkę pozycji bez ponownego sprawdzania jej ceny w katalogu."""
    return CheckoutItemSchema(
        product_id=item.product_id,
        name=item.name,
        unit_price_grosze=item.unit_price_grosze,
        unit_price_formatted=format_pln_from_grosze(item.unit_price_grosze),
        quantity=item.quantity,
        line_total_grosze=item.line_total_grosze,
        line_total_formatted=format_pln_from_grosze(item.line_total_grosze),
    )


def create_checkout_router(store: ReturnStateStore) -> APIRouter:
    """Przyjmuje ten sam magazyn co butelkomat i wystawia kontrakt kasy DEMO."""
    router = APIRouter(
        prefix="/api/checkout", tags=["checkout"],
        responses={code: {"model": ErrorResponse} for code in (400, 404, 409, 422, 500)},
    )

    @router.get("/context", response_model=CheckoutContextResponse)
    def read_checkout_context() -> CheckoutContextResponse:
        """Pobiera spójne bony i generację oraz katalog cen demonstracyjnych."""
        snapshot = store.get_checkout_snapshot()
        return CheckoutContextResponse(
            demo_generation_id=snapshot.demo_generation_id,
            products=[CheckoutProductSchema(
                product_id=p.product_id, name=p.name, unit_price_grosze=p.unit_price_grosze,
                unit_price_formatted=format_pln_from_grosze(p.unit_price_grosze),
            ) for p in get_checkout_products()],
            vouchers=[to_voucher_schema(voucher) for voucher in snapshot.vouchers],
        )

    @router.post("/quote", response_model=CheckoutQuoteResponse)
    def quote_basket(payload: CheckoutQuoteRequest) -> CheckoutQuoteResponse:
        """Wycenia koszyk bieżącego pokazu bez realizacji ani rezerwowania bonu."""
        snapshot = store.get_checkout_snapshot()
        if str(payload.demo_generation_id) != snapshot.demo_generation_id:
            raise DemoGenerationConflictError("Pokaz DEMO został zresetowany; odśwież dane kasy.")
        basket = Basket.from_items([item.model_dump() for item in payload.items])
        return CheckoutQuoteResponse(
            demo_generation_id=payload.demo_generation_id,
            items=[_to_item_schema(item) for item in basket.items],
            basket_total_grosze=basket.total_grosze,
            basket_total_formatted=format_pln_from_grosze(basket.total_grosze),
        )

    @router.post("/redeem", response_model=CheckoutRedemptionResponse)
    def redeem_voucher(payload: CheckoutRedemptionRequest) -> CheckoutRedemptionResponse:
        """Wykonuje jedną realizację lub odzyskuje wynik przed sprawdzeniem bieżącego katalogu."""
        result, replayed = store.redeem_voucher(
            operation_id=str(payload.operation_id),
            demo_generation_id=str(payload.demo_generation_id),
            voucher_code=payload.voucher_code,
            redemption_mode=payload.redemption_mode,
            items=[item.model_dump() for item in payload.items],
        )
        settlement = CheckoutSettlementSchema(
            operation_id=payload.operation_id, demo_generation_id=payload.demo_generation_id,
            voucher_code=result.voucher_code, redemption_mode=result.redemption_mode,
            redeemed_at_iso=result.redeemed_at_iso, voucher_status=result.voucher_status,
            items=[_to_item_schema(item) for item in result.items],
            basket_total_grosze=result.basket_total_grosze,
            basket_total_formatted=format_pln_from_grosze(result.basket_total_grosze),
            voucher_amount_grosze=result.voucher_amount_grosze,
            voucher_amount_formatted=format_pln_from_grosze(result.voucher_amount_grosze),
            amount_due_grosze=result.amount_due_grosze,
            amount_due_formatted=format_pln_from_grosze(result.amount_due_grosze),
            cash_payout_grosze=result.cash_payout_grosze,
            cash_payout_formatted=format_pln_from_grosze(result.cash_payout_grosze),
        )
        message = (
            "Przywrócono poprzedni wynik DEMO — nie wykonano ponownego rozliczenia."
            if replayed else "Rozliczono bon DEMO na zakupy."
            if result.redemption_mode == "purchases"
            else "Wypłacono pełną wartość bonu DEMO; zakupy pozostają nierozliczone."
        )
        return CheckoutRedemptionResponse(
            message=message, was_idempotent_replay=replayed, settlement=settlement,
        )

    return router
