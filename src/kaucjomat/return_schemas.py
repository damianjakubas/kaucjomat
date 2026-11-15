"""Modele Pydantic v2 dla żądań i odpowiedzi API butelkomatu (DEMO)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from kaucjomat.return_domain import DecisionStatus, PackageCategory, RejectionReason


class TestCardSchema(BaseModel):
    """Reprezentacja pojedynczej karty testowej opakowania na półce DEMO."""

    card_id: str = Field(description="Unikalny identyfikator karty testowej.")
    title: str = Field(description="Czytelna nazwa opakowania wyświetlana na karcie.")
    subtitle: str = Field(description="Podtytuł z EAN, numerem sztuki i statusem znaku.")
    badge: str = Field(description="Krótka etykieta kategorii i pojemności.")
    group: Literal["valid", "glass", "invalid"] = Field(
        description="Grupa demonstracyjna karty testowej."
    )
    expected_hint: str = Field(description="Edukacyjna podpowiedź przewidywanego wyniku wrzutu.")
    package_code: str = Field(description="Pełny kod opakowania przekazywany do skanera.")
    category: PackageCategory = Field(description="Kategoria materiałowa opakowania.")
    volume_ml: int = Field(description="Deklarowana pojemność opakowania w mililitrach.")
    has_deposit_logo: bool = Field(description="Czy opakowanie posiada znak systemu kaucyjnego.")
    is_crushed: bool = Field(description="Czy opakowanie jest zgniecione lub uszkodzone.")
    is_empty: bool = Field(description="Czy opakowanie zostało całkowicie opróżnione.")


class TestCardsListResponse(BaseModel):
    """Odpowiedź zawierająca listę 8 kart testowych gotowych do wrzutu w butelkomacie."""

    mode: Literal["DEMO"] = Field(
        default="DEMO",
        description="Oznaczenie edukacyjnego trybu demonstracyjnego.",
    )
    cards: list[TestCardSchema] = Field(description="Lista predefiniowanych kart testowych DEMO.")


class DepositCustomCandidateInput(BaseModel):
    """Parametry niestandardowego opakowania przesyłanego bezpośrednio w żądaniu wrzutu."""

    package_code: str = Field(
        min_length=1,
        max_length=128,
        description="Kod etykiety opakowania analizowany przez parser regex.",
    )
    category: PackageCategory = Field(description="Kategoria materiałowa opakowania.")
    volume_ml: int = Field(
        ge=-1_000_000,
        le=1_000_000,
        description="Pojemność opakowania w mililitrach.",
    )
    title: str = Field(
        default="Opakowanie niestandardowe",
        min_length=1,
        max_length=120,
        description="Nazwa opisowa opakowania prezentowana w historii sesji.",
    )
    has_deposit_logo: bool = Field(
        default=True,
        description="Informacja o obecności znaku KAUCJA na etykiecie.",
    )
    is_crushed: bool = Field(
        default=False,
        description="Informacja, czy opakowanie jest zgniecione lub nieczytelne.",
    )
    is_empty: bool = Field(
        default=True,
        description="Informacja, czy opakowanie zostało opróżnione przed wrzutem.",
    )


class DepositRequest(BaseModel):
    """Żądanie wrzutu pojedynczego opakowania przez identyfikator karty lub opis własny."""

    card_id: str | None = Field(
        default=None,
        max_length=64,
        description="Identyfikator predefiniowanej karty testowej z półki DEMO.",
    )
    custom_candidate: DepositCustomCandidateInput | None = Field(
        default=None,
        description="Niestandardowe dane opakowania używane zamiast card_id.",
    )


class DepositDecisionSchema(BaseModel):
    """Szczegółowy wynik walidacji pojedynczego wrzutu w butelkomacie DEMO."""

    status: DecisionStatus = Field(description="Rozstrzygnięcie skanera dla wrzuconego opakowania.")
    reason_code: RejectionReason | None = Field(
        default=None,
        description="Kod przyczyny odrzucenia lub None przy akceptacji / kasie.",
    )
    deposit_grosze: int = Field(description="Naliczona kaucja automatyczna w groszach.")
    deposit_formatted: str = Field(description="Naliczona kaucja sformatowana po polsku w zł.")
    cashier_suggested_grosze: int = Field(
        description="Sugerowana kwota zwrotu w Kasie Sklepowej w groszach."
    )
    cashier_suggested_formatted: str = Field(
        description="Sugerowana kwota zwrotu w Kasie Sklepowej sformatowana w zł."
    )
    message: str = Field(description="Czytelny komunikat decyzji wyświetlany w trybie DEMO.")
    package_code: str = Field(description="Przeanalizowany kod etykiety opakowania.")
    title: str = Field(description="Nazwa wrzuconego opakowania.")
    category: PackageCategory = Field(description="Kategoria materiałowa opakowania.")
    volume_ml: int = Field(description="Pojemność opakowania w mililitrach.")
    ean: str | None = Field(default=None, description="Wyodrębniony kod EAN-13 lub None.")
    instance_id: str | None = Field(
        default=None,
        description="Wyodrębniony identyfikator egzemplarza lub None.",
    )
    elapsed_ms: float = Field(description="Zmierzony czas walidacji w milisekundach.")
    within_latency_budget: bool = Field(
        description="Czy ocena zmieściła się w budżecie opóźnienia skanera."
    )


class SessionAttemptSchema(BaseModel):
    """Pojedynczy wpis historii prób w aktywnej sesji zwrotu."""

    attempt_no: int = Field(description="Kolejny numer próby w sesji zwrotu.")
    timestamp_iso: str = Field(description="Znacznik czasu próby w formacie ISO 8601 UTC.")
    card_id: str | None = Field(default=None, description="Identyfikator użytej karty lub None.")
    package_code: str = Field(description="Kod opakowania z tej próby wrzutu.")
    title: str = Field(description="Nazwa ocenianego opakowania.")
    category: str = Field(description="Kategoria materiałowa opakowania.")
    volume_ml: int = Field(description="Pojemność opakowania w mililitrach.")
    ean: str | None = Field(default=None, description="Wyodrębniony numer EAN-13 lub None.")
    instance_id: str | None = Field(
        default=None,
        description="Wyodrębniony identyfikator egzemplarza lub None.",
    )
    status: str = Field(description="Status decyzji z tej próby wrzutu.")
    reason_code: str | None = Field(default=None, description="Kod przyczyny odrzucenia lub None.")
    deposit_grosze: int = Field(description="Naliczona kwota kaucji w groszach.")
    cashier_suggested_grosze: int = Field(
        description="Sugerowana kwota do odbioru w Kasie Sklepowej w groszach."
    )
    message: str = Field(description="Komunikat skanera zapisany przy tej próbie.")
    elapsed_ms: float = Field(description="Czas oceny próby w milisekundach.")


class ReturnSessionSchema(BaseModel):
    """Aktualny stan aktywnej sesji zwrotów oraz trwałego rejestru egzemplarzy DEMO."""

    mode: Literal["DEMO"] = Field(
        default="DEMO",
        description="Oznaczenie edukacyjnego trybu demonstracyjnego.",
    )
    session_id: str = Field(description="Identyfikator aktywnej sesji zwrotu DEMO.")
    status: Literal["OPEN"] = Field(description="Status otwartej sesji zwrotu.")
    accepted_count: int = Field(description="Liczba zaakceptowanych opakowań w sesji.")
    redirected_glass_count: int = Field(
        description="Liczba opakowań szklanych skierowanych do Kasy Sklepowej."
    )
    rejected_count: int = Field(description="Liczba odrzuconych prób wrzutu w sesji.")
    total_grosze: int = Field(description="Łączna naliczona kaucja w sesji (w groszach).")
    total_formatted: str = Field(description="Łączna naliczona kaucja sformatowana w zł.")
    returned_registry_size: int = Field(
        description="Liczba unikalnych instance_id zapisanych w trwałym rejestrze DEMO."
    )
    can_issue_voucher: bool = Field(
        description="Informacja, czy sesja kwalifikuje się do wystawienia bonu DEMO."
    )
    attempts: list[SessionAttemptSchema] = Field(
        description="Lista prób w sesji posortowana od najnowszej."
    )


class DepositAttemptResponse(BaseModel):
    """Odpowiedź API po ocenie pojedynczego wrzutu opakowania."""

    mode: Literal["DEMO"] = Field(
        default="DEMO",
        description="Oznaczenie edukacyjnego trybu demonstracyjnego.",
    )
    decision: DepositDecisionSchema = Field(description="Wynik walidacji wrzuconego opakowania.")
    session: ReturnSessionSchema = Field(description="Zaktualizowany stan bieżącej sesji DEMO.")


class ResetStateResponse(BaseModel):
    """Odpowiedź API potwierdzająca wyczyszczenie rejestru i sesji DEMO."""

    mode: Literal["DEMO"] = Field(
        default="DEMO",
        description="Oznaczenie edukacyjnego trybu demonstracyjnego.",
    )
    message: str = Field(description="Czytelne potwierdzenie wykonania resetu stanu DEMO.")
    session: ReturnSessionSchema = Field(description="Nowa wyzerowana sesja zwrotu DEMO.")
