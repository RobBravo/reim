"""Cross-country comparison endpoint."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from apps.api.dependencies import PaginationDep, SessionDep
from reim.core.exceptions import ResourceNotFoundError
from reim.database.models import Country
from reim.repositories.comparison import (
    ComparisonQuery,
    count_comparison_periods,
    fetch_comparison_cells,
    summarise_series,
)
from reim.repositories.reference import (
    get_country_by_iso2,
    get_country_by_iso3,
    get_indicator_by_code,
)
from reim.schemas.common import PageMeta
from reim.schemas.comparison import (
    ComparisonIndicator,
    ComparisonResponse,
    ComparisonRow,
    ComparisonSeries,
    assess_comparability,
)

router = APIRouter(prefix="/api/v1/compare", tags=["comparison"])


def _resolve_countries(session: Session, codes: list[str]) -> list[Country]:
    """Resolve ISO-2 or ISO-3 codes to countries, preserving request order.

    Duplicates are dropped, so ``?country=NI&country=NI`` yields one column
    rather than two identical ones.

    Raises:
        ResourceNotFoundError: A code names no registered country.
    """
    resolved: list[Country] = []
    seen: set[str] = set()
    for code in codes:
        value = code.upper()
        country = (
            get_country_by_iso2(session, value)
            if len(value) == 2
            else get_country_by_iso3(session, value)
        )
        if country is None:
            msg = f"Country {value!r} is not registered"
            raise ResourceNotFoundError(msg, country=value)
        if country.iso3 not in seen:
            seen.add(country.iso3)
            resolved.append(country)
    return resolved


@router.get(
    "",
    response_model=ComparisonResponse,
    summary="Compare one indicator across countries",
)
def compare(
    session: SessionDep,
    pagination: PaginationDep,
    indicator: Annotated[str, Query(description="REIM indicator code.")],
    country: Annotated[
        list[str],
        Query(min_length=2, max_length=20, description="ISO alpha-2 or alpha-3 codes."),
    ],
    date_from: Annotated[
        date | None, Query(description="Earliest period start, inclusive (YYYY-MM-DD).")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="Latest period start, inclusive (YYYY-MM-DD).")
    ] = None,
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
) -> ComparisonResponse:
    """Return one indicator across several countries, aligned by period.

    Every row carries an entry for every requested country, ``null`` where that
    country publishes no figure: a gap is stated in the payload rather than
    inferred from a missing key.
    """
    definition = get_indicator_by_code(session, indicator)
    if definition is None:
        msg = f"Indicator {indicator!r} is not registered"
        raise ResourceNotFoundError(msg, indicator=indicator)

    countries = _resolve_countries(session, country)
    query = ComparisonQuery(
        indicator_code=definition.code,
        country_ids=tuple(c.id for c in countries),
        period_start_from=date_from,
        period_start_to=date_to,
    )

    total = count_comparison_periods(session, query)
    cells = fetch_comparison_cells(
        session,
        query,
        limit=pagination.limit,
        offset=pagination.offset,
        descending=order == "desc",
    )
    summaries = summarise_series(session, query, countries)
    comparable, notes = assess_comparability(summaries)

    requested = [c.iso3 for c in countries]
    rows: list[ComparisonRow] = []
    seen: dict[str, ComparisonRow] = {}
    for cell in cells:
        row = seen.get(cell.period_label)
        if row is None:
            row = ComparisonRow(
                period_start=cell.period_start,
                period_end=cell.period_end,
                period_label=cell.period_label,
                values=dict.fromkeys(requested),
            )
            seen[cell.period_label] = row
            rows.append(row)
        row.values[cell.country_iso3] = cell.value_numeric

    return ComparisonResponse(
        meta=PageMeta(
            total=total,
            limit=pagination.limit,
            offset=pagination.offset,
            returned=len(rows),
            has_more=pagination.offset + len(rows) < total,
        ),
        indicator=ComparisonIndicator(
            code=definition.code,
            name=definition.name,
            frequency=definition.frequency,
        ),
        comparable=comparable,
        comparability_notes=notes,
        series=[ComparisonSeries.model_validate(s) for s in summaries],
        data=rows,
    )
