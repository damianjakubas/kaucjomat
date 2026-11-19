"""Prekompilowane wyrażenia regularne i parsery kodów kaucyjnych."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final

# Pierwszy wzorzec z grupami nazwanymi: rozbiór pełnego kodu etykiety kaucyjnej DEMO.
PACKAGE_CODE_RE: Final[re.Pattern[str]] = re.compile(
    r"""
    ^
    (?P<country>PL)
    -
    (?P<deposit_mark>KAUCJA|BEZLOGO)
    -
    (?P<ean>\d{13})
    -
    (?P<instance_id>[A-Z]{3}-\d{6})
    $
    """,
    re.VERBOSE,
)

# Drugi niezależny wzorzec z grupami nazwanymi: walidacja i rozbiór ID egzemplarza.
INSTANCE_SERIAL_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<prefix>PET|CAN|GLS|OTH)-(?P<serial>\d{6})$"
)


@dataclass(frozen=True, slots=True)
class ParsedPackageCode:
    """Wynik rozbioru pełnego kodu opakowania kaucyjnego za pomocą `PACKAGE_CODE_RE`."""

    country: str
    deposit_mark: str
    ean: str
    instance_id: str


@dataclass(frozen=True, slots=True)
class ParsedInstanceSerial:
    """Wynik rozbioru identyfikatora pojedynczego egzemplarza przez `INSTANCE_SERIAL_RE`."""

    prefix: str
    serial: str


def parse_package_code(raw_code: str) -> ParsedPackageCode | None:
    """Rozbiera kod opakowania na grupy nazwane albo zwraca `None` przy błędnym formacie."""
    match = PACKAGE_CODE_RE.fullmatch(raw_code.strip())
    if match is None:
        return None
    groups = match.groupdict()
    return ParsedPackageCode(
        country=groups["country"],
        deposit_mark=groups["deposit_mark"],
        ean=groups["ean"],
        instance_id=groups["instance_id"],
    )


def parse_instance_serial(instance_id: str) -> ParsedInstanceSerial | None:
    """Rozbiera identyfikator egzemplarza na prefiks materiałowy i sześciocyfrowy numer."""
    match = INSTANCE_SERIAL_RE.fullmatch(instance_id.strip())
    if match is None:
        return None
    groups = match.groupdict()
    return ParsedInstanceSerial(
        prefix=groups["prefix"],
        serial=groups["serial"],
    )


def is_valid_ean13_checksum(ean: str) -> bool:
    """Weryfikuje standardową cyfrę kontrolną GS1 EAN-13 dla ciągu 13 cyfr."""
    if len(ean) != 13 or not ean.isdigit():
        return False

    # Wagi GS1 dla 12 pierwszych cyfr: 1 dla pozycji parzystych, 3 dla nieparzystych (od 0).
    weighted_sum = sum(
        int(digit) * (1 if index % 2 == 0 else 3)
        for index, digit in enumerate(ean[:12])
    )
    expected_check_digit = (10 - (weighted_sum % 10)) % 10
    return int(ean[12]) == expected_check_digit
