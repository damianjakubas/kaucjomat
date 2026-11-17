"""Presety przebiegów analityki uruchamianych z przeglądarki (limity czasu pokazu)."""

from __future__ import annotations

from dataclasses import dataclass

from kaucjomat.exceptions import InvalidConfigurationError


@dataclass(frozen=True, slots=True)
class AnalyticsPreset:
    """Niemutowalny zestaw parametrów zbioru, analizy i benchmarku dla jednego presetu."""

    preset_id: str
    label: str
    description: str
    file_count: int
    records_per_file: int
    chunk_size: int
    repeats: int
    work_iterations: int
    max_workers: int


ANALYTICS_PRESETS: dict[str, AnalyticsPreset] = {
    "quick": AnalyticsPreset(
        preset_id="quick", label="Szybki",
        description="Mały zbiór, przebieg ok. 10 s na maszynie wielordzeniowej.",
        file_count=4, records_per_file=2000, chunk_size=500,
        repeats=2, work_iterations=30, max_workers=8,
    ),
    "standard": AnalyticsPreset(
        preset_id="standard", label="Standardowy",
        description=(
            "Parametry referencyjne, przebieg ok. 45 s; "
            "na maszynie 1-rdzeniowej znacznie dłużej."
        ),
        file_count=8, records_per_file=5000, chunk_size=1000,
        repeats=3, work_iterations=30, max_workers=8,
    ),
}


def get_preset(preset_id: str) -> AnalyticsPreset:
    """Zwraca preset o podanym identyfikatorze lub zgłasza błąd konfiguracji."""
    # Wyszukiwanie w momencie wywołania pozwala testom podmienić preset przez monkeypatch.
    preset = ANALYTICS_PRESETS.get(preset_id)
    if preset is None:
        raise InvalidConfigurationError(f"Nieznany preset analityki: '{preset_id}'.")
    return preset
