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

TEMPLATES_DIRECTORY = Path(__file__).resolve().parent / "templates"
STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIRECTORY))

router = APIRouter(tags=["web"], include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
def catalog(request: Request) -> HTMLResponse:
    """The catalog browser: what REIM holds, how fresh it is, what is disabled."""
    return templates.TemplateResponse(request, "catalog.html", {})
