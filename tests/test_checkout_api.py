"""Przepływ HTTP kasy DEMO, historyczne ponowienia i zgodność z butelkomatem."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from kaucjomat import checkout_catalog, checkout_redemption
from kaucjomat.app import create_app


def test_context_initializes_stable_generation_and_expired_seed(
    checkout_client: TestClient, checkout_file: Path,
) -> None:
    """Kontekst inicjalizuje generację i udostępnia ceny oraz dotychczasowy format bonów."""
    response = checkout_client.get("/api/checkout/context")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "DEMO"
    assert str(UUID(body["demo_generation_id"])) == body["demo_generation_id"]
    assert [(p["product_id"], p["name"], p["unit_price_grosze"], p["unit_price_formatted"])
            for p in body["products"]] == [
        ("bread-roll", "Bułka", 50, "0,50 zł"), ("apple", "Jabłko", 150, "1,50 zł"),
        ("yogurt", "Jogurt", 250, "2,50 zł"), ("bread", "Chleb", 400, "4,00 zł"),
    ]
    assert body["vouchers"] == checkout_client.get("/api/returns/vouchers").json()["vouchers"]
    assert body["vouchers"][0]["status"] == "WYGASŁY"
    assert "DEMO" in body["vouchers"][0]["demo_watermark"]
    before = checkout_file.read_bytes()
    with TestClient(create_app(state_file=checkout_file)) as restarted:
        assert restarted.get("/api/checkout/context").json() == body
    assert checkout_file.read_bytes() == before


@pytest.mark.parametrize(("quantity", "total", "due"), [(2, 100, 0), (3, 150, 50)])
def test_full_purchase_flow_preserves_return_state(
    checkout_client: TestClient, checkout_file: Path, quantity: int, total: int, due: int,
) -> None:
    """Wystawienie, wycena i realizacja HTTP dają poprawne sumy oraz spójne statusy bonu."""
    for card_id in ("pet-water-1500-a", "pet-water-1500-b"):
        assert checkout_client.post("/api/returns/deposit", json={"card_id": card_id}).status_code == 200
    issued = checkout_client.post("/api/returns/voucher").json()
    context = checkout_client.get("/api/checkout/context").json()
    assert context["vouchers"][0] == issued["voucher"]
    session = checkout_client.post("/api/returns/deposit", json={"card_id": "glass-beer-500"}).json()["session"]
    payload = {"operation_id": str(uuid4()), "demo_generation_id": context["demo_generation_id"],
               "voucher_code": issued["voucher"]["voucher_code"], "redemption_mode": "purchases",
               "items": [{"product_id": "bread-roll", "quantity": quantity}]}
    before = json.loads(checkout_file.read_bytes())
    quote_response = checkout_client.post("/api/checkout/quote", json={
        "demo_generation_id": payload["demo_generation_id"], "items": payload["items"],
    })
    assert quote_response.status_code == 200
    quote = quote_response.json()
    assert json.loads(checkout_file.read_bytes()) == before
    response = checkout_client.post("/api/checkout/redeem", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "DEMO" and "DEMO" in body["message"]
    assert body["was_idempotent_replay"] is False
    result = body["settlement"]
    assert result["mode"] == "DEMO" and result["voucher_status"] == "ZUŻYTY"
    assert result["operation_id"] == payload["operation_id"]
    assert result["demo_generation_id"] == context["demo_generation_id"]
    assert result["voucher_code"] == payload["voucher_code"]
    assert result["redemption_mode"] == "purchases"
    assert datetime.fromisoformat(result["redeemed_at_iso"]).utcoffset() == timedelta(0)
    assert result["items"] == quote["items"] == [{
        "product_id": "bread-roll", "name": "Bułka", "unit_price_grosze": 50,
        "unit_price_formatted": "0,50 zł", "quantity": quantity, "line_total_grosze": total,
        "line_total_formatted": "1,00 zł" if quantity == 2 else "1,50 zł",
    }]
    assert result["basket_total_grosze"] == total
    assert result["basket_total_formatted"] == quote["basket_total_formatted"]
    assert result["voucher_amount_grosze"] == 100 and result["voucher_amount_formatted"] == "1,00 zł"
    assert result["amount_due_grosze"] == due
    assert result["amount_due_formatted"] == ("0,00 zł" if due == 0 else "0,50 zł")
    assert result["cash_payout_grosze"] == 0 and result["cash_payout_formatted"] == "0,00 zł"
    vouchers = checkout_client.get("/api/returns/vouchers").json()["vouchers"]
    assert vouchers == checkout_client.get("/api/checkout/context").json()["vouchers"]
    assert vouchers[0]["status"] == "ZUŻYTY" and vouchers[0]["redeemed_at_iso"] == result["redeemed_at_iso"]
    assert checkout_client.get("/api/returns/session").json() == session
    saved = json.loads(checkout_file.read_bytes())
    assert saved["returned_instance_ids"] == before["returned_instance_ids"]
    assert saved["session"] == before["session"] and len(saved["checkout_redemptions"]) == 1
    duplicate = checkout_client.post("/api/returns/deposit", json={"card_id": "pet-water-1500-a"})
    assert duplicate.json()["decision"]["reason_code"] == "DUPLICATE_INSTANCE_ID"


def test_cash_pays_full_voucher_independently_of_quote(
    checkout_client: TestClient, checkout_request: dict[str, Any], checkout_file: Path,
) -> None:
    """Wypłata nie używa wcześniejszej wyceny koszyka, a wynik jawnie opisuje pełną gotówkę."""
    quote = checkout_client.post("/api/checkout/quote", json={
        "demo_generation_id": checkout_request["demo_generation_id"],
        "items": [{"product_id": "bread", "quantity": 2}],
    }).json()
    checkout_request.update(redemption_mode="cash", items=[])
    response = checkout_client.post("/api/checkout/redeem", json=checkout_request)
    assert response.status_code == 200
    body = response.json()
    result = body["settlement"]
    assert quote["basket_total_grosze"] == 800 and "nierozliczone" in body["message"]
    assert result["items"] == [] and result["redemption_mode"] == "cash"
    assert result["basket_total_grosze"] == result["amount_due_grosze"] == 0
    assert result["basket_total_formatted"] == result["amount_due_formatted"] == "0,00 zł"
    assert result["cash_payout_grosze"] == result["voucher_amount_grosze"] == 100
    assert result["cash_payout_formatted"] == result["voucher_amount_formatted"] == "1,00 zł"
    assert len(json.loads(checkout_file.read_bytes())["checkout_redemptions"]) == 1


@pytest.mark.parametrize("mode", ["purchases", "cash"])
@pytest.mark.parametrize("catalog_change", ["prices", "removed"])
def test_replay_after_restart_ignores_current_catalog_and_time(
    checkout_client: TestClient, checkout_request: dict[str, Any], checkout_file: Path,
    monkeypatch: pytest.MonkeyPatch, mode: str, catalog_change: str,
) -> None:
    """Nowa aplikacja odzyskuje identyczny wynik, nawet po zmianie nazw, cen i terminu bonu."""
    checkout_request.update(redemption_mode=mode, items=[] if mode == "cash" else [
        {"product_id": "bread", "quantity": 1}, {"product_id": "apple", "quantity": 1},
    ])
    first = checkout_client.post("/api/checkout/redeem", json=checkout_request)
    assert first.status_code == 200
    before = checkout_file.read_bytes()

    class FutureClock:
        """Przesuwa ewentualną ocenę nowej realizacji daleko poza termin ważności."""

        @staticmethod
        def now(zone: object) -> datetime:
            """Zwraca przyszłą chwilę bez oczekiwania w czasie rzeczywistym."""
            return datetime.now(UTC) + timedelta(days=200)

    monkeypatch.setattr(checkout_redemption, "datetime", FutureClock)
    changed = tuple(replace(p, name="Inna nazwa", unit_price_grosze=9999) for p in checkout_catalog.PRODUCTS)
    monkeypatch.setattr(checkout_catalog, "PRODUCTS", () if catalog_change == "removed" else changed)
    checkout_request["operation_id"] = UUID(checkout_request["operation_id"]).hex.upper()
    checkout_request["demo_generation_id"] = UUID(checkout_request["demo_generation_id"]).hex.upper()
    checkout_request["voucher_code"] = f"  {checkout_request['voucher_code'].lower()}  "
    checkout_request["items"].reverse()
    with TestClient(create_app(state_file=checkout_file)) as restarted:
        replay = restarted.post("/api/checkout/redeem", json=checkout_request)
    assert replay.status_code == 200
    assert replay.json()["settlement"] == first.json()["settlement"]
    assert replay.json()["was_idempotent_replay"] is True
    assert "nie wykonano ponownego rozliczenia" in replay.json()["message"]
    assert "DEMO" in replay.json()["message"]
    assert checkout_file.read_bytes() == before


@pytest.mark.parametrize("items", [[], [{"product_id": "bread-roll", "quantity": 99}], [
    {"product_id": "bread", "quantity": 1}, {"product_id": "apple", "quantity": 2},
]])
def test_quote_is_sorted_and_does_not_modify_initialized_state(
    checkout_client: TestClient, checkout_request: dict[str, Any], checkout_file: Path,
    items: list[dict[str, Any]],
) -> None:
    """Pusty i niepusty koszyk wyceniają się z cen serwera bez rezerwacji ani zapisu."""
    before = checkout_file.read_bytes()
    response = checkout_client.post("/api/checkout/quote", json={
        "demo_generation_id": checkout_request["demo_generation_id"], "items": items,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "DEMO" and body["demo_generation_id"] == checkout_request["demo_generation_id"]
    assert [i["product_id"] for i in body["items"]] == sorted(i["product_id"] for i in items)
    assert body["basket_total_grosze"] == sum(i["unit_price_grosze"] * i["quantity"] for i in body["items"])
    if not items:
        assert body["basket_total_grosze"] == 0 and body["basket_total_formatted"] == "0,00 zł"
    assert checkout_file.read_bytes() == before


def test_context_migrates_legacy_used_voucher_without_inventing_result(
    checkout_client: TestClient, checkout_file: Path, legacy_state: dict[str, Any],
) -> None:
    """Kontekst utrwala migrację, zachowując zużyty bon bez daty i bez fikcyjnej realizacji."""
    legacy_state["vouchers"][0].update(status="ZUŻYTY", redeemed_at_iso=None)
    checkout_file.write_text(json.dumps(legacy_state), encoding="utf-8")
    response = checkout_client.get("/api/checkout/context")
    assert response.status_code == 200
    body = response.json()
    assert body["vouchers"][0]["status"] == "ZUŻYTY"
    assert body["vouchers"][0]["redeemed_at_iso"] is None
    assert "legacy_redeemed_without_timestamp" not in body["vouchers"][0]
    state = json.loads(checkout_file.read_bytes())
    assert state["schema_version"] == 2 and state["demo_generation_id"] == body["demo_generation_id"]
    assert state["checkout_redemptions"] == []
    assert state["session"] == legacy_state["session"]
    assert state["returned_instance_ids"] == legacy_state["returned_instance_ids"]
    assert checkout_client.get("/api/checkout/context").json() == body


def test_http_logs_distinguish_first_result_replay_and_refusal(
    checkout_client: TestClient, checkout_request: dict[str, Any], checkout_logs: pytest.LogCaptureFixture,
) -> None:
    """Przejście przez router zachowuje osobne logi zatwierdzenia, odzyskania i odmowy."""
    checkout_logs.clear()
    assert checkout_client.post("/api/checkout/redeem", json=checkout_request).status_code == 200
    assert checkout_client.post("/api/checkout/redeem", json=checkout_request).status_code == 200
    checkout_request.update(operation_id=str(uuid4()), voucher_code="NIEZNANY\nFAŁSZYWY\tWPIS")
    assert checkout_client.post("/api/checkout/redeem", json=checkout_request).status_code == 404
    messages = [r.getMessage() for r in checkout_logs.records]
    assert sum("Zapisano realizację" in m for m in messages) == 1
    assert sum("Odtworzono wynik realizacji" in m for m in messages) == 1
    refusals = [m for m in messages if "Odmowa realizacji" in m]
    assert len(refusals) == 1 and "VOUCHER_NOT_FOUND" in refusals[0]
    assert "\n" not in refusals[0] and "\t" not in refusals[0]
