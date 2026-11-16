"""Formatowanie raportów tekstowych DEMO i JSON dla analizy wsadowej."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from kaucjomat.batch_generator import BatchDatasetSummary

if TYPE_CHECKING:
    from kaucjomat.batch_runner import BatchAnalysisReport


def _format_pln(grosze: int) -> str:
    """Formatuje kwotę w groszach do czytelnej postaci PLN z przecinkiem."""
    return f"{grosze / 100:.2f} zł".replace(".", ",")


def format_batch_generation_report(summary: BatchDatasetSummary) -> str:
    """Formatuje czytelny polski raport wygenerowanego zbioru logów DEMO."""
    lines = [
        "KaucjaSim DEMO — wygenerowano zbiór logów wsadowych",
        f"Katalog: {summary.log_dir}",
        (
            f"Pliki: {summary.file_count} | Linie: {summary.total_lines} | "
            f"Poprawne rekordy: {summary.expected_valid_records} | "
            f"Błędne linie: {summary.expected_invalid_lines}"
        ),
        f"Ziarno (seed): {summary.seed} | Czas: {summary.elapsed_ms:.3f} ms",
    ]
    return "\n".join(lines)


def format_batch_analysis_report(report: BatchAnalysisReport) -> str:
    """Formatuje czytelny polski raport dwuetapowej analizy wsadowej DEMO."""
    s1 = report.stage_one_io
    s2 = report.stage_two_cpu
    m = s2.metrics
    lines = [
        f"KaucjaSim {report.mode_label} — dwuetapowa analiza logów wsadowych",
        (
            f"Katalog: {report.log_dir} | Wykryte rdzenie CPU: {report.cpu_count} | "
            f"Auto-generowanie: {'TAK' if report.auto_generated else 'NIE'}"
        ),
        (
            f"Etap 1 (I/O - wątki): {s1.io_elapsed_ms:.3f} ms | wątki={s1.io_workers} | "
            f"pliki={s1.files_processed} | porcje={s1.total_chunks} | "
            f"poprawne={s1.valid_records} | błędne={s1.invalid_lines}"
        ),
        (
            f"Etap 2 (CPU - procesy spawn): {s2.cpu_elapsed_ms:.3f} ms | "
            f"procesy={s2.cpu_workers} | rundy={s2.work_iterations} | "
            f"czas całkowity={report.total_elapsed_ms:.3f} ms"
        ),
        (
            f"Zwroty: przyjęte={m.accepted_count} ({_format_pln(m.accepted_deposit_grosze)}) | "
            f"szkło do kasy={m.redirected_glass_count} "
            f"(sugerowane {_format_pln(m.redirected_glass_grosze)}) | "
            f"odrzucone={m.rejected_count} | anomalie >150ms={m.anomalous_latency_count}"
        ),
        f"Suma kontrolna audytu: {hex(m.audit_checksum)}",
    ]
    return "\n".join(lines)


def batch_report_to_dict(report: BatchAnalysisReport) -> dict[str, Any]:
    """Konwertuje raport analizy wsadowej do słownika gotowego do serializacji JSON."""
    s1 = report.stage_one_io
    s2 = report.stage_two_cpu
    m = s2.metrics
    return {
        "mode_label": report.mode_label,
        "cpu_count": report.cpu_count,
        "log_dir": str(report.log_dir),
        "auto_generated": report.auto_generated,
        "total_elapsed_ms": report.total_elapsed_ms,
        "stage_one_io": {
            "files_processed": s1.files_processed,
            "total_chunks": s1.total_chunks,
            "valid_records": s1.valid_records,
            "invalid_lines": s1.invalid_lines,
            "io_workers": s1.io_workers,
            "io_elapsed_ms": s1.io_elapsed_ms,
            "file_stats": [
                {
                    "file_name": fs.file_name,
                    "valid_records": fs.valid_records,
                    "invalid_lines": fs.invalid_lines,
                }
                for fs in s1.file_stats
            ],
        },
        "stage_two_cpu": {
            "execution_mode": s2.execution_mode,
            "cpu_workers": s2.cpu_workers,
            "work_iterations": s2.work_iterations,
            "cpu_elapsed_ms": s2.cpu_elapsed_ms,
            "metrics": {
                "processed_records": m.processed_records,
                "accepted_count": m.accepted_count,
                "redirected_glass_count": m.redirected_glass_count,
                "rejected_count": m.rejected_count,
                "accepted_deposit_grosze": m.accepted_deposit_grosze,
                "redirected_glass_grosze": m.redirected_glass_grosze,
                "category_counts": dict(m.category_counts),
                "rejection_reason_counts": dict(m.rejection_reason_counts),
                "anomalous_latency_count": m.anomalous_latency_count,
                "audit_checksum": m.audit_checksum,
                "audit_checksum_hex": hex(m.audit_checksum),
            },
        },
    }
