"""Modele danych Pydantic v2 dla warstwy API aplikacji KaucjaSim DEMO."""

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Odpowiedź endpointu kontrolnego potwierdzająca gotowość backendu DEMO."""

    status: Literal["ok"] = Field(description="Status operacyjny usługi.")
    app_name: str = Field(description="Nazwa wyświetlana aplikacji.")
    version: str = Field(description="Wersja pakietu aplikacji.")
    mode: Literal["DEMO"] = Field(description="Oznaczenie edukacyjnego trybu demonstracyjnego.")
    views_count: int = Field(ge=1, description="Liczba zarejestrowanych widoków powłoki.")


class ViewSchema(BaseModel):
    """Metadane pojedynczego widoku powłoki webowej KaucjaSim DEMO."""

    id: str = Field(description="Techniczny identyfikator widoku.")
    title: str = Field(description="Czytelna nazwa zakładki widoku.")
    badge: str = Field(description="Krótka etykieta edukacyjna widoku.")
    description: str = Field(description="Opis roli widoku w symulatorze.")
    planned_scope: str = Field(description="Docelowy zakres funkcji powiązany z widokiem.")
    demo_mode: bool = Field(
        default=True,
        description="Flaga potwierdzająca działanie widoku wyłącznie w trybie DEMO.",
    )


class ViewsListResponse(BaseModel):
    """Lista widoków powłoki webowej wraz ze wskazaniem domyślnej zakładki."""

    mode: Literal["DEMO"] = Field(description="Oznaczenie edukacyjnego trybu demonstracyjnego.")
    default_view: str = Field(description="Identyfikator widoku otwieranego domyślnie.")
    views: list[ViewSchema] = Field(description="Uporządkowana lista dostępnych widoków.")


class ErrorResponse(BaseModel):
    """Ujednolicony format odpowiedzi błędu zwracany przez API aplikacji."""

    error_code: str = Field(description="Kod błędu domenowego lub błędu walidacji.")
    message: str = Field(description="Czytelny komunikat błędu dla użytkownika.")
    detail: str | None = Field(
        default=None,
        description="Opcjonalne szczegóły diagnostyczne dotyczące przyczyny błędu.",
    )
    mode: Literal["DEMO"] = Field(
        default="DEMO",
        description="Oznaczenie trybu pracy aplikacji podczas zgłoszenia błędu.",
    )
