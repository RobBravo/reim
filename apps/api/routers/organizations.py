"""Organization endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from apps.api.dependencies import PaginationDep, SessionDep
from reim.repositories.reference import list_organizations
from reim.schemas.common import Page
from reim.schemas.reference import OrganizationRead

router = APIRouter(prefix="/api/v1/organizations", tags=["sources"])


@router.get("", response_model=Page[OrganizationRead], summary="List organizations")
def list_all(
    session: SessionDep,
    pagination: PaginationDep,
    country: Annotated[
        str | None, Query(min_length=2, max_length=2, description="ISO alpha-2 filter.")
    ] = None,
) -> Page[OrganizationRead]:
    """List the institutions that publish data into REIM."""
    organizations = list_organizations(session, country_iso2=country)
    window = organizations[pagination.offset : pagination.offset + pagination.limit]
    return Page.build(
        [OrganizationRead.model_validate(org) for org in window],
        total=len(organizations),
        limit=pagination.limit,
        offset=pagination.offset,
    )
