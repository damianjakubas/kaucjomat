"""Testy odrzucania uszkodzonego v2 bez samoczynnej naprawy i bez nadpisania źródła."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from kaucjomat.exceptions import ReturnStateStorageError
from kaucjomat.return_store import ReturnStateStore
from kaucjomat.voucher_state_codec import LEGACY_REDEEMED_MARKER


@pytest.mark.parametrize(("path", "value"), [
    (("schema_version",), True),
    (("schema_version",), 2.0),
    (("schema_version",), 3),
    (("demo_generation_id",), "nie-uuid"),
    (("demo_generation_id",), "AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE"),
    (("checkout_redemptions",), {}),
    (("vouchers", 0, "status"), "AKTYWNY"),
    (("vouchers", 0, "redeemed_at_iso"), None),
    (("vouchers", 0, "redeemed_at_iso"), "2026-01-01T10:00:00"),
    (("vouchers", 0, "amount_grosze"), True),
    (("vouchers", 0, "amount_grosze"), 200),
    (("vouchers", 0, LEGACY_REDEEMED_MARKER), True),
    (("vouchers", 1, LEGACY_REDEEMED_MARKER), True),
    (("checkout_redemptions", 0, "operation_id"), "nie-uuid"),
    (("checkout_redemptions", 0, "demo_generation_id"), str(uuid4())),
    (("checkout_redemptions", 0, "request", "demo_generation_id"), str(uuid4())),
    (("checkout_redemptions", 0, "request", "voucher_code"), "BON-DEMO-INNY"),
    (("checkout_redemptions", 0, "request", "redemption_mode"), "cash"),
    (("checkout_redemptions", 0, "request", "items", 0, "quantity"), True),
    (("checkout_redemptions", 0, "request", "items", 0, "quantity"), 2.0),
    (("checkout_redemptions", 0, "request", "items", 0, "quantity"), 3),
    (("checkout_redemptions", 0, "result", "voucher_status"), "AKTYWNY"),
    (("checkout_redemptions", 0, "result", "mode"), "PRODUCTION"),
    (("checkout_redemptions", 0, "result", "items", 0, "name"), ""),
    (("checkout_redemptions", 0, "result", "items", 0, "unit_price_grosze"), True),
    (("checkout_redemptions", 0, "result", "items", 0, "line_total_grosze"), 101),
    (("checkout_redemptions", 0, "result", "items", 0, "quantity"), 100),
    (("checkout_redemptions", 0, "result", "basket_total_grosze"), 101),
    (("checkout_redemptions", 0, "result", "voucher_amount_grosze"), True),
    (("checkout_redemptions", 0, "result", "amount_due_grosze"), 1),
    (("checkout_redemptions", 0, "result", "cash_payout_grosze"), 1),
    (("checkout_redemptions", 0, "result", "redeemed_at_iso"), "2000-01-01T00:00:00+00:00"),
])
def test_inconsistent_v2_fields_preserve_file(
    redeemed_state: dict[str, Any], checkout_file: Path,
    path: tuple[str | int, ...], value: Any,
) -> None:
    """Uszkodzone typy, sumy i powiązania dają błąd magazynu bez zmiany bajtów pliku."""
    target = redeemed_state
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    checkout_file.write_text(json.dumps(redeemed_state, indent=1), encoding="utf-8")
    before = checkout_file.read_bytes()
    with pytest.raises(ReturnStateStorageError):
        ReturnStateStore(checkout_file).get_checkout_snapshot()
    assert checkout_file.read_bytes() == before


@pytest.mark.parametrize("field", ["demo_generation_id", "checkout_redemptions", "vouchers"])
def test_v2_missing_required_fields_is_not_migrated(
    redeemed_state: dict[str, Any], checkout_file: Path, field: str,
) -> None:
    """Brak pola v2 nie jest traktowany jak poprawny starszy schemat v1."""
    del redeemed_state[field]
    checkout_file.write_text(json.dumps(redeemed_state), encoding="utf-8")
    before = checkout_file.read_bytes()
    with pytest.raises(ReturnStateStorageError):
        ReturnStateStore(checkout_file).get_session_snapshot()
    assert checkout_file.read_bytes() == before


@pytest.mark.parametrize("conflict", [
    "operation", "voucher", "normalized_voucher", "missing_voucher", "another_operation_same_voucher",
    "missing_result_field", "extra_request_field", "missing_entry_field", "missing_voucher_timestamp",
    "legacy_with_history", "outside_validity", "cash_with_items", "noncanonical_code", "unsorted_items",
])
def test_structural_history_conflicts_are_rejected(
    redeemed_state: dict[str, Any], checkout_file: Path, conflict: str,
) -> None:
    """Historia nie dopuszcza duplikatów, osieroconych wyników ani wyjątków nowych realizacji."""
    entry = redeemed_state["checkout_redemptions"][0]
    voucher = redeemed_state["vouchers"][0]
    if conflict in {"operation", "another_operation_same_voucher"}:
        duplicate = deepcopy(entry)
        if conflict == "another_operation_same_voucher":
            duplicate["operation_id"] = str(uuid4())
        redeemed_state["checkout_redemptions"].append(duplicate)
    elif conflict in {"voucher", "normalized_voucher"}:
        duplicate = deepcopy(voucher)
        if conflict == "normalized_voucher":
            duplicate["voucher_code"] = f" {voucher['voucher_code'].lower()} "
        redeemed_state["vouchers"].append(duplicate)
    elif conflict == "missing_voucher":
        redeemed_state["vouchers"].pop(0)
    elif conflict == "missing_result_field":
        del entry["result"]["items"]
    elif conflict == "extra_request_field":
        entry["request"]["price"] = 100
    elif conflict == "missing_entry_field":
        del entry["demo_generation_id"]
    elif conflict == "missing_voucher_timestamp":
        del voucher["redeemed_at_iso"]
    elif conflict == "legacy_with_history":
        voucher[LEGACY_REDEEMED_MARKER] = True
        voucher["redeemed_at_iso"] = None
    elif conflict == "outside_validity":
        entry["result"]["redeemed_at_iso"] = voucher["expires_at_iso"]
        voucher["redeemed_at_iso"] = voucher["expires_at_iso"]
    elif conflict == "cash_with_items":
        entry["request"]["redemption_mode"] = "cash"
        entry["result"].update(redemption_mode="cash", amount_due_grosze=0, cash_payout_grosze=100)
    elif conflict == "noncanonical_code":
        entry["request"]["voucher_code"] = voucher["voucher_code"].lower()
    else:
        # Dwie poprawne pozycje w niekanonicznej kolejności nie mogą trafić do historii.
        entry["request"]["items"].insert(0, {"product_id": "yogurt", "quantity": 1})
    checkout_file.write_text(json.dumps(redeemed_state), encoding="utf-8")
    before = checkout_file.read_bytes()
    with pytest.raises(ReturnStateStorageError):
        ReturnStateStore(checkout_file).list_vouchers()
    assert checkout_file.read_bytes() == before


@pytest.mark.parametrize("marker", [None, False, 1, "true"])
def test_v2_legacy_exception_requires_exact_marker(
    redeemed_state: dict[str, Any], checkout_file: Path, marker: Any,
) -> None:
    """Zużyty bon bez daty wymaga jawnego bool True zamiast dowolnej wartości prawdziwej."""
    voucher = redeemed_state["vouchers"][0]
    voucher["redeemed_at_iso"] = None
    redeemed_state["checkout_redemptions"] = []
    if marker is not None:
        voucher[LEGACY_REDEEMED_MARKER] = marker
    checkout_file.write_text(json.dumps(redeemed_state), encoding="utf-8")
    with pytest.raises(ReturnStateStorageError):
        ReturnStateStore(checkout_file).get_checkout_snapshot()
