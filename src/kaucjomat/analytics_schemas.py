"""Modele Pydantic kontraktu HTTP widoku Analityka (kontekst, referencja, zadania w tle)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AnalyticsPresetSchema(BaseModel):
    """Opis presetu przebiegu widoczny w liście wyboru."""

    preset_id: str = Field(description="Identyfikator presetu (quick lub standard).")
    label: str = Field(description="Krótka nazwa presetu dla użytkownika.")
    description: str = Field(description="Opis czasu i charakteru przebiegu.")
    size_label: str = Field(description="Rozmiar zbioru, np. '4 pliki × 2000 rekordów'.")


class AnalyticsContextResponse(BaseModel):
    """Środowisko maszyny i dostępne presety przebiegów analityki."""

    mode: Literal["DEMO"] = "DEMO"
    cpu_count: int = Field(ge=1, description="Liczba rdzeni wykryta przez os.cpu_count().")
    gil_enabled: bool = Field(description="Czy blokada GIL jest aktywna w interpreterze.")
    single_core_warning: str | None = Field(description="Wyjaśnienie dla maszyn 1-rdzeniowych.")
    presets: list[AnalyticsPresetSchema]


class AnalyticsReferenceResponse(BaseModel):
    """Zapisane wyniki referencyjne benchmarku GIL wraz z adresem wykresu."""

    mode: Literal["DEMO"] = "DEMO"
    benchmark: dict[str, Any] = Field(description="Słownik raportu w kształcie jak wynik na żywo.")
    chart_url: str = Field(description="Adres wykresu PNG wyników referencyjnych.")


class AnalyticsJobRequest(BaseModel):
    """Żądanie startu zadania: rodzaj akcji i preset (bez wolnych parametrów)."""

    model_config: ConfigDict = ConfigDict(extra="forbid")

    kind: Literal["generate", "analysis", "benchmark"]
    preset: Literal["quick", "standard"]


class AnalyticsJobResponse(BaseModel):
    """Migawka zadania w tle albo stan ``idle``, gdy żadne zadanie nie było uruchomione."""

    mode: Literal["DEMO"] = "DEMO"
    status: Literal["idle", "running", "succeeded", "failed"]
    job_id: str | None = None
    kind: str | None = None
    preset_id: str | None = None
    phase: str | None = None
    progress_done: int | None = None
    progress_total: int | None = None
    started_at_iso: str | None = None
    finished_at_iso: str | None = None
    elapsed_ms: float | None = None
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
