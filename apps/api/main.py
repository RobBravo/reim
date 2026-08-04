"""FastAPI application factory.

The API is **read-only**. Ingestion is triggered from the CLI or an external
scheduler, never over HTTP — see decision D13 in ``docs/implementation-plan.md``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.errors import register_exception_handlers
from apps.api.routers import (
    countries,
    indicators,
    observations,
    organizations,
    pipelines,
    sources,
    system,
)
from reim import __version__
from reim.core.config import get_settings
from reim.core.exceptions import REIMError
from reim.core.logging import configure_logging, get_logger
from reim.domain.sources.catalog import get_catalog

logger = get_logger(__name__)

DESCRIPTION = """
**REIM** — Regional Economic Intelligence Monitor.

An open platform that collects, normalizes and publishes economic indicators for
Central America from official sources, with full provenance and quality controls.

This release covers **Nicaragua**.

Every observation carries its source, source URL, retrieval timestamp, connector
and pipeline versions, validation status and a content hash, so any figure can be
traced back to the publication it came from. Missing upstream values are never
imputed or interpolated.

The API is read-only; pipelines are run from the CLI.
"""

TAGS_METADATA = [
    {"name": "system", "description": "Health, readiness and platform status."},
    {"name": "countries", "description": "Countries covered by REIM."},
    {"name": "sources", "description": "Publishing organizations and registered data sources."},
    {"name": "indicators", "description": "Tracked economic concepts."},
    {"name": "observations", "description": "Economic datapoints and CSV export."},
    {"name": "pipelines", "description": "Ingestion runs, quality checks and data freshness."},
]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Validate the source catalog at startup.

    An invalid catalog is a hard failure: the API must not serve data whose
    provenance metadata cannot be trusted.
    """
    configure_logging()
    try:
        catalog = get_catalog()
    except REIMError as exc:
        logger.error("startup.invalid_catalog", error=exc.message)
        raise
    logger.info(
        "startup.complete",
        version=__version__,
        environment=get_settings().environment.value,
        sources=len(catalog.sources),
        sources_enabled=len(catalog.enabled_sources),
    )
    yield
    logger.info("shutdown.complete")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()
    app = FastAPI(
        title=settings.api_title,
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=TAGS_METADATA,
        root_path=settings.api_root_path,
        lifespan=lifespan,
        license_info={
            "name": "Apache-2.0",
            "url": "https://www.apache.org/licenses/LICENSE-2.0",
        },
        contact={"name": "REIM", "url": "https://github.com/reim-project/reim"},
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(system.router)
    app.include_router(countries.router)
    app.include_router(organizations.router)
    app.include_router(sources.router)
    app.include_router(indicators.router)
    app.include_router(observations.router)
    app.include_router(pipelines.router)
    return app


app = create_app()
