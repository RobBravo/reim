"""Observation endpoints, including the CSV export."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from apps.api.dependencies import PaginationDep, SessionDep, SettingsDep
from reim.core.constants import ObservationStatus, ValidationStatus
from reim.core.exceptions import InvalidRequestError
from reim.repositories.observations import (
    SORTABLE_COLUMNS,
    ObservationFilters,
    count_observations,
    latest_observations,
    list_observations,
)
from reim.schemas.common import Page
from reim.schemas.observations import ObservationRead
from reim.services.export import stream_observations_csv

router = APIRouter(prefix="/api/v1/observations", tags=["observations"])


def observation_filters(
    country: Annotated[
        str | None,
        Query(min_length=2, max_length=3, description="ISO alpha-2 or alpha-3 country code."),
    ] = None,
    indicator: Annotated[str | None, Query(description="REIM indicator code.")] = None,
    source: Annotated[str | None, Query(description="Catalog source key.")] = None,
    category: Annotated[str | None, Query(description="Indicator category.")] = None,
    date_from: Annotated[
        date | None, Query(description="Earliest period start, inclusive (YYYY-MM-DD).")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="Latest period start, inclusive (YYYY-MM-DD).")
    ] = None,
    validation_status: Annotated[ValidationStatus | None, Query()] = None,
    status: Annotated[
        ObservationStatus | None,
        Query(description="Lifecycle status. Defaults to active observations only."),
    ] = ObservationStatus.ACTIVE,
) -> ObservationFilters:
    """Build and sanity-check the shared observation filter set."""
    if date_from and date_to and date_from > date_to:
        msg = f"date_from ({date_from}) must not be later than date_to ({date_to})"
        raise InvalidRequestError(msg, date_from=str(date_from), date_to=str(date_to))
    return ObservationFilters(
        country=country,
        indicator=indicator,
        source=source,
        category=category,
        period_start_from=date_from,
        period_start_to=date_to,
        validation_status=validation_status,
        status=status,
    )


FiltersDep = Annotated[ObservationFilters, Depends(observation_filters)]


def _sort_params(sort_by: str, order: str) -> tuple[str, bool]:
    if sort_by not in SORTABLE_COLUMNS:
        msg = f"sort_by must be one of {sorted(SORTABLE_COLUMNS)}"
        raise InvalidRequestError(msg, sort_by=sort_by)
    if order not in ("asc", "desc"):
        msg = "order must be 'asc' or 'desc'"
        raise InvalidRequestError(msg, order=order)
    return sort_by, order == "desc"


@router.get("", response_model=Page[ObservationRead], summary="Query observations")
def list_all(
    session: SessionDep,
    pagination: PaginationDep,
    filters: FiltersDep,
    sort_by: Annotated[str, Query(description="Column to sort by.")] = "period_start",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
) -> Page[ObservationRead]:
    """Return a filtered, paginated page of observations.

    Page size is capped by ``REIM_MAX_PAGE_SIZE``; use
    ``/observations/export.csv`` for bulk retrieval.
    """
    column, descending = _sort_params(sort_by, order)
    total = count_observations(session, filters)
    rows = list_observations(
        session,
        filters,
        limit=pagination.limit,
        offset=pagination.offset,
        sort_by=column,
        descending=descending,
    )
    return Page.build(
        [ObservationRead.from_model(row) for row in rows],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get(
    "/latest",
    response_model=list[ObservationRead],
    summary="Latest observation per series",
)
def latest(
    session: SessionDep,
    filters: FiltersDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[ObservationRead]:
    """Return the most recent observation for each country/indicator/source series."""
    rows = latest_observations(session, filters, limit=limit)
    return [ObservationRead.from_model(row) for row in rows]


@router.get(
    "/export.csv",
    summary="Export observations as CSV",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/csv": {}},
            "description": "Streamed CSV with one row per observation.",
        }
    },
)
def export_csv(
    session: SessionDep,
    settings: SettingsDep,
    filters: FiltersDep,
    sort_by: Annotated[str, Query()] = "period_start",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[
        int | None, Query(ge=1, description="Row cap. Defaults to REIM_MAX_EXPORT_ROWS.")
    ] = None,
) -> StreamingResponse:
    """Stream matching observations as CSV, including full provenance columns."""
    column, descending = _sort_params(sort_by, order)
    row_limit = min(limit or settings.max_export_rows, settings.max_export_rows)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    parts = [part for part in (filters.country, filters.indicator) if part]
    filename = "_".join(["reim_observations", *parts, stamp]) + ".csv"

    return StreamingResponse(
        stream_observations_csv(
            session, filters, limit=row_limit, sort_by=column, descending=descending
        ),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
