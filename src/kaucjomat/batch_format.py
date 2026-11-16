"""Formatowanie raportów tekstowych DEMO i JSON dla analizy wsadowej."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from kaucjomat.batch_generator import BatchDatasetSummary
from kaucjomat.config import get_project_root
from kaucjomat.return_domain import format_pln_from_grosze

if TYPE_CHECKING:
    from kaucjomat.batch_runner import BatchAnalysisReport
    from kaucjomat.gil_benchmark import GilBenchmarkReport


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
            f"Zwroty: przyjęte={m.accepted_count} ({format_pln_from_grosze(m.accepted_deposit_grosze)}) | "
            f"szkło do kasy={m.redirected_glass_count} "
            f"(sugerowane {format_pln_from_grosze(m.redirected_glass_grosze)}) | "
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


def _portable_path(path: Path | None) -> str | None:
    """Zwraca ścieżkę względną POSIX wewnątrz projektu lub pełną, gdy leży poza nim."""
    if path is None:
        return None
    try:
        return path.resolve().relative_to(get_project_root().resolve()).as_posix()
    except ValueError:
        return str(path)


def gil_benchmark_report_to_dict(report: GilBenchmarkReport) -> dict[str, Any]:
    """Konwertuje raport benchmarku GIL do słownika gotowego do serializacji JSON."""
    m = report.verified_metrics
    return {
        "mode_label": report.mode_label,
        "generated_at_iso": report.generated_at_iso,
        "log_dir": _portable_path(report.log_dir),
        "auto_generated": report.auto_generated,
        "environment": {
            "python_version": report.environment.python_version,
            "implementation": report.environment.implementation,
            "platform_summary": report.environment.platform_summary,
            "cpu_count": report.environment.cpu_count,
            "gil_enabled": report.environment.gil_enabled,
            "free_threading_build": report.environment.free_threading_build,
            "switch_interval_s": report.environment.switch_interval_s,
        },
        "dataset": {
            "files_processed": report.files_processed,
            "total_chunks": report.total_chunks,
            "valid_records": report.valid_records,
            "invalid_lines": report.invalid_lines,
            "chunk_size": report.chunk_size,
            "work_iterations": report.work_iterations,
            "io_elapsed_ms": report.io_elapsed_ms,
        },
        "benchmark_config": {
            "repeats": report.repeats,
            "workers": report.workers,
            "total_benchmark_elapsed_ms": report.total_benchmark_elapsed_ms,
            "fastest_strategy_id": report.fastest_strategy_id,
        },
        "strategies": [
            {
                "strategy_id": s.strategy_id,
                "strategy_label": s.strategy_label,
                "workers": s.workers,
                "repeats": s.repeats,
                "runs_ms": list(s.runs_ms),
                "median_ms": s.median_ms,
                "mean_ms": s.mean_ms,
                "min_ms": s.min_ms,
                "max_ms": s.max_ms,
                "speedup_vs_sequential": s.speedup_vs_sequential,
                "relative_to_sequential_pct": s.relative_to_sequential_pct,
            }
            for s in report.strategies
        ],
        "verified_metrics": {
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
        "single_core_warning": report.single_core_warning,
        "conclusions": list(report.conclusions),
        "artifacts": {
            "json_path": _portable_path(report.json_artifact_path),
            "chart_png_path": _portable_path(report.chart_artifact_path),
        },
    }


def format_gil_benchmark_report(report: GilBenchmarkReport) -> str:
    """Formatuje czytelny polski raport porównawczego benchmarku GIL w trybie DEMO."""
    env = report.environment
    gil_state = "aktywny" if env.gil_enabled else "wyłączony (free-threading)"
    lines = [
        f"KaucjaSim {report.mode_label} — benchmark GIL (sekwencyjnie vs wątki vs procesy)",
        f"Python: {env.implementation} {env.python_version} | System: {env.platform_summary}",
        (
            f"Rdzenie CPU: {env.cpu_count} | GIL: {gil_state} | "
            f"Interwał przełączania: {env.switch_interval_s:.4f} s"
        ),
        (
            f"Dane: rekordy={report.valid_records} | porcje={report.total_chunks} "
            f"(po {report.chunk_size}) | rundy FNV-1a={report.work_iterations} | "
            f"powtórzenia={report.repeats} | pracownicy={report.workers}"
        ),
        f"Etap 1 (I/O): {report.io_elapsed_ms:.3f} ms | Czas całego pomiaru: {report.total_benchmark_elapsed_ms:.3f} ms",
        "",
        f"{'Strategia':<30} {'Mediana ms':>11} {'Średnia ms':>11} {'Min ms':>9} {'Max ms':>9} {'Speedup':>8}",
    ]
    for s in report.strategies:
        lines.append(
            f"{s.strategy_label:<30} {s.median_ms:>11.1f} {s.mean_ms:>11.1f} "
            f"{s.min_ms:>9.1f} {s.max_ms:>9.1f} {s.speedup_vs_sequential:>7.2f}x"
        )
    lines.append("")
    lines.append(f"Najszybsza strategia: {report.fastest_strategy_id}")
    lines.append(f"Suma kontrolna audytu (identyczna we wszystkich strategiach): {hex(report.verified_metrics.audit_checksum)}")
    lines.append("Wnioski:")
    lines.extend(f"  - {item}" for item in report.conclusions)
    if report.json_artifact_path is not None:
        lines.append(f"Raport JSON: {report.json_artifact_path}")
    if report.chart_artifact_path is not None:
        lines.append(f"Wykres PNG: {report.chart_artifact_path}")
    return "\n".join(lines)
