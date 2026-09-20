"""``build_metrics_snapshot``: the figures, the outage, and the query budget.

The snapshot needs a session, so it is tested here; every rendering rule is
tested without one in ``tests/unit/test_metrics_render.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from reim.core.constants import PipelineStatus
from reim.database.models import PipelineRun
from reim.domain.quality.rules import QualityRuleSet
from reim.services.metrics import RECORD_OUTCOMES, build_metrics_snapshot
from tests.conftest import requires_db


def _make_run(
    session: Session,
    *,
    pipeline_key: str,
    started_at: datetime,
    status: PipelineStatus = PipelineStatus.SUCCESS,
    duration_ms: int | None = 2_500,
    inserted: int = 0,
) -> PipelineRun:
    run = PipelineRun(
        id=uuid.uuid4(),
        pipeline_key=pipeline_key,
        started_at=started_at,
        status=status,
        duration_ms=duration_ms,
        records_inserted=inserted,
        created_at=started_at,
    )
    session.add(run)
    session.flush()
    return run


def _for(snapshot, pipeline_key: str):  # type: ignore[no-untyped-def]
    return next(item for item in snapshot.pipelines if item.pipeline_key == pipeline_key)


@requires_db
def test_every_catalog_entry_gets_a_row_even_with_no_runs(seeded_session: Session) -> None:
    """A pipeline that never ran is reported as never having run, not omitted.

    Omitting it would make a pipeline that stopped being scheduled invisible,
    which is the failure an operator most needs to see.
    """
    snapshot = build_metrics_snapshot(seeded_session)

    assert snapshot.database_up is True
    assert len(snapshot.pipelines) == 24
    never_ran = _for(snapshot, "worldbank_ni_cpi_inflation")
    assert never_ran.last_run_at is None
    assert never_ran.last_run_records is None
    assert never_ran.runs_by_status == {}
    assert never_ran.records_total == dict.fromkeys(RECORD_OUTCOMES, 0)


@requires_db
def test_the_last_run_and_the_totals_are_both_reported(seeded_session: Session) -> None:
    now = datetime.now(UTC)
    _make_run(
        seeded_session,
        pipeline_key="worldbank_ni_cpi_inflation",
        started_at=now - timedelta(days=1),
        inserted=7,
    )
    latest = _make_run(
        seeded_session, pipeline_key="worldbank_ni_cpi_inflation", started_at=now, inserted=3
    )
    seeded_session.flush()

    metrics = _for(build_metrics_snapshot(seeded_session), "worldbank_ni_cpi_inflation")

    assert metrics.last_run_at == latest.started_at
    assert metrics.last_run_records is not None
    assert metrics.last_run_records["inserted"] == 3
    assert metrics.records_total["inserted"] == 10
    assert metrics.runs_by_status == {"success": 2}
    assert metrics.duration_ms_total == 5_000


@requires_db
def test_a_failed_last_run_still_reports_the_older_success(seeded_session: Session) -> None:
    now = datetime.now(UTC)
    success = _make_run(
        seeded_session,
        pipeline_key="worldbank_ni_cpi_inflation",
        started_at=now - timedelta(days=3),
    )
    _make_run(
        seeded_session,
        pipeline_key="worldbank_ni_cpi_inflation",
        started_at=now,
        status=PipelineStatus.FAILED,
    )
    seeded_session.flush()

    metrics = _for(build_metrics_snapshot(seeded_session), "worldbank_ni_cpi_inflation")

    assert metrics.last_success_at == success.started_at
    assert metrics.last_run_at != success.started_at


@requires_db
def test_records_and_durations_fold_across_statuses_while_runs_stay_per_status(
    seeded_session: Session,
) -> None:
    """A per-status/cross-status mix-up in ``_fold_aggregates`` is invisible here otherwise.

    ``runs_by_status`` is assigned per status, because ``(pipeline, status)``
    is unique per row the ``GROUP BY pipeline_key, status`` query returns.
    ``records_total`` and ``duration_ms_total`` carry no status label, so they
    are summed across every status instead. Every other test in this file
    gives a pipeline only one status, so summing where the code should assign
    (or the reverse) would still pass all of them. This test gives one
    pipeline two statuses, with different record counts, so that mix-up would
    make it fail.
    """
    now = datetime.now(UTC)
    _make_run(
        seeded_session,
        pipeline_key="worldbank_ni_cpi_inflation",
        started_at=now - timedelta(days=1),
        status=PipelineStatus.SUCCESS,
        duration_ms=2_500,
        inserted=4,
    )
    _make_run(
        seeded_session,
        pipeline_key="worldbank_ni_cpi_inflation",
        started_at=now,
        status=PipelineStatus.FAILED,
        duration_ms=1_500,
        inserted=9,
    )
    seeded_session.flush()

    metrics = _for(build_metrics_snapshot(seeded_session), "worldbank_ni_cpi_inflation")

    assert metrics.runs_by_status == {"success": 1, "failed": 1}
    assert metrics.records_total["inserted"] == 13
    assert metrics.duration_ms_total == 4_000


@requires_db
def test_age_is_measured_from_the_newest_period_not_the_run(
    seeded_session: Session,
    make_observation,  # type: ignore[no-untyped-def]
) -> None:
    """A pipeline that runs nightly over a source stuck in 2020 is stale."""
    from reim.services.observation_writer import write_observations

    write_observations(seeded_session, [make_observation("2020")], connector_version="1.0.0")
    seeded_session.commit()

    snapshot = build_metrics_snapshot(seeded_session, today=date(2026, 1, 1))
    metrics = _for(snapshot, "worldbank_ni_cpi_inflation")

    assert metrics.observations == 1
    assert metrics.data_age_days == (date(2026, 1, 1) - date(2020, 12, 31)).days


@requires_db
def test_a_source_with_no_data_has_no_age_but_zero_observations(seeded_session: Session) -> None:
    metrics = _for(build_metrics_snapshot(seeded_session), "worldbank_ni_cpi_inflation")

    assert metrics.data_age_days is None
    assert metrics.observations == 0


@requires_db
def test_the_strictest_threshold_wins_across_a_pipelines_indicators(
    seeded_session: Session,
) -> None:
    """No catalog entry's indicators disagree today, so the case is constructed.

    ``reim/services/status.py:53`` takes ``indicators[0]``; this takes the
    minimum across the pipeline's indicators, so a freshness gauge fires early
    rather than never when two indicators in one source are given different
    thresholds.

    The real catalog is used rather than a synthetic one, because both
    ``SourceEntry`` and ``QualityRuleSet`` reject indicator codes that are not
    in ``INDICATORS_BY_CODE`` — an invented code cannot be validated into
    existence. ``inide_cpi_monthly`` declares nine indicators; two are given
    thresholds here and the remaining seven fall back to the rule file's
    defaults, which set none. So this pins both halves of the rule: the
    strictest configured threshold wins, and an indicator with no threshold is
    skipped rather than counted as zero.
    """
    rules = QualityRuleSet.model_validate(
        {
            "version": 1,
            "indicators": {
                "ni_cpi_index_monthly": {"freshness_max_age_days": 800},
                "ni_cpi_inflation_monthly": {"freshness_max_age_days": 30},
            },
        }
    )

    snapshot = build_metrics_snapshot(seeded_session, rules=rules)

    assert _for(snapshot, "inide_cpi_monthly").freshness_max_age_days == 30


@requires_db
def test_a_pipeline_whose_indicators_have_no_threshold_reports_none(
    seeded_session: Session,
) -> None:
    """Absence here becomes an absent series, which is how "no policy" reads."""
    rules = QualityRuleSet.model_validate({"version": 1, "indicators": {}})

    snapshot = build_metrics_snapshot(seeded_session, rules=rules)

    assert _for(snapshot, "inide_cpi_monthly").freshness_max_age_days is None


@requires_db
def test_a_database_failure_yields_a_down_snapshot_not_an_exception(
    seeded_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Discovered by querying and catching, never by a pre-check."""

    def _raise(*args: object, **kwargs: object) -> None:
        raise SQLAlchemyError("database is down")

    monkeypatch.setattr("reim.services.metrics.run_repo.latest_runs_by_pipeline", _raise)

    snapshot = build_metrics_snapshot(seeded_session)

    assert snapshot.database_up is False
    assert snapshot.pipelines == ()
    assert snapshot.failed_checks == ()


@requires_db
def test_a_snapshot_costs_six_queries_whatever_the_catalog_holds(
    seeded_session: Session,
) -> None:
    """The regression this increment exists to prevent.

    A change that reintroduces a query per source makes the endpoint slow
    rather than broken; without this assertion nothing fails.
    """
    seeded_session.commit()
    statements: list[str] = []
    bind = seeded_session.get_bind()

    def _record(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(bind, "before_cursor_execute", _record)
    try:
        build_metrics_snapshot(seeded_session)
    finally:
        event.remove(bind, "before_cursor_execute", _record)

    assert len(statements) == 6, "\n\n".join(statements)


@requires_db
def test_the_snapshot_reports_the_last_runs_status(seeded_session: Session) -> None:
    """``runs_by_status`` counts all history; alerting needs the latest outcome.

    Without this field the "last run failed" and "a run is stuck" conditions
    cannot be evaluated from the snapshot at all.
    """
    now = datetime.now(UTC)
    _make_run(
        seeded_session,
        pipeline_key="worldbank_ni_cpi_inflation",
        started_at=now - timedelta(days=1),
    )
    _make_run(
        seeded_session,
        pipeline_key="worldbank_ni_cpi_inflation",
        started_at=now,
        status=PipelineStatus.FAILED,
    )
    seeded_session.flush()

    metrics = _for(build_metrics_snapshot(seeded_session), "worldbank_ni_cpi_inflation")

    assert metrics.last_run_status is PipelineStatus.FAILED
    assert metrics.runs_by_status == {"success": 1, "failed": 1}


@requires_db
def test_a_pipeline_that_never_ran_has_no_last_run_status(seeded_session: Session) -> None:
    metrics = _for(build_metrics_snapshot(seeded_session), "worldbank_ni_cpi_inflation")

    assert metrics.last_run_status is None
