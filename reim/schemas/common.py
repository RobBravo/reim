"""Shared API schemas: pagination envelope and the error contract."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    """Body of every non-2xx response.

    Every failure — domain error, validation error or unhandled exception —
    is rendered in this shape so clients only ever parse one error format.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "code": "not_found",
                "message": "Indicator 'ni_gdp' is not registered",
                "details": {"indicator_code": "ni_gdp"},
            }
        }
    )

    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Human-readable description.")
    details: dict[str, Any] = Field(default_factory=dict, description="Structured context.")


class ErrorResponse(BaseModel):
    """Top-level error envelope."""

    error: ErrorDetail


class PageMeta(BaseModel):
    """Pagination metadata."""

    total: int = Field(description="Total rows matching the filters, ignoring pagination.")
    limit: int = Field(description="Maximum rows returned in this page.")
    offset: int = Field(description="Rows skipped before this page.")
    returned: int = Field(description="Rows actually present in this page.")
    has_more: bool = Field(description="Whether more rows exist beyond this page.")


class Page[T](BaseModel):
    """A paginated collection."""

    meta: PageMeta
    data: list[T]

    @classmethod
    def build(cls, items: list[T], *, total: int, limit: int, offset: int) -> Page[T]:
        """Assemble a page and derive its metadata."""
        return cls(
            meta=PageMeta(
                total=total,
                limit=limit,
                offset=offset,
                returned=len(items),
                has_more=offset + len(items) < total,
            ),
            data=items,
        )
