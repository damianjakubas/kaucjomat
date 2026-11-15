"""Testy integracyjne API zwrotów (/api/returns/*) oraz trwałości stanu JSON DEMO."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kaucjomat.app import create_app
from kaucjomat.return_store import ReturnStateStore
from kaucjomat.test_cards import get_test_card_by_id


def _make_client(state_file: Path) -> TestClient:
    """Tworzy klienta FastAPI podpiętego do wskazanego pliku stanu JSON."""
    return TestClient(create_app(state_file=state_file))


def test_list_returns_cards_exposes_eight_demo_cards(tmp_path: Path) -> None:
    """Endpoint GET /api/returns/cards zwraca dokładnie 8 kart testowych DEMO."""
    client = _make_client(tmp_path / "state.json")

    response = client.get("/api/returns/cards")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "DEMO"
    assert len(payload["cards"]) == 8
    for card in payload["cards"]:
        assert card["card_id"]
        assert card["package_code"]
        assert card["expected_hint"]


def test_deposit_flow_same_ean_duplicate_and_persistence_across_restart(tmp_path: Path) -> None:
    """Weryfikuje akceptację różnych ID dla tego samego EAN, duplikat i trwałość po restarcie."""
    state_file = tmp_path / "state" / "return_state.json"
    client = _make_client(state_file)

    first = client.post("/api/returns/deposit", json={"card_id": "pet-water-1500-a"})
    second = client.post("/api/returns/deposit", json={"card_id": "pet-water-1500-b"})
    third = client.post("/api/returns/deposit", json={"card_id": "can-cola-500"})

    assert first.status_code == 200
    assert first.json()["decision"]["status"] == "ACCEPTED"
    assert first.json()["decision"]["deposit_grosze"] == 50

    assert second.status_code == 200
    assert second.json()["decision"]["status"] == "ACCEPTED"
    assert second.json()["decision"]["ean"] == first.json()["decision"]["ean"]
    assert second.json()["decision"]["instance_id"] != first.json()["decision"]["instance_id"]
    assert second.json()["session"]["total_grosze"] == 100
    assert second.json()["session"]["total_formatted"] == "1,00 zł"

    assert third.status_code == 200
    assert third.json()["decision"]["status"] == "ACCEPTED"
    assert third.json()["session"]["total_grosze"] == 150
    assert third.json()["session"]["total_formatted"] == "1,50 zł"
    assert third.json()["session"]["accepted_count"] == 3
    assert third.json()["session"]["returned_registry_size"] == 3
    assert third.json()["session"]["can_issue_voucher"] is True

    # Drugi wrzut dokładnie tej samej sztuki zostaje zablokowany bez zmiany sumy kaucji.
    duplicate = client.post("/api/returns/deposit", json={"card_id": "pet-water-1500-a"})
    assert duplicate.status_code == 200
    dup_payload = duplicate.json()
    assert dup_payload["decision"]["status"] == "REJECTED"
    assert dup_payload["decision"]["reason_code"] == "DUPLICATE_INSTANCE_ID"
    assert dup_payload["session"]["total_grosze"] == 150
    assert dup_payload["session"]["rejected_count"] == 1
    assert dup_payload["session"]["attempts"][0]["attempt_no"] == 4

    # Symulacja restartu serwera przez nową instancję FastAPI na tym samym pliku JSON.
    restarted_client = _make_client(state_file)
    session_resp = restarted_client.get("/api/returns/session")
    assert session_resp.status_code == 200
    session_data = session_resp.json()
    assert session_data["session_id"] == dup_payload["session"]["session_id"]
    assert session_data["total_grosze"] == 150
    assert session_data["returned_registry_size"] == 3
    assert len(session_data["attempts"]) == 4

    duplicate_after_restart = restarted_client.post(
        "/api/returns/deposit",
        json={"card_id": "pet-water-1500-b"},
    )
    assert duplicate_after_restart.status_code == 200
    assert duplicate_after_restart.json()["decision"]["reason_code"] == "DUPLICATE_INSTANCE_ID"


def test_glass_redirect_and_all_invalid_cards_do_not_increment_registry(tmp_path: Path) -> None:
    """Szkło trafia do Kasy Sklepowej, a 4 karty błędne są odrzucane bez wpisu do rejestru."""
    client = _make_client(tmp_path / "state.json")

    glass_resp = client.post("/api/returns/deposit", json={"card_id": "glass-beer-500"})
    assert glass_resp.status_code == 200
    glass_data = glass_resp.json()
    assert glass_data["decision"]["status"] == "REDIRECT_TO_CASHIER"
    assert glass_data["decision"]["deposit_grosze"] == 0
    assert glass_data["decision"]["cashier_suggested_grosze"] == 100
    assert glass_data["session"]["redirected_glass_count"] == 1
    assert glass_data["session"]["returned_registry_size"] == 0
    assert glass_data["session"]["total_grosze"] == 0

    expected_rejections = {
        "reject-no-logo": "MISSING_DEPOSIT_LOGO",
        "reject-crushed-can": "CRUSHED_OR_DAMAGED",
        "reject-dairy-carton": "EXCLUDED_CATEGORY",
        "reject-over-volume": "VOLUME_LIMIT_EXCEEDED",
    }
    for card_id, expected_reason in expected_rejections.items():
        resp = client.post("/api/returns/deposit", json={"card_id": card_id})
        assert resp.status_code == 200
        body = resp.json()
        assert body["decision"]["status"] == "REJECTED"
        assert body["decision"]["reason_code"] == expected_reason
        assert body["session"]["total_grosze"] == 0
        assert body["session"]["returned_registry_size"] == 0


def test_custom_candidate_and_reset_clears_registry_and_session(tmp_path: Path) -> None:
    """Obsługuje wrzut custom_candidate oraz reset DEMO przywracający możliwość ponownego wrzutu."""
    client = _make_client(tmp_path / "state.json")

    card_resp = client.post("/api/returns/deposit", json={"card_id": "pet-water-1500-a"})
    custom_resp = client.post(
        "/api/returns/deposit",
        json={
            "custom_candidate": {
                "package_code": "PL-KAUCJA-5900000000992-CAN-009901",
                "category": "CAN",
                "volume_ml": 330,
                "title": "Własna puszka testowa 330 ml",
            }
        },
    )
    assert card_resp.status_code == 200
    assert custom_resp.status_code == 200
    assert custom_resp.json()["decision"]["status"] == "ACCEPTED"
    assert custom_resp.json()["session"]["total_grosze"] == 100
    assert custom_resp.json()["session"]["returned_registry_size"] == 2

    reset_resp = client.post("/api/returns/reset")
    assert reset_resp.status_code == 200
    reset_data = reset_resp.json()
    assert reset_data["mode"] == "DEMO"
    assert reset_data["session"]["total_grosze"] == 0
    assert reset_data["session"]["total_formatted"] == "0,00 zł"
    assert reset_data["session"]["returned_registry_size"] == 0
    assert reset_data["session"]["can_issue_voucher"] is False
    assert reset_data["session"]["attempts"] == []

    # Po resecie ta sama karta ponownie przechodzi walidację.
    after_reset = client.post("/api/returns/deposit", json={"card_id": "pet-water-1500-a"})
    assert after_reset.status_code == 200
    assert after_reset.json()["decision"]["status"] == "ACCEPTED"


@pytest.mark.parametrize(
    ("payload", "expected_status", "expected_code"),
    [
        ({"card_id": "nieznana-karta"}, 404, "PACKAGE_CARD_NOT_FOUND"),
        ({}, 400, "INVALID_DEPOSIT_REQUEST"),
        ({"card_id": "   "}, 400, "INVALID_DEPOSIT_REQUEST"),
        (
            {
                "card_id": "pet-water-1500-a",
                "custom_candidate": {
                    "package_code": "PL-KAUCJA-5900000000992-CAN-009901",
                    "category": "CAN",
                    "volume_ml": 330,
                },
            },
            400,
            "INVALID_DEPOSIT_REQUEST",
        ),
        (
            {
                "custom_candidate": {
                    "package_code": "PL-KAUCJA-5900000000992-CAN-009901",
                    "category": "CAN",
                    "volume_ml": "nie-liczba",
                }
            },
            422,
            "VALIDATION_ERROR",
        ),
        ({"card_id": "x" * 65}, 422, "VALIDATION_ERROR"),
        (
            {
                "custom_candidate": {
                    "package_code": "PL-KAUCJA-5900000000992-CAN-009901",
                    "category": "CAN",
                    "volume_ml": 2_000_000,
                }
            },
            422,
            "VALIDATION_ERROR",
        ),
    ],
)
def test_deposit_technical_errors_return_error_response_contract(
    tmp_path: Path,
    payload: dict[str, object],
    expected_status: int,
    expected_code: str,
) -> None:
    """Błędy techniczne żądania zwracają spójny kontrakt ErrorResponse z kodem HTTP."""
    client = _make_client(tmp_path / "state.json")

    response = client.post("/api/returns/deposit", json=payload)

    assert response.status_code == expected_status
    body = response.json()
    assert body["mode"] == "DEMO"
    assert body["error_code"] == expected_code
    assert body["message"]


def test_corrupted_state_file_returns_safe_500_error(tmp_path: Path) -> None:
    """Uszkodzony plik JSON skutkuje błędem 500 bez wycieku ścieżki systemowej."""
    state_file = tmp_path / "corrupted_state.json"
    state_file.write_text("{uszkodzony json", encoding="utf-8")
    client = _make_client(state_file)

    response = client.get("/api/returns/session")

    assert response.status_code == 500
    body = response.json()
    assert body["mode"] == "DEMO"
    assert body["error_code"] == "RETURN_STATE_STORAGE_ERROR"
    assert str(tmp_path) not in body["message"]
    assert body["detail"] is None


def test_corrupted_attempt_types_and_env_state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Waliduje błędne typy rekordów JSON (np. bool jako attempt_no) i zmienną środowiskową."""
    env_state = tmp_path / "env_state.json"
    bad_payload = {
        "schema_version": 1,
        "returned_instance_ids": [],
        "session": {
            "session_id": "DEMO-12345678",
            "status": "OPEN",
            "accepted_count": 0,
            "redirected_glass_count": 0,
            "rejected_count": 0,
            "total_grosze": 0,
            "attempts": [{"attempt_no": True}],
        },
    }
    env_state.write_text(json.dumps(bad_payload), encoding="utf-8")
    monkeypatch.setenv("KAUCJOMAT_STATE_FILE", str(env_state))

    client = TestClient(create_app())
    resp = client.get("/api/returns/session")
    assert resp.status_code == 500
    assert resp.json()["error_code"] == "RETURN_STATE_STORAGE_ERROR"


def test_concurrent_store_deposits_preserve_unique_attempt_numbers(tmp_path: Path) -> None:
    """Wielowątkowe wrzuty do ReturnStateStore zachowują spójność JSON i numerację prób."""
    store = ReturnStateStore(tmp_path / "concurrent.json")
    candidates = [
        get_test_card_by_id("pet-water-1500-a").candidate,
        get_test_card_by_id("pet-water-1500-b").candidate,
        get_test_card_by_id("can-cola-500").candidate,
        get_test_card_by_id("glass-beer-500").candidate,
        get_test_card_by_id("reject-no-logo").candidate,
        get_test_card_by_id("pet-water-1500-a").candidate,
    ]

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(store.process_deposit, candidates))

    assert len(results) == 6
    snapshot = store.get_session_snapshot()
    attempt_numbers = [item.attempt_no for item in snapshot.attempts]
    assert attempt_numbers == [6, 5, 4, 3, 2, 1]
    assert snapshot.total_grosze == 150
    assert snapshot.returned_registry_size == 3
