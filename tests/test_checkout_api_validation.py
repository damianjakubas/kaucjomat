"""Kontrakty błędów HTTP kasy, ścisłe wejście i brak fałszywego sukcesu zapisu."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest


@pytest.mark.parametrize("endpoint", ["quote", "redeem"])
@pytest.mark.parametrize("changes", [
    {"demo_generation_id": None}, {"demo_generation_id": "nie-uuid"},
    {"demo_generation_id": 123}, {"demo_generation_id": True},
    {"items": None}, {"items": {}}, {"items": "koszyk"}, {"items": [None]},
    {"items": [{"product_id": "bread-roll"}]}, {"items": [{"quantity": 1}]},
    {"items": [{"product_id": "", "quantity": 1}]},
    {"items": [{"product_id": "X" * 65, "quantity": 1}]},
    {"items": [{"product_id": 123, "quantity": 1}]},
    {"items": [{"product_id": "bread-roll", "quantity": 2, "unit_price_grosze": 1}]},
    {"items": [{"product_id": "bread-roll", "quantity": 2, "line_total_grosze": 1}]},
    {"basket_total_grosze": 1}, {"amount_due_grosze": 0},
    {"items": [{"product_id": "bread-roll", "quantity": 1}] * 21},
] + [{"items": [{"product_id": "bread-roll", "quantity": q}]}
     for q in (None, True, False, 1.0, 1.5, "2", 0, -1, 100)])
def test_structural_errors_are_422_without_writing(
    checkout_client: TestClient, checkout_request: dict[str, Any], checkout_file: Path,
    endpoint: str, changes: dict[str, Any],
) -> None:
    """Niepoprawny kształt, typy, limity i podrobione kwoty dają jednolity błąd walidacji."""
    payload = deepcopy(checkout_request) if endpoint == "redeem" else {
        k: checkout_request[k] for k in ("demo_generation_id", "items")
    }
    payload.update(changes)
    before = checkout_file.read_bytes()
    response = checkout_client.post(f"/api/checkout/{endpoint}", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"mode", "error_code", "message", "detail"}
    assert body["mode"] == "DEMO" and body["error_code"] == "VALIDATION_ERROR"
    assert body["message"] == "Nieprawidłowe parametry żądania." and body["detail"]
    assert checkout_file.read_bytes() == before


@pytest.mark.parametrize(("field", "value"), [
    ("operation_id", "błędny"), ("operation_id", 123), ("operation_id", True),
    ("operation_id", None), ("voucher_code", None), ("voucher_code", 123),
    ("voucher_code", True), ("voucher_code", "X" * 65),
    ("redemption_mode", "PURCHASES"), ("redemption_mode", None), ("redemption_mode", True),
])
def test_redemption_fields_are_required_and_typed(
    checkout_client: TestClient, checkout_request: dict[str, Any], checkout_file: Path,
    field: str, value: Any,
) -> None:
    """UUID, tekstowy kod i tryb nie przyjmują wartości o niezgodnym typie lub formacie."""
    before = checkout_file.read_bytes()
    checkout_request[field] = value
    response = checkout_client.post("/api/checkout/redeem", json=checkout_request)
    assert response.status_code == 422 and response.json()["error_code"] == "VALIDATION_ERROR"
    assert checkout_file.read_bytes() == before


@pytest.mark.parametrize("field", ["operation_id", "demo_generation_id", "voucher_code", "redemption_mode", "items"])
def test_missing_required_field_returns_422(
    checkout_client: TestClient, checkout_request: dict[str, Any], checkout_file: Path, field: str,
) -> None:
    """Brak któregokolwiek pola realizacji nie uruchamia operacji magazynu."""
    before = checkout_file.read_bytes()
    del checkout_request[field]
    response = checkout_client.post("/api/checkout/redeem", json=checkout_request)
    assert response.status_code == 422 and response.json()["error_code"] == "VALIDATION_ERROR"
    assert checkout_file.read_bytes() == before


@pytest.mark.parametrize("changes", [
    {"items": [{"product_id": "nieznany", "quantity": 1}]},
    {"items": [{"product_id": "bread-roll", "quantity": 1}] * 2},
])
def test_quote_rejects_unknown_or_duplicate_products(
    checkout_client: TestClient, checkout_request: dict[str, Any], checkout_file: Path,
    changes: dict[str, Any],
) -> None:
    """Wycena stosuje reguły katalogu i unikalności, nie zmieniając stanu bonów."""
    before = checkout_file.read_bytes()
    response = checkout_client.post("/api/checkout/quote", json={
        "demo_generation_id": checkout_request["demo_generation_id"], **changes,
    })
    assert response.status_code == 400 and response.json()["error_code"] == "INVALID_CHECKOUT_REQUEST"
    assert checkout_file.read_bytes() == before


@pytest.mark.parametrize("field", ["demo_generation_id", "items"])
def test_quote_requires_generation_and_items(checkout_client: TestClient, field: str) -> None:
    """Brak generacji lub listy koszyka nie jest zastępowany domyślnymi danymi."""
    payload = {"demo_generation_id": str(uuid4()), "items": []}
    del payload[field]
    response = checkout_client.post("/api/checkout/quote", json=payload)
    assert response.status_code == 422 and response.json()["error_code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("endpoint", ["quote", "redeem"])
@pytest.mark.parametrize("content", ["", "null", "[]", "{", '"tekst"'])
def test_missing_or_malformed_json_returns_standard_error(
    checkout_client: TestClient, endpoint: str, content: str, checkout_file: Path,
) -> None:
    """Niepoprawne JSON i brak obiektu są obsługiwane przez istniejący handler walidacji."""
    response = checkout_client.post(f"/api/checkout/{endpoint}", content=content,
                                    headers={"Content-Type": "application/json"})
    assert response.status_code == 422 and response.json()["error_code"] == "VALIDATION_ERROR"
    assert response.json()["mode"] == "DEMO" and not checkout_file.exists()


@pytest.mark.parametrize(("changes", "status", "code"), [
    ({"voucher_code": ""}, 400, "INVALID_CHECKOUT_REQUEST"),
    ({"voucher_code": " \t "}, 400, "INVALID_CHECKOUT_REQUEST"),
    ({"voucher_code": "NIEZNANY"}, 404, "VOUCHER_NOT_FOUND"),
    ({"voucher_code": "BON-DEMO-EXP-0001"}, 409, "VOUCHER_EXPIRED"),
    ({"items": []}, 409, "BASKET_TOO_SMALL"),
    ({"items": [{"product_id": "bread-roll", "quantity": 1}]}, 409, "BASKET_TOO_SMALL"),
    ({"items": [{"product_id": "nieznany", "quantity": 1}]}, 400, "INVALID_CHECKOUT_REQUEST"),
    ({"items": [{"product_id": " bread-roll ", "quantity": 2}]}, 400, "INVALID_CHECKOUT_REQUEST"),
    ({"items": [{"product_id": "bread-roll", "quantity": 1}] * 2}, 400, "INVALID_CHECKOUT_REQUEST"),
    ({"redemption_mode": "cash"}, 400, "INVALID_CHECKOUT_REQUEST"),
])
def test_business_errors_leave_voucher_and_file_unchanged(
    checkout_client: TestClient, checkout_request: dict[str, Any], checkout_file: Path,
    changes: dict[str, Any], status: int, code: str,
) -> None:
    """Każda odmowa biznesowa ma polski komunikat DEMO i pozostawia poprzednie bajty pliku."""
    checkout_request.update(changes)
    before = checkout_file.read_bytes()
    response = checkout_client.post("/api/checkout/redeem", json=checkout_request)
    assert response.status_code == status
    assert response.json() == {"mode": "DEMO", "error_code": code,
                               "message": response.json()["message"], "detail": None}
    assert "DEMO" in response.json()["message"]
    assert checkout_file.read_bytes() == before


@pytest.mark.parametrize("field", ["voucher_code", "redemption_mode", "items", "operation_id"])
def test_changed_payload_and_new_operation_on_used_voucher_are_conflicts(
    checkout_client: TestClient, checkout_request: dict[str, Any], checkout_file: Path, field: str,
) -> None:
    """Zmiana treści starego ID i nowe użycie zużytego bonu mają różne kody konfliktu."""
    assert checkout_client.post("/api/checkout/redeem", json=checkout_request).status_code == 200
    before = checkout_file.read_bytes()
    if field == "redemption_mode":
        checkout_request.update(redemption_mode="cash", items=[])
    else:
        checkout_request[field] = {"voucher_code": "NIEZNANY", "operation_id": str(uuid4()),
                                   "items": [{"product_id": "nieznany", "quantity": 1}]}[field]
    response = checkout_client.post("/api/checkout/redeem", json=checkout_request)
    assert response.status_code == 409
    assert response.json()["error_code"] == (
        "VOUCHER_ALREADY_REDEEMED" if field == "operation_id" else "CHECKOUT_OPERATION_CONFLICT"
    )
    assert checkout_file.read_bytes() == before


@pytest.mark.parametrize("endpoint", ["quote", "redeem"])
def test_reset_invalidates_quotes_and_previous_replays(
    checkout_client: TestClient, checkout_request: dict[str, Any], checkout_file: Path, endpoint: str,
) -> None:
    """Reset usuwa wyniki oraz odrzuca żądania poprzedniej generacji przed replayem."""
    assert checkout_client.post("/api/checkout/redeem", json=checkout_request).status_code == 200
    reset = checkout_client.post("/api/returns/reset")
    assert reset.status_code == 200 and "wyniki realizacji" in reset.json()["message"]
    before = checkout_file.read_bytes()
    payload = checkout_request if endpoint == "redeem" else {
        k: checkout_request[k] for k in ("demo_generation_id", "items")
    }
    response = checkout_client.post(f"/api/checkout/{endpoint}", json=payload)
    assert response.status_code == 409 and response.json()["error_code"] == "DEMO_GENERATION_CONFLICT"
    assert checkout_file.read_bytes() == before
    context = checkout_client.get("/api/checkout/context").json()
    assert context["demo_generation_id"] != checkout_request["demo_generation_id"]
    assert [v["voucher_code"] for v in context["vouchers"]] == ["BON-DEMO-EXP-0001"]
    assert json.loads(before)["checkout_redemptions"] == []


@pytest.mark.parametrize("endpoint", ["context", "quote", "redeem"])
def test_corrupt_storage_is_500_and_never_reinitialized(
    checkout_client: TestClient, checkout_request: dict[str, Any], checkout_file: Path, endpoint: str,
) -> None:
    """Uszkodzony v2 daje błąd magazynu w każdym endpointcie bez nadpisania źródła."""
    state = json.loads(checkout_file.read_bytes())
    del state["checkout_redemptions"]
    checkout_file.write_text(json.dumps(state), encoding="utf-8")
    before = checkout_file.read_bytes()
    payload = checkout_request if endpoint == "redeem" else {
        k: checkout_request[k] for k in ("demo_generation_id", "items")
    }
    response = (checkout_client.get("/api/checkout/context") if endpoint == "context"
                else checkout_client.post(f"/api/checkout/{endpoint}", json=payload))
    assert response.status_code == 500 and response.json()["error_code"] == "RETURN_STATE_STORAGE_ERROR"
    assert response.json()["mode"] == "DEMO" and response.json()["detail"] is None
    assert checkout_file.read_bytes() == before


def test_failed_replace_returns_500_with_active_voucher_and_allows_retry(
    checkout_client: TestClient, checkout_request: dict[str, Any], checkout_file: Path,
    monkeypatch: pytest.MonkeyPatch, checkout_logs: pytest.LogCaptureFixture,
) -> None:
    """Awaria zapisu nie staje się sukcesem HTTP ani logu i nie pozostawia zużytego bonu."""
    before = checkout_file.read_bytes()
    checkout_logs.clear()

    def fail_replace(source: Path, target: Path) -> Path:
        """Symuluje błąd dysku przed opublikowaniem przygotowanej realizacji."""
        raise OSError("Kontrolowana awaria replace")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", fail_replace)
        response = checkout_client.post("/api/checkout/redeem", json=checkout_request)
    assert response.status_code == 500 and response.json()["error_code"] == "RETURN_STATE_STORAGE_ERROR"
    assert "Nie udało się zapisać" in checkout_logs.text
    assert "Zapisano realizację" not in checkout_logs.text
    assert "Odtworzono wynik realizacji" not in checkout_logs.text
    assert checkout_file.read_bytes() == before and not list(checkout_file.parent.glob("*.tmp"))
    assert json.loads(before)["checkout_redemptions"] == []
    for endpoint in ("/api/checkout/context", "/api/returns/vouchers"):
        assert checkout_client.get(endpoint).json()["vouchers"][0]["status"] == "AKTYWNY"
    retry = checkout_client.post("/api/checkout/redeem", json=checkout_request)
    assert retry.status_code == 200 and retry.json()["was_idempotent_replay"] is False
    assert len(json.loads(checkout_file.read_bytes())["checkout_redemptions"]) == 1
