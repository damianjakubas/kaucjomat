"""Testy integracyjne API bonów kaucjomatowych (/api/returns/voucher*) i migracji stanu."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from kaucjomat.app import create_app
from kaucjomat.return_store import ReturnStateStore
from kaucjomat.test_cards import get_test_card_by_id


def _make_client(state_file: Path) -> TestClient:
    """Tworzy klienta FastAPI podpiętego do odizolowanego pliku stanu JSON."""
    return TestClient(create_app(state_file=state_file))


def test_list_vouchers_on_fresh_state_returns_seeded_expired_voucher(tmp_path: Path) -> None:
    """Czysty stan zawiera fabrycznie 1 wygasły bon testowy BON-DEMO-EXP-0001 (DEMO)."""
    client = _make_client(tmp_path / "state.json")

    response = client.get("/api/returns/vouchers")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "DEMO"
    assert len(body["vouchers"]) == 1
    seed = body["vouchers"][0]
    assert seed["mode"] == "DEMO"
    assert seed["voucher_code"] == "BON-DEMO-EXP-0001"
    assert seed["status"] == "WYGASŁY"
    assert seed["is_test_seed"] is True
    assert "DEMO" in seed["demo_watermark"]


def test_issue_voucher_rejects_empty_or_non_earning_session(tmp_path: Path) -> None:
    """Sesja z kwotą 0,00 zł (pusta oraz po samym szkle/odrzuceniach) zwraca 400."""
    client = _make_client(tmp_path / "state.json")

    empty_resp = client.post("/api/returns/voucher")
    assert empty_resp.status_code == 400
    assert empty_resp.json()["error_code"] == "EMPTY_RETURN_SESSION"

    client.post("/api/returns/deposit", json={"card_id": "glass-beer-500"})
    client.post("/api/returns/deposit", json={"card_id": "reject-no-logo"})

    non_earning_resp = client.post("/api/returns/voucher", json={})
    assert non_earning_resp.status_code == 400
    assert non_earning_resp.json()["error_code"] == "EMPTY_RETURN_SESSION"


def test_issue_voucher_closes_session_preserves_registry_and_blocks_duplicate(
    tmp_path: Path,
) -> None:
    """Wystawienie bonu zamyka sesję, otwiera nową (+100 dni ważności) i chroni rejestr ID."""
    client = _make_client(tmp_path / "state.json")
    client.post("/api/returns/deposit", json={"card_id": "pet-water-1500-a"})
    second = client.post("/api/returns/deposit", json={"card_id": "pet-water-1500-b"}).json()
    closed_session_id = second["session"]["session_id"]

    issue_resp = client.post("/api/returns/voucher", json={"session_id": closed_session_id})

    assert issue_resp.status_code == 200
    data = issue_resp.json()
    assert data["mode"] == "DEMO"
    assert data["was_idempotent_replay"] is False

    voucher = data["voucher"]
    assert voucher["mode"] == "DEMO"
    assert voucher["voucher_code"].startswith("BON-DEMO-0001-")
    assert voucher["source_session_id"] == closed_session_id
    assert voucher["status"] == "AKTYWNY"
    assert voucher["amount_grosze"] == 100
    assert voucher["amount_formatted"] == "1,00 zł"
    assert voucher["accepted_count"] == 2
    assert voucher["validity_days"] == 100
    assert voucher["is_test_seed"] is False
    assert "DEMO" in voucher["demo_watermark"]
    issued_dt = datetime.fromisoformat(voucher["issued_at_iso"])
    expires_dt = datetime.fromisoformat(voucher["expires_at_iso"])
    assert expires_dt - issued_dt == timedelta(days=100)

    new_session = data["session"]
    assert new_session["session_id"] != closed_session_id
    assert new_session["total_grosze"] == 0
    assert new_session["accepted_count"] == 0
    assert new_session["returned_registry_size"] == 2
    assert new_session["can_issue_voucher"] is False

    # Ta sama butelka wrzucona w nowej sesji nadal musi zostać zablokowana jako duplikat.
    dup_resp = client.post("/api/returns/deposit", json={"card_id": "pet-water-1500-a"})
    assert dup_resp.status_code == 200
    assert dup_resp.json()["decision"]["reason_code"] == "DUPLICATE_INSTANCE_ID"


def test_idempotent_replay_and_voucher_error_contracts(tmp_path: Path) -> None:
    """Powtórzone session_id oddaje istniejący bon, nie zamykając nowej sesji."""
    client = _make_client(tmp_path / "state.json")
    dep = client.post("/api/returns/deposit", json={"card_id": "can-cola-500"}).json()
    first_session_id = dep["session"]["session_id"]

    first_issue = client.post("/api/returns/voucher", json={"session_id": first_session_id}).json()
    second_deposit = client.post(
        "/api/returns/deposit", json={"card_id": "pet-water-1500-a"}
    ).json()
    active_session_id = second_deposit["session"]["session_id"]

    replay_resp = client.post("/api/returns/voucher", json={"session_id": first_session_id})
    assert replay_resp.status_code == 200
    replay = replay_resp.json()
    assert replay["was_idempotent_replay"] is True
    assert replay["voucher"]["voucher_code"] == first_issue["voucher"]["voucher_code"]
    assert replay["session"]["session_id"] == active_session_id
    assert replay["session"]["total_grosze"] == 50

    conflict_resp = client.post("/api/returns/voucher", json={"session_id": "DEMO-NIEISTNIEJE"})
    assert conflict_resp.status_code == 409
    assert conflict_resp.json()["error_code"] == "SESSION_VOUCHER_CONFLICT"

    blank_resp = client.post("/api/returns/voucher", json={"session_id": "   "})
    assert blank_resp.status_code == 400
    assert blank_resp.json()["error_code"] == "INVALID_DEPOSIT_REQUEST"

    too_long_resp = client.post("/api/returns/voucher", json={"session_id": "X" * 65})
    assert too_long_resp.status_code == 422
    assert too_long_resp.json()["error_code"] == "VALIDATION_ERROR"


def test_lossless_migration_of_v1_state_without_vouchers_key(tmp_path: Path) -> None:
    """Plik JSON bez klucza vouchers zachowuje rejestr ID i sesję oraz dopisuje seed."""
    state_file = tmp_path / "legacy_v1.json"
    legacy_payload = {
        "schema_version": 1,
        "returned_instance_ids": ["PET-5900000000114-000101"],
        "session": {
            "session_id": "DEMO-LEGACY01",
            "status": "OPEN",
            "accepted_count": 1,
            "redirected_glass_count": 0,
            "rejected_count": 0,
            "total_grosze": 50,
            "attempts": [],
        },
    }
    state_file.write_text(json.dumps(legacy_payload, ensure_ascii=False), encoding="utf-8")
    client = _make_client(state_file)

    vouchers_resp = client.get("/api/returns/vouchers")
    assert vouchers_resp.status_code == 200
    vouchers = vouchers_resp.json()["vouchers"]
    assert len(vouchers) == 1
    assert vouchers[0]["voucher_code"] == "BON-DEMO-EXP-0001"
    assert vouchers[0]["status"] == "WYGASŁY"

    session_resp = client.get("/api/returns/session")
    assert session_resp.status_code == 200
    session_data = session_resp.json()
    assert session_data["session_id"] == "DEMO-LEGACY01"
    assert session_data["total_grosze"] == 50
    assert session_data["returned_registry_size"] == 1

    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    assert len(persisted["vouchers"]) == 1
    assert persisted["vouchers"][0]["voucher_code"] == "BON-DEMO-EXP-0001"


def test_reset_removes_user_vouchers_and_restores_expired_seed(tmp_path: Path) -> None:
    """Reset DEMO usuwa bony użytkownika i przywraca pojedynczy BON-DEMO-EXP-0001."""
    client = _make_client(tmp_path / "state.json")
    client.post("/api/returns/deposit", json={"card_id": "pet-water-1500-a"})
    client.post("/api/returns/voucher")
    assert len(client.get("/api/returns/vouchers").json()["vouchers"]) == 2

    reset_resp = client.post("/api/returns/reset")
    assert reset_resp.status_code == 200
    assert "bon" in reset_resp.json()["message"].lower()

    after_reset = client.get("/api/returns/vouchers").json()["vouchers"]
    assert [item["voucher_code"] for item in after_reset] == ["BON-DEMO-EXP-0001"]


@pytest.mark.parametrize("worker_count", [6])
def test_concurrent_issue_voucher_creates_exactly_one_voucher(
    tmp_path: Path,
    worker_count: int,
) -> None:
    """Współbieżne wywołania issue_voucher dla tego samego session_id tworzą 1 bon."""
    store = ReturnStateStore(tmp_path / "concurrent_voucher.json")
    _, snapshot = store.process_deposit(get_test_card_by_id("can-cola-500").candidate)
    target_session_id = snapshot.session_id

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        results = list(pool.map(store.issue_voucher, [target_session_id] * worker_count))

    created_codes = {voucher.voucher_code for voucher, _, _ in results}
    replay_flags = [replayed for _, _, replayed in results]
    assert len(created_codes) == 1
    assert replay_flags.count(False) == 1
    assert replay_flags.count(True) == worker_count - 1

    all_vouchers = store.list_vouchers()
    assert len(all_vouchers) == 2
    assert all_vouchers[0].source_session_id == target_session_id
    assert all_vouchers[1].voucher_code == "BON-DEMO-EXP-0001"


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("expires_at_iso", "not-an-iso-date"),
        ("expires_at_iso", "2026-04-12T10:00:00"),
        ("issued_at_iso", "2026-01-02T10:00:00"),
        ("redeemed_at_iso", "invalid-redeemed-ts"),
    ],
)
def test_corrupted_voucher_timestamp_returns_storage_error_500(
    tmp_path: Path,
    field_name: str,
    bad_value: str,
) -> None:
    """Uszkodzony lub pozbawiony strefy czasowej timestamp bonu w pliku stanu daje HTTP 500."""
    state_file = tmp_path / "corrupt_voucher.json"
    client = _make_client(state_file)
    assert client.get("/api/returns/vouchers").status_code == 200

    raw_state = json.loads(state_file.read_text(encoding="utf-8"))
    raw_state["vouchers"][0][field_name] = bad_value
    state_file.write_text(json.dumps(raw_state), encoding="utf-8")

    response = client.get("/api/returns/vouchers")
    assert response.status_code == 500
    assert response.json()["error_code"] == "RETURN_STATE_STORAGE_ERROR"
