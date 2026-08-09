"""Queries backing the cross-country comparison endpoint.

Kept apart from :mod:`reim.repositories.observations`, which already carries
ten functions over a different shape: that module answers "which observations
match these filters", this one answers "what does this indicator look like
across these countries, period by period".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from reim.core.constants import ObservationStatus
from reim.database.models import Country, DataSource, Indicator, Observation


@dataclass(frozen=True, slots=True)
class ComparisonQuery:
    """One indicator, several countries, optionally bounded in time."""

    indicator_code: str
    country_ids: tuple[uuid.UUID, ...]
    period_start_from: date | None = None
    period_start_to: date | None = None


@dataclass(frozen=True, slots=True)
class ComparisonCell:
    """One country's figure for one period."""

    period_start: date
    period_end: date
    period_label: str
    country_iso3: str
    value_numeric: Decimal | None


@dataclass(frozen=True, slots=True)
class SeriesSummary:
    """What one country's series looks like, including when it is empty.

    ``units``, ``currency_codes`` and ``source_keys`` are tuples because a
    country's series can carry more than one of each over time, and collapsing
    that to a scalar would hide exactly the difference a comparison must show.
    """

    country_iso2: str
    country_iso3: str
    country_name: str
    units: tuple[str, ...]
    currency_codes: tuple[str | None, ...]
    source_keys: tuple[str, ...]
    observations: int
    first_period: str | None
    last_period: str | None


def _restrict[S: Select[Any]](statement: S, query: ComparisonQuery) -> S:
    """Narrow a statement already joined to indicator and country."""
    statement = statement.where(
        Indicator.code == query.indicator_code,
        Observation.country_id.in_(query.country_ids),
        Observation.status == ObservationStatus.ACTIVE,
    )
    if query.period_start_from is not None:
        statement = statement.where(Observation.period_start >= query.period_start_from)
    if query.period_start_to is not None:
        statement = statement.where(Observation.period_start <= query.period_start_to)
    return statement


def _period_page(
    query: ComparisonQuery, *, limit: int, offset: int, descending: bool
) -> Select[tuple[date, date, str]]:
    """The page of distinct periods, which is what pagination slices."""
    order = Observation.period_start.desc() if descending else Observation.period_start.asc()
    statement = (
        select(Observation.period_start, Observation.period_end, Observation.period_label)
        .join(Observation.indicator)
        .distinct()
        .order_by(order)
        .limit(limit)
        .offset(offset)
    )
    return _restrict(statement, query)


def count_comparison_periods(session: Session, query: ComparisonQuery) -> int:
    """Count the distinct periods any requested country reports."""
    inner = _restrict(
        select(Observation.period_start).join(Observation.indicator).distinct(), query
    ).subquery()
    return int(session.scalar(select(func.count()).select_from(inner)) or 0)


def fetch_comparison_cells(
    session: Session,
    query: ComparisonQuery,
    *,
    limit: int,
    offset: int,
    descending: bool = False,
) -> list[ComparisonCell]:
    """Return every country's figure for the requested page of periods.

    Pagination slices **periods**, not rows: a page of one period carries that
    period's cell for every country holding it.
    """
    periods = session.execute(
        _period_page(query, limit=limit, offset=offset, descending=descending)
    ).all()
    if not periods:
        return []

    starts = [row[0] for row in periods]
    statement = _restrict(
        select(
            Observation.period_start,
            Observation.period_end,
            Observation.period_label,
            Country.iso3,
            Observation.value_numeric,
        )
        .join(Observation.indicator)
        .join(Observation.country),
        query,
    ).where(Observation.period_start.in_(starts))

    order = Observation.period_start.desc() if descending else Observation.period_start.asc()
    rows = session.execute(statement.order_by(order, Country.iso3)).all()
    return [
        ComparisonCell(
            period_start=row[0],
            period_end=row[1],
            period_label=row[2],
            country_iso3=row[3],
            value_numeric=row[4],
        )
        for row in rows
    ]


def summarise_series(
    session: Session, query: ComparisonQuery, countries: list[Country]
) -> list[SeriesSummary]:
    """Describe each requested country's series, empty ones included.

    ``countries`` is passed in rather than derived from the data so a country
    holding nothing still appears — a grouped query would silently drop it.
    """
    statement = _restrict(
        select(
            Country.iso3,
            Observation.unit,
            Observation.currency_code,
            DataSource.source_key,
            Observation.period_start,
            Observation.period_label,
        )
        .join(Observation.indicator)
        .join(Observation.country)
        .join(Observation.source),
        query,
    )

    units: dict[str, set[str]] = {}
    currencies: dict[str, set[str | None]] = {}
    sources: dict[str, set[str]] = {}
    counts: dict[str, int] = {}
    earliest: dict[str, tuple[date, str]] = {}
    latest: dict[str, tuple[date, str]] = {}

    for iso3, unit, currency, source_key, start, label in session.execute(statement):
        units.setdefault(iso3, set()).add(unit)
        currencies.setdefault(iso3, set()).add(currency)
        sources.setdefault(iso3, set()).add(source_key)
        counts[iso3] = counts.get(iso3, 0) + 1
        if iso3 not in earliest or start < earliest[iso3][0]:
            earliest[iso3] = (start, label)
        if iso3 not in latest or start > latest[iso3][0]:
            latest[iso3] = (start, label)

    return [
        SeriesSummary(
            country_iso2=country.iso2,
            country_iso3=country.iso3,
            country_name=country.name,
            units=tuple(sorted(units.get(country.iso3, set()))),
            currency_codes=tuple(
                sorted(currencies.get(country.iso3, set()), key=lambda c: (c is None, c or ""))
            ),
            source_keys=tuple(sorted(sources.get(country.iso3, set()))),
            observations=counts.get(country.iso3, 0),
            first_period=earliest.get(country.iso3, (None, None))[1],
            last_period=latest.get(country.iso3, (None, None))[1],
        )
        for country in countries
    ]
