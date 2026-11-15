"""Fabryka aplikacji FastAPI, trasy API oraz handlery wyjątków dla KaucjaSim DEMO."""

import os
import string
from pathlib import Path
from typing import cast, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from kaucjomat.config import (
    APP_NAME,
    APP_TITLE,
    APP_VERSION,
    DEFAULT_VIEW_ID,
    DEMO_LABEL,
    VIEWS,
    VIEWS_BY_ID,
    ViewDefinition,
    get_static_dir,
)
from kaucjomat.exceptions import InvalidConfigurationError, KaucjomatError, ViewNotFoundError
from kaucjomat.logging_config import configure_logging, get_logger, sanitize_for_log
from kaucjomat.schemas import ErrorResponse, HealthResponse, ViewSchema, ViewsListResponse

_ALLOWED_VIEW_ID_CHARS: frozenset[str] = frozenset(string.ascii_lowercase + string.digits + "-")
_MIN_VIEW_ID_LENGTH: int = 2
_MAX_VIEW_ID_LENGTH: int = 32
_DEMO_MODE: Literal["DEMO"] = cast(Literal["DEMO"], DEMO_LABEL)


def _to_view_schema(view: ViewDefinition) -> ViewSchema:
    """Konwertuje definicję widoku z konfiguracji na model Pydantic."""
    return ViewSchema(
        id=view.id,
        title=view.title,
        badge=view.badge,
        description=view.description,
        planned_scope=view.planned_scope,
        demo_mode=True,
    )


def get_view_or_raise(view_id: str) -> ViewSchema:
    """Waliduje identyfikator widoku i zwraca jego metadane lub rzuca wyjątek domenowy."""
    # Jawna walidacja znaków ASCII bez wyrażeń regularnych zachowuje rozdział zakresów etapów.
    has_valid_length = _MIN_VIEW_ID_LENGTH <= len(view_id) <= _MAX_VIEW_ID_LENGTH
    has_valid_chars = all(char in _ALLOWED_VIEW_ID_CHARS for char in view_id)
    safe_view_id = sanitize_for_log(view_id)
    if not (has_valid_length and has_valid_chars):
        raise InvalidConfigurationError(
            "Nieprawidłowy identyfikator widoku: "
            f"'{safe_view_id}'. Dozwolone są małe litery ASCII, cyfry i myślnik (2-32 znaki)."
        )

    view = VIEWS_BY_ID.get(view_id)
    if view is None:
        raise ViewNotFoundError(f"Nie znaleziono widoku o identyfikatorze '{safe_view_id}'.")

    return _to_view_schema(view)


def _format_validation_errors(exc: RequestValidationError) -> str | None:
    """Buduje zwięzły opis błędów walidacji FastAPI do pola diagnostycznego odpowiedzi."""
    parts: list[str] = []
    for err in exc.errors():
        location = ".".join(str(segment) for segment in err.get("loc", ()))
        message = str(err.get("msg", "Nieprawidłowa wartość."))
        parts.append(f"{location}: {message}" if location else message)
    return "; ".join(parts) if parts else None


def create_app() -> FastAPI:
    """Tworzy i konfiguruje instancję aplikacji FastAPI bez efektów ubocznych przy imporcie."""
    # Uruchomienie przez uvicorn --factory (także proces potomny --reload) odtwarza konfigurację ze środowiska.
    if not get_logger().handlers:
        env_level = os.getenv("KAUCJOMAT_LOG_LEVEL", "INFO")
        env_log_file = os.getenv("KAUCJOMAT_LOG_FILE")
        configure_logging(
            level=env_level,
            log_file=Path(env_log_file) if env_log_file else None,
        )

    logger = get_logger("app")
    app = FastAPI(
        title=APP_TITLE,
        version=APP_VERSION,
        description="Edukacyjny symulator polskiego systemu kaucyjnego w trybie DEMO.",
    )

    @app.exception_handler(KaucjomatError)
    async def handle_kaucjomat_error(request: Request, exc: KaucjomatError) -> JSONResponse:
        """Obsługuje wyjątki domenowe aplikacji i zwraca spójny JSON błędu DEMO."""
        logger.warning(
            "Błąd domenowy HTTP %s [%s] na %s: %s",
            exc.status_code,
            exc.error_code,
            sanitize_for_log(request.url.path, max_length=128),
            sanitize_for_log(exc.message, max_length=200),
        )
        payload = ErrorResponse(
            error_code=exc.error_code,
            message=exc.message,
            detail=None,
            mode=_DEMO_MODE,
        )
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        """Konwertuje błędy walidacji FastAPI do ujednoliconego formatu ErrorResponse."""
        detail = _format_validation_errors(exc)
        logger.warning(
            "Błąd walidacji żądania HTTP 422 na %s: %s",
            sanitize_for_log(request.url.path, max_length=128),
            sanitize_for_log(detail, max_length=200) if detail else "brak szczegółów",
        )
        payload = ErrorResponse(
            error_code="VALIDATION_ERROR",
            message="Nieprawidłowe parametry żądania.",
            detail=detail,
            mode=_DEMO_MODE,
        )
        return JSONResponse(status_code=422, content=payload.model_dump())

    static_dir = get_static_dir()
    index_file = static_dir / "index.html"
    if not static_dir.is_dir() or not index_file.is_file():
        raise InvalidConfigurationError(
            f"Brak wymaganych zasobów statycznych powłoki DEMO w katalogu: '{static_dir}'."
        )
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    def read_index() -> FileResponse:
        """Serwuje główny dokument HTML lokalnej powłoki KaucjaSim DEMO."""
        return FileResponse(index_file, media_type="text/html")

    @app.get("/api/health", response_model=HealthResponse, tags=["system"])
    def read_health() -> HealthResponse:
        """Zwraca podstawowy status gotowości lokalnego backendu DEMO."""
        return HealthResponse(
            status="ok",
            app_name=APP_NAME,
            version=APP_VERSION,
            mode=_DEMO_MODE,
            views_count=len(VIEWS),
        )

    @app.get("/api/views", response_model=ViewsListResponse, tags=["views"])
    def list_views() -> ViewsListResponse:
        """Zwraca uporządkowaną listę 3 widoków edukacyjnej powłoki KaucjaSim DEMO."""
        return ViewsListResponse(
            mode=_DEMO_MODE,
            default_view=DEFAULT_VIEW_ID,
            views=[_to_view_schema(view) for view in VIEWS],
        )

    @app.get("/api/views/{view_id}", response_model=ViewSchema, tags=["views"])
    def read_view(view_id: str) -> ViewSchema:
        """Zwraca metadane wybranego widoku lub zgłasza błąd 400/404 w formacie ErrorResponse."""
        return get_view_or_raise(view_id)

    return app
