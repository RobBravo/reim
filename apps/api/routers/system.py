"""System endpoints: health, readiness, status and metrics."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from apps.api.dependencies import SessionDep
from reim import __version__
from reim.core.config import get_settings
from reim.database.session import check_database_connection
from reim.schemas.pipelines import HealthStatus, ReadinessStatus, SystemStatus
from reim.services.status import build_system_status

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthStatus, summary="Liveness probe")
def health() -> HealthStatus:
    """Return OK whenever the process is running.

    Deliberately touches no dependency: a failing database must not restart the
    container, it must only mark it unready.
    """
    return HealthStatus(status="ok", version=__version__)


@router.get(
    "/ready",
    response_model=ReadinessStatus,
    summary="Readiness probe",
    responses={503: {"description": "A dependency is unavailable"}},
)
def ready(response: Response) -> ReadinessStatus:
    """Report whether the API can serve traffic, checking the database."""
    database_ok = check_database_connection()
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessStatus(
        status="ready" if database_ok else "not_ready",
        version=__version__,
        checks={"database": database_ok},
    )


@router.get(
    "/api/v1/status",
    response_model=SystemStatus,
    tags=["system"],
    summary="Platform status and data coverage",
)
def system_status(session: SessionDep) -> SystemStatus:
    """Return aggregate counters, last ingestion time and recent quality signal."""
    return build_system_status(session)


@router.get("/metrics", include_in_schema=False, summary="Prometheus metrics")
def metrics() -> Response:
    """Expose process metrics in Prometheus text format.

    Disabled by setting ``REIM_METRICS_ENABLED=false``.
    """
    if not get_settings().metrics_enabled:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
