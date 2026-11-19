"""Strażnicy zasobów warstwy Tactile: ilustracje SVG, podlinkowane arkusze i bezpieczeństwo kodu klienta."""

import re
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
TACTILE_CSS = ["tactile_shell.css", "tactile_shelf.css"]
TACTILE_JS = ["return_machine_art.js"]
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
    expected = ["styles", "return_machine", "checkout", "analytics", "tactile_shell", "tactile_shelf", "voucher_print"]
    assert hrefs == [f"/static/{name}.css" for name in expected]
