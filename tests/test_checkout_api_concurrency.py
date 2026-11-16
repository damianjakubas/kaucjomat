"""Rzeczywiście nakładające się żądania HTTP do jednego magazynu aplikacji DEMO."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest


@pytest.mark.parametrize("same_operation", [False, True])
def test_parallel_http_redemptions_commit_once(
    checkout_client: TestClient, checkout_request: dict[str, Any], checkout_file: Path,
    same_operation: bool,
) -> None:
    """Osiem klientów jednego procesu dostaje jeden pierwszy sukces oraz odmowy lub replaye."""
    barrier = Barrier(8)

    def submit(index: int) -> tuple[int, dict[str, Any]]:
        """Synchronizuje start żądań realizacji bez sztucznego opóźniania testu."""
        payload = deepcopy(checkout_request)
        if not same_operation:
            payload["operation_id"] = str(uuid4())
            if index % 2:
                payload.update(redemption_mode="cash", items=[])
        barrier.wait(timeout=5)
        response = checkout_client.post("/api/checkout/redeem", json=payload)
        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(submit, range(8)))
    successes = [body for status, body in responses if status == 200]
    assert sum(body["was_idempotent_replay"] is False for body in successes) == 1
    if same_operation:
        assert len(successes) == 8 and sum(body["was_idempotent_replay"] for body in successes) == 7
        assert all(body["settlement"] == successes[0]["settlement"] for body in successes)
    else:
        assert len(successes) == 1
        assert [(status, body["error_code"]) for status, body in responses if status != 200] == [
            (409, "VOUCHER_ALREADY_REDEEMED"),
        ] * 7
    state = json.loads(checkout_file.read_bytes())
    assert len(state["checkout_redemptions"]) == 1
    assert state["vouchers"][0]["redeemed_at_iso"] == successes[0]["settlement"]["redeemed_at_iso"]


def test_parallel_return_deposit_and_checkout_keep_both_changes(
    checkout_client: TestClient, checkout_request: dict[str, Any], checkout_file: Path,
) -> None:
    """Routery butelkomatu i kasy zachowują jednoczesne mutacje we wspólnym pliku."""
    barrier = Barrier(2)

    def submit(endpoint: str) -> int:
        """Wysyła wrzut lub realizację do tej samej działającej aplikacji."""
        payload = checkout_request if endpoint == "checkout/redeem" else {"card_id": "can-cola-500"}
        barrier.wait(timeout=5)
        return checkout_client.post(f"/api/{endpoint}", json=payload).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(submit, ["returns/deposit", "checkout/redeem"])) == [200, 200]
    state = json.loads(checkout_file.read_bytes())
    assert len(state["checkout_redemptions"]) == 1 and len(state["returned_instance_ids"]) == 3
    session = checkout_client.get("/api/returns/session").json()
    assert session["accepted_count"] == 1 and session["total_grosze"] == 50
