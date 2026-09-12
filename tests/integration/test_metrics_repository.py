"""The grouped aggregates behind ``/metrics``, against real PostgreSQL.

``DISTINCT ON`` is PostgreSQL syntax and the nullable-``duration_ms`` sum is
PostgreSQL semantics, so these run against the database rather than being
mocked into agreement with themselves. Each one replaces a per-source loop, so
the assertions are about the grouping being right, not about speed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from reim.core.constants import PipelineStatus
from reim.database.models import PipelineRun
from reim.repositories import pipeline_runs as run_repo
from tests.conftest import requires_db


def _make_run(
    session: Session,
    *,
    pipeline_key: str,
    started_at: datetime,
    status: PipelineStatus = PipelineStatus.SUCCESS,
    duration_ms: int | None = 100,
    inserted: int = 0,
    unchanged: int = 0,
) -> PipelineRun:
    run = PipelineRun(
        id=uuid.uuid4(),
        pipeline_key=pipeline_key,
        started_at=started_at,
        status=status,
        duration_ms=duration_ms,
        records_inserted=inserted,
        records_unchanged=unchanged,
        created_at=started_at,
    )
    session.add(run)
    session.flush()
    return run


@requires_db
def test_the_latest_run_per_pipeline_is_the_newest_one(session: Session) -> None:
    now = datetime.now(UTC)
    _make_run(session, pipeline_key="a", started_at=now - timedelta(days=2))
    newest = _make_run(session, pipeline_key="a", started_at=now)
    _make_run(session, pipeline_key="b", started_at=now - timedelta(days=1))

    latest = run_repo.latest_runs_by_pipeline(session)

    assert set(latest) == {"a", "b"}
    assert latest["a"].id == newest.id


@requires_db
def test_the_latest_successful_run_accepts_partial_and_skips_failures(
    session: Session,
) -> None:
    """``partial`` wrote data, so it counts as a success for freshness."""
    now = datetime.now(UTC)
    partial = _make_run(
        session,
        pipeline_key="a",
        started_at=now - timedelta(hours=1),
        status=PipelineStatus.PARTIAL,
    )
    _make_run(session, pipeline_key="a", started_at=now, status=PipelineStatus.FAILED)

    latest = run_repo.latest_successful_runs_by_pipeline(session)

    assert latest["a"].id == partial.id


@requires_db
def test_a_pipeline_with_no_successful_run_is_absent_not_null(session: Session) -> None:
    """Absence is what the caller turns into a missing series, not a zero."""
    _make_run(
        session,
        pipeline_key="a",
        started_at=datetime.now(UTC),
        status=PipelineStatus.FAILED,
    )

    assert run_repo.latest_successful_runs_by_pipeline(session) == {}
    assert set(run_repo.latest_runs_by_pipeline(session)) == {"a"}


@requires_db
def test_the_totals_cover_every_run_not_only_the_last(session: Session) -> None:
    now = datetime.now(UTC)
    for index in range(3):
        _make_run(
            session,
            pipeline_key="a",
            started_at=now - timedelta(hours=index),
            duration_ms=200,
            inserted=10,
        )

    rows = run_repo.aggregate_runs_by_pipeline(session)

    assert len(rows) == 1
    assert rows[0].runs == 3
    assert rows[0].records_inserted == 30
    assert rows[0].duration_ms == 600


@requires_db
def test_the_totals_are_separated_by_status(session: Session) -> None:
    now = datetime.now(UTC)
    _make_run(session, pipeline_key="a", started_at=now, inserted=5)
    _make_run(
        session,
        pipeline_key="a",
        started_at=now - timedelta(hours=1),
        status=PipelineStatus.FAILED,
        inserted=0,
    )

    by_status = {row.status: row for row in run_repo.aggregate_runs_by_pipeline(session)}

    assert by_status[PipelineStatus.SUCCESS].runs == 1
    assert by_status[PipelineStatus.FAILED].runs == 1
    assert by_status[PipelineStatus.SUCCESS].records_inserted == 5


@requires_db
def test_a_crashed_run_with_no_duration_does_not_null_the_sum(session: Session) -> None:
    """``duration_ms`` is nullable: a run that crashed never got one.

    Without the coalesce, one crashed run makes the whole pipeline's duration
    total null, and the counter silently stops being exported.
    """
    now = datetime.now(UTC)
    _make_run(session, pipeline_key="a", started_at=now, duration_ms=None)
    _make_run(session, pipeline_key="a", started_at=now - timedelta(hours=1), duration_ms=500)

    rows = run_repo.aggregate_runs_by_pipeline(session)

    assert rows[0].duration_ms == 500
