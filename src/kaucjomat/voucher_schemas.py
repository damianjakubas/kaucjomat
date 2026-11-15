"""Modele Pydantic v2 dla żądań i odpowiedzi API bonów kaucjomatowych DEMO."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from kaucjomat.return_schemas import ReturnSessionSchema
from kaucjomat.voucher_domain import VOUCHER_VALIDITY_DAYS, VoucherStatus

DEFAULT_DEMO_WATERMARK = "BON KAUCYJNY — TRYB DEMO (Dokument niefiskalny)"


class IssueVoucherRequest(BaseModel):
    """Opcjonalne żądanie wystawienia bonu pozwalające wymusić idempotencję po sesji."""

    session_id: str | None = Field(
        default=None,
        max_length=64,
        description="Opcjonalny identyfikator zamykanej sesji zwrotu zapewniający idempotencję.",
    )


class VoucherSchema(BaseModel):
    """Pełna reprezentacja bonu kaucjomatowego DEMO zwracana przez API."""

    mode: Literal["DEMO"] = Field(
        default="DEMO",
        description="Oznaczenie edukacyjnego trybu demonstracyjnego.",
    )
    voucher_code: str = Field(description="Unikalny kod bonu DEMO (np. BON-DEMO-0001-XXXX).")
    source_session_id: str = Field(
        description="Identyfikator sesji zwrotu, z której wygenerowano bon."
    )
    amount_grosze: int = Field(description="Łączna wartość kaucji na bonie w groszach.")
    amount_formatted: str = Field(description="Kwota bonu sformatowana po polsku w zł.")
    accepted_count: int = Field(description="Liczba zaakceptowanych opakowań objętych bonem.")
    issued_at_iso: str = Field(description="Znacznik czasu wystawienia bonu w formacie UTC ISO-8601.")
    expires_at_iso: str = Field(
        description="Znacznik czasu wygaśnięcia bonu w formacie UTC ISO-8601."
    )
    validity_days: int = Field(
        default=VOUCHER_VALIDITY_DAYS,
        description="Nominalny okres ważności bonu kaucyjnego w dniach.",
    )
    status: VoucherStatus = Field(
        description="Aktualny status bonu DEMO (AKTYWNY, ZUŻYTY lub WYGASŁY)."
    )
    redeemed_at_iso: str | None = Field(
        default=None,
        description="Znacznik czasu realizacji bonu w kasie lub None dla bonu nierealizowanego.",
    )
    is_test_seed: bool = Field(
        description="Czy bon jest fabrycznym bonem testowym DEMO (np. wygasłym)."
    )
    demo_watermark: str = Field(
        default=DEFAULT_DEMO_WATERMARK,
        description="Obowiązkowe oznaczenie niefiskalnego dokumentu demonstracyjnego.",
    )


class IssueVoucherResponse(BaseModel):
    """Odpowiedź HTTP po zakończeniu sesji zwrotu i wystawieniu bonu DEMO."""

    mode: Literal["DEMO"] = Field(
        default="DEMO",
        description="Oznaczenie edukacyjnego trybu demonstracyjnego.",
    )
    message: str = Field(description="Czytelny komunikat potwierdzający wystawienie bonu DEMO.")
    was_idempotent_replay: bool = Field(
        description="Informacja, czy zwrócono istniejący bon dla powtórzonego session_id."
    )
    voucher: VoucherSchema = Field(description="Wystawiony lub odtworzony bon kaucjomatowy DEMO.")
    session: ReturnSessionSchema = Field(
        description="Stan nowej (lub aktualnej przy replayu) otwartej sesji butelkomatu."
    )


class VouchersListResponse(BaseModel):
    """Lista wszystkich zapisanych bonów DEMO (użytkownika i fabrycznych testowych)."""

    mode: Literal["DEMO"] = Field(
        default="DEMO",
        description="Oznaczenie edukacyjnego trybu demonstracyjnego.",
    )
    vouchers: list[VoucherSchema] = Field(
        description="Bony DEMO uporządkowane od najnowszych użytkownika po bon testowy."
    )
