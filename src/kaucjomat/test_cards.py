"""Katalog 8 predefiniowanych kart testowych DEMO dla półki butelkomatu."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from kaucjomat.exceptions import PackageCardNotFoundError
from kaucjomat.logging_config import sanitize_for_log
from kaucjomat.return_domain import PackageCandidate, PackageCategory


@dataclass(frozen=True, slots=True)
class TestPackageCard:
    """Pojedyncza karta testowego opakowania wyświetlana na półce symulatora."""

    card_id: str
    title: str
    subtitle: str
    badge: str
    group: Literal["valid", "glass", "invalid"]
    expected_hint: str
    candidate: PackageCandidate


TEST_PACKAGE_CARDS: Final[tuple[TestPackageCard, ...]] = (
    TestPackageCard(
        card_id="pet-water-1500-a",
        title="Woda źródlana PET 1,5 l (Sztuka #1)",
        subtitle="EAN 5900000000114 · ID PET-000101 · Znak KAUCJA",
        badge="PET · 1500 ml",
        group="valid",
        expected_hint="Akceptacja +0,50 zł (drugi wrzut tej samej karty -> duplikat ID)",
        candidate=PackageCandidate(
            package_code="PL-KAUCJA-5900000000114-PET-000101",
            title="Woda źródlana PET 1,5 l (Sztuka #1)",
            category=PackageCategory.PET,
            volume_ml=1500,
            has_deposit_logo=True,
            is_crushed=False,
            is_empty=True,
        ),
    ),
    TestPackageCard(
        card_id="pet-water-1500-b",
        title="Woda źródlana PET 1,5 l (Sztuka #2 — ten sam EAN)",
        subtitle="EAN 5900000000114 · ID PET-000102 · Znak KAUCJA",
        badge="PET · 1500 ml",
        group="valid",
        expected_hint="Akceptacja +0,50 zł (ten sam EAN, inne ID egzemplarza)",
        candidate=PackageCandidate(
            package_code="PL-KAUCJA-5900000000114-PET-000102",
            title="Woda źródlana PET 1,5 l (Sztuka #2 — ten sam EAN)",
            category=PackageCategory.PET,
            volume_ml=1500,
            has_deposit_logo=True,
            is_crushed=False,
            is_empty=True,
        ),
    ),
    TestPackageCard(
        card_id="can-cola-500",
        title="Napój gazowany Puszka 0,5 l",
        subtitle="EAN 5900000000220 · ID CAN-000201 · Znak KAUCJA",
        badge="Puszka · 500 ml",
        group="valid",
        expected_hint="Akceptacja +0,50 zł",
        candidate=PackageCandidate(
            package_code="PL-KAUCJA-5900000000220-CAN-000201",
            title="Napój gazowany Puszka 0,5 l",
            category=PackageCategory.CAN,
            volume_ml=500,
            has_deposit_logo=True,
            is_crushed=False,
            is_empty=True,
        ),
    ),
    TestPackageCard(
        card_id="glass-beer-500",
        title="Butelka szklana zwrotna 0,5 l",
        subtitle="EAN 5900000000336 · ID GLS-000301 · Szkło wielorazowe",
        badge="Szkło · 500 ml",
        group="glass",
        expected_hint="Przekierowanie do Kasy Sklepowej (+1,00 zł w kasie)",
        candidate=PackageCandidate(
            package_code="PL-KAUCJA-5900000000336-GLS-000301",
            title="Butelka szklana zwrotna 0,5 l",
            category=PackageCategory.GLASS,
            volume_ml=500,
            has_deposit_logo=True,
            is_crushed=False,
            is_empty=True,
        ),
    ),
    TestPackageCard(
        card_id="reject-no-logo",
        title="Butelka PET 0,5 l bez znaku kaucji",
        subtitle="EAN 5900000000442 · ID PET-000401 · Brak znaku KAUCJA",
        badge="PET · Brak logo",
        group="invalid",
        expected_hint="Odrzucenie: brak znaku systemu kaucyjnego",
        candidate=PackageCandidate(
            package_code="PL-BEZLOGO-5900000000442-PET-000401",
            title="Butelka PET 0,5 l bez znaku kaucji",
            category=PackageCategory.PET,
            volume_ml=500,
            has_deposit_logo=False,
            is_crushed=False,
            is_empty=True,
        ),
    ),
    TestPackageCard(
        card_id="reject-crushed-can",
        title="Zgnieciona puszka aluminiowa 0,5 l",
        subtitle="EAN 5900000000220 · ID CAN-000202 · Zgnieciona etykieta",
        badge="Puszka · Zgnieciona",
        group="invalid",
        expected_hint="Odrzucenie: opakowanie zgniecione / uszkodzone",
        candidate=PackageCandidate(
            package_code="PL-KAUCJA-5900000000220-CAN-000202",
            title="Zgnieciona puszka aluminiowa 0,5 l",
            category=PackageCategory.CAN,
            volume_ml=500,
            has_deposit_logo=True,
            is_crushed=True,
            is_empty=True,
        ),
    ),
    TestPackageCard(
        card_id="reject-dairy-carton",
        title="Karton po mleku 1,0 l (nabiał)",
        subtitle="EAN 5900000000558 · ID OTH-000501 · Kategoria wyłączona",
        badge="Nabiał · 1000 ml",
        group="invalid",
        expected_hint="Odrzucenie: kategoria wyłączona z systemu kaucji",
        candidate=PackageCandidate(
            package_code="PL-KAUCJA-5900000000558-OTH-000501",
            title="Karton po mleku 1,0 l (nabiał)",
            category=PackageCategory.DAIRY_CARTON,
            volume_ml=1000,
            has_deposit_logo=True,
            is_crushed=False,
            is_empty=True,
        ),
    ),
    TestPackageCard(
        card_id="reject-over-volume",
        title="Bukłak PET 5,0 l (powyżej limitu 3 l)",
        subtitle="EAN 5900000000664 · ID PET-000601 · Przekroczony limit",
        badge="PET · 5000 ml",
        group="invalid",
        expected_hint="Odrzucenie: przekroczony limit pojemności 3000 ml",
        candidate=PackageCandidate(
            package_code="PL-KAUCJA-5900000000664-PET-000601",
            title="Bukłak PET 5,0 l (powyżej limitu 3 l)",
            category=PackageCategory.PET,
            volume_ml=5000,
            has_deposit_logo=True,
            is_crushed=False,
            is_empty=True,
        ),
    ),
)

_CARDS_BY_ID: Final[dict[str, TestPackageCard]] = {
    card.card_id: card for card in TEST_PACKAGE_CARDS
}


def get_test_cards() -> tuple[TestPackageCard, ...]:
    """Zwraca niemutowalną krotkę 8 predefiniowanych kart testowych na półkę DEMO."""
    return TEST_PACKAGE_CARDS


def get_test_card_by_id(card_id: str) -> TestPackageCard:
    """Wyszukuje kartę testową po identyfikatorze albo zgłasza `PackageCardNotFoundError`."""
    normalized_id = card_id.strip()
    card = _CARDS_BY_ID.get(normalized_id)
    if card is None:
        safe_id = sanitize_for_log(card_id, max_length=64)
        raise PackageCardNotFoundError(
            f"Nie znaleziono karty testowej opakowania o identyfikatorze '{safe_id}'."
        )
    return card
