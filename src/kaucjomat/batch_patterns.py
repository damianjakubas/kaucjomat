"""Wzorce logów wsadowych, potok generatorów oraz iterator porcjujący rekordy DEMO."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
import re
from typing import Final

from kaucjomat.exceptions import BatchLogAnalysisError, InvalidConfigurationError
from kaucjomat.return_patterns import parse_package_code

# Prekompilowany wzorzec pojedynczej linii logu zwrotu z grupami nazwanymi.
BATCH_LOG_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"""
    ^
    (?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)
    \s\|\s
    (?P<machine_id>DEMO-M\d{2})
    \s\|\ssession=(?P<session_id>DEMO-[A-Z0-9]{8})
    \s\|\scode=(?P<package_code>[A-Z0-9-]+)
    \s\|\scat=(?P<category>PET|CAN|GLASS|DAIRY_CARTON|OTHER)
    \s\|\svol_ml=(?P<volume_ml>\d{1,5})
    \s\|\sstatus=(?P<status>ACCEPTED|REDIRECT_TO_CASHIER|REJECTED)
    \s\|\sreason=(?P<reason>[A-Z_]+|-)
    \s\|\sdeposit_gr=(?P<deposit_grosze>\d{1,4})
    \s\|\sglass_gr=(?P<cashier_grosze>\d{1,4})
    \s\|\slatency_ms=(?P<elapsed_ms>\d+\.\d{2})
    $
    """,
    re.VERBOSE,
)


@dataclass(frozen=True, slots=True)
class BatchLogRecord:
    """Pojedynczy zparsowany rekord zdarzenia zwrotu opakowania w logu wsadowym."""

    timestamp_iso: str
    machine_id: str
    session_id: str
    package_code: str
    ean: str
    instance_id: str
    category: str
    volume_ml: int
    status: str
    reason_code: str | None
    deposit_grosze: int
    cashier_grosze: int
    elapsed_ms: float


@dataclass(frozen=True, slots=True)
class BatchLogFileStats:
    """Podsumowanie odczytu pojedynczego pliku logu wsadowego."""

    file_name: str
    valid_records: int
    invalid_lines: int


def parse_batch_log_line(raw_line: str) -> BatchLogRecord | None:
    """Parsuje pojedynczą linię logu wsadowego i weryfikuje strukturę kodu opakowania."""
    match = BATCH_LOG_LINE_RE.fullmatch(raw_line.strip())
    if match is None:
        return None

    package_code = match.group("package_code")
    parsed_code = parse_package_code(package_code)
    if parsed_code is None:
        return None

    status = match.group("status")
    raw_reason = match.group("reason")
    reason_code = None if raw_reason == "-" else raw_reason

    # Pilnujemy podstawowej spójności statusu decyzji i obecności powodu odrzucenia.
    if status == "REJECTED" and reason_code is None:
        return None
    if status != "REJECTED" and reason_code is not None:
        return None

    return BatchLogRecord(
        timestamp_iso=match.group("timestamp"),
        machine_id=match.group("machine_id"),
        session_id=match.group("session_id"),
        package_code=package_code,
        ean=parsed_code.ean,
        instance_id=parsed_code.instance_id,
        category=match.group("category"),
        volume_ml=int(match.group("volume_ml")),
        status=status,
        reason_code=reason_code,
        deposit_grosze=int(match.group("deposit_grosze")),
        cashier_grosze=int(match.group("cashier_grosze")),
        elapsed_ms=float(match.group("elapsed_ms")),
    )


def iter_raw_log_lines(file_path: Path) -> Iterator[str]:
    """Strumieniowo zwraca oczyszczone, niepuste i niekomentowane linie pliku logu."""
    try:
        with file_path.open("r", encoding="utf-8", errors="replace") as handle:
            stripped_lines = (line.strip() for line in handle)
            for line in stripped_lines:
                if line and not line.startswith("#"):
                    yield line
    except OSError as exc:
        raise BatchLogAnalysisError(
            f"Nie udało się odczytać pliku logu wsadowego: {file_path}"
        ) from exc


def stream_valid_log_records(
    file_path: Path,
    invalid_counter: list[int] | None = None,
) -> Iterator[BatchLogRecord]:
    """Tworzy leniwy potok generatorów zwracający poprawne rekordy i zliczający błędy."""
    for raw_line in iter_raw_log_lines(file_path):
        record = parse_batch_log_line(raw_line)
        if record is None:
            if invalid_counter:
                invalid_counter[0] += 1
            continue
        yield record


class BatchChunkIterator(Iterator[tuple[BatchLogRecord, ...]]):
    """Własny iterator grupujący strumień rekordów logów w stałe porcje (chunki)."""

    def __init__(
        self,
        records: Iterable[BatchLogRecord],
        chunk_size: int = 1000,
    ) -> None:
        """Inicjalizuje iterator porcjujący i waliduje dodatni rozmiar porcji."""
        if chunk_size <= 0:
            raise InvalidConfigurationError(
                "Rozmiar porcji (chunk_size) musi być liczbą dodatnią."
            )
        self._iterator = iter(records)
        self._chunk_size = chunk_size

    def __iter__(self) -> BatchChunkIterator:
        """Zwraca samego siebie zgodnie z protokołem iteratora Pythona."""
        return self

    def __next__(self) -> tuple[BatchLogRecord, ...]:
        """Pobiera kolejną porcję rekordów lub kończy iterację wyjątkiem StopIteration."""
        chunk = tuple(islice(self._iterator, self._chunk_size))
        if not chunk:
            raise StopIteration
        return chunk
