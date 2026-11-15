"""Testy bezstratnej migracji v1 i jawnego wyjątku bonów historycznych bez daty."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from unittest.mock import patch

import pytest

from kaucjomat.checkout_exceptions import BasketTooSmallError, DemoGenerationConflictError, VoucherAlreadyRedeemedError
from kaucjomat.exceptions import ReturnStateStorageError
from kaucjomat.return_state_codec import validate_state_payload
from kaucjomat.return_store import ReturnStateStore
from kaucjomat.test_cards import get_test_card_by_id
from kaucjomat.voucher_state_codec import LEGACY_REDEEMED_MARKER


def test_lossless_migration_and_stable_generation(
    legacy_state: dict[str, Any], checkout_file: Path,
) -> None:
    """Migracja utrwala jeden UUID oraz zachowuje bony, próby, sesję i rejestr ID."""
    original = deepcopy(legacy_state)
    checkout_file.write_text(json.dumps(legacy_state), encoding="utf-8")
    store = ReturnStateStore(checkout_file)
    snapshot = store.get_checkout_snapshot()
    persisted = json.loads(checkout_file.read_text(encoding="utf-8"))
    assert str(UUID(snapshot.demo_generation_id)) == snapshot.demo_generation_id
    assert persisted["schema_version"] == 2
    assert persisted["checkout_redemptions"] == []
    for field in ("session", "returned_instance_ids", "vouchers"):
        assert persisted[field] == original[field]
    assert ReturnStateStore(checkout_file).get_checkout_snapshot() == snapshot
    assert len(validate_state_payload(persisted)) == 4
    assert validate_state_payload(persisted)[3] is False


def test_codec_does_not_mutate_legacy_input(legacy_state: dict[str, Any]) -> None:
    """Konwersja zwraca nowy obiekt i nie pozostawia częściowej migracji u wywołującego."""
    original = deepcopy(legacy_state)
    state, attempts, vouchers, migrated = validate_state_payload(legacy_state)
    assert migrated is True and state["schema_version"] == 2
    assert attempts and vouchers and legacy_state == original


@pytest.mark.parametrize("with_vouchers", [False, True])
def test_legacy_missing_seed_is_completed(
    legacy_state: dict[str, Any], with_vouchers: bool,
) -> None:
    """Obie starsze postaci v1 otrzymują wygasły seed oraz nowe pola kasy."""
    if with_vouchers:
        legacy_state["vouchers"] = legacy_state["vouchers"][:1]
    else:
        del legacy_state["vouchers"]
    state, _, vouchers, migrated = validate_state_payload(legacy_state)
    assert migrated and state["checkout_redemptions"] == []
    assert vouchers[-1].voucher_code == "BON-DEMO-EXP-0001"


@pytest.mark.parametrize("dated", [False, True])
def test_historical_redeemed_voucher_survives_restart_without_fake_result(
    legacy_state: dict[str, Any], checkout_file: Path, dated: bool,
) -> None:
    """Bon zużyty v1 pozostaje zużyty, bez dorabiania daty ani fikcyjnego rozliczenia."""
    old = legacy_state["vouchers"][0]
    old["status"] = "ZUŻYTY"
    old["redeemed_at_iso"] = old["issued_at_iso"] if dated else None
    checkout_file.write_text(json.dumps(legacy_state), encoding="utf-8")
    first = ReturnStateStore(checkout_file).get_checkout_snapshot()
    before = checkout_file.read_bytes()
    persisted = json.loads(before)
    assert persisted["checkout_redemptions"] == []
    assert persisted["vouchers"][0]["redeemed_at_iso"] == old["redeemed_at_iso"]
    assert (LEGACY_REDEEMED_MARKER in persisted["vouchers"][0]) is not dated
    restarted = ReturnStateStore(checkout_file)
    assert restarted.get_checkout_snapshot() == first
    with pytest.raises(VoucherAlreadyRedeemedError):
        restarted.redeem_voucher(str(uuid4()), first.demo_generation_id, old["voucher_code"], "cash", [])
    assert checkout_file.read_bytes() == before
    # Inna mutacja także musi zachować migracyjny znacznik i pustą historię realizacji.
    restarted.process_deposit(get_test_card_by_id("can-cola-500").candidate)
    restarted.issue_voucher()
    saved = json.loads(checkout_file.read_bytes())
    historical = next(v for v in saved["vouchers"] if v["voucher_code"] == old["voucher_code"])
    assert historical == persisted["vouchers"][0]
    assert saved["checkout_redemptions"] == []


@pytest.mark.parametrize("conflict", [
    "duplicate", "normalized_duplicate", "active_with_date", "expired_with_date", "forged_marker",
])
def test_ambiguous_legacy_data_is_rejected_without_writing(
    legacy_state: dict[str, Any], checkout_file: Path, conflict: str,
) -> None:
    """Zaostrzone reguły nie scalają starych bonów ani nie poprawiają ich automatycznie."""
    voucher = legacy_state["vouchers"][0]
    if conflict in {"duplicate", "normalized_duplicate"}:
        duplicate = deepcopy(voucher)
        if conflict == "normalized_duplicate":
            duplicate["voucher_code"] = f" {voucher['voucher_code'].lower()} "
        legacy_state["vouchers"].append(duplicate)
    elif conflict == "forged_marker":
        voucher[LEGACY_REDEEMED_MARKER] = True
    else:
        voucher["status"] = "AKTYWNY" if conflict == "active_with_date" else "WYGASŁY"
        voucher["redeemed_at_iso"] = voucher["issued_at_iso"]
    checkout_file.write_text(json.dumps(legacy_state, indent=1), encoding="utf-8")
    before = checkout_file.read_bytes()
    original = deepcopy(legacy_state)
    with pytest.raises(ValueError):
        validate_state_payload(legacy_state)
    assert legacy_state == original
    with pytest.raises(ReturnStateStorageError):
        ReturnStateStore(checkout_file).get_checkout_snapshot()
    assert checkout_file.read_bytes() == before


def test_refused_redemption_does_not_persist_migration(
    legacy_state: dict[str, Any], checkout_file: Path,
) -> None:
    """Odmowa starej generacji nie zapisuje nawet poprawnej migracji odczytanego v1."""
    checkout_file.write_text(json.dumps(legacy_state), encoding="utf-8")
    before = checkout_file.read_bytes()
    with pytest.raises(DemoGenerationConflictError):
        ReturnStateStore(checkout_file).redeem_voucher(
            str(uuid4()), str(uuid4()), legacy_state["vouchers"][0]["voucher_code"], "cash", [],
        )
    assert checkout_file.read_bytes() == before


def test_new_voucher_never_receives_legacy_marker(checkout_file: Path) -> None:
    """Zwykłe wystawienie i realizacja tworzą rekord bez wyjątku migracyjnego."""
    store = ReturnStateStore(checkout_file)
    store.process_deposit(get_test_card_by_id("can-cola-500").candidate)
    voucher, _, _ = store.issue_voucher()
    snapshot = store.get_checkout_snapshot()
    result, _ = store.redeem_voucher(str(uuid4()), snapshot.demo_generation_id, voucher.voucher_code, "cash", [])
    state = json.loads(checkout_file.read_bytes())
    assert LEGACY_REDEEMED_MARKER not in state["vouchers"][0]
    assert state["vouchers"][0]["redeemed_at_iso"] == result.redeemed_at_iso


def test_redeemed_voucher_still_requires_valid_expiry(legacy_state: dict[str, Any]) -> None:
    """Priorytet zużycia nie może ukrywać uszkodzonej daty ważności w magazynie."""
    legacy_state["vouchers"][0].update(status="ZUŻYTY", expires_at_iso="błędna-data")
    with pytest.raises(ValueError):
        validate_state_payload(legacy_state, now=datetime.now(UTC))


@pytest.mark.parametrize("status", ["AKTYWNY", "ZUŻYTY"])
def test_legacy_absent_optional_timestamp_becomes_valid_v2(
    legacy_state: dict[str, Any], checkout_file: Path, status: str,
) -> None:
    """Brak opcjonalnego klucza daty v1 nie tworzy po migracji nieczytelnego v2."""
    voucher = legacy_state["vouchers"][0]
    voucher["status"] = status
    del voucher["redeemed_at_iso"]
    checkout_file.write_text(json.dumps(legacy_state), encoding="utf-8")
    first = ReturnStateStore(checkout_file).get_checkout_snapshot()
    saved = json.loads(checkout_file.read_bytes())
    assert saved["vouchers"][0]["redeemed_at_iso"] is None
    assert (LEGACY_REDEEMED_MARKER in saved["vouchers"][0]) is (status == "ZUŻYTY")
    assert ReturnStateStore(checkout_file).get_checkout_snapshot() == first


def test_business_refusal_during_migration_does_not_save(
    legacy_state: dict[str, Any], checkout_file: Path,
) -> None:
    """Zgodna generacja nie powoduje zapisu migracji, gdy ocena nowej transakcji odmawia."""
    generation = uuid4()
    checkout_file.write_text(json.dumps(legacy_state, indent=1), encoding="utf-8")
    before = checkout_file.read_bytes()
    with patch("kaucjomat.checkout_state_codec.uuid4", return_value=generation):
        with pytest.raises(BasketTooSmallError):
            ReturnStateStore(checkout_file).redeem_voucher(
                str(uuid4()), str(generation), legacy_state["vouchers"][0]["voucher_code"], "purchases", [],
            )
    assert checkout_file.read_bytes() == before


def test_successful_mutation_also_persists_migration(
    legacy_state: dict[str, Any], checkout_file: Path,
) -> None:
    """Poprawny wrzut zapisuje całe v2, zachowując starsze bony i ich wyjątki."""
    legacy_state["vouchers"][0]["status"] = "ZUŻYTY"
    checkout_file.write_text(json.dumps(legacy_state), encoding="utf-8")
    store = ReturnStateStore(checkout_file)
    store.process_deposit(get_test_card_by_id("can-cola-500").candidate)
    state = json.loads(checkout_file.read_bytes())
    assert state["schema_version"] == 2 and state["checkout_redemptions"] == []
    assert state["session"]["session_id"] == legacy_state["session"]["session_id"]
    assert state["vouchers"][0][LEGACY_REDEEMED_MARKER] is True
    assert state["session"]["total_grosze"] == legacy_state["session"]["total_grosze"] + 50
    assert ReturnStateStore(checkout_file).get_checkout_snapshot().demo_generation_id == state["demo_generation_id"]


def test_migration_does_not_duplicate_seed_with_noncanonical_old_code(
    legacy_state: dict[str, Any],
) -> None:
    """Uzupełnianie seeda uwzględnia normalizację kodu, zachowując starszy zapis bez duplikatu."""
    legacy_state["vouchers"][-1]["voucher_code"] = " bon-demo-exp-0001 "
    state, _, vouchers, migrated = validate_state_payload(legacy_state)
    assert migrated and len(vouchers) == len(legacy_state["vouchers"])
    assert state["vouchers"] == legacy_state["vouchers"]
