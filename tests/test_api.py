"""Testy warstwy API FastAPI, obsługi błędów HTTP i wywołania serwera z CLI."""

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
import pytest

from kaucjomat.app import create_app
from kaucjomat.cli import main
from kaucjomat.config import APP_NAME, DEFAULT_VIEW_ID
from kaucjomat.logging_config import configure_logging, get_logger


def _build_client() -> TestClient:
    """Tworzy klienta testowego FastAPI opartego o fabrykę aplikacji."""
    return TestClient(create_app())


def test_health_endpoint_returns_demo_status() -> None:
    """Endpoint /api/health zwraca status gotowości oraz tryb DEMO."""
    client = _build_client()
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["app_name"] == APP_NAME
    assert payload["mode"] == "DEMO"
    assert payload["views_count"] == 3


def test_views_list_endpoint_returns_all_three_views() -> None:
    """Endpoint /api/views zwraca 3 widoki powłoki wraz z domyślną zakładką."""
    client = _build_client()
    response = client.get("/api/views")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "DEMO"
    assert payload["default_view"] == DEFAULT_VIEW_ID
    assert [item["id"] for item in payload["views"]] == [
        "butelkomat",
        "kasa",
        "analityka",
    ]
    assert all(item["demo_mode"] is True for item in payload["views"])


@pytest.mark.parametrize(
    ("view_id", "expected_title_fragment"),
    [
        ("butelkomat", "Butelkomat"),
        ("kasa", "Kasa Sklepowa"),
        ("analityka", "Analityka"),
    ],
)
def test_single_view_endpoint_accepts_known_views(
    view_id: str,
    expected_title_fragment: str,
) -> None:
    """Endpoint /api/views/{view_id} zwraca metadane każdego z 3 znanych widoków."""
    client = _build_client()
    response = client.get(f"/api/views/{view_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == view_id
    assert expected_title_fragment in payload["title"]
    assert payload["demo_mode"] is True


def test_unknown_view_returns_404_error_response() -> None:
    """Nieznany identyfikator o poprawnym formacie zwraca 404 VIEW_NOT_FOUND."""
    client = _build_client()
    response = client.get("/api/views/nieznany-widok")

    assert response.status_code == 404
    payload = response.json()
    assert payload["error_code"] == "VIEW_NOT_FOUND"
    assert payload["mode"] == "DEMO"
    assert "nieznany-widok" in payload["message"]


@pytest.mark.parametrize("invalid_view_id", ["BAD_ID!", "a", "x" * 33, "kasa_demo"])
def test_invalid_view_id_format_returns_400_error_response(invalid_view_id: str) -> None:
    """Niepoprawny format identyfikatora widoku zwraca 400 INVALID_CONFIGURATION."""
    client = _build_client()
    response = client.get(f"/api/views/{invalid_view_id}")

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "INVALID_CONFIGURATION"
    assert payload["mode"] == "DEMO"


def test_validation_error_handler_returns_unified_error_response() -> None:
    """Błąd walidacji FastAPI zwraca status 422 i spójny model ErrorResponse."""
    app = create_app()

    @app.get("/api/_test-validation")
    def validate_query_param(count: int) -> dict[str, int]:
        """Pomocniczy endpoint testowy wymuszający walidację typu int."""
        return {"count": count}

    client = TestClient(app)
    response = client.get("/api/_test-validation", params={"count": "nie-liczba"})

    assert response.status_code == 422
    payload = response.json()
    assert payload["error_code"] == "VALIDATION_ERROR"
    assert payload["mode"] == "DEMO"
    assert payload["detail"] is not None
    assert "count" in payload["detail"]


def test_api_errors_are_logged_via_shared_logger(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Handlery błędów HTTP logują ostrzeżenia przez wspólny logger kaucjomat."""
    log_file = tmp_path / "api_errors.log"
    configure_logging(level="WARNING", log_file=log_file)
    try:
        client = _build_client()
        not_found = client.get("/api/views/nieznany-widok")
        bad_format = client.get("/api/views/BAD_ID!")

        assert not_found.status_code == 404
        assert bad_format.status_code == 400

        captured = capsys.readouterr()
        log_content = log_file.read_text(encoding="utf-8")
        assert "VIEW_NOT_FOUND" in captured.err
        assert "INVALID_CONFIGURATION" in captured.err
        assert "VIEW_NOT_FOUND" in log_content
        assert "INVALID_CONFIGURATION" in log_content
    finally:
        # Przywrócenie konfiguracji loggera zamyka uchwyt pliku tymczasowego na Windows.
        configure_logging(level="INFO")


def test_api_error_handler_emits_warning_to_custom_handler() -> None:
    """Wspólny logger kaucjomat przekazuje ostrzeżenie HTTP do podpiętego handlera."""
    root_logger = get_logger()
    recorded: list[logging.LogRecord] = []

    class _ListHandler(logging.Handler):
        """Prosty handler testowy zbierający rekordy logowania w pamięci."""

        def emit(self, record: logging.LogRecord) -> None:
            """Zapisuje przechwycony rekord logowania do listy testowej."""
            recorded.append(record)

    configure_logging(level="INFO")
    handler = _ListHandler()
    root_logger.addHandler(handler)
    try:
        client = _build_client()
        response = client.get("/api/views/nieznany-widok")
        assert response.status_code == 404
    finally:
        root_logger.removeHandler(handler)

    assert any("VIEW_NOT_FOUND" in record.getMessage() for record in recorded)


def test_cli_serve_invokes_uvicorn_with_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Podkomenda CLI serve przekazuje fabrykę aplikacji do uvicorn.run."""
    mock_run = MagicMock()
    monkeypatch.setitem(
        __import__("sys").modules,
        "uvicorn",
        SimpleNamespace(run=mock_run),
    )

    exit_code = main(["serve", "--host", "127.0.0.1", "--port", "9100", "--reload"])

    assert exit_code == 0
    mock_run.assert_called_once_with(
        "kaucjomat.app:create_app",
        host="127.0.0.1",
        port=9100,
        reload=True,
        factory=True,
    )
