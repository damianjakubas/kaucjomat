"""Strażnicy zasobów warstwy Tactile: ilustracje SVG, podlinkowane arkusze i bezpieczeństwo kodu klienta."""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kaucjomat.app import create_app

STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "kaucjomat" / "static"
ASSETS_DIR = STATIC_DIR / "assets"
SVG_NAMES = [
    "pet-1500.svg", "pet-500-no-logo.svg", "can-500.svg", "can-crushed.svg",
    "glass-500.svg", "carton-milk.svg", "pet-jug-5000.svg",
]
TACTILE_CSS = ["tactile_shell.css", "tactile_machine.css", "tactile_voucher.css", "tactile_shelf.css"]
TACTILE_JS = ["return_machine_art.js", "return_machine_fx.js"]
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class AncestryParser(HTMLParser):
    """Zapamiętuje dla każdego id listę przodków (tag, id, klasy), żeby sprawdzać zagnieżdżenie elementów."""

    def __init__(self) -> None:
        """Przygotowuje pusty stos otwartych elementów i indeks przodków po id."""
        super().__init__()
        self.stack: list[tuple[str, str, set[str]]] = []
        self.ancestors: dict[str, list[tuple[str, str, set[str]]]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Rejestruje element z przodkami i odkłada go na stos, pomijając elementy bez zamknięcia."""
        values = dict(attrs)
        element_id = values.get("id") or ""
        classes = set((values.get("class") or "").split())
        if element_id:
            self.ancestors[element_id] = list(self.stack)
        if tag not in VOID_TAGS:
            self.stack.append((tag, element_id, classes))

    def handle_endtag(self, tag: str) -> None:
        """Zdejmuje ze stosu najbliższy otwarty element o tej samej nazwie."""
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return
FORBIDDEN_DOM_WRITES = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write")
EXTERNAL_SCHEMES = ("http://", "https://", "ws://", "wss://", "ftp://")


def _read(path: Path) -> str:
    """Wczytuje plik tekstowy zasobu w UTF-8."""
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", SVG_NAMES)
def test_svg_asset_is_self_contained(name: str) -> None:
    """Każdy SVG istnieje, ma viewBox, polski tytuł i nie odwołuje się do zewnętrznych zasobów."""
    path = ASSETS_DIR / name
    assert path.is_file(), f"Brak ilustracji {name}."
    content = _read(path)
    assert 'xmlns="http://www.w3.org/2000/svg"' in content
    assert "viewBox=" in content
    assert 'role="img"' in content
    assert re.search(r"<title>[^<]+</title>", content)
    lowered = content.lower()
    assert "<script" not in lowered
    assert "<style" not in lowered
    assert "@font-face" not in lowered
    assert 'href="http' not in lowered and "xlink:href=\"http" not in lowered
    for href in re.findall(r'href="([^"]*)"', content):
        assert href.startswith("#"), f"Niedozwolone odwołanie {href} w {name}."


@pytest.mark.parametrize("name", SVG_NAMES)
def test_svg_asset_is_served_with_svg_mime(name: str) -> None:
    """Ilustracje są serwowane lokalnie z typem MIME image/svg+xml."""
    with TestClient(create_app()) as client:
        response = client.get(f"/static/assets/{name}")
    assert response.status_code == 200
    assert response.headers["content-type"].split(";")[0] == "image/svg+xml"


@pytest.mark.parametrize("name", TACTILE_CSS + TACTILE_JS)
def test_tactile_sources_are_offline_and_safe(name: str) -> None:
    """Nowe CSS i JS nie mają zewnętrznych adresów ani niebezpiecznych zapisów do DOM."""
    content = _read(STATIC_DIR / name)
    lowered = content.lower()
    for scheme in EXTERNAL_SCHEMES:
        assert scheme not in lowered, f"Zewnętrzny adres {scheme} w {name}."
    for ref in ('src="//', 'href="//', "url(//", 'url("//', "url('//"):
        assert ref not in lowered
    for call in FORBIDDEN_DOM_WRITES:
        assert call not in content, f"Zakazany zapis {call} w {name}."
    if name.endswith(".js"):
        assert "/**" in content


def test_index_links_tactile_styles_in_cascade_order() -> None:
    """Arkusze tactile ładują się po starych stylach, a wydruk na samym końcu."""
    with TestClient(create_app()) as client:
        html = client.get("/").text
    hrefs = re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
    expected = [
        "styles", "return_machine", "checkout", "analytics",
        "tactile_shell", "tactile_machine", "tactile_voucher", "tactile_shelf", "voucher_print",
    ]
    assert hrefs == [f"/static/{name}.css" for name in expected]


def _index_ancestors() -> dict[str, list[tuple[str, str, set[str]]]]:
    """Pobiera `/` i zwraca mapę id elementu na listę jego przodków."""
    with TestClient(create_app()) as client:
        html = client.get("/").text
    parser = AncestryParser()
    parser.feed(html)
    return parser.ancestors


def test_lcd_is_sibling_of_inlet_and_voucher_sits_in_printer_slot() -> None:
    """LCD leży obok wlotu (nie w nim), a bon DEMO w szczelinie wydruku; oba w froncie lub kolumnie maszyny."""
    ancestors = _index_ancestors()
    lcd_parents = {element_id for _, element_id, _ in ancestors["scanner-result-box"]}
    assert "deposit-dropzone" not in lcd_parents
    assert any("machine-front" in classes for _, _, classes in ancestors["scanner-result-box"])
    assert any("machine-front" in classes for _, _, classes in ancestors["deposit-dropzone"])
    assert any("printer-slot" in classes for _, _, classes in ancestors["issued-voucher-card"])
    for element_id in ("scanner-package-value", "scanner-ean-value", "scanner-instance-value", "scanner-timing-value"):
        assert "scanner-result-box" in {parent_id for _, parent_id, _ in ancestors[element_id]}


def test_print_rules_hide_machine_front_and_flatten_voucher() -> None:
    """Blok `@media print` ukrywa front automatu i wyłącza ruch oraz dekoracje bonu."""
    css = _read(STATIC_DIR / "voucher_print.css")
    printed = css[css.index("@media print"):]
    for selector in (".machine-front", ".printer-slot-bar", ".session-history-box", ".return-column-right"):
        assert selector in printed, f"Brak ukrycia {selector} w druku."
    assert "animation: none" in printed and "transform: none" in printed
    assert "#issued-voucher-card::before" in printed


def test_screen_voucher_and_print_button_styles_live_in_tactile_sheets() -> None:
    """Ekranowy wygląd bonu i przycisku druku jest w arkuszu tactile, a nie nadpisywany przez ostatni arkusz."""
    voucher = _read(STATIC_DIR / "tactile_voucher.css")
    printed = _read(STATIC_DIR / "voucher_print.css")
    assert ".issued-voucher-card {" in voucher and ".btn-print-voucher {" in voucher
    assert ".issued-voucher-card {" not in printed and ".btn-print-voucher {" not in printed
