"""Indicator endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from apps.api.dependencies import PaginationDep, SessionDep
from reim.core.constants import Frequency, IndicatorCategory
from reim.core.exceptions import ResourceNotFoundError
from reim.database.models import Country, DataSource, Indicator, Observation
from reim.repositories.reference import get_indicator_by_code
from reim.schemas.common import Page
from reim.schemas.reference import IndicatorRead

router = APIRouter(prefix="/api/v1/indicators", tags=["indicators"])


@router.get("", response_model=Page[IndicatorRead], summary="List indicators")
def list_all(
    session: SessionDep,
    pagination: PaginationDep,
    category: Annotated[IndicatorCategory | None, Query()] = None,
    frequency: Annotated[Frequency | None, Query()] = None,
    country: Annotated[
        str | None,
        Query(
            min_length=2,
            max_length=3,
            description="Only indicators that have observations for this country.",
        ),
    ] = None,
    source: Annotated[
        str | None, Query(description="Only indicators fed by this source key.")
    ] = None,
    active_only: Annotated[bool, Query()] = False,
) -> Page[IndicatorRead]:
    """List tracked economic concepts.

    The ``country`` and ``source`` filters are resolved through stored
    observations, so they return what REIM actually holds data for.
    """
    statement = select(Indicator).order_by(Indicator.code)
    if category:
        statement = statement.where(Indicator.category == category)
    if frequency:
        statement = statement.where(Indicator.frequency == frequency)
    if active_only:
        statement = statement.where(Indicator.is_active.is_(True))

    if country or source:
        subquery = select(Observation.indicator_id)
        if country:
            value = country.upper()
            column = Country.iso2 if len(value) == 2 else Country.iso3
            subquery = subquery.join(Country, Observation.country_id == Country.id).where(
                column == value
            )
        if source:
            subquery = subquery.join(DataSource, Observation.source_id == DataSource.id).where(
                DataSource.source_key == source
            )
        statement = statement.where(Indicator.id.in_(subquery.distinct()))

    indicators = list(session.scalars(statement))
    window = indicators[pagination.offset : pagination.offset + pagination.limit]
    return Page.build(
        [IndicatorRead.model_validate(indicator) for indicator in window],
        total=len(indicators),
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get(
    "/{indicator_code}",
    response_model=IndicatorRead,
    summary="Get one indicator by code",
    responses={404: {"description": "Indicator not registered"}},
)
def get_one(session: SessionDep, indicator_code: str) -> IndicatorRead:
    """Return a single indicator by its REIM code."""
    indicator = get_indicator_by_code(session, indicator_code)
    if indicator is None:
        msg = f"Indicator {indicator_code!r} is not registered"
        raise ResourceNotFoundError(msg, indicator_code=indicator_code)
    return IndicatorRead.model_validate(indicator)
