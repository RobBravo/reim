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

from reim.core.constants import CheckSeverity, CheckStatus, CheckType, PipelineStatus
from reim.database.models import DataQualityCheck, PipelineRun
from reim.repositories import observations as observation_repo
from reim.repositories import pipeline_runs as run_repo
from reim.repositories import reference as reference_repo
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


def _make_check(
    session: Session,
    *,
    run: PipelineRun,
    check_name: str,
    status: CheckStatus = CheckStatus.FAILED,
) -> None:
    session.add(
        DataQualityCheck(
            id=uuid.uuid4(),
            pipeline_run_id=run.id,
            check_name=check_name,
            check_type=CheckType.COMPLETENESS,
            status=status,
            severity=CheckSeverity.ERROR,
            created_at=run.started_at,
        )
    )
    session.flush()


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
def test_a_crashed_run_does_not_erase_its_siblings_duration(session: Session) -> None:
    """``duration_ms`` is nullable: a run that crashed never got one.

    Postgres ``SUM`` skips nulls when any row in the group has a value, so
    a mixed group cannot detect a missing coalesce; this test verifies the
    more important property: that one run's missing duration doesn't erase
    another run's recorded duration in the same (pipeline, status) group.
    """
    now = datetime.now(UTC)
    _make_run(session, pipeline_key="a", started_at=now, duration_ms=None)
    _make_run(session, pipeline_key="a", started_at=now - timedelta(hours=1), duration_ms=500)

    rows = run_repo.aggregate_runs_by_pipeline(session)

    assert rows[0].duration_ms == 500


@requires_db
def test_a_pipeline_whose_every_run_crashed_totals_zero_not_null(session: Session) -> None:
    """The case the coalesce actually exists for.

    Postgres ``SUM`` skips nulls when any row in the group has a value, so a
    mixed group cannot detect a missing coalesce. Only a group where every
    ``duration_ms`` is null makes the un-coalesced sum return null — and then
    ``int(None)`` raises, and the counter silently stops being exported.
    """
    now = datetime.now(UTC)
    _make_run(session, pipeline_key="a", started_at=now, duration_ms=None)
    _make_run(session, pipeline_key="a", started_at=now - timedelta(hours=1), duration_ms=None)

    rows = run_repo.aggregate_runs_by_pipeline(session)

    assert rows[0].duration_ms == 0


@requires_db
def test_sources_are_summarized_in_one_pass(seeded_session: Session, make_observation) -> None:  # type: ignore[no-untyped-def]
    """Count and newest period for every source, without a query per source."""
    from reim.services.observation_writer import write_observations

    write_observations(
        seeded_session,
        [make_observation(str(year)) for year in (2020, 2021, 2022)],
        connector_version="1.0.0",
    )
    seeded_session.commit()

    source_ids = reference_repo.source_ids_by_key(seeded_session)
    volumes = observation_repo.summarize_sources(seeded_session)
    volume = volumes[source_ids["worldbank_ni_cpi_inflation"]]

    assert volume.observations == 3
    assert volume.latest_period_end is not None
    assert volume.latest_period_end.year == 2022


@requires_db
def test_a_source_holding_nothing_is_absent_rather_than_zero(seeded_session: Session) -> None:
    """Storing nothing and storing rows that cover nothing are different facts.

    The caller turns absence into a missing age series and a zero observation
    count; it cannot make that distinction if the repository flattens it here.
    """
    source_ids = reference_repo.source_ids_by_key(seeded_session)

    volumes = observation_repo.summarize_sources(seeded_session)

    assert volumes == {}
    assert "worldbank_ni_cpi_inflation" in source_ids


@requires_db
def test_every_registered_source_is_keyed_by_its_catalog_key(seeded_session: Session) -> None:
    source_ids = reference_repo.source_ids_by_key(seeded_session)

    assert len(source_ids) >= 23
    assert all(isinstance(value, uuid.UUID) for value in source_ids.values())


@requires_db
def test_the_same_check_failing_in_two_pipelines_is_two_rows(session: Session) -> None:
    """The whole reason this is not ``summarize_failed_checks_by_name``.

    Grouped by name alone, an alert could say a freshness check is failing but
    not which pipeline to look at.
    """
    now = datetime.now(UTC)
    for key in ("a", "b", "a"):
        run = _make_run(session, pipeline_key=key, started_at=now)
        _make_check(session, run=run, check_name="freshness")

    counts = run_repo.summarize_failed_checks_by_pipeline(session)

    assert [(row.pipeline_key, row.failures) for row in counts] == [("a", 2), ("b", 1)]


@requires_db
def test_passing_checks_are_not_counted_as_failures(session: Session) -> None:
    run = _make_run(session, pipeline_key="a", started_at=datetime.now(UTC))
    _make_check(session, run=run, check_name="freshness", status=CheckStatus.PASSED)

    assert run_repo.summarize_failed_checks_by_pipeline(session) == []


@requires_db
def test_failed_check_counts_come_back_in_a_stable_order(session: Session) -> None:
    """Two renders of identical data must produce identical exposition text."""
    now = datetime.now(UTC)
    run = _make_run(session, pipeline_key="a", started_at=now)
    for name in ("range", "freshness", "completeness"):
        _make_check(session, run=run, check_name=name)

    counts = run_repo.summarize_failed_checks_by_pipeline(session)

    assert [row.check_name for row in counts] == ["completeness", "freshness", "range"]
