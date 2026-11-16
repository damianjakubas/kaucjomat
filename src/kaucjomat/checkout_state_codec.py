"""Walidacja migracji i historycznych rozliczeń DEMO bez odwołań do bieżącego katalogu."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import uuid4

from kaucjomat.checkout_domain import (
    GLASS_UNIT_DEPOSIT_GROSZE, MAX_GLASS_COUNT, RedemptionMode, SettlementItem, SettlementResult,
)
from kaucjomat.checkout_request import (
    canonical_items, canonical_request, canonical_uuid, normalize_voucher_code,
)
from kaucjomat.exceptions import KaucjomatError
from kaucjomat.voucher_domain import VoucherStatus
from kaucjomat.voucher_state_codec import (
    LEGACY_REDEEMED_MARKER,
    require_int,
    require_str,
    require_utc_iso,
    validate_voucher_lifecycle,
)

_REQUEST_FIELDS = {"demo_generation_id", "voucher_code", "redemption_mode", "items", "glass_count"}
_RESULT_FIELDS = {
    "voucher_code", "redemption_mode", "items", "basket_total_grosze", "voucher_amount_grosze",
    "amount_due_grosze", "cash_payout_grosze", "redeemed_at_iso", "voucher_status", "mode",
    "glass_count", "glass_return_grosze",
}


def settlement_to_dict(result: SettlementResult) -> dict[str, Any]:
    """Serializuje niezmienną migawkę rozliczenia na niezależny obiekt JSON."""
    payload = asdict(result)
    payload["items"] = [asdict(item) for item in result.items]
    payload["redemption_mode"] = result.redemption_mode.value
    payload["voucher_status"] = result.voucher_status.value
    return payload


def settlement_from_dict(raw: dict[str, Any]) -> SettlementResult:
    """Odtwarza historyczne ceny i sumy, sprawdzając arytmetykę oraz ścisłe typy."""
    if not isinstance(raw, dict) or set(raw) != _RESULT_FIELDS:
        raise ValueError("Niekompletna migawka realizacji DEMO.")
    if raw["mode"] != "DEMO" or raw["voucher_status"] != VoucherStatus.REDEEMED:
        raise ValueError("Wynik realizacji musi oznaczać zużycie bonu DEMO.")
    code = normalize_voucher_code(raw["voucher_code"])
    if code != raw["voucher_code"]:
        raise ValueError("Wynik wymaga znormalizowanego kodu bonu.")
    mode = RedemptionMode(raw["redemption_mode"])
    timestamp = require_utc_iso(require_str(raw, "redeemed_at_iso"), "redeemed_at_iso")
    items_raw = raw["items"]
    if not isinstance(items_raw, list):
        raise ValueError("Pozycje historyczne muszą być listą.")
    items: list[SettlementItem] = []
    for item in items_raw:
        fields = {"product_id", "name", "unit_price_grosze", "quantity", "line_total_grosze"}
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError("Niekompletna historyczna pozycja koszyka.")
        product = require_str(item, "product_id", non_empty=True)
        name = require_str(item, "name", non_empty=True)
        price = require_int(item, "unit_price_grosze", minimum=1)
        quantity = require_int(item, "quantity", minimum=1)
        line_total = require_int(item, "line_total_grosze", minimum=1)
        if line_total != price * quantity:
            raise ValueError("Niezgodna wartość pozycji historycznej.")
        items.append(SettlementItem(product, name, price, quantity, line_total))
    # Wspólna walidacja kształtu i limitów nie sprawdza obecności produktu w dzisiejszym katalogu.
    item_payload = [{"product_id": item.product_id, "quantity": item.quantity} for item in items]
    if canonical_items(item_payload) != item_payload:
        raise ValueError("Pozycje historyczne nie są w kolejności kanonicznej.")
    total = require_int(raw, "basket_total_grosze", minimum=0)
    amount = require_int(raw, "voucher_amount_grosze", minimum=1)
    due = require_int(raw, "amount_due_grosze", minimum=0)
    payout = require_int(raw, "cash_payout_grosze", minimum=0)
    glass_count = require_int(raw, "glass_count", minimum=0)
    glass_return = require_int(raw, "glass_return_grosze", minimum=0)
    if glass_count > MAX_GLASS_COUNT or glass_return != glass_count * GLASS_UNIT_DEPOSIT_GROSZE:
        raise ValueError("Niespójny zwrot szkła w historii realizacji DEMO.")
    if total != sum(item.line_total_grosze for item in items):
        raise ValueError("Niezgodna suma koszyka w historii.")
    if mode == RedemptionMode.PURCHASES:
        if total < amount + glass_return or due != total - amount - glass_return or payout != 0:
            raise ValueError("Niespójne kwoty zakupów historycznych.")
    elif items or total != 0 or due != 0 or payout != amount + glass_return:
        raise ValueError("Niespójne kwoty historycznej wypłaty.")
    return SettlementResult(
        code, mode, tuple(items), total, amount, due, payout, timestamp,
        glass_count=glass_count, glass_return_grosze=glass_return,
    )


def _migrate_glass_return(entry: dict[str, Any]) -> bool:
    """Uzupełnia wyłącznie kompletną parę starszego żądania i wyniku o zerowy zwrot szkła."""
    request, result = entry["request"], entry["result"]
    if not isinstance(request, dict) or not isinstance(result, dict):
        raise ValueError("Żądanie i wynik historii realizacji muszą być obiektami.")
    legacy_request = _REQUEST_FIELDS - {"glass_count"}
    legacy_result = _RESULT_FIELDS - {"glass_count", "glass_return_grosze"}
    # Nie naprawiamy częściowych rekordów: migracji podlega tylko dokładny starszy format.
    if set(request) == legacy_request and set(result) == legacy_result:
        request["glass_count"] = result["glass_count"] = result["glass_return_grosze"] = 0
        return True
    if "glass_count" not in request or not {"glass_count", "glass_return_grosze"} <= result.keys():
        raise ValueError("Niekompletny zapis zwrotu szkła w historii realizacji.")
    return False


def validate_checkout_state(state: dict[str, Any], *, migrating: bool) -> bool:
    """Migruje pola kasy i sprawdza unikalność oraz powiązania historii z bonami."""
    try:
        return _validate_checkout_state(state, migrating=migrating)
    except KaucjomatError as exc:
        raise ValueError(f"Niepoprawny stan kasy DEMO: {exc.message}") from exc


def _validate_checkout_state(state: dict[str, Any], *, migrating: bool) -> bool:
    """Waliduje całość historii jako jedną spójną generację bez wyceny katalogowej."""
    if migrating:
        if "demo_generation_id" in state or "checkout_redemptions" in state:
            raise ValueError("Plik v1 zawiera nieoczekiwane pola kasy v2.")
        state["demo_generation_id"] = str(uuid4())
        state["checkout_redemptions"] = []
    generation = canonical_uuid(state["demo_generation_id"], "demo_generation_id")
    if generation != state["demo_generation_id"]:
        raise ValueError("Generacja DEMO musi mieć kanoniczny UUID.")
    vouchers: dict[str, dict[str, Any]] = {}
    for voucher in state["vouchers"]:
        code = normalize_voucher_code(voucher["voucher_code"])
        if code in vouchers:
            raise ValueError("Powtórzony kod bonu po normalizacji; wymagana ręczna korekta kopii danych.")
        validate_voucher_lifecycle(voucher, migrating=migrating)
        vouchers[code] = voucher
    history = state["checkout_redemptions"]
    if not isinstance(history, list):
        raise ValueError("checkout_redemptions musi być listą.")
    operation_ids: set[str] = set()
    redeemed_codes: set[str] = set()
    migrated = migrating
    for entry in history:
        if not isinstance(entry, dict) or set(entry) != {
            "operation_id", "demo_generation_id", "request", "result",
        }:
            raise ValueError("Niekompletny rekord historii realizacji.")
        operation_id = canonical_uuid(entry["operation_id"], "operation_id")
        if operation_id != entry["operation_id"] or operation_id in operation_ids:
            raise ValueError("Niekanoniczny lub powtórzony UUID operacji.")
        operation_ids.add(operation_id)
        migrated = _migrate_glass_return(entry) or migrated
        request = entry["request"]
        if set(request) != _REQUEST_FIELDS:
            raise ValueError("Niekompletne zapisane żądanie.")
        canonical = canonical_request(**request)
        if canonical != request or entry["demo_generation_id"] != generation:
            raise ValueError("Niezgodna generacja lub niekanoniczna treść operacji.")
        if request["demo_generation_id"] != generation:
            raise ValueError("Żądanie pochodzi z innej generacji DEMO.")
        result = settlement_from_dict(entry["result"])
        code = result.voucher_code
        if code in redeemed_codes or code not in vouchers:
            raise ValueError("Powtórzona realizacja lub wynik nieistniejącego bonu.")
        redeemed_codes.add(code)
        voucher = vouchers[code]
        expected_items = [{"product_id": i.product_id, "quantity": i.quantity} for i in result.items]
        if (request["voucher_code"] != code or request["redemption_mode"] != result.redemption_mode
                or request["items"] != expected_items or request["glass_count"] != result.glass_count):
            raise ValueError("Żądanie i wynik historyczny są rozbieżne.")
        if (voucher["status"] != VoucherStatus.REDEEMED or LEGACY_REDEEMED_MARKER in voucher
                or voucher["redeemed_at_iso"] != result.redeemed_at_iso
                or voucher["amount_grosze"] != result.voucher_amount_grosze):
            raise ValueError("Historia i rekord zużytego bonu są niespójne.")
        redeemed_at = datetime.fromisoformat(result.redeemed_at_iso)
        if not (datetime.fromisoformat(voucher["issued_at_iso"]) <= redeemed_at
                < datetime.fromisoformat(voucher["expires_at_iso"])):
            raise ValueError("Data realizacji leży poza okresem ważności bonu.")
    return migrated
