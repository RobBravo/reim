"""Query helpers for the observations fact table."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload

from reim.core.constants import ObservationStatus, ValidationStatus
from reim.database.models import Country, DataSource, Indicator, Observation

#: Columns callers may sort by, mapped to their ORM attributes.
SORTABLE_COLUMNS = {
    "period_start": Observation.period_start,
    "period_end": Observation.period_end,
    "retrieved_at": Observation.retrieved_at,
    "published_at": Observation.published_at,
    "value_numeric": Observation.value_numeric,
}


@dataclass(frozen=True, slots=True)
class ObservationFilters:
    """Filter set shared by the list, count and export queries."""

    country: str | None = None
    indicator: str | None = None
    source: str | None = None
    category: str | None = None
    period_start_from: date | None = None
    period_start_to: date | None = None
    validation_status: ValidationStatus | None = None
    status: ObservationStatus | None = ObservationStatus.ACTIVE


def _base_query() -> Select[tuple[Observation]]:
    return (
        select(Observation)
        .join(Observation.country)
        .join(Observation.indicator)
        .join(Observation.source)
    )


def apply_filters[S: Select[Any]](statement: S, filters: ObservationFilters) -> S:
    """Apply ``filters`` to a statement already joined to the reference tables."""
    if filters.country:
        value = filters.country.upper()
        column = Country.iso2 if len(value) == 2 else Country.iso3
        statement = statement.where(column == value)
    if filters.indicator:
        statement = statement.where(Indicator.code == filters.indicator)
    if filters.category:
        statement = statement.where(Indicator.category == filters.category)
    if filters.source:
        statement = statement.where(DataSource.source_key == filters.source)
    if filters.period_start_from:
        statement = statement.where(Observation.period_start >= filters.period_start_from)
    if filters.period_start_to:
        statement = statement.where(Observation.period_start <= filters.period_start_to)
    if filters.validation_status:
        statement = statement.where(Observation.validation_status == filters.validation_status)
    if filters.status:
        statement = statement.where(Observation.status == filters.status)
    return statement


def count_observations(session: Session, filters: ObservationFilters) -> int:
    """Return how many observations match ``filters``."""
    statement = (
        select(func.count(Observation.id))
        .select_from(Observation)
        .join(Observation.country)
        .join(Observation.indicator)
        .join(Observation.source)
    )
    return int(session.scalar(apply_filters(statement, filters)) or 0)


def list_observations(
    session: Session,
    filters: ObservationFilters,
    *,
    limit: int,
    offset: int = 0,
    sort_by: str = "period_start",
    descending: bool = True,
) -> list[Observation]:
    """Return a page of observations with their reference rows eagerly loaded."""
    column = SORTABLE_COLUMNS.get(sort_by, Observation.period_start)
    order = column.desc() if descending else column.asc()
    statement = (
        apply_filters(_base_query(), filters)
        .options(
            joinedload(Observation.country),
            joinedload(Observation.indicator),
            joinedload(Observation.source),
        )
        .order_by(order, Observation.id)
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(statement))


def iter_observations(
    session: Session,
    filters: ObservationFilters,
    *,
    limit: int,
    sort_by: str = "period_start",
    descending: bool = True,
    chunk_size: int = 1000,
) -> Iterator[Observation]:
    """Yield observations in chunks, for streaming exports.

    Uses a server-side cursor so a large CSV export never materialises the whole
    result set in memory.
    """
    column = SORTABLE_COLUMNS.get(sort_by, Observation.period_start)
    order = column.desc() if descending else column.asc()
    statement = (
        apply_filters(_base_query(), filters)
        .options(
            joinedload(Observation.country),
            joinedload(Observation.indicator),
            joinedload(Observation.source),
        )
        .order_by(order, Observation.id)
        .limit(limit)
        .execution_options(yield_per=chunk_size)
    )
    yield from session.scalars(statement)


def latest_observations(
    session: Session, filters: ObservationFilters, *, limit: int
) -> list[Observation]:
    """Return the most recent observation per (country, indicator, source).

    Implemented with ``DISTINCT ON``, which PostgreSQL evaluates efficiently
    against the ``(country_id, indicator_id, period_start)`` index.
    """
    statement = (
        apply_filters(_base_query(), filters)
        .options(
            joinedload(Observation.country),
            joinedload(Observation.indicator),
            joinedload(Observation.source),
        )
        .distinct(Observation.country_id, Observation.indicator_id, Observation.source_id)
        .order_by(
            Observation.country_id,
            Observation.indicator_id,
            Observation.source_id,
            Observation.period_start.desc(),
        )
        .limit(limit)
    )
    return list(session.scalars(statement))


def get_by_natural_key(
    session: Session,
    *,
    country_id: uuid.UUID,
    indicator_id: uuid.UUID,
    source_id: uuid.UUID,
    period_start: date,
    period_end: date,
) -> Observation | None:
    """Return the observation matching the natural key, if it exists."""
    return session.scalar(
        select(Observation).where(
            Observation.country_id == country_id,
            Observation.indicator_id == indicator_id,
            Observation.source_id == source_id,
            Observation.period_start == period_start,
            Observation.period_end == period_end,
        )
    )


def latest_retrieved_at(session: Session, source_id: uuid.UUID) -> datetime | None:
    """Return when this source last produced an observation."""
    return session.scalar(
        select(func.max(Observation.retrieved_at)).where(Observation.source_id == source_id)
    )


def latest_period_end(session: Session, source_id: uuid.UUID) -> date | None:
    """Return the newest period covered by this source's data."""
    return session.scalar(
        select(func.max(Observation.period_end)).where(Observation.source_id == source_id)
    )
