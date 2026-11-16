"""Testy trwałego wyniku, atomowego zapisu, odmów i odtworzenia realizacji po restarcie."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from kaucjomat import checkout_catalog, checkout_redemption
from kaucjomat.checkout_exceptions import InvalidCheckoutRequestError
from kaucjomat.exceptions import KaucjomatError, ReturnStateStorageError
from kaucjomat.return_store import ReturnStateStore
from kaucjomat.test_cards import get_test_card_by_id
from kaucjomat.voucher_domain import VoucherStatus


@pytest.mark.parametrize("mode", ["purchases", "cash"])
def test_atomic_redemption_preserves_session_and_records_one_result(
    checkout_store: ReturnStateStore, checkout_file: Path, checkout_request: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    """Jeden replace zapisuje zarazem status i wynik, zachowując pozostałe dane DEMO."""
    before = json.loads(checkout_file.read_bytes())
    checkout_request.update(redemption_mode=mode, items=[] if mode == "cash" else checkout_request["items"])
    replacements: list[Path] = []
    original_replace = Path.replace

    def counted_replace(source: Path, destination: Path) -> Path:
        """Zlicza rzeczywiste podmiany pliku w całej nowej operacji."""
        replacements.append(destination)
        return original_replace(source, destination)

    monkeypatch.setattr(Path, "replace", counted_replace)
    result, replayed = checkout_store.redeem_voucher(**checkout_request)
    saved = json.loads(checkout_file.read_bytes())
    assert replacements == [checkout_file] and replayed is False
    assert result.mode == "DEMO" and result.voucher_status == VoucherStatus.REDEEMED
    assert result.voucher_amount_grosze == 100 and result.amount_due_grosze == 0
    assert result.cash_payout_grosze == (100 if mode == "cash" else 0)
    assert result.basket_total_grosze == (0 if mode == "cash" else 100)
    assert saved["vouchers"][0]["status"] == "ZUŻYTY"
    assert saved["vouchers"][0]["redeemed_at_iso"] == result.redeemed_at_iso
    assert len(saved["checkout_redemptions"]) == 1
    entry = saved["checkout_redemptions"][0]
    assert entry["operation_id"] == checkout_request["operation_id"]
    assert entry["demo_generation_id"] == checkout_request["demo_generation_id"]
    assert entry["result"]["redemption_mode"] == mode
    for key in ("session", "returned_instance_ids", "demo_generation_id"):
        assert saved[key] == before[key]
    assert checkout_store.list_vouchers()[0].status == VoucherStatus.REDEEMED


@pytest.mark.parametrize("mode", ["purchases", "cash"])
@pytest.mark.parametrize("catalog_change", ["prices", "removed"])
def test_replay_survives_restart_expiry_and_catalog_removal(
    checkout_store: ReturnStateStore, checkout_request: dict[str, Any], checkout_file: Path,
    monkeypatch: pytest.MonkeyPatch, mode: str, catalog_change: str,
) -> None:
    """Zapisany wynik nie zależy od czasu, cen, nazw ani dalszego istnienia produktu."""
    checkout_request.update(redemption_mode=mode, items=[] if mode == "cash" else checkout_request["items"])
    result, _ = checkout_store.redeem_voucher(**checkout_request)
    before = checkout_file.read_bytes()

    class FutureClock:
        """Zegar umieszcza nową ocenę daleko po ważności bonu."""

        @staticmethod
        def now(zone: object) -> datetime:
            """Zwraca przyszły czas bez czekania na upływ ważności."""
            return datetime.now(UTC) + timedelta(days=200)

    monkeypatch.setattr(checkout_redemption, "datetime", FutureClock)
    changed_products = tuple(replace(p, name="Zmieniona nazwa", unit_price_grosze=9999)
                             for p in checkout_catalog.PRODUCTS)
    monkeypatch.setattr(checkout_catalog, "PRODUCTS", () if catalog_change == "removed" else changed_products)
    restarted = ReturnStateStore(checkout_file)
    restored, replayed = restarted.redeem_voucher(**checkout_request)
    assert replayed is True and restored == result
    assert checkout_file.read_bytes() == before


def test_normalized_uuid_code_and_item_order_identify_same_operation(
    checkout_store: ReturnStateStore, checkout_request: dict[str, Any], checkout_file: Path,
) -> None:
    """Tożsamość operacji uwzględnia kanoniczne UUID, kod oraz posortowane pozycje."""
    checkout_request["items"] = [{"product_id": "bread", "quantity": 1}, {"product_id": "apple", "quantity": 2}]
    original = deepcopy(checkout_request)
    result, _ = checkout_store.redeem_voucher(**checkout_request)
    assert checkout_request == original
    before = checkout_file.read_bytes()
    checkout_request["operation_id"] = UUID(checkout_request["operation_id"]).hex.upper()
    checkout_request["demo_generation_id"] = UUID(checkout_request["demo_generation_id"]).hex.upper()
    checkout_request["voucher_code"] = f"  {checkout_request['voucher_code'].lower()}  "
    checkout_request["items"].reverse()
    assert checkout_store.redeem_voucher(**checkout_request) == (result, True)
    assert checkout_file.read_bytes() == before
    assert result.basket_total_grosze == 700 and result.amount_due_grosze == 600
    assert [item.product_id for item in result.items] == ["apple", "bread"]


@pytest.mark.parametrize(("field", "value", "code"), [
    ("voucher_code", "BON-DEMO-INNY", "CHECKOUT_OPERATION_CONFLICT"),
    ("redemption_mode", "cash", "CHECKOUT_OPERATION_CONFLICT"),
    ("items", [{"product_id": "bread-roll", "quantity": 3}], "CHECKOUT_OPERATION_CONFLICT"),
    ("operation_id", str(uuid4()), "VOUCHER_ALREADY_REDEEMED"),
    ("demo_generation_id", str(uuid4()), "DEMO_GENERATION_CONFLICT"),
])
def test_changed_operation_is_refused_without_write(
    checkout_store: ReturnStateStore, checkout_request: dict[str, Any], checkout_file: Path,
    field: str, value: Any, code: str,
) -> None:
    """Zmiana treści lub nowe ID nie mogą ponownie rozliczyć zużytego bonu."""
    checkout_store.redeem_voucher(**checkout_request)
    before = checkout_file.read_bytes()
    checkout_request[field] = value
    if field == "redemption_mode":
        checkout_request["items"] = []
    with pytest.raises(KaucjomatError) as exc:
        checkout_store.redeem_voucher(**checkout_request)
    assert exc.value.error_code == code
    assert checkout_file.read_bytes() == before


@pytest.mark.parametrize(("changes", "code"), [
    ({"voucher_code": "NIEZNANY"}, "VOUCHER_NOT_FOUND"),
    ({"voucher_code": "BON-DEMO-EXP-0001"}, "VOUCHER_EXPIRED"),
    ({"items": []}, "BASKET_TOO_SMALL"),
    ({"items": [{"product_id": "bread-roll", "quantity": 1}]}, "BASKET_TOO_SMALL"),
    ({"items": [{"product_id": "nieznany", "quantity": 1}]}, "INVALID_CHECKOUT_REQUEST"),
    ({"items": [{"product_id": "bread-roll", "quantity": True}]}, "INVALID_CHECKOUT_REQUEST"),
    ({"items": [{"product_id": "bread-roll", "quantity": 2, "price": 100}]}, "INVALID_CHECKOUT_REQUEST"),
    ({"operation_id": "błędny-uuid"}, "INVALID_CHECKOUT_REQUEST"),
    ({"voucher_code": "   "}, "INVALID_CHECKOUT_REQUEST"),
])
def test_business_and_input_refusals_preserve_bytes(
    checkout_store: ReturnStateStore, checkout_request: dict[str, Any], checkout_file: Path,
    changes: dict[str, Any], code: str,
) -> None:
    """Każda odmowa nowej operacji zachowuje poprzedni plik bajtowo bez zmian."""
    before = checkout_file.read_bytes()
    checkout_request.update(changes)
    with pytest.raises(KaucjomatError) as exc:
        checkout_store.redeem_voucher(**checkout_request)
    assert exc.value.error_code == code
    assert checkout_file.read_bytes() == before


def test_replace_failure_cleans_temporary_file_and_allows_retry(
    checkout_store: ReturnStateStore, checkout_request: dict[str, Any], checkout_file: Path,
    monkeypatch: pytest.MonkeyPatch, checkout_logs: pytest.LogCaptureFixture,
) -> None:
    """Awaria podmiany nie publikuje sukcesu, nie zużywa bonu i nie pozostawia pliku tmp."""
    before = checkout_file.read_bytes()

    def broken_replace(source: Path, destination: Path) -> Path:
        """Przerywa zapis tuż przed publikacją nowej wersji pliku."""
        assert "Zapisano realizację" not in checkout_logs.text
        assert json.loads(source.read_bytes())["checkout_redemptions"]
        raise OSError("Symulacja awarii replace")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", broken_replace)
        with pytest.raises(ReturnStateStorageError):
            checkout_store.redeem_voucher(**checkout_request)
    assert checkout_file.read_bytes() == before
    assert not list(checkout_file.parent.glob("*.tmp"))
    assert "Nie udało się zapisać" in checkout_logs.text
    assert "Zapisano realizację" not in checkout_logs.text
    assert checkout_store.list_vouchers()[0].status == VoucherStatus.ACTIVE
    result, replayed = checkout_store.redeem_voucher(**checkout_request)
    assert replayed is False and result.voucher_status == VoucherStatus.REDEEMED
    assert "Zapisano realizację" in checkout_logs.text


def test_later_deposit_issue_and_reads_preserve_redemption_history(
    checkout_store: ReturnStateStore, checkout_request: dict[str, Any], checkout_file: Path,
) -> None:
    """Operacje butelkomatu zachowują generację i poprzednie wyniki kasy."""
    result, _ = checkout_store.redeem_voucher(**checkout_request)
    history = json.loads(checkout_file.read_bytes())["checkout_redemptions"]
    checkout_store.process_deposit(get_test_card_by_id("can-cola-500").candidate)
    checkout_store.issue_voucher()
    checkout_store.get_session_snapshot()
    checkout_store.list_vouchers()
    state = json.loads(checkout_file.read_bytes())
    assert state["checkout_redemptions"] == history
    assert state["demo_generation_id"] == checkout_request["demo_generation_id"]
    assert ReturnStateStore(checkout_file).redeem_voucher(**checkout_request) == (result, True)


def test_success_replay_and_sanitized_refusal_have_distinct_logs(
    checkout_store: ReturnStateStore, checkout_request: dict[str, Any], checkout_logs: pytest.LogCaptureFixture,
) -> None:
    """Log rozróżnia zapis, odtworzenie i odmowę oraz usuwa znaki sterujące wejścia."""
    checkout_store.redeem_voucher(**checkout_request)
    checkout_store.redeem_voucher(**checkout_request)
    checkout_request.update(operation_id=str(uuid4()), voucher_code="NIEZNANY\nFAŁSZYWY\tWPIS")
    with pytest.raises(KaucjomatError):
        checkout_store.redeem_voucher(**checkout_request)
    messages = [record.getMessage() for record in checkout_logs.records]
    assert sum("Zapisano realizację" in msg for msg in messages) == 1
    assert sum("Odtworzono wynik realizacji" in msg for msg in messages) == 1
    refusals = [msg for msg in messages if "Odmowa realizacji" in msg]
    assert len(refusals) == 1 and "VOUCHER_NOT_FOUND" in refusals[0]
    assert "\n" not in refusals[0] and "\t" not in refusals[0]


def test_refusal_on_missing_state_does_not_create_file(checkout_file: Path) -> None:
    """Stare żądanie do niezainicjalizowanego magazynu nie utrwala nowej generacji."""
    with pytest.raises(KaucjomatError):
        ReturnStateStore(checkout_file).redeem_voucher(str(uuid4()), str(uuid4()), "NIEZNANY", "cash", [])
    assert not checkout_file.exists()


def test_replay_does_not_accept_bool_equal_to_recorded_quantity(
    checkout_store: ReturnStateStore, checkout_request: dict[str, Any], checkout_file: Path,
) -> None:
    """Ścisła walidacja przed porównaniem chroni przed równością bool i int w Pythonie."""
    checkout_request["items"] = [{"product_id": "apple", "quantity": 1}]
    checkout_store.redeem_voucher(**checkout_request)
    before = checkout_file.read_bytes()
    checkout_request["items"][0]["quantity"] = True
    with pytest.raises(InvalidCheckoutRequestError):
        checkout_store.redeem_voucher(**checkout_request)
    assert checkout_file.read_bytes() == before
