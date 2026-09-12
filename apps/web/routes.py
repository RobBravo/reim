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

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from apps.api.dependencies import SessionDep
from reim.database.session import check_database_connection
from reim.domain.sources.catalog import SourceEntry, get_catalog
from reim.schemas.pipelines import PipelineSummary
from reim.services.status import build_pipeline_summaries

TEMPLATES_DIRECTORY = Path(__file__).resolve().parent / "templates"
STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIRECTORY))

router = APIRouter(tags=["web"], include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
def catalog(request: Request, session: SessionDep) -> HTMLResponse:
    """The catalog browser: what REIM holds, how fresh it is, what is disabled.

    Checks the database before querying it, the same guard ``/ready`` uses:
    the page must still render — header, stylesheet, empty table — when the
    database is down, rather than 500. ``build_pipeline_summaries`` needs a
    live connection for run history, so it only runs once the check passes.
    """
    rows: list[tuple[PipelineSummary, SourceEntry]] = []
    if check_database_connection():
        source_catalog = get_catalog()
        rows = [
            (summary, source_catalog.get(summary.source_key))
            for summary in build_pipeline_summaries(session)
        ]
        rows.sort(key=lambda row: (row[1].organization, row[1].key))
    return templates.TemplateResponse(request, "catalog.html", {"rows": rows})
