"""Pakiet główny symulatora polskiego systemu kaucyjnego KaucjaSim DEMO."""

from __future__ import annotations

from kaucjomat.cli import main
from kaucjomat.config import APP_VERSION

__version__: str = APP_VERSION
__all__: list[str] = ["__version__", "main"]
