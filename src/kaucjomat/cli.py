"""Interfejs wiersza poleceń (CLI) dla symulatora KaucjaSim DEMO."""

from __future__ import annotations

import argparse
import importlib.util
import os
import platform
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from kaucjomat.batch_cli import (
    execute_batch_cli_command,
    register_batch_subparsers,
)
from kaucjomat.config import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_HOST,
    DEMO_LABEL,
    VIEWS,
    ViewDefinition,
    get_default_log_dir,
    get_static_dir,
    resolve_port,
)
from kaucjomat.exceptions import KaucjomatError
from kaucjomat.logging_config import configure_logging, get_logger


@dataclass(frozen=True, slots=True)
class RuntimeInfo:
    """Podsumowanie parametrów środowiska uruchomieniowego aplikacji."""

    app_name: str
    mode: str
    version: str
    python_version: str
    cpu_count: int
    static_dir: Path
    log_dir: Path
    views: tuple[ViewDefinition, ...]


def build_runtime_info() -> RuntimeInfo:
    """Zbiera aktualne dane o środowisku Pythona, liczbie rdzeni i ścieżkach."""
    detected_cpus = os.cpu_count() or 1
    return RuntimeInfo(
        app_name=APP_NAME,
        mode=DEMO_LABEL,
        version=APP_VERSION,
        python_version=platform.python_version(),
        cpu_count=detected_cpus,
        static_dir=get_static_dir(),
        log_dir=get_default_log_dir(),
        views=VIEWS,
    )


def format_runtime_info(info: RuntimeInfo) -> str:
    """Formatuje czytelny raport diagnostyczny środowiska po polsku."""
    lines = [
        f"{info.app_name} ({info.mode}) v{info.version}",
        f"Python: {info.python_version}",
        f"Liczba rdzeni CPU: {info.cpu_count}",
        f"Katalog statyczny: {info.static_dir}",
        f"Domyślny katalog logów: {info.log_dir}",
        "Dostępne widoki powłoki:",
    ]
    for view in info.views:
        lines.append(f"  - {view.id}: {view.title} [{view.badge}]")
    return "\n".join(lines)


def create_parser() -> argparse.ArgumentParser:
    """Tworzy parser ``argparse`` z flagami globalnymi oraz podkomendami ``info`` i ``serve``."""
    parser = argparse.ArgumentParser(
        prog="kaucjomat",
        description="Symulator polskiego systemu kaucyjnego KaucjaSim (TRYB DEMO).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Poziom logowania zdarzeń (DEBUG, INFO, WARNING, ERROR, CRITICAL).",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Opcjonalna ścieżka do pliku logów zdarzeń.",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title="Dostępne podkomendy",
        metavar="{info,serve,generate-logs,analyze-logs}",
    )
    subparsers.add_parser(
        "info",
        help="Wyświetla diagnostykę środowiska uruchomieniowego i listę widoków DEMO.",
        description="Wypisuje wersję Pythona, liczbę rdzeni CPU, ścieżki i widoki DEMO.",
    )

    serve_parser = subparsers.add_parser(
        "serve",
        help="Uruchamia lokalny serwer webowy FastAPI (Uvicorn).",
        description="Startuje serwer HTTP aplikacji KaucjaSim DEMO.",
    )
    serve_parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Adres nasłuchiwania serwera (domyślnie {DEFAULT_HOST}).",
    )
    # Domyślna wartość None chroni podkomendy ``info`` i ``--help`` przed błędnym PORT.
    serve_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Numer portu serwera (domyślnie zmienna PORT lub 8000).",
    )
    serve_parser.add_argument(
        "--reload",
        action="store_true",
        help="Włącza automatyczne przeładowanie serwera przy zmianach w kodzie.",
    )
    register_batch_subparsers(subparsers)
    return parser


def run_server(
    host: str,
    port: int,
    reload: bool = False,
    log_level: str | None = None,
    log_file: Path | None = None,
) -> None:
    """Uruchamia serwer Uvicorn wskazując fabrykę aplikacji w trybie bezpiecznym dla spawn."""
    if importlib.util.find_spec("kaucjomat.app") is None:
        raise KaucjomatError(
            "Warstwa serwera webowego (kaucjomat.app) nie jest jeszcze dostępna.",
            error_code="APP_NOT_AVAILABLE",
            status_code=500,
        )

    # Przekazujemy ustawienia loggera przez zmienne środowiskowe dla procesu potomnego --reload.
    if log_level:
        os.environ["KAUCJOMAT_LOG_LEVEL"] = log_level
    if log_file is not None:
        os.environ["KAUCJOMAT_LOG_FILE"] = str(log_file)

    import uvicorn

    uvicorn.run(
        "kaucjomat.app:create_app",
        host=host,
        port=port,
        reload=reload,
        factory=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Główny punkt wejścia CLI parsujący argumenty i obsługujący błędy domenowe."""
    parser = create_parser()
    args = parser.parse_args(argv)

    try:
        logger = configure_logging(level=args.log_level, log_file=args.log_file)
        if args.command is None:
            parser.print_help()
            return 0

        if args.command == "info":
            runtime_info = build_runtime_info()
            print(format_runtime_info(runtime_info))
            logger.info(
                "Wyświetlono diagnostykę środowiska %s %s (Python %s, CPU=%s).",
                runtime_info.app_name,
                runtime_info.mode,
                runtime_info.python_version,
                runtime_info.cpu_count,
            )
            return 0

        if args.command == "serve":
            port = resolve_port(args.port)
            logger.info(
                "Uruchamianie serwera %s %s pod http://%s:%s (reload=%s).",
                APP_NAME,
                DEMO_LABEL,
                args.host,
                port,
                args.reload,
            )
            run_server(
                host=args.host,
                port=port,
                reload=args.reload,
                log_level=args.log_level,
                log_file=args.log_file,
            )
            return 0

        if args.command in {"generate-logs", "analyze-logs"}:
            return execute_batch_cli_command(args)
    except KaucjomatError as exc:
        root_logger = get_logger()
        if root_logger.handlers:
            get_logger("cli").error(
                "Błąd uruchomienia [%s]: %s", exc.error_code, exc.message
            )
        print(f"Błąd [{exc.error_code}]: {exc.message}", file=sys.stderr)
        return 2

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
