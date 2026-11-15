"""Wspólne, odizolowane dane magazynu dla testów trwałej realizacji bonów DEMO."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from kaucjomat.return_store import ReturnStateStore
from kaucjomat.logging_config import get_logger
from kaucjomat.test_cards import get_test_card_by_id


@pytest.fixture
def checkout_file(tmp_path: Path) -> Path:
    """Zwraca odizolowaną ścieżkę stanu bez używania danych demonstracji użytkownika."""
    return tmp_path / "checkout.json"


@pytest.fixture
def checkout_store(checkout_file: Path) -> ReturnStateStore:
    """Wystawia aktywny bon na 100 gr w magazynie współdzielonym przez dany test."""
    store = ReturnStateStore(checkout_file)
    for card_id in ("pet-water-1500-a", "pet-water-1500-b"):
        store.process_deposit(get_test_card_by_id(card_id).candidate)
    store.issue_voucher()
    return store


@pytest.fixture
def checkout_request(checkout_store: ReturnStateStore) -> dict[str, Any]:
    """Przygotowuje zakup dwóch bułek za dokładną wartość wystawionego bonu."""
    snapshot = checkout_store.get_checkout_snapshot()
    return {
        "operation_id": str(uuid4()),
        "demo_generation_id": snapshot.demo_generation_id,
        "voucher_code": snapshot.vouchers[0].voucher_code,
        "redemption_mode": "purchases",
        "items": [{"product_id": "bread-roll", "quantity": 2}],
    }


@pytest.fixture
def redeemed_state(
    checkout_store: ReturnStateStore, checkout_request: dict[str, Any], checkout_file: Path,
) -> dict[str, Any]:
    """Zwraca prawdziwy zapis v2 z bonem zużytym i powiązaną historią zakupów."""
    checkout_store.redeem_voucher(**checkout_request)
    return json.loads(checkout_file.read_text(encoding="utf-8"))


@pytest.fixture
def legacy_state(checkout_store: ReturnStateStore, checkout_file: Path) -> dict[str, Any]:
    """Buduje stan v1 z bonami, rejestrem ID i niepustą historią otwartej sesji."""
    checkout_store.process_deposit(get_test_card_by_id("glass-beer-500").candidate)
    raw = json.loads(checkout_file.read_text(encoding="utf-8"))
    raw["schema_version"] = 1
    del raw["demo_generation_id"], raw["checkout_redemptions"]
    return raw


@pytest.fixture
def checkout_logs(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.LogCaptureFixture]:
    """Przechwytuje logger magazynu niezależnie od konfiguracji konsoli i propagacji aplikacji."""
    logger = get_logger("returns.store")
    monkeypatch.setattr(logger, "handlers", [caplog.handler])
    monkeypatch.setattr(logger, "propagate", False)
    with caplog.at_level(logging.INFO, logger=logger.name):
        yield caplog
