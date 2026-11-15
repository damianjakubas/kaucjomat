"""Testy jednostkowe CLI, konfiguracji, wyjątków oraz modułu logowania."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from kaucjomat.cli import build_runtime_info, main
from kaucjomat.config import resolve_port
from kaucjomat.exceptions import InvalidConfigurationError
from kaucjomat.logging_config import configure_logging, get_logger


def test_runtime_info_reports_python_313_and_demo_mode() -> None:
    """Sprawdza raportowanie wersji Pythona 3.13+, rdzeni CPU, trybu DEMO i 3 widoków."""
    info = build_runtime_info()

    assert info.app_name == "KaucjaSim"
    assert info.mode == "DEMO"
    assert info.python_version.startswith("3.13")
    assert info.cpu_count >= 1
    assert [view.id for view in info.views] == ["butelkomat", "kasa", "analityka"]


def test_cli_without_subcommand_prints_help_and_returns_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Wywołanie CLI bez podkomendy powinno wypisać pomoc i zakończyć się kodem 0."""
    exit_code = main([])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "kaucjomat" in captured.out
    assert "info" in captured.out
    assert "serve" in captured.out


def test_cli_info_prints_polish_diagnostics_and_views(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Podkomenda info wypisuje czytelną diagnostykę po polsku oraz listę 3 widoków."""
    exit_code = main(["info"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "KaucjaSim (DEMO)" in captured.out
    assert "Python: 3.13" in captured.out
    assert "Butelkomat" in captured.out
    assert "Kasa Sklepowa" in captured.out
    assert "Analityka i Benchmark GIL" in captured.out


@pytest.mark.parametrize("bad_port", ["0", "-5", "70000"])
def test_cli_rejects_invalid_port(
    bad_port: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Nieprawidłowy numer portu w CLI zwraca kod błędu 2 i komunikat po polsku."""
    exit_code = main(["serve", "--port", bad_port])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "INVALID_CONFIGURATION" in captured.err
    assert "Nieprawidłowy numer portu" in captured.err


def test_resolve_port_uses_environment_variable_and_rejects_non_numeric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Funkcja resolve_port odczytuje PORT ze środowiska i waliduje liczby."""
    monkeypatch.setenv("PORT", "9090")
    assert resolve_port(None) == 9090

    monkeypatch.setenv("PORT", "abc")
    with pytest.raises(InvalidConfigurationError, match="PORT"):
        resolve_port(None)


def test_configure_logging_console_and_optional_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Logger zapisuje komunikaty na stderr i do pliku tymczasowego oraz zwalnia uchwyt."""
    log_file = tmp_path / "logs" / "kaucjomat.log"
    configure_logging(level="INFO", log_file=log_file)
    logger = get_logger("test_suite")
    logger.info("Zdarzenie testowe DEMO")

    # Ponowna konfiguracja bez pliku zamyka FileHandler i zwalnia blokadę na Windows.
    configure_logging(level="INFO", log_file=None)
    captured = capsys.readouterr()

    assert "Zdarzenie testowe DEMO" in captured.err
    assert log_file.exists()
    file_content = log_file.read_text(encoding="utf-8")
    assert "Zdarzenie testowe DEMO" in file_content
    assert "kaucjomat.test_suite" in file_content

    log_file.unlink()
    assert not log_file.exists()


def test_configure_logging_invalid_level_raises_domain_error() -> None:
    """Nieznany poziom logowania zgłasza InvalidConfigurationError."""
    with pytest.raises(InvalidConfigurationError, match="Nieznany poziom logowania"):
        configure_logging(level="NIEISTNIEJACY")


def test_python_module_entrypoint_info() -> None:
    """Uruchomienie przez ``python -m kaucjomat info`` działa poprawnie w podprocesie."""
    result = subprocess.run(
        [sys.executable, "-m", "kaucjomat", "info"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0
    assert "KaucjaSim (DEMO)" in result.stdout
    assert "Liczba rdzeni CPU:" in result.stdout
