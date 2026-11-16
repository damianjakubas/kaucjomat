"""Deterministyczne obliczenia CPU-bound w czystym Pythonie dla analizy wsadowej."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from kaucjomat.batch_patterns import BatchLogRecord
from kaucjomat.exceptions import InvalidConfigurationError

_MASK_64 = 0xFFFFFFFFFFFFFFFF
_FNV_OFFSET_BASIS = 0xCBF29CE484222325
_FNV_PRIME = 0x100000001B3
_ANOMALOUS_LATENCY_MS = 150.0


@dataclass(frozen=True, slots=True)
class ChunkAnalysisResult:
    """Zagregowany wynik analizy pojedynczej porcji lub złączonych porcji logów."""

    processed_records: int
    accepted_count: int
    redirected_glass_count: int
    rejected_count: int
    accepted_deposit_grosze: int
    redirected_glass_grosze: int
    category_counts: tuple[tuple[str, int], ...]
    rejection_reason_counts: tuple[tuple[str, int], ...]
    anomalous_latency_count: int
    audit_checksum: int


def _validate_work_iterations(work_iterations: int) -> None:
    """Sprawdza, czy liczba rund obliczeniowych CPU jest dodatnią liczbą całkowitą."""
    if work_iterations <= 0:
        raise InvalidConfigurationError(
            "Liczba rund obliczeń CPU (work_iterations) musi być większa od zera."
        )


def compute_record_audit_signature(
    record: BatchLogRecord,
    work_iterations: int = 200,
) -> int:
    """Wylicza 64-bitową sygnaturę kontrolną rekordu w czystym Pythonie (CPU-bound)."""
    _validate_work_iterations(work_iterations)

    # Przygotowanie wartości wejściowych z pól tekstowych i liczbowych rekordu.
    payload_bytes = (
        f"{record.package_code}|{record.session_id}|{record.timestamp_iso}"
    ).encode("utf-8")
    numeric_salt = (
        (record.volume_ml * 1315423911)
        ^ (record.deposit_grosze * 2654435761)
        ^ (record.cashier_grosze * 97531)
    ) & _MASK_64

    signature = _FNV_OFFSET_BASIS ^ numeric_salt
    # Wielorundowa pętla FNV-1a + mieszanie bitowe celowo obciąża interpreter (GIL).
    for round_idx in range(work_iterations):
        acc = (signature ^ (round_idx + 1)) & _MASK_64
        for byte_val in payload_bytes:
            acc = ((acc ^ byte_val) * _FNV_PRIME) & _MASK_64
        acc ^= (acc >> 33) ^ ((numeric_salt + round_idx) & _MASK_64)
        signature = (acc * 0xFF51AFD7ED558CCD) & _MASK_64

    return signature


def analyze_record_chunk(
    chunk: tuple[BatchLogRecord, ...],
    work_iterations: int = 200,
) -> ChunkAnalysisResult:
    """Analizuje porcję rekordów zwrotu i zwraca deterministyczne metryki oraz sumę kontrolną."""
    _validate_work_iterations(work_iterations)

    accepted_count = 0
    redirected_glass_count = 0
    rejected_count = 0
    accepted_deposit_grosze = 0
    redirected_glass_grosze = 0
    anomalous_latency_count = 0
    audit_checksum = 0
    category_counter: Counter[str] = Counter()
    reason_counter: Counter[str] = Counter()

    for record in chunk:
        category_counter[record.category] += 1
        if record.status == "ACCEPTED":
            accepted_count += 1
            accepted_deposit_grosze += record.deposit_grosze
        elif record.status == "REDIRECT_TO_CASHIER":
            redirected_glass_count += 1
            redirected_glass_grosze += record.cashier_grosze
        elif record.status == "REJECTED":
            rejected_count += 1
            if record.reason_code is not None:
                reason_counter[record.reason_code] += 1

        if record.elapsed_ms > _ANOMALOUS_LATENCY_MS:
            anomalous_latency_count += 1

        signature = compute_record_audit_signature(record, work_iterations=work_iterations)
        audit_checksum = (audit_checksum + signature) & _MASK_64

    return ChunkAnalysisResult(
        processed_records=len(chunk),
        accepted_count=accepted_count,
        redirected_glass_count=redirected_glass_count,
        rejected_count=rejected_count,
        accepted_deposit_grosze=accepted_deposit_grosze,
        redirected_glass_grosze=redirected_glass_grosze,
        category_counts=tuple(sorted(category_counter.items())),
        rejection_reason_counts=tuple(sorted(reason_counter.items())),
        anomalous_latency_count=anomalous_latency_count,
        audit_checksum=audit_checksum,
    )


def merge_chunk_results(results: Iterable[ChunkAnalysisResult]) -> ChunkAnalysisResult:
    """Łączy wyniki cząstkowe z wielu porcji niezależnie od kolejności ich zakończenia."""
    processed_records = 0
    accepted_count = 0
    redirected_glass_count = 0
    rejected_count = 0
    accepted_deposit_grosze = 0
    redirected_glass_grosze = 0
    anomalous_latency_count = 0
    audit_checksum = 0
    category_counter: Counter[str] = Counter()
    reason_counter: Counter[str] = Counter()

    for item in results:
        processed_records += item.processed_records
        accepted_count += item.accepted_count
        redirected_glass_count += item.redirected_glass_count
        rejected_count += item.rejected_count
        accepted_deposit_grosze += item.accepted_deposit_grosze
        redirected_glass_grosze += item.redirected_glass_grosze
        anomalous_latency_count += item.anomalous_latency_count
        # Dodawanie modularne jest przemienne, więc wynik nie zależy od kolejności procesów.
        audit_checksum = (audit_checksum + item.audit_checksum) & _MASK_64
        for cat, count in item.category_counts:
            category_counter[cat] += count
        for reason, count in item.rejection_reason_counts:
            reason_counter[reason] += count

    return ChunkAnalysisResult(
        processed_records=processed_records,
        accepted_count=accepted_count,
        redirected_glass_count=redirected_glass_count,
        rejected_count=rejected_count,
        accepted_deposit_grosze=accepted_deposit_grosze,
        redirected_glass_grosze=redirected_glass_grosze,
        category_counts=tuple(sorted(category_counter.items())),
        rejection_reason_counts=tuple(sorted(reason_counter.items())),
        anomalous_latency_count=anomalous_latency_count,
        audit_checksum=audit_checksum,
    )
