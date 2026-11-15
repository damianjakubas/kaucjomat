"""Logika domenowa walidacji opakowań wrzucanych do butelkomatu DEMO."""

from __future__ import annotations

from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from kaucjomat.decorators import enforce_latency_budget, log_deposit_attempt
from kaucjomat.return_patterns import (
    is_valid_ean13_checksum,
    parse_instance_serial,
    parse_package_code,
)


class PackageCategory(StrEnum):
    """Kategorie opakowań rozpoznawane przez skaner butelkomatu."""

    PET = "PET"
    CAN = "CAN"
    GLASS = "GLASS"
    DAIRY_CARTON = "DAIRY_CARTON"
    OTHER = "OTHER"


class DecisionStatus(StrEnum):
    """Możliwe wyniki pojedynczej próby wrzutu opakowania do automatu."""

    ACCEPTED = "ACCEPTED"
    REDIRECT_TO_CASHIER = "REDIRECT_TO_CASHIER"
    REJECTED = "REJECTED"


class RejectionReason(StrEnum):
    """Jednoznaczne kody przyczyn odrzucenia opakowania przez walidator."""

    INVALID_CODE_FORMAT = "INVALID_CODE_FORMAT"
    MISSING_DEPOSIT_LOGO = "MISSING_DEPOSIT_LOGO"
    EXCLUDED_CATEGORY = "EXCLUDED_CATEGORY"
    CRUSHED_OR_DAMAGED = "CRUSHED_OR_DAMAGED"
    NOT_EMPTY = "NOT_EMPTY"
    VOLUME_LIMIT_EXCEEDED = "VOLUME_LIMIT_EXCEEDED"
    DUPLICATE_INSTANCE_ID = "DUPLICATE_INSTANCE_ID"


PET_CAN_DEPOSIT_GROSZE: Final[int] = 50
GLASS_CASHIER_DEPOSIT_GROSZE: Final[int] = 100

VOLUME_LIMITS_ML: Final[dict[PackageCategory, int]] = {
    PackageCategory.PET: 3000,
    PackageCategory.CAN: 1000,
    PackageCategory.GLASS: 1500,
}

CATEGORY_SERIAL_PREFIXES: Final[dict[PackageCategory, str]] = {
    PackageCategory.PET: "PET",
    PackageCategory.CAN: "CAN",
    PackageCategory.GLASS: "GLS",
    PackageCategory.DAIRY_CARTON: "OTH",
    PackageCategory.OTHER: "OTH",
}

_AUTOMATIC_MACHINE_CATEGORIES: Final[frozenset[PackageCategory]] = frozenset(
    {PackageCategory.PET, PackageCategory.CAN}
)
_EXCLUDED_CATEGORIES: Final[frozenset[PackageCategory]] = frozenset(
    {PackageCategory.DAIRY_CARTON, PackageCategory.OTHER}
)


@dataclass(frozen=True, slots=True)
class PackageCandidate:
    """Dane opakowania przekazywane do walidatora podczas próby zwrotu."""

    package_code: str
    title: str
    category: PackageCategory
    volume_ml: int
    has_deposit_logo: bool
    is_crushed: bool
    is_empty: bool = True


@dataclass(frozen=True, slots=True)
class DepositDecision:
    """Kompletna decyzja skanera butelkomatu wraz z kwotą w groszach i czasem."""

    status: DecisionStatus
    deposit_grosze: int
    cashier_suggested_grosze: int
    message: str
    package_code: str
    title: str
    category: PackageCategory
    volume_ml: int
    ean: str | None
    instance_id: str | None
    reason_code: RejectionReason | None = None
    elapsed_ms: float = 0.0
    within_latency_budget: bool = True


def format_pln_from_grosze(grosze: int) -> str:
    """Formatuje kwotę podaną w groszach na polski zapis w złotych z przecinkiem."""
    sign = "-" if grosze < 0 else ""
    abs_grosze = abs(grosze)
    zloty = abs_grosze // 100
    rest = abs_grosze % 100
    return f"{sign}{zloty},{rest:02d} zł"


def _build_rejected_decision(
    candidate: PackageCandidate,
    reason_code: RejectionReason,
    message: str,
    *,
    ean: str | None = None,
    instance_id: str | None = None,
) -> DepositDecision:
    """Tworzy ustandaryzowaną decyzję odrzucenia opakowania z podaniem przyczyny."""
    return DepositDecision(
        status=DecisionStatus.REJECTED,
        deposit_grosze=0,
        cashier_suggested_grosze=0,
        message=message,
        package_code=candidate.package_code.strip(),
        title=candidate.title,
        category=candidate.category,
        volume_ml=candidate.volume_ml,
        ean=ean,
        instance_id=instance_id,
        reason_code=reason_code,
    )


@log_deposit_attempt
@enforce_latency_budget(max_ms=200.0)
def evaluate_package_return(
    candidate: PackageCandidate,
    already_returned_ids: AbstractSet[str],
) -> DepositDecision:
    """Ocenia pojedyncze opakowanie wrzucone do butelkomatu według priorytetu reguł DEMO."""
    parsed_code = parse_package_code(candidate.package_code)
    if parsed_code is None or not is_valid_ean13_checksum(parsed_code.ean):
        return _build_rejected_decision(
            candidate,
            RejectionReason.INVALID_CODE_FORMAT,
            "Odrzucono (DEMO): niepoprawny format kodu etykiety lub błędna suma kontrolna EAN-13.",
        )

    parsed_serial = parse_instance_serial(parsed_code.instance_id)
    expected_prefix = CATEGORY_SERIAL_PREFIXES[candidate.category]
    if parsed_serial is None or parsed_serial.prefix != expected_prefix:
        return _build_rejected_decision(
            candidate,
            RejectionReason.INVALID_CODE_FORMAT,
            (
                "Odrzucono (DEMO): prefiks identyfikatora sztuki nie odpowiada "
                f"kategorii opakowania ({candidate.category.value})."
            ),
            ean=parsed_code.ean,
            instance_id=parsed_code.instance_id,
        )

    # Reguła #2: opakowanie bez aktywnego oznaczenia kaucji nie podlega zwrotowi.
    if not candidate.has_deposit_logo or parsed_code.deposit_mark != "KAUCJA":
        return _build_rejected_decision(
            candidate,
            RejectionReason.MISSING_DEPOSIT_LOGO,
            "Odrzucono (DEMO): brak wymaganego znaku systemu kaucyjnego (KAUCJA).",
            ean=parsed_code.ean,
            instance_id=parsed_code.instance_id,
        )

    # Reguła #3: kategorie wyłączone ustawowo z kaucji (np. kartony po nabiale).
    if candidate.category in _EXCLUDED_CATEGORIES or parsed_serial.prefix == "OTH":
        return _build_rejected_decision(
            candidate,
            RejectionReason.EXCLUDED_CATEGORY,
            "Odrzucono (DEMO): opakowania tej kategorii (np. po nabiale) są wyłączone z systemu kaucji.",
            ean=parsed_code.ean,
            instance_id=parsed_code.instance_id,
        )

    # Reguła #4: zgniot lub uszkodzona etykieta uniemożliwia przyjęcie przez skaner.
    if candidate.is_crushed:
        return _build_rejected_decision(
            candidate,
            RejectionReason.CRUSHED_OR_DAMAGED,
            "Odrzucono (DEMO): opakowanie jest zgniecione lub etykieta uległa uszkodzeniu.",
            ean=parsed_code.ean,
            instance_id=parsed_code.instance_id,
        )

    # Reguła #5: automat przyjmuje wyłącznie puste opakowania.
    if not candidate.is_empty:
        return _build_rejected_decision(
            candidate,
            RejectionReason.NOT_EMPTY,
            "Odrzucono (DEMO): opakowanie musi być całkowicie opróżnione przed wrzutem.",
            ean=parsed_code.ean,
            instance_id=parsed_code.instance_id,
        )

    # Reguła #6: kontrola limitu pojemności właściwego dla materiału.
    volume_limit = VOLUME_LIMITS_ML.get(candidate.category)
    if candidate.volume_ml <= 0 or (volume_limit is not None and candidate.volume_ml > volume_limit):
        limit_hint = f"{volume_limit} ml" if volume_limit is not None else "dozwolonego zakresu"
        return _build_rejected_decision(
            candidate,
            RejectionReason.VOLUME_LIMIT_EXCEEDED,
            f"Odrzucono (DEMO): pojemność {candidate.volume_ml} ml przekracza limit {limit_hint}.",
            ean=parsed_code.ean,
            instance_id=parsed_code.instance_id,
        )

    # Reguła #7: wykrycie powtórnie użytego identyfikatora sztuki (anty-duplikat per egzemplarz).
    if (
        candidate.category in _AUTOMATIC_MACHINE_CATEGORIES
        and parsed_code.instance_id in already_returned_ids
    ):
        return _build_rejected_decision(
            candidate,
            RejectionReason.DUPLICATE_INSTANCE_ID,
            (
                f"Odrzucono (DEMO): egzemplarz {parsed_code.instance_id} został już wcześniej "
                "zwrócony w systemie."
            ),
            ean=parsed_code.ean,
            instance_id=parsed_code.instance_id,
        )

    # Reguła #8a: szkło wielokrotnego użytku kierujemy do obsługi w Kasie Sklepowej (+1,00 zł).
    if candidate.category == PackageCategory.GLASS:
        suggested = format_pln_from_grosze(GLASS_CASHIER_DEPOSIT_GROSZE)
        return DepositDecision(
            status=DecisionStatus.REDIRECT_TO_CASHIER,
            deposit_grosze=0,
            cashier_suggested_grosze=GLASS_CASHIER_DEPOSIT_GROSZE,
            message=(
                "Skierowano do Kasy Sklepowej (DEMO): butelkomat nie przyjmuje szkła wielorazowego. "
                f"Oddaj butelkę w kasie, aby otrzymać {suggested}."
            ),
            package_code=candidate.package_code.strip(),
            title=candidate.title,
            category=candidate.category,
            volume_ml=candidate.volume_ml,
            ean=parsed_code.ean,
            instance_id=parsed_code.instance_id,
        )

    # Reguła #8b: poprawne opakowanie PET lub puszka otrzymuje +0,50 zł kaucji.
    deposit_text = format_pln_from_grosze(PET_CAN_DEPOSIT_GROSZE)
    return DepositDecision(
        status=DecisionStatus.ACCEPTED,
        deposit_grosze=PET_CAN_DEPOSIT_GROSZE,
        cashier_suggested_grosze=0,
        message=(
            f"Zaakceptowano (DEMO): naliczono +{deposit_text} kaucji "
            f"(egzemplarz {parsed_code.instance_id})."
        ),
        package_code=candidate.package_code.strip(),
        title=candidate.title,
        category=candidate.category,
        volume_ml=candidate.volume_ml,
        ean=parsed_code.ean,
        instance_id=parsed_code.instance_id,
    )
