"""The web catalog browser: routing/static wiring, and the catalog table.

The six tests below need no database. They cover routing, static-file
wiring, the page's no-database fallback, and the disabled-sources block, so
they run against a plain ``TestClient`` with no seeded session and no
dependency override — the ordinary gate, not the database-gated integration
suite. The catalog itself (name, organization, frequency, indicators,
licence, ``enabled``/``disabled_reason``) comes from ``get_catalog()``,
reading ``sources/catalog.yml``, and needs no database — only the freshness
data does, so ``test_the_catalog_page_renders`` and its neighbours below
genuinely exercise the "database unreachable" branch of the route on a bare
checkout, ``test_the_catalog_lists_every_source_when_the_database_is_down``
pins that branch deterministically with a monkeypatch, and the two
disabled-block tests exercise the catalog-only branch the same way,
independent of whether a real database happens to be reachable in the
environment running the gate.

The two API routes checked below are ``/health`` and ``/metrics``. Only
``/health`` touches no dependency at all. ``/metrics`` now takes a session
via ``SessionDep`` and runs six queries per request, so it belongs here for
a different reason: it degrades instead of failing.
``build_metrics_snapshot`` catches ``SQLAlchemyError``, so with no reachable
database the scrape still answers 200, reporting ``reim_database_up 0`` and
no per-pipeline series. That is a deliberate design decision — the scrape an
operator most needs is the one taken during an outage — and it is what this
test actually pins for ``/metrics``: a 200 regardless of whether the
database is up.

The catalog-freshness tests further down need a live session — the page calls
``build_pipeline_summaries``, which queries the last run per source — so they
are marked ``requires_db`` individually rather than at module scope. That
keeps the six tests above running on a bare checkout with no database.

The final test pins decision D3: views call services and repositories
directly and never the application's own HTTP API. It is deliberately not
``requires_db``, even though it sits textually after the ``requires_db``
block: it needs no data, only that no HTTP call is made, and a guard that
only runs when a database happens to be present is not run in the gate that
matters. Nothing else in this suite would catch a page that fetched its own
API instead — every other test only checks what came back, not how it was
produced. It covers all four routes this application serves — ``/``,
``/runs``, ``/runs/{run_id}`` and ``/series`` — not only the catalog page it
was written alongside: the rule it pins applies to every view, and a route
added after this test would otherwise go unchecked by it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.dependencies import get_db
from apps.api.main import create_app
from reim.core.constants import AccessType, Frequency, IndicatorCategory, SourceFormat
from reim.domain.sources.catalog import SourceCatalog, SourceEntry, get_catalog, reset_catalog_cache
from tests.conftest import requires_db


def test_the_catalog_page_renders() -> None:
    """The skeleton serves HTML at the site root, beside the API."""
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "REIM" in response.text


def test_the_api_is_unchanged_by_the_web_surface() -> None:
    """Mounting pages at / must not move or shadow any API route."""
    client = TestClient(create_app())

    assert client.get("/health").status_code == 200
    assert client.get("/metrics").status_code == 200


def test_the_stylesheet_is_served() -> None:
    """No CDN: the one stylesheet ships with the application."""
    client = TestClient(create_app())

    response = client.get("/static/reim.css")

    assert response.status_code == 200
    assert "css" in response.headers["content-type"]


def test_the_catalog_lists_every_source_when_the_database_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The catalog is the page's spine; only freshness needs the database.

    There is no separate connectivity check to patch any more (finding 3):
    the route discovers the database is gone by trying to use it, inside
    ``load_pipeline_summaries``. So this pins the branch the same way a real
    outage would trigger it — the query itself failing — by making
    ``build_pipeline_summaries`` raise the exception a lost connection
    surfaces as.
    """

    def _raise_as_if_the_database_were_down(*args: object, **kwargs: object) -> None:
        raise SQLAlchemyError("database is down")

    monkeypatch.setattr(
        "apps.web.routes.build_pipeline_summaries", _raise_as_if_the_database_were_down
    )
    client = TestClient(create_app())

    body = client.get("/").text

    catalog = get_catalog()
    for entry in catalog.sources:
        assert entry.name in body, f"{entry.name} is missing from the page"
    assert "freshness is unavailable" in body.lower()


def test_the_disabled_block_states_its_own_emptiness() -> None:
    """Nothing is disabled today: 23 sources, 23 enabled.

    An empty section reads as a failed load. The page must say the absence
    out loud, so a reader can tell "none" from "did not render".
    """
    client = TestClient(create_app())

    body = client.get("/").text

    assert all(entry.enabled for entry in get_catalog().sources)
    assert "No source is disabled" in body


def _disabled_test_entry() -> SourceEntry:
    """A catalog entry that is disabled, with a documented reason.

    ``disabled_reason`` has never run against real data — v0.1.0 shipped the
    BCN exchange-rate connector disabled and v0.2.0 unblocked it, leaving the
    field in the schema with nothing exercising it. Every field below but
    ``enabled``/``disabled_reason`` is arbitrary but valid, matching the
    shape of a real ``sources/catalog.yml`` entry.
    """
    return SourceEntry(
        key="disabled_test_source",
        name="Disabled test source",
        organization="WORLDBANK",
        category=IndicatorCategory.EXCHANGE_RATE,
        access_type=AccessType.HTTP_API,
        frequency=Frequency.ANNUAL,
        format=SourceFormat.JSON,
        base_url="https://example.invalid",
        connector="reim.ingestion.connectors.test.disabled_test_source",
        indicators=["ni_exchange_rate_official_annual_avg"],
        enabled=False,
        disabled_reason="Blocked pending a data-sharing agreement with the publisher.",
    )


def test_a_disabled_source_renders_its_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """`disabled_reason` has never run against real data — so construct it.

    v0.1.0 shipped the BCN connector disabled and v0.2.0 unblocked it,
    leaving the field in the schema with nothing exercising it. This is the
    only test that proves the block works when there is something to put in
    it.

    Introduced by monkeypatching ``load_catalog`` (the function
    ``get_catalog`` calls under its ``lru_cache``) and clearing that cache,
    rather than adding a test-only parameter to the view: the route calls
    ``get_catalog()`` directly, and both it and this test resolve the same
    name from ``reim.domain.sources.catalog``, so patching there reaches the
    view without touching its signature. ``reset_catalog_cache()`` runs both
    before (to force this fake catalog to load) and after, in a ``finally``,
    so later tests see the real one again.
    """
    entry = _disabled_test_entry()
    catalog = SourceCatalog(sources=[entry])
    monkeypatch.setattr("reim.domain.sources.catalog.load_catalog", lambda *a, **k: catalog)
    reset_catalog_cache()
    try:
        client = TestClient(create_app())
        body = client.get("/").text
    finally:
        reset_catalog_cache()

    assert entry.key in body
    assert entry.disabled_reason is not None
    assert entry.disabled_reason in body
    assert "No source is disabled" not in body


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    """A test client backed by a live, empty test schema."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@requires_db
def test_every_catalog_source_appears(client: TestClient) -> None:
    """All 23, not a page of them: this is a catalog, not a feed."""
    body = client.get("/").text

    catalog = get_catalog()
    assert len(catalog.sources) == 23
    for entry in catalog.sources:
        assert entry.name in body, f"{entry.name} is missing from the page"


@requires_db
def test_each_source_shows_its_organization_and_frequency(client: TestClient) -> None:
    """The two facts that say what a row actually is."""
    body = client.get("/").text

    assert "CEPAL" in body
    assert "BANGUAT" in body
    assert "quarterly" in body.lower()
    assert "daily" in body.lower()


@requires_db
def test_a_source_links_to_its_documentation(client: TestClient) -> None:
    """Every figure links back — the rule the project applies to charts."""
    body = client.get("/").text

    entry = get_catalog().get("cepalstat_bop_quarterly")
    assert entry.documentation_url is not None
    assert str(entry.documentation_url) in body


@requires_db
def test_freshness_is_shown_per_source(client: TestClient) -> None:
    """A catalog that does not say how old its data is, is a list of promises."""
    body = client.get("/").text

    assert "Last success" in body or "last success" in body.lower()


@requires_db
def test_a_source_that_never_ran_says_so(client: TestClient) -> None:
    """Never-run and ran-and-failed are different states and must read that way."""
    body = client.get("/").text

    # The seeded fixture runs no pipelines, so every source is in this state.
    assert "Never" in body or "never" in body


@requires_db
def test_non_open_licences_are_marked(client: TestClient) -> None:
    """Three of REIM's sources forbid redistribution; the page says which."""
    body = client.get("/").text

    imf = get_catalog().get("imf_imts_nicaragua")
    assert imf is not None
    assert imf.license in body


@respx.mock
def test_the_pages_make_no_outbound_http_requests() -> None:
    """Views call services directly; a page fetching the app's own API is wrong.

    This is the D3 guard, and it needs no data — only that no HTTP call is
    made — so it runs on a plain ``TestClient`` with no database and no
    ``requires_db``, unlike its neighbours above: it must run in the
    ordinary gate, the one every change actually goes through, not only when
    a database happens to be present.

    respx is mounted with no routes, so any outbound *httpx* request —
    including one aimed at REIM's own ``/api/v1``, the mistake decision D3
    rules out — raises rather than escaping to the network or looping back
    into the same process. respx patches httpx's transports only: a
    self-call made through ``urllib`` or ``requests`` instead would escape
    it undetected. That gap is accepted here because ``reim/ingestion/http.py``
    — the only HTTP client this codebase uses — is httpx throughout, so
    nothing REIM would plausibly call this with can slip past. This is the
    only test in the suite that would catch a later page calling the
    application's own API instead of its services and repositories directly.

    Covers all four routes the branch added or kept, not only the catalog:
    ``/runs``, ``/runs/{run_id}`` and ``/series`` are exercised the same way,
    with no session override, so a rewrite of any view to fetch its own HTTP
    API instead of calling repositories directly would trip this guard too.
    Unlike its neighbours above, this test has no ``requires_db`` and so
    must pass whether or not a database is reachable, and the detail route
    genuinely has two correct answers depending on that: with a database
    present, a random ``uuid.UUID`` is a real id that does not exist, so
    ``run_detail`` returns 404; with no database, it catches
    ``SQLAlchemyError`` and renders the degraded "cannot be read" page with
    200 instead. Either is proof the request reached the view rather than
    escaping over HTTP, which is all this guard cares about, so the
    assertion accepts both status codes instead of picking one that would
    be false in the other world.

    ``/series`` has no such split: the indicator and country are resolved
    from the in-process registries before any database access, so a real
    code for each resolves regardless of the database, and any query that
    then fails is caught inside ``load_series_page`` and rendered as the
    "database is not responding" state rather than an error status — 200 in
    both worlds, for the bare form and for a real selection alike.
    """
    client = TestClient(create_app())

    assert client.get("/").status_code == 200
    assert client.get("/runs").status_code == 200
    assert client.get(f"/runs/{uuid.uuid4()}").status_code in {200, 404}
    assert client.get("/series").status_code == 200
    assert client.get("/series?indicator=ni_cpi_inflation_annual&country=NIC").status_code == 200
