"""FastAPI dependencies: database sessions and shared query parameters."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from reim.core.config import Settings, get_settings
from reim.database.session import get_session_factory


def get_db() -> Iterator[Session]:
    """Yield a read-only request-scoped session.

    The API never writes, so the session is rolled back rather than committed;
    that also releases any implicit transaction PostgreSQL opened for the reads.
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


SessionDep = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


class Pagination:
    """Validated pagination parameters, capped by ``REIM_MAX_PAGE_SIZE``."""

    def __init__(
        self,
        limit: Annotated[
            int | None,
            Query(ge=1, description="Rows per page. Defaults to REIM_DEFAULT_PAGE_SIZE."),
        ] = None,
        offset: Annotated[int, Query(ge=0, description="Rows to skip.")] = 0,
    ) -> None:
        settings = get_settings()
        requested = limit if limit is not None else settings.default_page_size
        self.limit = min(requested, settings.max_page_size)
        self.offset = offset


PaginationDep = Annotated[Pagination, Depends(Pagination)]
