"""Testy współbieżności jednej instancji magazynu oraz granicy resetu i czasu oceny."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import threading
from typing import Any
from uuid import uuid4

import pytest

from kaucjomat import checkout_redemption
from kaucjomat.checkout_domain import SettlementResult
from kaucjomat.checkout_exceptions import DemoGenerationConflictError, VoucherExpiredError
from kaucjomat.exceptions import KaucjomatError
from kaucjomat.return_store import ReturnStateStore
from kaucjomat.test_cards import get_test_card_by_id


def _race_requests(
    store: ReturnStateStore, requests: list[dict[str, Any]],
) -> list[tuple[SettlementResult, bool] | str]:
    """Uruchamia rzeczywiście jednoczesne próby przez barierę, zbierając także odmowy."""
    barrier = threading.Barrier(len(requests))

    def submit(payload: dict[str, Any]) -> tuple[SettlementResult, bool] | str:
        """Czeka na pozostałe wątki i wykonuje operację na wspólnym magazynie."""
        barrier.wait(timeout=5)
        try:
            return store.redeem_voucher(**payload)
        except KaucjomatError as exc:
            return exc.error_code

    with ThreadPoolExecutor(max_workers=len(requests)) as pool:
        return list(pool.map(submit, requests))


def test_competing_cash_and_purchases_redeem_exactly_once(
    checkout_store: ReturnStateStore, checkout_request: dict[str, Any], checkout_file: Path,
) -> None:
    """Osiem różnych ID w dwóch trybach daje jeden wynik i siedem odmów zużytego bonu."""
    requests = []
    for mode in ["cash", "purchases"] * 4:
        payload = deepcopy(checkout_request)
        payload.update(operation_id=str(uuid4()), redemption_mode=mode)
        if mode == "cash":
            payload["items"] = []
        requests.append(payload)
    results = _race_requests(checkout_store, requests)
    successes = [r for r in results if isinstance(r, tuple)]
    assert len(successes) == 1 and successes[0][1] is False
    assert results.count("VOUCHER_ALREADY_REDEEMED") == 7
    saved = json.loads(checkout_file.read_bytes())
    assert len(saved["checkout_redemptions"]) == 1
    assert saved["checkout_redemptions"][0]["result"]["redeemed_at_iso"] == successes[0][0].redeemed_at_iso


def test_identical_parallel_operations_write_once_and_replay(
    checkout_store: ReturnStateStore, checkout_request: dict[str, Any], checkout_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wspólne ID i payload powodują jeden zapis i siedem identycznych odtworzeń."""
    saved_states: list[dict[str, Any]] = []
    original_save = checkout_store._save_state

    def counted_save(state: dict[str, Any]) -> None:
        """Zlicza zapisy stanu wykonywane pod tą samą blokadą."""
        saved_states.append(deepcopy(state))
        original_save(state)

    monkeypatch.setattr(checkout_store, "_save_state", counted_save)
    results = _race_requests(checkout_store, [deepcopy(checkout_request) for _ in range(8)])
    assert all(isinstance(r, tuple) for r in results)
    assert len({r[0] for r in results}) == 1
    assert [r[1] for r in results].count(False) == 1
    assert [r[1] for r in results].count(True) == 7
    assert len(saved_states) == 1
    assert len(json.loads(checkout_file.read_bytes())["checkout_redemptions"]) == 1


def test_same_id_with_competing_payloads_returns_conflicts(
    checkout_store: ReturnStateStore, checkout_request: dict[str, Any], checkout_file: Path,
) -> None:
    """Po zapisaniu jednego wariantu wspólne ID nie pozwala zmienić trybu rozliczenia."""
    cash = dict(checkout_request, redemption_mode="cash", items=[])
    results = _race_requests(checkout_store, [deepcopy(p) for p in [cash, checkout_request] * 4])
    successes = [r for r in results if isinstance(r, tuple)]
    assert len(successes) == 4 and len({r[0] for r in successes}) == 1
    assert [r[1] for r in successes].count(False) == 1
    assert results.count("CHECKOUT_OPERATION_CONFLICT") == 4
    assert len(json.loads(checkout_file.read_bytes())["checkout_redemptions"]) == 1


@pytest.mark.parametrize("other_operation", ["deposit", "issue"])
def test_return_machine_and_checkout_share_one_transaction_lock(
    checkout_store: ReturnStateStore, checkout_request: dict[str, Any], checkout_file: Path,
    other_operation: str,
) -> None:
    """Wrzut albo wystawienie współbieżne z realizacją nie gubi żadnej części pliku."""
    card = get_test_card_by_id("can-cola-500").candidate
    if other_operation == "issue":
        checkout_store.process_deposit(card)
    barrier = threading.Barrier(2)

    def redeem() -> None:
        """Realizuje dotychczasowy bon równolegle z operacją butelkomatu."""
        barrier.wait(timeout=5)
        checkout_store.redeem_voucher(**checkout_request)

    def mutate_returns() -> None:
        """Wykonuje drugą mutację tego samego stanu JSON."""
        barrier.wait(timeout=5)
        if other_operation == "issue":
            checkout_store.issue_voucher()
        else:
            checkout_store.process_deposit(card)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(redeem), pool.submit(mutate_returns)]
        for future in futures:
            future.result(timeout=5)
    state = json.loads(checkout_file.read_bytes())
    assert len(state["checkout_redemptions"]) == 1
    assert len(state["returned_instance_ids"]) == 3
    assert state["demo_generation_id"] == checkout_request["demo_generation_id"]
    assert len(state["vouchers"]) == (3 if other_operation == "issue" else 2)
    assert state["session"]["total_grosze"] == (0 if other_operation == "issue" else 50)
    assert ReturnStateStore(checkout_file).redeem_voucher(**checkout_request)[1] is True


def test_reset_invalidates_old_request_even_when_voucher_code_reappears(
    checkout_store: ReturnStateStore, checkout_request: dict[str, Any], checkout_file: Path,
) -> None:
    """Generacja jest sprawdzana przed replayem i wyszukaniem odtworzonego kodu bonu."""
    original = json.loads(checkout_file.read_bytes())
    checkout_store.redeem_voucher(**checkout_request)
    old_session = original["session"]["session_id"]
    checkout_store.reset_demo_state()
    reset_state = json.loads(checkout_file.read_bytes())
    assert reset_state["demo_generation_id"] != checkout_request["demo_generation_id"]
    assert reset_state["checkout_redemptions"] == []
    assert reset_state["session"]["session_id"] != old_session
    assert reset_state["session"]["attempts"] == [] and reset_state["returned_instance_ids"] == []
    assert [v["voucher_code"] for v in reset_state["vouchers"]] == ["BON-DEMO-EXP-0001"]
    # Celowo przywracamy identyczny aktywny kod w nowym pokazie, bez polegania na losowych ID.
    reset_state["vouchers"].insert(0, original["vouchers"][0])
    checkout_file.write_text(json.dumps(reset_state), encoding="utf-8")
    before = checkout_file.read_bytes()
    with pytest.raises(DemoGenerationConflictError):
        checkout_store.redeem_voucher(**checkout_request)
    assert checkout_file.read_bytes() == before
    checkout_request["demo_generation_id"] = reset_state["demo_generation_id"]
    assert checkout_store.redeem_voucher(**checkout_request)[1] is False


def test_expiry_is_checked_after_waiting_for_store_lock(
    checkout_store: ReturnStateStore, checkout_request: dict[str, Any], checkout_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bon wygasły podczas oczekiwania nie korzysta z czasu zapamiętanego przed blokadą."""
    state = json.loads(checkout_file.read_bytes())
    expiry = datetime.fromisoformat(state["vouchers"][0]["expires_at_iso"])
    clock_value = expiry - timedelta(microseconds=1)
    entered = threading.Event()
    clock_calls: list[datetime] = []

    class ControlledClock:
        """Zegar kontrolowany bez opóźnień i bez zależności od szybkości maszyny."""

        @staticmethod
        def now(zone: object) -> datetime:
            """Zapamiętuje chwilę oceny i podaje ustawioną wartość czasu."""
            clock_calls.append(clock_value)
            return clock_value

    def redeem() -> None:
        """Sygnalizuje rozpoczęcie wywołania, które musi poczekać na blokadę."""
        entered.set()
        checkout_store.redeem_voucher(**checkout_request)

    monkeypatch.setattr(checkout_redemption, "datetime", ControlledClock)
    before = checkout_file.read_bytes()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with checkout_store._lock:
            future = pool.submit(redeem)
            assert entered.wait(timeout=5)
            assert not clock_calls
            clock_value = expiry
        with pytest.raises(VoucherExpiredError):
            future.result(timeout=5)
    assert clock_calls == [expiry]
    assert checkout_file.read_bytes() == before
