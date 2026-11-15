"""Wspólna konfiguracja modułu ``logging`` dla CLI oraz aplikacji FastAPI."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from kaucjomat.exceptions import InvalidConfigurationError

ROOT_LOGGER_NAME: str = "kaucjomat"
LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

_VALID_LOG_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def resolve_log_level(level: str) -> int:
    """Przelicza nazwę poziomu logowania na stałą liczbową lub zgłasza błąd."""
    normalized = level.strip().upper()
    if normalized not in _VALID_LOG_LEVELS:
        allowed = ", ".join(sorted(_VALID_LOG_LEVELS))
        raise InvalidConfigurationError(
            f"Nieznany poziom logowania: '{level}'. Dozwolone wartości: {allowed}."
        )
    return _VALID_LOG_LEVELS[normalized]


def configure_logging(
    level: str = "INFO",
    log_file: Path | None = None,
) -> logging.Logger:
    """Konfiguruje główny logger pakietu z wyjściem na ``stderr`` i opcjonalnym plikiem."""
    numeric_level = resolve_log_level(level)
    logger = logging.getLogger(ROOT_LOGGER_NAME)

    # Zamykamy poprzednie handlery przed rekonfiguracją, aby nie blokować plików na Windows.
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

    logger.setLevel(numeric_level)
    logger.propagate = False

    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file is not None:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str = ROOT_LOGGER_NAME) -> logging.Logger:
    """Zwraca logger przypisany do wspólnej przestrzeni nazw ``kaucjomat``."""
    if name == ROOT_LOGGER_NAME or name.startswith(f"{ROOT_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")
