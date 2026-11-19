"""Testy dostarczenia semantycznej kasy i jej lokalnych zasobów, bez symulowania JS."""

from html.parser import HTMLParser

from fastapi.testclient import TestClient
import pytest

from kaucjomat.app import create_app


class CheckoutMarkup(HTMLParser):
    """Zbiera identyfikatory i atrybuty zasobów z faktycznej odpowiedzi HTML."""

    def __init__(self) -> None:
        """Inicjalizuje indeks elementów oraz kolejność lokalnych skryptów."""
        super().__init__()
        self.elements: dict[str, tuple[str, dict[str, str | None]]] = {}
        self.scripts: list[str] = []
        self.styles: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Indeksuje identyfikatory, zgłaszając powtórzenia i zapisując ścieżki zasobów."""
        values = dict(attrs)
        if element_id := values.get("id"):
            assert element_id not in self.elements, f"Powtórzone id: {element_id}"
            self.elements[element_id] = (tag, values)
        if tag == "script" and (src := values.get("src")):
            self.scripts.append(src)
            assert "defer" in values
        if tag == "link" and values.get("rel") == "stylesheet" and (href := values.get("href")):
            self.styles.append(href)


def test_checkout_semantics_labels_status_and_script_order() -> None:
    """Sprawdza semantykę kontrolek, etykiety, DEMO i kolejność zależności lokalnych."""
    with TestClient(create_app()) as client:
        response = client.get("/")
    assert response.status_code == 200
    markup = CheckoutMarkup()
    markup.feed(response.text)
    for element_id, tag in {
        "checkout-products": "ul", "checkout-basket": "ul", "checkout-vouchers": "ul",
        "checkout-code": "input", "checkout-purchases": "button", "checkout-cash": "button",
        "checkout-retry": "button", "checkout-refresh": "button", "checkout-result": "section",
        "checkout-glass": "div", "checkout-glass-total": "strong",
    }.items():
        assert markup.elements[element_id][0] == tag
    assert 'for="checkout-code"' in response.text
    assert markup.elements["checkout-code"][1]["maxlength"] == "64"
    assert markup.elements["checkout-message"][1]["aria-live"] == "polite"
    assert markup.elements["checkout-message"][1]["tabindex"] == "-1"
    assert markup.elements["checkout-glass"][1]["role"] == "group"
    assert markup.elements["checkout-glass"][1]["aria-label"] == "Zwrot szkła wielokrotnego użytku DEMO"
    assert markup.elements["checkout-glass-total"][1]["aria-live"] == "polite"
    assert "sumę bonu i zwróconego szkła (+1,00 zł/szt.)" in response.text
    assert "szkło powiększa wypłatę DEMO" in response.text
    assert "hidden" in markup.elements["checkout-pending"][1]
    assert "hidden" in markup.elements["checkout-result"][1]
    assert "disabled" in markup.elements["checkout-purchases"][1]
    assert "disabled" in markup.elements["checkout-cash"][1]
    assert "Ostatnie rozliczenie — DEMO (dokument niefiskalny)" in response.text
    assert "Koszyk musi".lower() in response.text.lower()
    assert "KASA SKLEPOWA — TRYB DEMO (Dokumenty niefiskalne)" in response.text
    expected = ["demo_state.js", "app.js", "return_machine_art.js", "return_machine_view.js",
                "return_machine_fx.js", "return_machine_drag.js", "return_machine.js",
                "checkout_contract.js", "checkout_state.js", "checkout_view.js", "checkout.js",
                "analytics_contract.js", "analytics_view.js", "analytics.js"]
    assert markup.scripts == [f"/static/{name}" for name in expected]
    assert "/static/checkout.css" in markup.styles


@pytest.mark.parametrize("name", [
    "demo_state.js", "checkout_contract.js", "checkout_state.js", "checkout_view.js", "checkout.js", "checkout.css",
])
def test_checkout_local_assets_and_mime(name: str) -> None:
    """Potwierdza faktyczne serwowanie zasobów z poprawnym MIME i bez odwołań zewnętrznych."""
    with TestClient(create_app()) as client:
        response = client.get(f"/static/{name}")
    assert response.status_code == 200
    assert ("text/css" if name.endswith(".css") else "javascript") in response.headers["content-type"]
    assert "DEMO" in response.text
    assert not any(scheme in response.text for scheme in ("https://", "http://", "src=\"//", "href=\"//"))
    if name.endswith(".js"):
        assert "/**" in response.text
