"""Własne dekoratory funkcji do audytu i kontroli budżetu czasu skanera (KZ-01, KZ-18)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields, is_dataclass, replace
from functools import wraps
import time
from typing import ParamSpec, TypeVar, cast

from kaucjomat.exceptions import InvalidConfigurationError
from kaucjomat.logging_config import get_logger

P = ParamSpec("P")
R = TypeVar("R")

_RETURNS_LOGGER = get_logger("returns")


def _extract_package_code(args: tuple[object, ...], kwargs: dict[str, object]) -> str:
    """Wyciąga bezpiecznie kod opakowania z argumentów wywołania na potrzeby logów."""
    candidate = kwargs.get("candidate")
    if candidate is None and args:
        candidate = args[0]
    return str(getattr(candidate, "package_code", candidate or "?"))


def _attach_timing_to_result(result: R, elapsed_ms: float, within_budget: bool) -> R:
    """Aktualizuje pola pomiaru czasu w wyniku typu dataclass, jeśli je posiada."""
    if not is_dataclass(result) or isinstance(result, type):
        return result

    field_names = {field.name for field in fields(result)}
    updates: dict[str, object] = {}
    if "elapsed_ms" in field_names:
        updates["elapsed_ms"] = max(0.01, elapsed_ms)
    if "within_latency_budget" in field_names:
        updates["within_latency_budget"] = within_budget

    if not updates:
        return result
    return cast(R, replace(result, **updates))


def log_deposit_attempt(func: Callable[P, R]) -> Callable[P, R]:
    """Dekorator bezparametrowy rejestrujący próbę i wynik walidacji wrzutu w logach."""

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        """Otacza wywołanie funkcji walidującej i zapisuje decyzję w loggerze zwrotów."""
        package_code = _extract_package_code(args, kwargs)
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            _RETURNS_LOGGER.warning(
                "Błąd podczas walidacji wrzutu opakowania %s w %s: %s",
                package_code,
                func.__name__,
                exc,
            )
            raise

        status = getattr(result, "status", None)
        reason_code = getattr(result, "reason_code", None)
        deposit_grosze = getattr(result, "deposit_grosze", None)
        elapsed_ms = getattr(result, "elapsed_ms", None)

        if status is not None:
            _RETURNS_LOGGER.info(
                "Wrzut %s -> status=%s, powód=%s, kaucja=%s gr, czas=%s ms",
                package_code,
                status,
                reason_code or "-",
                deposit_grosze if deposit_grosze is not None else "-",
                elapsed_ms if elapsed_ms is not None else "-",
            )
        else:
            _RETURNS_LOGGER.info(
                "Wywołanie %s dla %s zakończone wynikiem typu %s",
                func.__name__,
                package_code,
                type(result).__name__,
            )
        return result

    return wrapper


def enforce_latency_budget(
    max_ms: float = 200.0,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Fabryka dekoratora mierząca czas walidacji i pilnująca progu opóźnienia w ms."""
    if max_ms <= 0:
        raise InvalidConfigurationError(
            "Parametr max_ms dla budżetu opóźnienia musi być liczbą dodatnią."
        )

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        """Dekoruje przekazaną funkcję kontrolą czasu wykonania względem `max_ms`."""

        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            """Mierzy czas działania funkcji i dopisuje metryki do decyzji skanera."""
            started_at = time.perf_counter()
            result = func(*args, **kwargs)
            elapsed_ms = round((time.perf_counter() - started_at) * 1000.0, 3)
            within_budget = elapsed_ms <= max_ms

            if not within_budget:
                _RETURNS_LOGGER.warning(
                    "Przekroczono budżet czasu funkcji %s: %.3f ms > %.3f ms",
                    func.__name__,
                    elapsed_ms,
                    max_ms,
                )

            return _attach_timing_to_result(result, elapsed_ms, within_budget)

        return wrapper

    return decorator
