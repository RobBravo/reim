"""Data source endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from apps.api.dependencies import PaginationDep, SessionDep
from reim.core.constants import Frequency, IndicatorCategory
from reim.core.exceptions import ResourceNotFoundError
from reim.database.models import Country, DataSource
from reim.repositories.reference import get_source_by_key
from reim.schemas.common import Page
from reim.schemas.reference import DataSourceRead

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


@router.get("", response_model=Page[DataSourceRead], summary="List data sources")
def list_all(
    session: SessionDep,
    pagination: PaginationDep,
    country: Annotated[
        str | None, Query(min_length=2, max_length=3, description="ISO alpha-2 or alpha-3.")
    ] = None,
    category: Annotated[IndicatorCategory | None, Query()] = None,
    frequency: Annotated[Frequency | None, Query()] = None,
    active_only: Annotated[
        bool, Query(description="Exclude sources disabled in the catalog.")
    ] = False,
) -> Page[DataSourceRead]:
    """List registered data sources with their operational flags.

    Disabled sources are returned by default and carry ``disabled_reason``, so
    the catalog stays transparent about what is not being ingested and why.
    """
    statement = select(DataSource).order_by(DataSource.source_key)
    if country:
        value = country.upper()
        column = Country.iso2 if len(value) == 2 else Country.iso3
        statement = statement.join(Country, DataSource.country_id == Country.id).where(
            column == value
        )
    if category:
        statement = statement.where(DataSource.category == category)
    if frequency:
        statement = statement.where(DataSource.frequency == frequency)
    if active_only:
        statement = statement.where(DataSource.is_active.is_(True))

    sources = list(session.scalars(statement))
    window = sources[pagination.offset : pagination.offset + pagination.limit]
    return Page.build(
        [DataSourceRead.model_validate(source) for source in window],
        total=len(sources),
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get(
    "/{source_key}",
    response_model=DataSourceRead,
    summary="Get one data source by catalog key",
    responses={404: {"description": "Source not registered"}},
)
def get_one(session: SessionDep, source_key: str) -> DataSourceRead:
    """Return a single data source by its catalog key."""
    source = get_source_by_key(session, source_key)
    if source is None:
        msg = f"Source {source_key!r} is not registered"
        raise ResourceNotFoundError(msg, source_key=source_key)
    return DataSourceRead.model_validate(source)
