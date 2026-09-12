"""REIM's web pages, served from the same application as the API.

Server-rendered rather than a client application, so the project keeps one
language, one linter, one type checker and one test runner, and its deployment
stays the container it already is. See the design document for why that was
chosen over a SPA.

These views call the same service and repository functions the API routers
call. They do **not** issue HTTP requests to the application's own API: a
process requesting from itself adds a network hop that can fail on its own, a
second serialisation of data already in memory, and an ordering problem at
startup — for nothing. The Pydantic schemas are still the shape handed to the
templates, which is what keeps the two surfaces from drifting apart.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.dependencies import SessionDep
from reim.domain.sources.catalog import SourceEntry, get_catalog
from reim.schemas.pipelines import PipelineSummary
from reim.services.status import build_pipeline_summaries

TEMPLATES_DIRECTORY = Path(__file__).resolve().parent / "templates"
STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"


def _format_freshness(value: datetime | None) -> str:
    """Render a timestamp as a date with its age beside it.

    ``2026-09-09 · 2 days ago`` — "how fresh" is the question this column
    answers, and a bare timestamp makes the reader do the arithmetic.

    ``None`` means the source has never completed a successful run, which is
    a different state from an old timestamp: it renders as the words "Never
    run" rather than an empty cell, which would be indistinguishable from a
    rendering fault.
    """
    if value is None:
        return "Never run"
    reference = value.date()
    age_days = (datetime.now(UTC).date() - reference).days
    if age_days <= 0:
        age = "today"
    elif age_days == 1:
        age = "yesterday"
    elif age_days < 14:
        age = f"{age_days} days ago"
    elif age_days < 60:
        age = f"{age_days // 7} weeks ago"
    elif age_days < 730:
        age = f"{age_days // 30} months ago"
    else:
        age = f"{age_days // 365} years ago"
    return f"{reference.isoformat()} · {age}"


templates = Jinja2Templates(directory=str(TEMPLATES_DIRECTORY))
templates.env.filters["freshness"] = _format_freshness

router = APIRouter(tags=["web"], include_in_schema=False)


def load_pipeline_summaries(session: Session) -> tuple[bool, dict[str, PipelineSummary]]:
    """Return freshness data keyed by source, and whether the database answered.

    There is no separate connectivity check beforehand: a pre-check reachable
    at time T tells nothing about a query issued at T+1ms, and would add a
    second connection attempt to every request on top of the one ``session``
    already opens on first use. So this calls ``build_pipeline_summaries``
    directly and treats its failure as the answer, which also means there is
    exactly one place — and one moment — where "the database is unreachable"
    is decided. ``SQLAlchemyError`` is what a lost connection or a failed
    query surfaces as (a ``psycopg`` connection failure arrives wrapped as
    ``sqlalchemy.exc.OperationalError``, a subclass of it); anything else is a
    real bug and is left to propagate.

    A view with a third data source alongside pipeline summaries calls this
    once for its degradation and keeps its own dict for the other source,
    rather than growing a second copy of this try/except.
    """
    try:
        summaries = build_pipeline_summaries(session)
    except SQLAlchemyError:
        return False, {}
    return True, {summary.source_key: summary for summary in summaries}


@router.get("/", response_class=HTMLResponse)
def catalog(request: Request, session: SessionDep) -> HTMLResponse:
    """The catalog browser: what REIM holds, how fresh it is, what is disabled.

    The catalog itself — name, organization, frequency, indicators, licence —
    comes entirely from ``get_catalog()``, reading ``sources/catalog.yml``,
    and needs no database. Only the freshness data (``PipelineSummary``, from
    ``build_pipeline_summaries``) needs a live session, so
    ``load_pipeline_summaries`` attaches it per row only once the database
    answers, discovered by trying rather than by a separate check beforehand
    (see its docstring for why). When it does not, the full catalog still
    renders — all rows, every column the catalog itself supplies — and the
    template says so plainly, as a status notice sitting directly above the
    table, rather than rendering nothing: an empty table would be
    indistinguishable from a broken page (decision D5 makes the same call for
    disabled sources). A row whose summary is ``None`` renders those columns
    as "—", not "Never run": the database being unreachable is a different
    state from a source that has genuinely never succeeded.

    A second block, below the table, lists what is disabled and why. The
    catalog entry is the authority for ``enabled``/``disabled_reason`` — not
    the ``PipelineSummary`` also carrying those two fields — because it needs
    no database, so this block renders identically whether or not the
    database answers. Today that list is empty (23 sources, 23 enabled); the
    template states that absence explicitly rather than rendering nothing,
    for the same reason decision D5 does for the freshness notice: an empty
    section reads as a failed render, not as a fact about the catalog.
    """
    entries = sorted(get_catalog().sources, key=lambda entry: (entry.organization, entry.key))
    database_available, summaries = load_pipeline_summaries(session)
    rows: list[tuple[PipelineSummary | None, SourceEntry]] = [
        (summaries.get(entry.key), entry) for entry in entries
    ]
    disabled_entries = [entry for entry in entries if not entry.enabled]
    return templates.TemplateResponse(
        request,
        "catalog.html",
        {
            "rows": rows,
            "database_available": database_available,
            "disabled_entries": disabled_entries,
        },
    )
