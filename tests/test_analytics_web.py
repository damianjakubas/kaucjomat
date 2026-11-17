"""Testy dostarczenia i semantyki HTML oraz zasobów widoku Analityka (bez symulowania JS)."""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser

from fastapi.testclient import TestClient

from kaucjomat.app import create_app
from kaucjomat.config import get_project_root

_STATIC_DIR = get_project_root() / "src" / "kaucjomat" / "static"
_NEW_JS = ("analytics_contract.js", "analytics_view.js", "analytics.js")


class _ShellParser(HTMLParser):
    """Zbiera atrybuty znaczników z index.html, żeby sprawdzać id, etykiety i skrypty."""

    def __init__(self) -> None:
        """Przygotowuje puste kolekcje znaczników."""
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Zapamiętuje znacznik wraz ze słownikiem jego atrybutów."""
        self.tags.append((tag, dict(attrs)))


def _parse(client: TestClient) -> _ShellParser:
    """Pobiera stronę główną i parsuje ją do listy znaczników."""
    parser = _ShellParser()
    parser.feed(client.get("/").text)
    return parser


def _by_id(parser: _ShellParser, element_id: str) -> dict[str, str | None]:
    """Zwraca atrybuty elementu o danym id albo zgłasza czytelny błąd asercji."""
    for _, attrs in parser.tags:
        if attrs.get("id") == element_id:
            return attrs
    raise AssertionError(f"Brak elementu #{element_id} w index.html")


def test_html_ids_are_unique_and_analytics_view_is_semantic() -> None:
    """Id są unikalne, a widok ma etykiety, regiony live i ukryty komunikat 1-rdzeniowy."""
    parser = _parse(TestClient(create_app()))
    ids = [attrs["id"] for _, attrs in parser.tags if attrs.get("id")]
    assert [name for name, number in Counter(ids).items() if number > 1] == []

    panel = _by_id(parser, "view-analityka")
    assert panel["data-view-panel"] == "analityka"
    assert any(attrs.get("data-view-badge") == "analityka" for _, attrs in parser.tags)

    label_targets = {attrs.get("for") for tag, attrs in parser.tags if tag == "label"}
    assert "analytics-preset" in label_targets
    assert "hidden" in _by_id(parser, "analytics-single-core")
    assert _by_id(parser, "analytics-single-core")["role"] == "status"
    assert _by_id(parser, "analytics-status")["aria-live"] == "polite"
    assert _by_id(parser, "analytics-chart")["alt"]
    kinds = {attrs.get("data-analytics-kind") for _, attrs in parser.tags if attrs.get("data-analytics-kind")}
    assert kinds == {"generate", "analysis", "benchmark"}


def test_analytics_view_is_marked_demo_with_stage_cards() -> None:
    """Widok niesie napis DEMO, karty obu etapów analizy i kontenery wyniku benchmarku."""
    html = TestClient(create_app()).get("/").text
    for fragment in (
        'data-view-badge="analityka">DEMO<', "Etap 1 — odczyt plików (wątki)",
        "Etap 2 — obliczenia (procesy spawn)", 'id="analytics-table-body"',
        'id="analytics-conclusions"', "Pokaż wyniki referencyjne", "Uruchom benchmark GIL",
    ):
        assert fragment in html, f"Brak fragmentu widoku Analityka: {fragment}"


def test_scripts_loaded_in_order_with_defer_after_checkout() -> None:
    """Kontrakt, widok i kontroler Analityki ładują się z defer, w tej kolejności, po skryptach Kasy."""
    parser = _parse(TestClient(create_app()))
    scripts = [attrs for tag, attrs in parser.tags if tag == "script"]
    sources = [attrs["src"] for attrs in scripts]
    expected = [f"/static/{name}" for name in _NEW_JS]
    positions = [sources.index(src) for src in expected]
    assert positions == sorted(positions)
    assert positions[0] > sources.index("/static/checkout.js")
    assert all("defer" in attrs for attrs in scripts)
    assert "/static/analytics.css" in [a.get("href") for t, a in parser.tags if t == "link"]


def test_new_static_files_served_with_expected_types() -> None:
    """Nowe zasoby statyczne są serwowane z poprawnym typem i bez zewnętrznych adresów."""
    client = TestClient(create_app())
    css = client.get("/static/analytics.css")
    assert css.status_code == 200 and "text/css" in css.headers["content-type"]
    assert "http://" not in css.text and "https://" not in css.text
    for name, symbol in zip(_NEW_JS, ("KaucjomatAnalyticsContract", "KaucjomatAnalyticsView", "kaucjomatSetError")):
        response = client.get(f"/static/{name}")
        assert response.status_code == 200 and "javascript" in response.headers["content-type"]
        assert symbol in response.text and "/**" in response.text
        assert "http://" not in response.text and "https://" not in response.text


def test_new_js_never_uses_inner_html_and_app_registers_error_sources() -> None:
    """Nowe pliki JS nie używają innerHTML, a app.js zna trzy źródła błędów analityki."""
    for name in _NEW_JS:
        source = (_STATIC_DIR / name).read_text(encoding="utf-8")
        for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            assert forbidden not in source, f"{forbidden} w {name}"
    app_js = (_STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for source_name in ("analyticsContext", "analyticsReference", "analyticsJob"):
        assert f"{source_name}:" in app_js
    controller = (_STATIC_DIR / "analytics.js").read_text(encoding="utf-8")
    assert "KaucjomatDemo.begin" not in controller, "Zadanie analityczne nie blokuje butelkomatu i kasy."
    assert "/api/analytics/jobs/current" in controller
