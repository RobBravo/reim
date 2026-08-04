"""Country endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from apps.api.dependencies import PaginationDep, SessionDep
from reim.core.exceptions import ResourceNotFoundError
from reim.repositories.reference import get_country_by_iso2, list_countries
from reim.schemas.common import Page
from reim.schemas.reference import CountryRead

router = APIRouter(prefix="/api/v1/countries", tags=["countries"])


@router.get("", response_model=Page[CountryRead], summary="List countries")
def list_all(
    session: SessionDep,
    pagination: PaginationDep,
    active_only: Annotated[
        bool, Query(description="Only countries currently covered by REIM.")
    ] = False,
) -> Page[CountryRead]:
    """List every country registered in REIM."""
    countries = list_countries(session, active_only=active_only)
    window = countries[pagination.offset : pagination.offset + pagination.limit]
    return Page.build(
        [CountryRead.model_validate(country) for country in window],
        total=len(countries),
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get(
    "/{iso2}",
    response_model=CountryRead,
    summary="Get one country by ISO alpha-2 code",
    responses={404: {"description": "Country not registered"}},
)
def get_one(session: SessionDep, iso2: str) -> CountryRead:
    """Return a single country by its ISO-3166 alpha-2 code."""
    country = get_country_by_iso2(session, iso2)
    if country is None:
        msg = f"Country {iso2.upper()!r} is not registered"
        raise ResourceNotFoundError(msg, iso2=iso2.upper())
    return CountryRead.model_validate(country)
