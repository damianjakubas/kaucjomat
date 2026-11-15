"""Testy jednostkowe domeny walidacji zwrotów, wzorców re, dekoratorów i kart DEMO."""

from __future__ import annotations

import logging
import time

import pytest

from kaucjomat.decorators import enforce_latency_budget, log_deposit_attempt
from kaucjomat.exceptions import InvalidConfigurationError, PackageCardNotFoundError
from kaucjomat.logging_config import get_logger
from kaucjomat.return_domain import (
    GLASS_CASHIER_DEPOSIT_GROSZE,
    PET_CAN_DEPOSIT_GROSZE,
    DecisionStatus,
    PackageCandidate,
    PackageCategory,
    RejectionReason,
    evaluate_package_return,
    format_pln_from_grosze,
)
from kaucjomat.return_patterns import (
    INSTANCE_SERIAL_RE,
    PACKAGE_CODE_RE,
    is_valid_ean13_checksum,
    parse_instance_serial,
    parse_package_code,
)
from kaucjomat.test_cards import get_test_card_by_id, get_test_cards


class _MemoryLogHandler(logging.Handler):
    """Tymczasowy handler zbierający wpisy z loggera `kaucjomat.returns` w testach."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_decorators_preserve_wraps_metadata_and_measure_latency() -> None:
    """Sprawdza zachowanie `__name__` i `__doc__` (`functools.wraps`) oraz pomiar czasu."""

    @log_deposit_attempt
    @enforce_latency_budget(max_ms=150.0)
    def sample_validator(value: int) -> dict[str, int]:
        """Przykładowy walidator testujący dekoratory."""
        return {"value": value * 2}

    assert sample_validator.__name__ == "sample_validator"
    assert sample_validator.__doc__ == "Przykładowy walidator testujący dekoratory."
    assert sample_validator(21) == {"value": 42}

    assert evaluate_package_return.__name__ == "evaluate_package_return"
    assert evaluate_package_return.__doc__ is not None

    with pytest.raises(InvalidConfigurationError):
        enforce_latency_budget(max_ms=0.0)

    with pytest.raises(InvalidConfigurationError):
        enforce_latency_budget(max_ms=-5.0)


def test_log_deposit_attempt_and_latency_warning_emit_log_records() -> None:
    """Weryfikuje logowanie decyzji wrzutu oraz ostrzeżenia po przekroczeniu progu czasu."""
    logger = get_logger("returns")
    handler = _MemoryLogHandler()
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        card = get_test_card_by_id("pet-water-1500-a")
        decision = evaluate_package_return(card.candidate, set())
        assert decision.elapsed_ms > 0.0
        assert decision.within_latency_budget is True

        @log_deposit_attempt
        @enforce_latency_budget(max_ms=0.1)
        def slow_operation(candidate: PackageCandidate) -> PackageCandidate:
            """Symuluje operację przekraczającą niski próg budżetu opóźnienia."""
            time.sleep(0.01)
            return candidate

        slow_operation(card.candidate)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    messages = [record.getMessage() for record in handler.records]
    assert any("status=ACCEPTED" in msg and "PL-KAUCJA-5900000000114-PET-000101" in msg for msg in messages)
    assert any("Przekroczono budżet czasu funkcji slow_operation" in msg for msg in messages)


def test_package_code_regex_named_groups_valid_and_invalid() -> None:
    """Testuje grupy nazwane `PACKAGE_CODE_RE` oraz sumę kontrolną GS1 EAN-13."""
    valid_match = PACKAGE_CODE_RE.fullmatch("PL-KAUCJA-5901234567893-PET-000101")
    assert valid_match is not None
    assert valid_match.groupdict() == {
        "country": "PL",
        "deposit_mark": "KAUCJA",
        "ean": "5901234567893",
        "instance_id": "PET-000101",
    }

    parsed = parse_package_code("  PL-BEZLOGO-5900000000442-PET-000401  ")
    assert parsed is not None
    assert parsed.deposit_mark == "BEZLOGO"
    assert is_valid_ean13_checksum(parsed.ean) is True
    assert is_valid_ean13_checksum("5901234567890") is False
    assert is_valid_ean13_checksum("ABC") is False

    for invalid_code in (
        "DE-KAUCJA-5901234567893-PET-000101",
        "PL-KAUCJA-590123456789-PET-000101",
        "PL-INNY-5901234567893-PET-000101",
        "PL-KAUCJA-5901234567893-PET-12345",
        "",
    ):
        assert parse_package_code(invalid_code) is None


def test_instance_serial_regex_named_groups() -> None:
    """Testuje drugi wzorzec regex `INSTANCE_SERIAL_RE` i jego grupy nazwane."""
    match = INSTANCE_SERIAL_RE.fullmatch("CAN-000201")
    assert match is not None
    assert match.groupdict() == {"prefix": "CAN", "serial": "000201"}

    parsed = parse_instance_serial("GLS-000301")
    assert parsed is not None
    assert parsed.prefix == "GLS"
    assert parsed.serial == "000301"

    assert parse_instance_serial("BAD-000101") is None
    assert parse_instance_serial("PET-12345") is None


def test_all_predefined_cards_produce_expected_decisions() -> None:
    """Sprawdza komplet 8 predefiniowanych kart testowych DEMO (`KZ-13`)."""
    cards = get_test_cards()
    assert len(cards) == 8

    returned_ids: set[str] = set()
    results = {
        card.card_id: evaluate_package_return(card.candidate, returned_ids)
        for card in cards
    }

    assert results["pet-water-1500-a"].status == DecisionStatus.ACCEPTED
    assert results["pet-water-1500-a"].deposit_grosze == PET_CAN_DEPOSIT_GROSZE
    assert results["pet-water-1500-b"].status == DecisionStatus.ACCEPTED
    assert results["can-cola-500"].status == DecisionStatus.ACCEPTED

    glass = results["glass-beer-500"]
    assert glass.status == DecisionStatus.REDIRECT_TO_CASHIER
    assert glass.deposit_grosze == 0
    assert glass.cashier_suggested_grosze == GLASS_CASHIER_DEPOSIT_GROSZE

    assert results["reject-no-logo"].reason_code == RejectionReason.MISSING_DEPOSIT_LOGO
    assert results["reject-crushed-can"].reason_code == RejectionReason.CRUSHED_OR_DAMAGED
    assert results["reject-dairy-carton"].reason_code == RejectionReason.EXCLUDED_CATEGORY
    assert results["reject-over-volume"].reason_code == RejectionReason.VOLUME_LIMIT_EXCEEDED

    with pytest.raises(PackageCardNotFoundError):
        get_test_card_by_id("unknown-card")


def test_same_ean_different_instance_ids_and_duplicate_rejection() -> None:
    """Potwierdza rozróżnianie EAN od ID sztuki oraz brak blokady dla przekierowanego szkła."""
    returned_ids: set[str] = set()
    first = get_test_card_by_id("pet-water-1500-a").candidate
    second = get_test_card_by_id("pet-water-1500-b").candidate

    decision_first = evaluate_package_return(first, returned_ids)
    assert decision_first.status == DecisionStatus.ACCEPTED
    assert decision_first.ean == "5900000000114"
    assert decision_first.instance_id == "PET-000101"
    returned_ids.add(decision_first.instance_id)

    decision_second = evaluate_package_return(second, returned_ids)
    assert decision_second.status == DecisionStatus.ACCEPTED
    assert decision_second.ean == "5900000000114"
    assert decision_second.instance_id == "PET-000102"

    duplicate = evaluate_package_return(first, returned_ids)
    assert duplicate.status == DecisionStatus.REJECTED
    assert duplicate.reason_code == RejectionReason.DUPLICATE_INSTANCE_ID
    assert duplicate.deposit_grosze == 0

    glass = get_test_card_by_id("glass-beer-500").candidate
    returned_ids.add("GLS-000301")
    glass_decision = evaluate_package_return(glass, returned_ids)
    assert glass_decision.status == DecisionStatus.REDIRECT_TO_CASHIER


def test_all_rejection_reasons_and_deterministic_priority() -> None:
    """Weryfikuje wszystkie 7 kodów odrzucenia oraz stały priorytet reguł walidatora."""
    invalid_format = PackageCandidate(
        package_code="PL-KAUCJA-5900000000119-PET-000101",
        title="Błędna suma EAN",
        category=PackageCategory.PET,
        volume_ml=1500,
        has_deposit_logo=False,
        is_crushed=True,
        is_empty=False,
    )
    assert (
        evaluate_package_return(invalid_format, {"PET-000101"}).reason_code
        == RejectionReason.INVALID_CODE_FORMAT
    )

    mismatched_prefix_dairy = PackageCandidate(
        package_code="PL-KAUCJA-5900000000114-PET-000199",
        title="Niespójny prefiks PET dla nabiału",
        category=PackageCategory.DAIRY_CARTON,
        volume_ml=1000,
        has_deposit_logo=True,
        is_crushed=False,
        is_empty=True,
    )
    assert (
        evaluate_package_return(mismatched_prefix_dairy, set()).reason_code
        == RejectionReason.INVALID_CODE_FORMAT
    )

    not_empty = PackageCandidate(
        package_code="PL-KAUCJA-5900000000114-PET-000777",
        title="Pełna butelka PET",
        category=PackageCategory.PET,
        volume_ml=500,
        has_deposit_logo=True,
        is_crushed=False,
        is_empty=False,
    )
    assert evaluate_package_return(not_empty, set()).reason_code == RejectionReason.NOT_EMPTY
    assert format_pln_from_grosze(50) == "0,50 zł"
    assert format_pln_from_grosze(100) == "1,00 zł"
