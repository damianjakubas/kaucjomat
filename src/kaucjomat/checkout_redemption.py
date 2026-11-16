"""Transformacja stanu realizacji bonu wykonywana wyłącznie wewnątrz blokady magazynu."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from kaucjomat.checkout_domain import Basket, RedemptionMode, SettlementResult, VoucherSettlement
from kaucjomat.checkout_exceptions import (
    DemoGenerationConflictError, RedemptionOperationConflictError, VoucherNotFoundError,
)
from kaucjomat.checkout_request import canonical_request, canonical_uuid, normalize_voucher_code
from kaucjomat.checkout_state_codec import settlement_from_dict, settlement_to_dict
from kaucjomat.voucher_domain import VoucherRecord, VoucherStatus
from kaucjomat.voucher_state_codec import voucher_dict_to_record


@dataclass(frozen=True, slots=True)
class CheckoutSnapshot:
    """Niezmienna generacja i lista bonów odczytane wspólnie pod blokadą magazynu."""

    demo_generation_id: str
    vouchers: tuple[VoucherRecord, ...]


def prepare_redemption(
    state: dict[str, Any],
    operation_id: str,
    demo_generation_id: str,
    voucher_code: str,
    redemption_mode: RedemptionMode | str,
    items: Sequence[Mapping[str, object]],
) -> tuple[SettlementResult, bool]:
    """Rozpoznaje ponowienie albo przygotowuje jedną zmianę bonu i historii do atomowego zapisu."""
    generation = canonical_uuid(demo_generation_id, "demo_generation_id")
    if generation != state["demo_generation_id"]:
        raise DemoGenerationConflictError("Pokaz DEMO został zresetowany; odśwież dane kasy.")
    operation = canonical_uuid(operation_id, "operation_id")
    request = canonical_request(generation, voucher_code, redemption_mode, items)
    previous = next((e for e in state["checkout_redemptions"] if e["operation_id"] == operation), None)
    if previous is not None:
        if previous["request"] != request:
            raise RedemptionOperationConflictError("Identyfikator operacji DEMO ma już inną treść.")
        return settlement_from_dict(previous["result"]), True

    voucher_dict = next((v for v in state["vouchers"]
                         if normalize_voucher_code(v["voucher_code"]) == request["voucher_code"]), None)
    if voucher_dict is None:
        raise VoucherNotFoundError("Nie znaleziono bonu o podanym kodzie w tym pokazie DEMO.")
    basket = Basket.from_items(request["items"])
    # Czas pobieramy już pod blokadą, po odczycie pliku i możliwie blisko oceny aktywności.
    now = datetime.now(UTC)
    voucher = voucher_dict_to_record(voucher_dict, now=now)
    voucher = replace(voucher, voucher_code=request["voucher_code"])
    result = VoucherSettlement(voucher, now).settle(request["redemption_mode"], basket)
    voucher_dict["status"] = VoucherStatus.REDEEMED.value
    voucher_dict["redeemed_at_iso"] = result.redeemed_at_iso
    state["checkout_redemptions"].append({
        "operation_id": operation,
        "demo_generation_id": generation,
        "request": request,
        "result": settlement_to_dict(result),
    })
    return result, False
