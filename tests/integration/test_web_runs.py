"""The run-history page: routing, the table, and its three empty states.

These need no database except where marked: the page's "database is
unreachable" branch is reached by making the query raise, which is how a real
outage reaches it, and the "no runs yet" branch needs a live but empty schema.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.dependencies import get_db
from apps.api.main import create_app
from reim.core.constants import PipelineStatus
from reim.database.models import PipelineRun
from reim.domain.sources.catalog import get_catalog
from tests.conftest import requires_db


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    """A test client backed by a live, empty test schema."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _add_run(
    session: Session,
    *,
    pipeline_key: str = "banguat_exchange_rate",
    status: PipelineStatus = PipelineStatus.SUCCESS,
    started_at: datetime | None = None,
    **fields: object,
) -> PipelineRun:
    moment = started_at or datetime.now(UTC)
    run = PipelineRun(
        id=uuid.uuid4(),
        pipeline_key=pipeline_key,
        started_at=moment,
        status=status,
        created_at=moment,
        **fields,
    )
    session.add(run)
    session.flush()
    return run


def test_the_runs_page_is_served() -> None:
    client = TestClient(create_app())

    response = client.get("/runs")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_a_dead_database_is_said_out_loud_not_shown_as_an_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """State one of three: the query itself fails, as a real outage would."""

    def _raise(*args: object, **kwargs: object) -> None:
        raise SQLAlchemyError("database is down")

    monkeypatch.setattr("apps.web.routes.run_repo.list_runs", _raise)
    client = TestClient(create_app())

    body = client.get("/runs").text

    assert "database is not responding" in body.lower()
    assert "no pipeline has run yet" not in body.lower()


@requires_db
def test_an_empty_history_says_nothing_has_run_not_that_it_is_broken(
    client: TestClient,
) -> None:
    """State two of three, and the one a fresh install sees."""
    body = client.get("/runs").text

    assert "No pipeline has run yet" in body
    assert "database is not responding" not in body.lower()


@requires_db
def test_a_run_shows_its_source_status_and_record_counts(
    client: TestClient, session: Session
) -> None:
    """State three: the table, with the facts that make a row worth reading."""
    _add_run(
        session,
        pipeline_key="banguat_exchange_rate",
        status=PipelineStatus.PARTIAL,
        duration_ms=4200,
        records_inserted=17,
        records_updated=3,
        records_rejected=1,
    )

    body = client.get("/runs").text

    assert get_catalog().get("banguat_exchange_rate").name in body
    assert "partial" in body
    assert "4.2 s" in body
    assert "17" in body


@requires_db
def test_a_run_whose_pipeline_left_the_catalog_still_renders(
    client: TestClient, session: Session
) -> None:
    """History outlives the catalog: a removed source must not 500 the page."""
    _add_run(session, pipeline_key="a_source_that_was_removed")

    response = client.get("/runs")

    assert response.status_code == 200
    assert "a_source_that_was_removed" in response.text


@requires_db
def test_the_page_says_it_is_showing_a_bounded_window(client: TestClient, session: Session) -> None:
    """100 runs is not "all runs", and a page that implies otherwise lies."""
    _add_run(session)

    body = client.get("/runs").text

    assert "100" in body


@requires_db
def test_every_listed_run_links_to_its_detail_page(client: TestClient, session: Session) -> None:
    run = _add_run(session)

    body = client.get("/runs").text

    assert f"/runs/{run.id}" in body
