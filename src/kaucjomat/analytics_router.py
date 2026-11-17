"""Synchroniczne endpointy widoku Analityka: kontekst, referencja, wykresy PNG i zadania w tle."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from kaucjomat.analytics_jobs import AnalyticsJobManager, AnalyticsJobSnapshot
from kaucjomat.analytics_presets import ANALYTICS_PRESETS
from kaucjomat.analytics_schemas import (
    AnalyticsContextResponse,
    AnalyticsJobRequest,
    AnalyticsJobResponse,
    AnalyticsPresetSchema,
    AnalyticsReferenceResponse,
)
from kaucjomat.config import (
    BENCHMARK_CHART_PNG_NAME,
    REFERENCE_BENCHMARK_PNG_NAME,
    get_reference_benchmark_dir,
)
from kaucjomat.exceptions import AnalyticsArtifactNotFoundError, GilBenchmarkError
from kaucjomat.gil_benchmark import collect_gil_environment_info
from kaucjomat.gil_conclusions import build_single_core_warning
from kaucjomat.logging_config import get_logger, sanitize_for_log
from kaucjomat.schemas import ErrorResponse

_LOGGER = get_logger("kaucjomat.analytics")

_REFERENCE_CHART_URL: str = "/api/analytics/reference/chart"


def _to_job_response(snapshot: AnalyticsJobSnapshot | None) -> AnalyticsJobResponse:
    """Zamienia migawkę menedżera na odpowiedź HTTP lub stan ``idle`` przy braku zadania."""
    if snapshot is None:
        return AnalyticsJobResponse(status="idle")
    return AnalyticsJobResponse(
        status=snapshot.status, job_id=snapshot.job_id, kind=snapshot.kind,
        preset_id=snapshot.preset_id, phase=snapshot.phase,
        progress_done=snapshot.progress_done, progress_total=snapshot.progress_total,
        started_at_iso=snapshot.started_at_iso, finished_at_iso=snapshot.finished_at_iso,
        elapsed_ms=snapshot.elapsed_ms, result=snapshot.result,
        error_code=snapshot.error_code, error_message=snapshot.error_message,
    )


def _png_response(path: Path, label: str) -> FileResponse:
    """Zwraca plik PNG bez cache'owania albo zgłasza błąd 404, gdy go nie ma."""
    if not path.is_file():
        raise AnalyticsArtifactNotFoundError(f"Brak wykresu: {label}.")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


def create_analytics_router(manager: AnalyticsJobManager) -> APIRouter:
    """Przyjmuje menedżer zadań aplikacji i wystawia kontrakt widoku Analityka."""
    router = APIRouter(
        prefix="/api/analytics", tags=["analytics"],
        responses={code: {"model": ErrorResponse} for code in (400, 404, 409, 422, 500)},
    )

    @router.get("/context", response_model=AnalyticsContextResponse)
    def read_analytics_context() -> AnalyticsContextResponse:
        """Zwraca rdzenie, stan GIL, komunikat 1-rdzeniowy i listę presetów."""
        env = collect_gil_environment_info()
        return AnalyticsContextResponse(
            cpu_count=env.cpu_count, gil_enabled=env.gil_enabled,
            single_core_warning=build_single_core_warning(env.cpu_count),
            presets=[
                AnalyticsPresetSchema(
                    preset_id=p.preset_id, label=p.label, description=p.description,
                    size_label=f"Pliki: {p.file_count}, rekordów w pliku: {p.records_per_file}",
                ) for p in ANALYTICS_PRESETS.values()
            ],
        )

    @router.get("/reference", response_model=AnalyticsReferenceResponse)
    def read_analytics_reference() -> AnalyticsReferenceResponse:
        """Zwraca zwalidowane wyniki referencyjne benchmarku i adres ich wykresu."""
        # Import leniwy: gil_chart ładuje matplotlib, którego nie chcemy przy starcie serwera.
        from kaucjomat.gil_chart import load_reference_gil_benchmark_dict

        try:
            benchmark = load_reference_gil_benchmark_dict()
        except GilBenchmarkError as exc:
            # Szczegóły pliku referencji pozostają w logu, poza odpowiedzią HTTP.
            _LOGGER.warning("Błąd odczytu referencji: %s", sanitize_for_log(exc.message, max_length=200))
            raise GilBenchmarkError(
                "Nie udało się wczytać wyników referencyjnych; szczegóły zapisano w logu serwera.",
                error_code=exc.error_code, status_code=exc.status_code,
            ) from exc
        return AnalyticsReferenceResponse(benchmark=benchmark, chart_url=_REFERENCE_CHART_URL)

    @router.get("/reference/chart", response_class=FileResponse)
    def read_reference_chart() -> FileResponse:
        """Serwuje wykres PNG wyników referencyjnych."""
        return _png_response(
            get_reference_benchmark_dir() / REFERENCE_BENCHMARK_PNG_NAME, "wyniki referencyjne",
        )

    @router.get("/benchmark/chart", response_class=FileResponse)
    def read_benchmark_chart() -> FileResponse:
        """Serwuje wykres PNG ostatniego benchmarku uruchomionego z przeglądarki."""
        return _png_response(
            manager.base_dir / "benchmark" / BENCHMARK_CHART_PNG_NAME, "ostatni benchmark",
        )

    @router.post("/jobs", response_model=AnalyticsJobResponse, status_code=202)
    def start_analytics_job(payload: AnalyticsJobRequest) -> AnalyticsJobResponse:
        """Uruchamia zadanie w tle albo zwraca 409, gdy inne zadanie jeszcze trwa."""
        return _to_job_response(manager.start(payload.kind, payload.preset))

    @router.get("/jobs/current", response_model=AnalyticsJobResponse)
    def read_current_job() -> AnalyticsJobResponse:
        """Zwraca migawkę bieżącego lub ostatniego zadania albo stan ``idle``."""
        return _to_job_response(manager.current())

    return router
