"""Testy migracji starszego v2 i integralności trwałych rozliczeń ze zwrotem szkła DEMO."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from kaucjomat.checkout_exceptions import RedemptionOperationConflictError
from kaucjomat.checkout_state_codec import settlement_from_dict, validate_checkout_state
from kaucjomat.exceptions import ReturnStateStorageError
from kaucjomat.return_state_codec import validate_state_payload
from kaucjomat.return_store import ReturnStateStore
from kaucjomat.test_cards import get_test_card_by_id


@pytest.fixture
def glass_state(
    checkout_store: ReturnStateStore, checkout_request: dict[str, Any], checkout_file: Path,
) -> dict[str, Any]:
    """Zapisuje zakup za 400 gr pomniejszony o bon 100 gr i dwie butelki po 100 gr."""
    checkout_request.update(glass_count=2, items=[{"product_id": "bread", "quantity": 1}])
    checkout_store.redeem_voucher(**checkout_request)
    return json.loads(checkout_file.read_bytes())


def _remove_glass_fields(entry: dict[str, Any]) -> None:
    """Odtwarza dokładny kształt pary żądania i wyniku zapisanej przed obsługą szkła."""
    del entry["request"]["glass_count"], entry["result"]["glass_count"], entry["result"]["glass_return_grosze"]


def _assert_rejected_without_write(state: dict[str, Any], state_file: Path) -> None:
    """Sprawdza odmowę kodeka i magazynu bez częściowej zmiany wejścia ani bajtów źródła."""
    original = deepcopy(state)
    with pytest.raises(ValueError):
        validate_state_payload(state)
    assert state == original
    state_file.write_text(json.dumps(state, indent=1), encoding="utf-8")
    before = state_file.read_bytes()
    with pytest.raises(ReturnStateStorageError):
        ReturnStateStore(state_file).get_checkout_snapshot()
    assert state_file.read_bytes() == before


@pytest.mark.parametrize("mode", ["purchases", "cash"])
@pytest.mark.parametrize("read_method", ["get_checkout_snapshot", "get_session_snapshot", "list_vouchers", "replay"])
def test_legacy_v2_migrates_losslessly_once_and_replays(
    checkout_store: ReturnStateStore, checkout_request: dict[str, Any], checkout_file: Path,
    mode: str, read_method: str,
) -> None:
    """Starsza para v2 otrzymuje wyłącznie zera, zachowując wynik, UUID oraz dane butelkomatu."""
    checkout_request.update(redemption_mode=mode, items=[] if mode == "cash" else checkout_request["items"])
    result, _ = checkout_store.redeem_voucher(**checkout_request)
    expected = json.loads(checkout_file.read_bytes())
    legacy = deepcopy(expected)
    _remove_glass_fields(legacy["checkout_redemptions"][0])
    original = deepcopy(legacy)
    normalized, _, _, migrated = validate_state_payload(legacy)
    assert migrated is True and normalized == expected and legacy == original
    assert validate_state_payload(normalized)[3] is False
    checkout_file.write_text(json.dumps(legacy), encoding="utf-8")
    restarted = ReturnStateStore(checkout_file)
    if read_method == "replay":
        assert restarted.redeem_voucher(**checkout_request) == (result, True)
    else:
        getattr(restarted, read_method)()
    assert json.loads(checkout_file.read_bytes()) == expected
    before = checkout_file.read_bytes()
    assert ReturnStateStore(checkout_file).redeem_voucher(**checkout_request) == (result, True)
    assert checkout_file.read_bytes() == before


def test_mixed_history_normalizes_only_legacy_entry(
    redeemed_state: dict[str, Any], checkout_store: ReturnStateStore,
    checkout_request: dict[str, Any], checkout_file: Path,
) -> None:
    """Wspólna historia zachowuje nowe rozliczenie ze szkłem i migruje tylko starszą parę."""
    checkout_store.process_deposit(get_test_card_by_id("can-cola-500").candidate)
    voucher, _, _ = checkout_store.issue_voucher()
    checkout_request.update(operation_id=str(uuid4()), voucher_code=voucher.voucher_code,
                            redemption_mode="cash", items=[], glass_count=20)
    checkout_store.redeem_voucher(**checkout_request)
    expected = json.loads(checkout_file.read_bytes())
    mixed = deepcopy(expected)
    _remove_glass_fields(mixed["checkout_redemptions"][0])
    assert validate_checkout_state(mixed, migrating=False) is True
    assert mixed == expected
    assert validate_checkout_state(mixed, migrating=False) is False


@pytest.mark.parametrize("missing_mask", range(1, 7))
def test_partial_glass_records_are_never_migrated(
    redeemed_state: dict[str, Any], checkout_file: Path, missing_mask: int,
) -> None:
    """Każdy niepełny podzbiór trzech pól szkła oznacza uszkodzenie, także przy zerach."""
    entry = redeemed_state["checkout_redemptions"][0]
    for bit, (section, key) in enumerate([
        ("request", "glass_count"), ("result", "glass_count"), ("result", "glass_return_grosze"),
    ]):
        if missing_mask & (1 << bit):
            del entry[section][key]
    with pytest.raises(ValueError, match="Niekompletny zapis zwrotu szkła"):
        validate_checkout_state(deepcopy(redeemed_state), migrating=False)
    _assert_rejected_without_write(redeemed_state, checkout_file)


@pytest.mark.parametrize(("section", "key", "value"), [
    ("request", "glass_count", 1),
    ("request", "glass_count", True),
    ("request", "glass_count", 2.0),
    ("request", "glass_count", "2"),
    ("request", "glass_count", -1),
    ("request", "glass_count", 21),
    ("result", "glass_count", True),
    ("result", "glass_count", 2.0),
    ("result", "glass_count", "2"),
    ("result", "glass_count", -1),
    ("result", "glass_count", 21),
    ("result", "glass_return_grosze", True),
    ("result", "glass_return_grosze", 200.0),
    ("result", "glass_return_grosze", "200"),
    ("result", "glass_return_grosze", -1),
    ("result", "glass_return_grosze", 199),
    ("result", "glass_return_grosze", 201),
    ("result", "amount_due_grosze", 300),
    ("result", "cash_payout_grosze", 1),
])
def test_glass_history_rejects_types_amounts_and_request_mismatch(
    glass_state: dict[str, Any], checkout_file: Path, section: str, key: str, value: Any,
) -> None:
    """Kodek nie dopuszcza zmiany kaucji, niespójnych równań ani rozbieżności liczby butelek."""
    glass_state["checkout_redemptions"][0][section][key] = value
    _assert_rejected_without_write(glass_state, checkout_file)


def test_glass_cannot_exceed_purchase_total_in_history(glass_state: dict[str, Any], checkout_file: Path) -> None:
    """Nawet nieujemna dopłata nie usprawiedliwia koszyka mniejszego niż suma bonu i szkła."""
    entry = glass_state["checkout_redemptions"][0]
    entry["request"]["glass_count"] = 4
    entry["result"].update(glass_count=4, glass_return_grosze=400, amount_due_grosze=0)
    _assert_rejected_without_write(glass_state, checkout_file)


@pytest.mark.parametrize("payout", [100, 299, 301])
def test_cash_history_requires_voucher_plus_glass(
    glass_state: dict[str, Any], checkout_file: Path, payout: int,
) -> None:
    """Historyczna wypłata musi dokładnie pokrywać bon oraz kaucję za przyjęte szkło."""
    entry = glass_state["checkout_redemptions"][0]
    entry["request"].update(redemption_mode="cash", items=[])
    entry["result"].update(redemption_mode="cash", items=[], basket_total_grosze=0,
                           amount_due_grosze=0, cash_payout_grosze=payout)
    _assert_rejected_without_write(glass_state, checkout_file)


@pytest.mark.parametrize("section", ["request", "result"])
def test_legacy_migration_requires_exact_key_sets(
    redeemed_state: dict[str, Any], checkout_file: Path, section: str,
) -> None:
    """Brak szkła nie daje prawa do migrowania starszej pary z obcymi polami."""
    entry = redeemed_state["checkout_redemptions"][0]
    _remove_glass_fields(entry)
    entry[section]["unexpected"] = 0
    _assert_rejected_without_write(redeemed_state, checkout_file)


def test_refused_operation_does_not_persist_legacy_v2_migration(
    redeemed_state: dict[str, Any], checkout_request: dict[str, Any], checkout_file: Path,
) -> None:
    """Zmiana liczby butelek odmawia konfliktu, nie utrwalając nawet poprawnej migracji v2."""
    _remove_glass_fields(redeemed_state["checkout_redemptions"][0])
    checkout_file.write_text(json.dumps(redeemed_state, indent=1), encoding="utf-8")
    before = checkout_file.read_bytes()
    with pytest.raises(RedemptionOperationConflictError):
        ReturnStateStore(checkout_file).redeem_voucher(**checkout_request, glass_count=1)
    assert checkout_file.read_bytes() == before


def test_snapshot_decoder_does_not_migrate_legacy_in_isolation(redeemed_state: dict[str, Any]) -> None:
    """Samego wyniku bez pól szkła nie można naprawić bez zgodnego starszego żądania."""
    result = redeemed_state["checkout_redemptions"][0]["result"]
    del result["glass_count"], result["glass_return_grosze"]
    with pytest.raises(ValueError):
        settlement_from_dict(result)
