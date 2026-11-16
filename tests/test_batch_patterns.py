"""Testy jednostkowe wzorca logu wsadowego, generatorów, iteratora i generatora plików."""

from __future__ import annotations

from pathlib import Path

import pytest

from kaucjomat.batch_generator import format_batch_log_line, generate_batch_log_dataset
from kaucjomat.batch_patterns import (
    BATCH_LOG_LINE_RE,
    BatchChunkIterator,
    BatchLogRecord,
    iter_raw_log_lines,
    parse_batch_log_line,
    stream_valid_log_records,
)
from kaucjomat.exceptions import InvalidConfigurationError


def _make_sample_record(serial_num: int = 101) -> BatchLogRecord:
    """Tworzy przykładowy rekord logu wsadowego na potrzeby testów iteratora."""
    serial_str = f"{serial_num:06d}"
    return BatchLogRecord(
        timestamp_iso="2026-11-16T10:15:03Z",
        machine_id="DEMO-M01",
        session_id="DEMO-A1B2C3D4",
        package_code=f"PL-KAUCJA-5901234567893-PET-{serial_str}",
        ean="5901234567893",
        instance_id=f"PET-{serial_str}",
        category="PET",
        volume_ml=500,
        status="ACCEPTED",
        reason_code=None,
        deposit_grosze=50,
        cashier_grosze=0,
        elapsed_ms=12.40,
    )


def test_batch_log_line_regex_and_parser_extract_named_groups() -> None:
    """Weryfikuje grupy nazwane BATCH_LOG_LINE_RE oraz poprawne parsowanie rekordu."""
    raw_line = format_batch_log_line(
        timestamp_iso="2026-11-16T10:15:03Z",
        machine_id="DEMO-M01",
        session_id="DEMO-A1B2C3D4",
        package_code="PL-KAUCJA-5901234567893-PET-000101",
        category="PET",
        volume_ml=500,
        status="ACCEPTED",
        reason_code=None,
        deposit_grosze=50,
        cashier_grosze=0,
        elapsed_ms=12.40,
    )

    match = BATCH_LOG_LINE_RE.fullmatch(raw_line)
    assert match is not None
    assert match.group("machine_id") == "DEMO-M01"
    assert match.group("session_id") == "DEMO-A1B2C3D4"
    assert match.group("status") == "ACCEPTED"

    record = parse_batch_log_line(raw_line)
    assert record is not None
    assert record.ean == "5901234567893"
    assert record.instance_id == "PET-000101"
    assert record.deposit_grosze == 50
    assert record.reason_code is None


def test_parse_batch_log_line_rejects_corrupted_and_inconsistent_lines() -> None:
    """Sprawdza, że uszkodzone lub niespójne linie zwracają None bez wyjątku."""
    assert parse_batch_log_line("CORRUPTED | LINE") is None
    assert parse_batch_log_line("") is None
    # Błędny prefix kodu (brak PL-KAUCJA/BEZLOGO) powinien zostać odrzucony przez parse_package_code.
    bad_code_line = format_batch_log_line(
        timestamp_iso="2026-11-16T10:15:03Z",
        machine_id="DEMO-M01",
        session_id="DEMO-A1B2C3D4",
        package_code="DE-KAUCJA-5901234567893-PET-000101",
        category="PET",
        volume_ml=500,
        status="ACCEPTED",
        reason_code=None,
        deposit_grosze=50,
        cashier_grosze=0,
        elapsed_ms=12.40,
    )
    assert parse_batch_log_line(bad_code_line) is None


def test_generator_pipeline_skips_comments_and_counts_invalid_lines(tmp_path: Path) -> None:
    """Testuje leniwe strumieniowanie generatorów oraz zliczanie uszkodzonych wierszy."""
    log_file = tmp_path / "sample.log"
    valid_one = format_batch_log_line(
        timestamp_iso="2026-11-16T10:15:03Z",
        machine_id="DEMO-M01",
        session_id="DEMO-00000001",
        package_code="PL-KAUCJA-5901234567893-CAN-000001",
        category="CAN",
        volume_ml=330,
        status="ACCEPTED",
        reason_code=None,
        deposit_grosze=50,
        cashier_grosze=0,
        elapsed_ms=11.10,
    )
    valid_two = format_batch_log_line(
        timestamp_iso="2026-11-16T10:15:04Z",
        machine_id="DEMO-M02",
        session_id="DEMO-00000002",
        package_code="PL-KAUCJA-5901234567890-PET-000002",
        category="PET",
        volume_ml=500,
        status="REJECTED",
        reason_code="INVALID_CODE_FORMAT",
        deposit_grosze=0,
        cashier_grosze=0,
        elapsed_ms=9.50,
    )
    log_file.write_text(
        "\n".join(
            [
                "# KaucjaSim DEMO komentarz",
                "",
                valid_one,
                "USZKODZONA_LINIA_TESTOWA",
                valid_two,
                "   ",
            ]
        ),
        encoding="utf-8",
    )

    raw_lines = list(iter_raw_log_lines(log_file))
    assert len(raw_lines) == 3

    invalid_counter = [0]
    records = list(stream_valid_log_records(log_file, invalid_counter=invalid_counter))
    assert len(records) == 2
    assert invalid_counter == [1]
    assert records[1].reason_code == "INVALID_CODE_FORMAT"


def test_batch_chunk_iterator_protocol_and_exhaustion() -> None:
    """Weryfikuje __iter__, next(), niepełną ostatnią porcję i StopIteration."""
    records = [_make_sample_record(idx) for idx in range(5)]
    iterator = BatchChunkIterator(records, chunk_size=2)

    assert iter(iterator) is iterator
    first = next(iterator)
    second = next(iterator)
    third = next(iterator)

    assert len(first) == 2
    assert len(second) == 2
    assert len(third) == 1
    assert third[0].instance_id == "PET-000004"

    with pytest.raises(StopIteration):
        next(iterator)
    # Wyczerpany iterator pozostaje pusty przy kolejnych próbach pętli for.
    assert list(iterator) == []

    with pytest.raises(InvalidConfigurationError):
        BatchChunkIterator(records, chunk_size=0)


def test_generate_batch_log_dataset_is_deterministic_and_cleans_stale_files(
    tmp_path: Path,
) -> None:
    """Sprawdza powtarzalność zbioru dla seeda oraz usuwanie starych plików logów."""
    stale_file = tmp_path / "batch_returns_999.log"
    stale_file.write_text("stary wpis", encoding="utf-8")

    summary_a = generate_batch_log_dataset(
        tmp_path,
        file_count=2,
        records_per_file=150,
        invalid_ratio=0.05,
        seed=42,
    )
    assert not stale_file.exists()
    assert summary_a.file_names == ("batch_returns_001.log", "batch_returns_002.log")
    assert summary_a.total_lines == 300
    assert summary_a.expected_valid_records + summary_a.expected_invalid_lines == 300

    first_file = tmp_path / "batch_returns_001.log"
    first_content = first_file.read_text(encoding="utf-8")
    assert "# KaucjaSim DEMO" in first_content
    assert "session=DEMO-" in first_content
    assert "code=PL-" in first_content

    summary_b = generate_batch_log_dataset(
        tmp_path,
        file_count=2,
        records_per_file=150,
        invalid_ratio=0.05,
        seed=42,
    )
    assert summary_b.expected_valid_records == summary_a.expected_valid_records
    assert summary_b.expected_invalid_lines == summary_a.expected_invalid_lines
    assert first_file.read_text(encoding="utf-8") == first_content

    # Weryfikacja, że strumień odczyta dokładnie expected_valid_records i expected_invalid_lines.
    invalid_counter = [0]
    parsed_count = 0
    for name in summary_a.file_names:
        parsed_count += sum(
            1
            for _ in stream_valid_log_records(
                tmp_path / name,
                invalid_counter=invalid_counter,
            )
        )
    assert parsed_count == summary_a.expected_valid_records
    assert invalid_counter[0] == summary_a.expected_invalid_lines
