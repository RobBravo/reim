"""The run-history page: routing, the table, and its three empty states.

These need no database except where marked: the page's "database is
unreachable" branch is reached by making the query raise, which is how a real
outage reaches it, and the "no runs yet" branch needs a live but empty schema.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.dependencies import get_db
from apps.api.main import create_app
from reim.core.constants import CheckSeverity, CheckStatus, CheckType, PipelineStatus
from reim.database.models import DataQualityCheck, PipelineRun
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


@requires_db
def test_no_runs_in_the_window_is_not_reported_as_no_failures(
    client: TestClient, session: Session
) -> None:
    """The distinction the whole block exists for.

    A pipeline that stopped running 90 days ago produces no failed checks in
    a 30-day window — identical output to a pipeline that ran perfectly, and
    the opposite situation. One says "investigate", the other says "fine".
    """
    _add_run(session, started_at=datetime.now(UTC) - timedelta(days=90))

    body = client.get("/runs").text

    assert "No pipeline ran in the last 30 days" in body
    assert "no failed checks" not in body.lower()


@requires_db
def test_runs_without_failures_report_how_many_ran(client: TestClient, session: Session) -> None:
    """ "Healthy" is only meaningful with the evidence beside it."""
    _add_run(session, started_at=datetime.now(UTC) - timedelta(days=1))
    _add_run(session, started_at=datetime.now(UTC) - timedelta(days=2))

    body = client.get("/runs").text

    assert "2 runs in the last 30 days" in body
    assert "no failed checks" in body.lower()
    assert "No pipeline ran in the last 30 days" not in body


@requires_db
def test_a_single_run_without_failures_is_not_mispluralized(
    client: TestClient, session: Session
) -> None:
    """The unpluralized "1 runs" reads as a rendering fault."""
    _add_run(session, started_at=datetime.now(UTC) - timedelta(days=1))

    body = client.get("/runs").text

    assert "1 run in the last 30 days" in body
    assert "1 runs in the last 30 days" not in body


@requires_db
def test_a_failing_check_created_inside_the_window_wins_even_if_its_run_started_outside_it(
    client: TestClient, session: Session
) -> None:
    """The straddling case ``count_runs`` and ``summarize_failed_checks_by_name``
    can disagree on: ``count_runs`` windows on ``PipelineRun.started_at``,
    the failed-check query on ``DataQualityCheck.created_at``. A run that
    started outside the 30-day window but whose check was created inside it
    must still surface the failure — never hidden behind "no pipeline ran".
    """
    run = _add_run(session, started_at=datetime.now(UTC) - timedelta(days=31))
    session.add(
        DataQualityCheck(
            id=uuid.uuid4(),
            pipeline_run_id=run.id,
            check_name="freshness_within_threshold",
            check_type=CheckType.TIMELINESS,
            status=CheckStatus.FAILED,
            severity=CheckSeverity.ERROR,
            created_at=datetime.now(UTC) - timedelta(days=29),
        )
    )
    session.flush()

    body = client.get("/runs").text

    assert "freshness_within_threshold" in body
    assert "No pipeline ran in the last 30 days" not in body


@requires_db
def test_a_failing_check_is_named_counted_and_dated(client: TestClient, session: Session) -> None:
    now = datetime.now(UTC)
    for offset in range(1, 14):
        run = _add_run(session, started_at=now - timedelta(days=offset))
        session.add(
            DataQualityCheck(
                id=uuid.uuid4(),
                pipeline_run_id=run.id,
                check_name="freshness_within_threshold",
                check_type=CheckType.TIMELINESS,
                status=CheckStatus.FAILED,
                severity=CheckSeverity.ERROR,
                created_at=now - timedelta(days=offset),
            )
        )
    session.flush()

    body = client.get("/runs").text

    assert "freshness_within_threshold" in body
    assert "13" in body
    assert "error" in body
    assert "banguat_exchange_rate" in body or "Banco de Guatemala" in body
    assert "no failed checks" not in body.lower()


def test_a_malformed_run_id_gets_a_page_not_a_json_envelope() -> None:
    """FastAPI would answer 422 JSON; a browser can do nothing with that."""
    client = TestClient(create_app())

    response = client.get("/runs/not-a-uuid")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "not-a-uuid" in response.text


def test_a_dead_database_is_said_out_loud_not_confused_with_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The detail page's own unreachable-database branch, exercised as a real
    outage would trigger it: the query itself raises, not a pre-check.

    Distinct from the 404 page a malformed or unknown run gets: "the database
    is not responding" and "that run is not here" call for different reader
    actions, so the two pages must not share wording or status code.
    """

    def _raise(*args: object, **kwargs: object) -> None:
        raise SQLAlchemyError("database is down")

    monkeypatch.setattr("apps.web.routes.run_repo.get_run", _raise)
    client = TestClient(create_app())

    response = client.get(f"/runs/{uuid.uuid4()}")

    assert response.status_code == 200
    assert "this run cannot be read" in response.text.lower()
    assert "no pipeline run is recorded" not in response.text.lower()
    assert "run not found" not in response.text.lower()


@requires_db
def test_an_unknown_run_gets_the_same_page(client: TestClient) -> None:
    unknown = uuid.uuid4()

    response = client.get(f"/runs/{unknown}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")


@requires_db
def test_a_run_detail_shows_all_five_counters(client: TestClient, session: Session) -> None:
    """Extracted and unchanged appear nowhere else in the web surface.

    ``extracted`` against the other four is how a reader sees rows going
    missing, which is precisely what the overview's three counters hide.
    """
    run = _add_run(
        session,
        records_extracted=100,
        records_inserted=60,
        records_updated=20,
        records_unchanged=15,
        records_rejected=5,
    )

    body = client.get(f"/runs/{run.id}").text

    for count in ("100", "60", "20", "15", "5"):
        assert count in body


@requires_db
def test_a_failed_run_shows_its_error(client: TestClient, session: Session) -> None:
    run = _add_run(
        session,
        status=PipelineStatus.FAILED,
        error_type="ConnectorTimeout",
        error_message="Banguat did not answer within 30s",
    )

    body = client.get(f"/runs/{run.id}").text

    assert "ConnectorTimeout" in body
    assert "Banguat did not answer within 30s" in body


@requires_db
def test_a_successful_run_shows_no_error_block(client: TestClient, session: Session) -> None:
    run = _add_run(session, status=PipelineStatus.SUCCESS)

    body = client.get(f"/runs/{run.id}").text

    assert "<h3>Error</h3>" not in body


@requires_db
def test_run_metadata_is_shown_when_the_connector_recorded_any(
    client: TestClient, session: Session
) -> None:
    run = _add_run(session, run_metadata={"connector_key": "banguat_exchange_rate"})

    body = client.get(f"/runs/{run.id}").text

    assert "connector_key" in body
    assert "banguat_exchange_rate" in body


@requires_db
def test_the_checks_a_run_produced_are_listed(client: TestClient, session: Session) -> None:
    run = _add_run(session)
    session.add(
        DataQualityCheck(
            id=uuid.uuid4(),
            pipeline_run_id=run.id,
            check_name="value_within_range",
            check_type=CheckType.VALIDITY,
            status=CheckStatus.FAILED,
            severity=CheckSeverity.ERROR,
            indicator_code="gt_exchange_rate_official_daily",
            period_label="2026-09-01",
            expected_value="<= 8.0",
            actual_value="41.7",
            created_at=datetime.now(UTC),
        )
    )
    session.flush()

    body = client.get(f"/runs/{run.id}").text

    assert "value_within_range" in body
    assert "gt_exchange_rate_official_daily" in body
    assert "41.7" in body


@requires_db
def test_a_run_with_no_checks_says_so(client: TestClient, session: Session) -> None:
    """An empty table reads as a broken page; the words read as a fact."""
    run = _add_run(session)

    body = client.get(f"/runs/{run.id}").text

    assert "recorded no quality checks" in body.lower()


def test_both_pages_are_reachable_from_the_navigation() -> None:
    """A page nobody can click is a page nobody reads.

    Asserted on the ``href`` attribute rather than on rendered text, because
    that is the one place in this file where an attribute *is* the fact
    under test: a navigation link's reachability has no rendered-text form
    to assert on instead.
    """
    client = TestClient(create_app())

    for path in ("/", "/runs"):
        body = client.get(path).text
        assert 'href="/runs"' in body
        assert 'href="/"' in body
