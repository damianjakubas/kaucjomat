"""Stałe aplikacyjne, definicje trzech widoków DEMO oraz funkcje ścieżek i portu."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from kaucjomat.exceptions import InvalidConfigurationError

APP_NAME: str = "KaucjaSim"
DEMO_LABEL: str = "DEMO"
APP_TITLE: str = f"{APP_NAME} {DEMO_LABEL}"
APP_VERSION: str = "0.1.0"
DEFAULT_HOST: str = "127.0.0.1"
DEFAULT_PORT: int = 8000
DEFAULT_VIEW_ID: str = "butelkomat"


@dataclass(frozen=True, slots=True)
class ViewDefinition:
    """Niemutowalna definicja pojedynczego widoku w powłoce KaucjaSim DEMO."""

    id: str
    title: str
    badge: str
    description: str
    planned_scope: str


VIEWS: tuple[ViewDefinition, ...] = (
    ViewDefinition(
        id="butelkomat",
        title="Butelkomat",
        badge="DEMO • Automat",
        description="Automat przyjmujący opakowania kaucyjne i drukujący bon DEMO.",
        planned_scope=(
            "Walidacja wrzutów PET i puszek oraz wystawianie numerowanego bonu "
            "ważnego 100 dni."
        ),
    ),
    ViewDefinition(
        id="kasa",
        title="Kasa Sklepowa",
        badge="DEMO • Kasa",
        description="Stanowisko kasowe DEMO rozliczające zakupy, bony oraz zwrot szkła.",
        planned_scope=(
            "Kompletowanie koszyka, realizacja aktywnego bonu i przyjmowanie "
            "szkła wielokrotnego użytku."
        ),
    ),
    ViewDefinition(
        id="analityka",
        title="Analityka i Benchmark GIL",
        badge="DEMO • Benchmark",
        description="Panel statystyk wsadowych, raportów i pomiaru narzutu GIL.",
        planned_scope=(
            "Dwuetapowa analiza logów (wątki I/O + procesy CPU) oraz porównanie "
            "czasów wykonania z wykresem PNG."
        ),
    ),
)

VIEWS_BY_ID: dict[str, ViewDefinition] = {view.id: view for view in VIEWS}


def get_package_dir() -> Path:
    """Zwraca katalog pakietu ``kaucjomat`` niezależnie od katalogu roboczego."""
    return Path(__file__).resolve().parent


def get_static_dir() -> Path:
    """Zwraca ścieżkę do katalogu zasobów statycznych powłoki webowej."""
    return get_package_dir() / "static"


def get_project_root() -> Path:
    """Zwraca katalog główny repozytorium wyliczony względem lokalizacji pakietu."""
    return get_package_dir().parent.parent


def get_default_log_dir() -> Path:
    """Zwraca domyślny katalog na opcjonalne pliki logów generowanych lokalnie."""
    return get_project_root() / "data" / "generated" / "logs"


def resolve_port(cli_port: int | None = None) -> int:
    """Wyznacza i waliduje numer portu serwera z argumentu CLI lub zmiennej PORT."""
    if cli_port is not None:
        port = cli_port
    else:
        env_port = os.environ.get("PORT")
        if env_port is None or not env_port.strip():
            return DEFAULT_PORT
        try:
            port = int(env_port.strip())
        except ValueError as exc:
            raise InvalidConfigurationError(
                f"Nieprawidłowa wartość zmiennej środowiskowej PORT: '{env_port}'."
            ) from exc

    # Odrzucamy wartości boolowskie (podtyp int) oraz numery spoza zakresu TCP.
    if isinstance(port, bool) or not 1 <= port <= 65535:
        raise InvalidConfigurationError(
            f"Nieprawidłowy numer portu: {port}. Dozwolony zakres to 1–65535."
        )
    return port
