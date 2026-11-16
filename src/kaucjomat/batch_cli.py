"""Obsługa podkomend CLI ``generate-logs`` i ``analyze-logs`` dla analizy wsadowej DEMO."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from kaucjomat.batch_format import (
    batch_report_to_dict,
    format_batch_analysis_report,
    format_batch_generation_report,
)
from kaucjomat.batch_generator import generate_batch_log_dataset
from kaucjomat.batch_runner import run_two_stage_batch_analysis
from kaucjomat.exceptions import BatchLogAnalysisError


def register_batch_subparsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Rejestruje podkomendy ``generate-logs`` i ``analyze-logs`` w parserze CLI."""
    gen_parser = subparsers.add_parser(
        "generate-logs",
        help="Generuje syntetyczny zbiór logów kaucjomatów DEMO.",
        description=(
            "Tworzy deterministyczny zestaw plików .log z poprawnymi rekordami "
            "oraz kontrolowanym odsetkiem uszkodzonych linii (TRYB DEMO)."
        ),
    )
    gen_parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="Docelowy katalog na pliki .log (domyślnie data/generated/logs).",
    )
    gen_parser.add_argument(
        "--files",
        type=int,
        default=8,
        help="Liczba plików .log do wygenerowania (domyślnie 8).",
    )
    gen_parser.add_argument(
        "--records-per-file",
        type=int,
        default=5000,
        help="Liczba linii w pojedynczym pliku .log (domyślnie 5000).",
    )
    gen_parser.add_argument(
        "--invalid-ratio",
        type=float,
        default=0.01,
        help="Odsetek uszkodzonych linii z przedziału [0.0, 1.0) (domyślnie 0.01).",
    )
    gen_parser.add_argument(
        "--seed",
        type=int,
        default=2026,
        help="Ziarno generatora losowego dla powtarzalności wyników (domyślnie 2026).",
    )
    gen_parser.add_argument(
        "--json",
        action="store_true",
        help="Wypisuje podsumowanie generowania w formacie JSON.",
    )

    analyze_parser = subparsers.add_parser(
        "analyze-logs",
        help="Uruchamia dwuetapową analizę wsadową logów (wątki I/O + procesy CPU).",
        description=(
            "Wczytuje pliki .log wielowątkowo i agreguje metryki wieloprocesowo "
            "w trybie spawn (TRYB DEMO)."
        ),
    )
    analyze_parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="Katalog z plikami .log do analizy (domyślnie data/generated/logs).",
    )
    analyze_parser.add_argument(
        "--chunk-size",
        type=int,
        default=1000,
        help="Maksymalna liczba rekordów w jednej paczce CPU (domyślnie 1000).",
    )
    analyze_parser.add_argument(
        "--io-workers",
        type=int,
        default=None,
        help="Liczba wątków w etapie I/O (domyślnie dobierana automatycznie).",
    )
    analyze_parser.add_argument(
        "--cpu-workers",
        type=int,
        default=None,
        help="Liczba procesów roboczych w etapie CPU (domyślnie os.cpu_count()).",
    )
    analyze_parser.add_argument(
        "--work-iterations",
        type=int,
        default=200,
        help="Liczba iteracji czysto pythonowego hashowania FNV-1a na rekord (domyślnie 200).",
    )
    analyze_parser.add_argument(
        "--no-auto-generate",
        action="store_true",
        help="Wyłącza automatyczne generowanie logów DEMO, gdy katalog jest pusty.",
    )
    analyze_parser.add_argument(
        "--json",
        action="store_true",
        help="Wypisuje pełny raport analizy w formacie JSON.",
    )


def execute_batch_cli_command(args: argparse.Namespace) -> int:
    """Wykonuje podkomendę ``generate-logs`` lub ``analyze-logs`` i zwraca kod wyjścia."""
    if args.command == "generate-logs":
        summary = generate_batch_log_dataset(
            args.log_dir,
            file_count=args.files,
            records_per_file=args.records_per_file,
            invalid_ratio=args.invalid_ratio,
            seed=args.seed,
        )
        if args.json:
            payload = asdict(summary)
            payload["log_dir"] = str(summary.log_dir)
            payload["mode_label"] = "DEMO"
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(format_batch_generation_report(summary))
        return 0

    if args.command == "analyze-logs":
        report = run_two_stage_batch_analysis(
            args.log_dir,
            chunk_size=args.chunk_size,
            io_workers=args.io_workers,
            cpu_workers=args.cpu_workers,
            work_iterations=args.work_iterations,
            auto_generate=not args.no_auto_generate,
        )
        if args.json:
            print(json.dumps(batch_report_to_dict(report), ensure_ascii=False, indent=2))
        else:
            print(format_batch_analysis_report(report))
        return 0

    raise BatchLogAnalysisError(
        f"Nieobsługiwana podkomenda analizy wsadowej: {args.command}."
    )
