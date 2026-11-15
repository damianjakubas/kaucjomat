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


def sanitize_for_log(value: object, max_length: int = 64) -> str:
    """Usuwa znaki sterujące i skraca wartość przed umieszczeniem jej w logu lub błędzie."""
    text = str(value)
    # Zamiana znaków kontrolnych (\r, \n, \t itp.) chroni logi przed wstrzykiwaniem wpisów.
    cleaned = "".join(" " if ord(char) < 32 or ord(char) == 127 else char for char in text)
    if max_length > 3 and len(cleaned) > max_length:
        return f"{cleaned[: max_length - 3]}..."
    return cleaned[:max_length]


def resolve_log_level(level: str) -> int:
    """Przelicza nazwę poziomu logowania na stałą liczbową lub zgłasza błąd."""
    normalized = level.strip().upper()
    if normalized not in _VALID_LOG_LEVELS:
        allowed = ", ".join(sorted(_VALID_LOG_LEVELS))
        safe_level = sanitize_for_log(level)
        raise InvalidConfigurationError(
            f"Nieznany poziom logowania: '{safe_level}'. Dozwolone wartości: {allowed}."
        )
    return _VALID_LOG_LEVELS[normalized]


def configure_logging(
    level: str = "INFO",
    log_file: Path | None = None,
) -> logging.Logger:
    """Konfiguruje główny logger pakietu z wyjściem na ``stderr`` i opcjonalnym plikiem."""
    numeric_level = resolve_log_level(level)
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    new_handlers: list[logging.Handler] = [console_handler]

    if log_file is not None:
        log_path = Path(log_file)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
        except OSError as exc:
            console_handler.close()
            safe_path = sanitize_for_log(log_path, max_length=128)
            raise InvalidConfigurationError(
                f"Nie można otworzyć pliku logów '{safe_path}': {exc}."
            ) from exc
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        new_handlers.append(file_handler)

    # Najpierw odpinamy, a potem zamykamy stare handlery dopiero po przygotowaniu nowych.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    logger.setLevel(numeric_level)
    logger.propagate = False
    for handler in new_handlers:
        logger.addHandler(handler)

    return logger


def get_logger(name: str = ROOT_LOGGER_NAME) -> logging.Logger:
    """Zwraca logger przypisany do wspólnej przestrzeni nazw ``kaucjomat``."""
    if name == ROOT_LOGGER_NAME or name.startswith(f"{ROOT_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")
