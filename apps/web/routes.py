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

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.dependencies import SessionDep
from apps.web.charts import CHART_PALETTE, Chart, SeriesRow, build_chart, pivot_cells
from reim.core.exceptions import CatalogError
from reim.domain.countries.registry import (
    COUNTRIES,
    COUNTRIES_BY_ISO2,
    COUNTRIES_BY_ISO3,
    CountryDefinition,
)
from reim.domain.indicators.registry import INDICATORS, INDICATORS_BY_CODE, IndicatorDefinition
from reim.domain.sources.catalog import SourceEntry, get_catalog
from reim.repositories import comparison as comparison_repo
from reim.repositories import pipeline_runs as run_repo
from reim.repositories.comparison import ComparisonQuery, SeriesSummary
from reim.repositories.reference import get_country_by_iso3
from reim.schemas.comparison import assess_comparability, levels_comparable
from reim.schemas.pipelines import (
    FailedCheckGroup,
    PipelineRunDetail,
    PipelineRunRead,
    PipelineSummary,
)
from reim.services.status import build_pipeline_summaries

TEMPLATES_DIRECTORY = Path(__file__).resolve().parent / "templates"
STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"

#: How many runs the history page shows. Roughly four complete sweeps of the
#: 23 pipelines; deeper history is the paginated API's job, and the page says so.
RUN_HISTORY_LIMIT = 100

#: Window for the failed-check trends. Thirty days and not the seven
#: ``SystemStatus`` uses, because these series are ingested infrequently and a
#: block that is always empty stops being read.
TRENDS_WINDOW_DAYS = 30

#: How many distinct periods one chart may draw. Nothing is ever downsampled —
#: REIM does not discard published figures to cheapen a drawing — so a denser
#: range is refused with an explanation instead. The cap bites only on the two
#: daily sources (BCN and Banguat exchange rates): 1,500 points is about four
#: years of daily data, but 125 years of monthly and 375 of quarterly.
PERIOD_LIMIT = 1500


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


def _format_duration(milliseconds: int | None) -> str:
    """Render a run's duration at the precision a reader can act on.

    ``None`` means the run has not finished — a dash, not "0 ms", which would
    claim it finished instantly.

    The units step up so the number stays two or three significant figures:
    a 90-minute backfill reported as "5400000 ms" is a number nobody reads.
    """
    if milliseconds is None:
        return "—"
    if milliseconds < 1000:
        return f"{milliseconds} ms"
    seconds = milliseconds / 1000
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, remaining_seconds = divmod(int(seconds), 60)
    return f"{minutes}m {remaining_seconds}s"


templates = Jinja2Templates(directory=str(TEMPLATES_DIRECTORY))
templates.env.filters["freshness"] = _format_freshness
templates.env.filters["duration"] = _format_duration
# The palette lives beside ``build_chart`` in charts.py, its only other
# reader, so the stroke a template draws and the colour build_chart's caller
# assigned by request position never drift apart.
templates.env.globals["chart_palette"] = CHART_PALETTE

router = APIRouter(prefix="/legacy", tags=["web"], include_in_schema=False)


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
    database answers. Today that list is empty (25 sources, 25 enabled); the
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


@dataclass(frozen=True)
class RunsPageData:
    """Everything ``/runs`` renders, loaded together or not at all."""

    runs: list[PipelineRunRead]
    runs_in_window: int
    failed_checks: list[FailedCheckGroup]


def load_runs_page(session: Session) -> RunsPageData | None:
    """Return the history page's data, or ``None`` when the database is out.

    Three queries share one ``try``: the page has nothing to show if any of
    them fails, so there is no partial state worth rendering, and one
    ``except`` means one place decides "unreachable" — the same argument
    ``load_pipeline_summaries`` makes, and the reason neither function pings
    the database first. ``None`` rather than a flag because there is no
    meaningful empty ``RunsPageData``: zero runs and no data at all are
    different answers, and the template must not be able to confuse them.
    """
    since = datetime.now(UTC) - timedelta(days=TRENDS_WINDOW_DAYS)
    try:
        runs = run_repo.list_runs(session, limit=RUN_HISTORY_LIMIT)
        runs_in_window = run_repo.count_runs(session, since=since)
        failed_checks = run_repo.summarize_failed_checks_by_name(session, since=since)
    except SQLAlchemyError:
        return None
    return RunsPageData(
        runs=[PipelineRunRead.model_validate(run) for run in runs],
        runs_in_window=runs_in_window,
        failed_checks=failed_checks,
    )


def source_name_for(pipeline_key: str) -> str:
    """The catalog's name for a run's pipeline, falling back to the key.

    History outlives the catalog: a source removed from ``sources/catalog.yml``
    keeps its runs in the database, and ``SourceCatalog.get`` raises
    ``CatalogError`` for a key it does not know
    (``reim/domain/sources/catalog.py:160-170``) rather than returning
    ``None``. Falling back to the raw key keeps that row readable instead of
    failing a page whose whole job is to show history.
    """
    try:
        return get_catalog().get(pipeline_key).name
    except CatalogError:
        return pipeline_key


@router.get("/runs", response_class=HTMLResponse)
def runs(request: Request, session: SessionDep) -> HTMLResponse:
    """Run history across every pipeline, newest first.

    Three states the table must never conflate, because they call for three
    different actions: the database is unreachable (investigate the database),
    nothing has run (start the scheduler), and runs exist (read them). The
    template gives each its own sentence.
    """
    data = load_runs_page(session)
    rows = (
        [(run, source_name_for(run.pipeline_key)) for run in data.runs] if data is not None else []
    )
    return templates.TemplateResponse(
        request,
        "runs.html",
        {
            "data": data,
            "rows": rows,
            "history_limit": RUN_HISTORY_LIMIT,
            "window_days": TRENDS_WINDOW_DAYS,
        },
    )


@router.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(request: Request, session: SessionDep, run_id: str) -> HTMLResponse:
    """One run in full: every counter, its error, its metadata, its checks.

    ``run_id`` is a ``str`` and parsed here rather than annotated ``uuid.UUID``
    on purpose. A ``UUID`` annotation hands validation to FastAPI, whose
    ``RequestValidationError`` handler returns a JSON envelope — correct for
    the API, useless to a browser. Both a malformed identifier and an unknown
    run are the same thing to a reader ("that run is not here"), so both get
    the same HTML page with status 404.

    The view never raises ``ResourceNotFoundError`` the way
    ``apps/api/routers/pipelines.py`` does, because every handler in
    ``apps/api/errors.py`` answers in JSON unconditionally. Teaching those
    handlers to negotiate content would make every API error path carry a
    branch that exists for two view functions.
    """
    try:
        identifier = uuid.UUID(run_id)
    except ValueError:
        return _run_not_found(request, run_id)

    try:
        run = run_repo.get_run(session, identifier)
    except SQLAlchemyError:
        return templates.TemplateResponse(request, "run_detail.html", {"run": None})

    if run is None:
        return _run_not_found(request, run_id)

    detail = PipelineRunDetail.model_validate(run)
    return templates.TemplateResponse(
        request,
        "run_detail.html",
        {"run": detail, "source_name": source_name_for(detail.pipeline_key)},
    )


def _run_not_found(request: Request, run_id: str) -> HTMLResponse:
    """The 404 page, for a malformed identifier and an unknown run alike."""
    return templates.TemplateResponse(
        request, "run_not_found.html", {"run_id": run_id}, status_code=404
    )


@dataclass(frozen=True)
class SeriesPageData:
    """Everything ``/series`` draws once a selection resolves."""

    indicator: IndicatorDefinition
    countries: list[CountryDefinition]
    rows: list[SeriesRow]
    summaries: list[SeriesSummary]
    comparable: bool
    levels_comparable: bool
    notes: list[str]
    total_periods: int
    #: The overlaid case: one shared axis, filled only when ``comparable`` and
    #: ``levels_comparable`` both hold and no country is ``undrawable``.
    chart: Chart | None
    #: The small-multiple case: one independently-scaled panel per drawable
    #: country. Filled instead of ``chart`` whenever the countries may not
    #: honestly share one axis. A panel is itself ``None`` when its country
    #: has no plottable values, the same case ``build_chart`` already reports
    #: that way for the overlay.
    panels: list[tuple[CountryDefinition, Chart | None]]
    #: Countries excluded from both ``chart`` and ``panels`` because their own
    #: series carries more than one unit — a unit switch within one country's
    #: values, which no single axis, shared or its own, can honestly draw.
    undrawable: list[tuple[CountryDefinition, tuple[str, ...]]]


def load_series_page(
    session: Session,
    indicator: IndicatorDefinition,
    countries: list[CountryDefinition],
    date_from: date | None,
    date_to: date | None,
) -> SeriesPageData | None:
    """Return the page's data, or ``None`` when the database did not answer.

    Four queries share one ``try``: with any of them failing there is no
    partial page worth rendering, and one ``except`` means one place decides
    "unreachable" — the same argument ``load_pipeline_summaries`` and
    ``load_runs_page`` make, and the reason none of them pings the database
    first.

    ``total_periods`` is counted before the cells are fetched so the page can
    say how dense a range is even when it declines to draw it.
    """
    try:
        resolved = [get_country_by_iso3(session, country.iso3) for country in countries]
        query = ComparisonQuery(
            indicator_code=indicator.code,
            country_ids=tuple(row.id for row in resolved if row is not None),
            period_start_from=date_from,
            period_start_to=date_to,
        )
        total_periods = comparison_repo.count_comparison_periods(session, query)
        cells = (
            comparison_repo.fetch_comparison_cells(
                session, query, limit=PERIOD_LIMIT, offset=0, descending=False
            )
            if total_periods <= PERIOD_LIMIT
            else []
        )
        summaries = comparison_repo.summarise_series(
            session, query, [row for row in resolved if row is not None]
        )
    except SQLAlchemyError:
        return None

    definition = INDICATORS_BY_CODE.get(indicator.code)
    comparable, notes = assess_comparability(summaries, definition)
    levels_ok = levels_comparable(definition)
    rows = pivot_cells(cells, [country.iso3 for country in countries])

    # A country whose own series crosses a unit change (spec D4) cannot be
    # rescued by any axis, shared or its own, so it is set aside before the
    # comparable/levels_comparable decision even runs on the rest.
    summaries_by_iso3 = {summary.country_iso3: summary for summary in summaries}
    undrawable: list[tuple[CountryDefinition, tuple[str, ...]]] = []
    drawable_countries: list[CountryDefinition] = []
    for country in countries:
        summary = summaries_by_iso3.get(country.iso3)
        if summary is not None and len(summary.units) > 1:
            undrawable.append((country, summary.units))
        else:
            drawable_countries.append(country)

    # Overlay only when levels read across countries and every remaining
    # country can honestly be drawn at all; small multiples own every other
    # case, including "no plottable values", which ``build_chart`` already
    # reports as ``None``.
    chart: Chart | None = None
    panels: list[tuple[CountryDefinition, Chart | None]] = []
    if comparable and levels_ok and not undrawable:
        chart = build_chart(rows, [c.iso3 for c in drawable_countries])
    else:
        panels = [(country, build_chart(rows, [country.iso3])) for country in drawable_countries]

    return SeriesPageData(
        indicator=indicator,
        countries=countries,
        rows=rows,
        summaries=summaries,
        comparable=comparable,
        levels_comparable=levels_ok,
        notes=notes,
        total_periods=total_periods,
        chart=chart,
        panels=panels,
        undrawable=undrawable,
    )


@router.get("/series", response_class=HTMLResponse)
def series(
    request: Request,
    session: SessionDep,
    indicator: str | None = None,
    country: Annotated[list[str] | None, Query()] = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> HTMLResponse:
    """One indicator over time across several countries.

    The indicator and the countries are resolved from the in-process
    registries **before** any database access, so a mistyped code answers with
    a proper 404 page even when PostgreSQL is unreachable. The view never
    raises ``ResourceNotFoundError``: every handler in ``apps/api/errors.py``
    answers in JSON, which is right for the API and useless to a browser.
    """
    context: dict[str, object] = {
        "indicator_options": INDICATORS,
        "country_options": COUNTRIES,
        "selection": {
            "indicator": indicator,
            "country": country or [],
            "date_from": date_from,
            "date_to": date_to,
        },
        "period_limit": PERIOD_LIMIT,
        "date_range_invalid": False,
        "data": None,
    }

    if not indicator or not country:
        # State 1: nothing chosen yet. Not an error, and not an empty chart.
        return templates.TemplateResponse(request, "series.html", context)

    if date_from is not None and date_to is not None and date_from > date_to:
        # An inverted range: needs no database to answer, and must not share
        # wording with "holds no data" — the country may well hold data, the
        # range as given simply cannot select any of it.
        context["date_range_invalid"] = True
        return templates.TemplateResponse(request, "series.html", context)

    definition = INDICATORS_BY_CODE.get(indicator)
    if definition is None:
        return _series_not_found(request, "indicator", indicator)

    countries: list[CountryDefinition] = []
    seen: set[str] = set()
    for code in country:
        value = code.upper()
        found = COUNTRIES_BY_ISO2.get(value) if len(value) == 2 else COUNTRIES_BY_ISO3.get(value)
        if found is None:
            return _series_not_found(request, "country", value)
        if found.iso3 not in seen:
            seen.add(found.iso3)
            countries.append(found)

    context["data"] = load_series_page(session, definition, countries, date_from, date_to)
    context["selection"] = {
        "indicator": indicator,
        "country": [c.iso3 for c in countries],
        "date_from": date_from,
        "date_to": date_to,
    }
    return templates.TemplateResponse(request, "series.html", context)


def _series_not_found(request: Request, kind: str, value: str) -> HTMLResponse:
    """States 3 and 4 — an unregistered indicator or country, named as such."""
    return templates.TemplateResponse(
        request, "series_not_found.html", {"kind": kind, "value": value}, status_code=404
    )
