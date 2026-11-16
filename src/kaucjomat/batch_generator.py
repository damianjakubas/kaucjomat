"""Deterministyczny generator wieloplikowego zbioru logów zwrotów DEMO."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import random
from time import perf_counter
from typing import Final

from kaucjomat.config import get_default_log_dir
from kaucjomat.exceptions import BatchLogAnalysisError, InvalidConfigurationError
from kaucjomat.logging_config import get_logger
from kaucjomat.return_domain import (
    CATEGORY_SERIAL_PREFIXES,
    DecisionStatus,
    PackageCategory,
    RejectionReason,
)

# Stała lista wszystkich powodów odrzucenia do równomiernego pokrycia w danych DEMO.
_REJECTION_REASONS: Final[tuple[RejectionReason, ...]] = tuple(RejectionReason)
# Bazowy znacznik czasu startu generowanych zdarzeń wsadowych.
_BASE_TIMESTAMP: Final[datetime] = datetime(2026, 11, 16, 8, 0, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class BatchDatasetSummary:
    """Podsumowanie wygenerowanego wieloplikowego zbioru logów wsadowych DEMO."""

    log_dir: Path
    file_names: tuple[str, ...]
    file_count: int
    records_per_file: int
    total_lines: int
    expected_valid_records: int
    expected_invalid_lines: int
    seed: int
    elapsed_ms: float


def _compute_ean13_check_digit(prefix_12: str) -> str:
    """Oblicza poprawną 13. cyfrę kontrolną kodu EAN-13 dla 12-cyfrowego prefiksu."""
    weighted_sum = sum(
        int(char) * (1 if index % 2 == 0 else 3)
        for index, char in enumerate(prefix_12)
    )
    return str((10 - (weighted_sum % 10)) % 10)


def _build_ean13(prefix_12: str, *, valid_checksum: bool) -> str:
    """Buduje 13-cyfrowy kod EAN-13 z poprawną lub celowo błędną cyfrą kontrolną."""
    check_digit = _compute_ean13_check_digit(prefix_12)
    if valid_checksum:
        return f"{prefix_12}{check_digit}"
    wrong_digit = str((int(check_digit) + 1) % 10)
    return f"{prefix_12}{wrong_digit}"


def format_batch_log_line(
    *,
    timestamp_iso: str,
    machine_id: str,
    session_id: str,
    package_code: str,
    category: str,
    volume_ml: int,
    status: str,
    reason_code: str | None,
    deposit_grosze: int,
    cashier_grosze: int,
    elapsed_ms: float,
) -> str:
    """Formatuje pojedynczy poprawny wiersz logu wsadowego zgodny z BATCH_LOG_LINE_RE."""
    reason_field = "-" if reason_code is None else reason_code
    return (
        f"{timestamp_iso} | {machine_id} | session={session_id} | "
        f"code={package_code} | cat={category} | vol_ml={volume_ml} | "
        f"status={status} | reason={reason_field} | "
        f"deposit_gr={deposit_grosze} | glass_gr={cashier_grosze} | "
        f"latency_ms={elapsed_ms:.2f}"
    )


def _build_valid_log_line(
    rng: random.Random,
    file_index: int,
    row_index: int,
) -> str:
    """Tworzy deterministyczny, poprawny składniowo wiersz zwrotu z pełnym przekrojem domeny."""
    timestamp_iso = (
        _BASE_TIMESTAMP + timedelta(seconds=file_index * 10_000 + row_index)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    machine_id = f"DEMO-M{1 + (row_index % 4):02d}"
    session_id = f"DEMO-{(file_index * 100_000 + row_index):08X}"

    prefix_12 = f"590{(file_index * 1_000_000 + row_index) % 1_000_000_000:09d}"
    serial_num = f"{(file_index * 100_000 + row_index) % 1_000_000:06d}"

    roll = rng.random()
    if roll < 0.62:
        category = PackageCategory.PET if row_index % 2 == 0 else PackageCategory.CAN
        volume_ml = 500 if category == PackageCategory.PET else 330
        deposit_mark = "KAUCJA"
        ean = _build_ean13(prefix_12, valid_checksum=True)
        status = DecisionStatus.ACCEPTED.value
        reason_code: str | None = None
        deposit_grosze = 50
        cashier_grosze = 0
    elif roll < 0.78:
        category = PackageCategory.GLASS
        volume_ml = 500
        deposit_mark = "KAUCJA"
        ean = _build_ean13(prefix_12, valid_checksum=True)
        status = DecisionStatus.REDIRECT_TO_CASHIER.value
        reason_code = None
        deposit_grosze = 0
        cashier_grosze = 100
    else:
        reason = _REJECTION_REASONS[row_index % len(_REJECTION_REASONS)]
        reason_code = reason.value
        status = DecisionStatus.REJECTED.value
        deposit_grosze = 0
        cashier_grosze = 0
        category = _pick_rejected_category(reason, row_index)
        volume_ml = 3500 if reason == RejectionReason.VOLUME_LIMIT_EXCEEDED else 500
        deposit_mark = (
            "BEZLOGO" if reason == RejectionReason.MISSING_DEPOSIT_LOGO else "KAUCJA"
        )
        # Dla INVALID_CODE_FORMAT zachowujemy składnię PACKAGE_CODE_RE, psując cyfrę EAN-13.
        valid_ean = reason != RejectionReason.INVALID_CODE_FORMAT
        ean = _build_ean13(prefix_12, valid_checksum=valid_ean)

    prefix = CATEGORY_SERIAL_PREFIXES[category]
    package_code = f"PL-{deposit_mark}-{ean}-{prefix}-{serial_num}"
    # Część opóźnień przekracza 150 ms, aby testować licznik anomalii czasowych.
    elapsed_ms = 185.40 if row_index % 29 == 0 else round(rng.uniform(8.0, 65.0), 2)

    return format_batch_log_line(
        timestamp_iso=timestamp_iso,
        machine_id=machine_id,
        session_id=session_id,
        package_code=package_code,
        category=category.value,
        volume_ml=volume_ml,
        status=status,
        reason_code=reason_code,
        deposit_grosze=deposit_grosze,
        cashier_grosze=cashier_grosze,
        elapsed_ms=elapsed_ms,
    )


def _pick_rejected_category(reason: RejectionReason, row_index: int) -> PackageCategory:
    """Dobiera kategorię opakowania spójną z powodem odrzucenia."""
    if reason == RejectionReason.EXCLUDED_CATEGORY:
        return (
            PackageCategory.DAIRY_CARTON
            if row_index % 2 == 0
            else PackageCategory.OTHER
        )
    return PackageCategory.PET if row_index % 2 == 0 else PackageCategory.CAN


def _build_corrupted_log_line(file_index: int, row_index: int) -> str:
    """Tworzy celowo uszkodzoną linię logu do weryfikacji odporności parsera."""
    return (
        f"2026-11-16T08:00:00Z | CORRUPTED-LINE | file={file_index} | "
        f"row={row_index} | code=BAD_TOKEN"
    )


def generate_batch_log_dataset(
    log_dir: Path | None = None,
    *,
    file_count: int = 8,
    records_per_file: int = 5000,
    invalid_ratio: float = 0.01,
    seed: int = 2026,
) -> BatchDatasetSummary:
    """Generuje deterministyczny, wieloplikowy zbiór logów zwrotów DEMO w podanym katalogu."""
    if file_count < 1:
        raise InvalidConfigurationError("Liczba plików (file_count) musi wynosić >= 1.")
    if records_per_file < 1:
        raise InvalidConfigurationError(
            "Liczba wierszy na plik (records_per_file) musi wynosić >= 1."
        )
    if not (0.0 <= invalid_ratio < 1.0):
        raise InvalidConfigurationError(
            "Odsetek uszkodzonych linii (invalid_ratio) musi należeć do [0.0, 1.0)."
        )

    started_at = perf_counter()
    target_dir = get_default_log_dir() if log_dir is None else log_dir
    rng = random.Random(seed)
    logger = get_logger("kaucjomat.batch")

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        for stale_file in target_dir.glob("batch_returns_*.log"):
            if stale_file.is_file():
                stale_file.unlink()
    except OSError as exc:
        raise BatchLogAnalysisError(
            f"Nie udało się przygotować katalogu logów wsadowych: {target_dir}"
        ) from exc

    file_names: list[str] = []
    expected_valid = 0
    expected_invalid = 0

    for file_index in range(1, file_count + 1):
        file_name = f"batch_returns_{file_index:03d}.log"
        file_path = target_dir / file_name
        lines: list[str] = [
            f"# KaucjaSim DEMO - plik logow wsadowych ({file_name}, seed={seed})",
            "",
        ]
        for row_index in range(records_per_file):
            if rng.random() < invalid_ratio:
                lines.append(_build_corrupted_log_line(file_index, row_index))
                expected_invalid += 1
            else:
                lines.append(_build_valid_log_line(rng, file_index, row_index))
                expected_valid += 1

        try:
            file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as exc:
            raise BatchLogAnalysisError(
                f"Nie udało się zapisać pliku logów wsadowych: {file_path}"
            ) from exc
        file_names.append(file_name)

    elapsed_ms = round((perf_counter() - started_at) * 1000.0, 3)
    total_lines = file_count * records_per_file
    logger.info(
        "Wygenerowano zbiór logów wsadowych DEMO: %d plików, %d linii (%d poprawnych, %d uszkodzonych) w %.2f ms",
        file_count,
        total_lines,
        expected_valid,
        expected_invalid,
        elapsed_ms,
    )

    return BatchDatasetSummary(
        log_dir=target_dir,
        file_names=tuple(file_names),
        file_count=file_count,
        records_per_file=records_per_file,
        total_lines=total_lines,
        expected_valid_records=expected_valid,
        expected_invalid_lines=expected_invalid,
        seed=seed,
        elapsed_ms=elapsed_ms,
    )
