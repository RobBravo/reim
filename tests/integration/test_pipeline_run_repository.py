"""The run window and the failed-check aggregate, against real PostgreSQL.

``array_agg`` and ``DISTINCT`` inside an aggregate are PostgreSQL behaviour,
not SQLAlchemy behaviour, so these run against the real database rather than
being mocked into agreement with themselves.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from reim.core.constants import CheckSeverity, CheckStatus, CheckType, PipelineStatus
from reim.database.models import DataQualityCheck, PipelineRun
from reim.repositories import pipeline_runs as run_repo
from tests.conftest import requires_db


def _make_run(session: Session, *, pipeline_key: str, started_at: datetime) -> PipelineRun:
    run = PipelineRun(
        id=uuid.uuid4(),
        pipeline_key=pipeline_key,
        started_at=started_at,
        status=PipelineStatus.SUCCESS,
        created_at=started_at,
    )
    session.add(run)
    session.flush()
    return run


def _make_check(
    session: Session,
    *,
    run: PipelineRun,
    check_name: str,
    severity: CheckSeverity,
    created_at: datetime,
    status: CheckStatus = CheckStatus.FAILED,
) -> None:
    session.add(
        DataQualityCheck(
            id=uuid.uuid4(),
            pipeline_run_id=run.id,
            check_name=check_name,
            check_type=CheckType.COMPLETENESS,
            status=status,
            severity=severity,
            created_at=created_at,
        )
    )
    session.flush()


@requires_db
def test_since_excludes_runs_older_than_the_window(session: Session) -> None:
    now = datetime.now(UTC)
    _make_run(session, pipeline_key="a", started_at=now - timedelta(days=1))
    _make_run(session, pipeline_key="b", started_at=now - timedelta(days=90))

    since = now - timedelta(days=30)

    assert run_repo.count_runs(session, since=since) == 1
    assert run_repo.count_runs(session) == 2
    assert [run.pipeline_key for run in run_repo.list_runs(session, since=since)] == ["a"]


@requires_db
def test_the_aggregate_counts_every_failure_not_a_truncated_page(session: Session) -> None:
    """The reason this is SQL and not a Python fold over ``list_checks``."""
    now = datetime.now(UTC)
    for index in range(250):
        run = _make_run(session, pipeline_key="a", started_at=now - timedelta(minutes=index))
        _make_check(
            session,
            run=run,
            check_name="freshness",
            severity=CheckSeverity.ERROR,
            created_at=now - timedelta(minutes=index),
        )

    groups = run_repo.summarize_failed_checks_by_name(session)

    assert len(groups) == 1
    assert groups[0].failures == 250


@requires_db
def test_the_aggregate_reports_every_pipeline_a_check_failed_in(session: Session) -> None:
    now = datetime.now(UTC)
    for key in ("banguat_exchange_rate", "inide_cpi_monthly", "banguat_exchange_rate"):
        run = _make_run(session, pipeline_key=key, started_at=now)
        _make_check(
            session, run=run, check_name="freshness", severity=CheckSeverity.WARNING, created_at=now
        )

    groups = run_repo.summarize_failed_checks_by_name(session)

    assert groups[0].pipeline_keys == ["banguat_exchange_rate", "inide_cpi_monthly"]


@requires_db
def test_passing_checks_are_not_reported_as_failures(session: Session) -> None:
    now = datetime.now(UTC)
    run = _make_run(session, pipeline_key="a", started_at=now)
    _make_check(
        session,
        run=run,
        check_name="freshness",
        severity=CheckSeverity.ERROR,
        created_at=now,
        status=CheckStatus.PASSED,
    )

    assert run_repo.summarize_failed_checks_by_name(session) == []


@requires_db
def test_the_aggregate_honours_the_window_and_reports_the_latest_failure(
    session: Session,
) -> None:
    now = datetime.now(UTC)
    recent = now - timedelta(days=2)
    old = now - timedelta(days=90)
    for moment in (recent, old):
        run = _make_run(session, pipeline_key="a", started_at=moment)
        _make_check(
            session,
            run=run,
            check_name="freshness",
            severity=CheckSeverity.ERROR,
            created_at=moment,
        )

    groups = run_repo.summarize_failed_checks_by_name(session, since=now - timedelta(days=30))

    assert len(groups) == 1
    assert groups[0].failures == 1
    assert groups[0].last_failed_at.replace(microsecond=0) == recent.replace(microsecond=0)
