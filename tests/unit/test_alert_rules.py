"""``evaluate``: the four conditions, and every boundary they turn on.

Pure — a snapshot and a list of checks in, alerts out — so all of it runs
without a database, a clock or a webhook. The boundaries are where alerting
bugs live: an age exactly equal to its threshold, a run stuck for exactly the
grace period, a check one severity below the floor.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from reim.core.constants import CheckSeverity, PipelineStatus
from reim.repositories.pipeline_runs import LatestFailedCheck
from reim.services.alert_rules import AlertCondition, evaluate
from reim.services.metrics import MetricsSnapshot, PipelineMetrics

NOW = datetime(2026, 9, 12, 18, 0, tzinfo=UTC)


def _metrics(**overrides: Any) -> PipelineMetrics:
    """A healthy pipeline, so each test overrides only its own concern."""
    defaults: dict[str, Any] = {
        "pipeline_key": "bcn_fx",
        "enabled": True,
        "observations": 100,
        "data_age_days": 2,
        "freshness_max_age_days": 7,
        "last_run_at": NOW - timedelta(hours=1),
        "last_success_at": NOW - timedelta(hours=1),
        "last_run_duration_ms": 2_500,
        "last_run_status": PipelineStatus.SUCCESS,
        "last_run_records": dict.fromkeys(
            ("extracted", "inserted", "updated", "unchanged", "rejected"), 1
        ),
        "runs_by_status": {"success": 1},
        "records_total": dict.fromkeys(
            ("extracted", "inserted", "updated", "unchanged", "rejected"), 1
        ),
        "duration_ms_total": 2_500,
    }
    defaults.update(overrides)
    return PipelineMetrics(**defaults)  # type: ignore[arg-type]


def _evaluate(
    checks: list[LatestFailedCheck] | None = None,
    *,
    floor: CheckSeverity = CheckSeverity.ERROR,
    stuck_after: timedelta = timedelta(hours=6),
    **overrides: Any,
) -> list[Any]:
    snapshot = MetricsSnapshot(database_up=True, pipelines=(_metrics(**overrides),))
    return evaluate(
        snapshot,
        checks or [],
        severity_floor=floor,
        stuck_run_after=stuck_after,
        now=NOW,
    )


def test_a_healthy_pipeline_produces_nothing() -> None:
    assert _evaluate() == []


def test_data_older_than_its_threshold_is_stale() -> None:
    alerts = _evaluate(data_age_days=9, freshness_max_age_days=7)

    assert [alert.condition for alert in alerts] == [AlertCondition.STALE]
    assert alerts[0].details == {"data_age_days": 9, "freshness_max_age_days": 7}


def test_an_age_exactly_at_the_threshold_is_not_stale() -> None:
    """The threshold is a maximum tolerated age, so equal is still tolerated."""
    assert _evaluate(data_age_days=7, freshness_max_age_days=7) == []


def test_no_configured_threshold_never_goes_stale() -> None:
    """No policy means no verdict — the metrics design's absent-series rule."""
    assert _evaluate(data_age_days=9_000, freshness_max_age_days=None) == []


def test_a_source_holding_no_data_is_not_reported_as_stale() -> None:
    assert _evaluate(data_age_days=None) == []


def test_a_failed_last_run_alerts() -> None:
    alerts = _evaluate(last_run_status=PipelineStatus.FAILED)

    assert [alert.condition for alert in alerts] == [AlertCondition.FAILED_RUN]
    assert alerts[0].severity is CheckSeverity.ERROR


def test_a_partial_run_is_not_a_failure() -> None:
    """``partial`` wrote data; the metrics increment already counts it a success."""
    assert _evaluate(last_run_status=PipelineStatus.PARTIAL) == []


def test_a_run_still_running_past_the_grace_period_is_stuck() -> None:
    """A killed process leaves ``running`` forever and never becomes ``failed``."""
    alerts = _evaluate(
        last_run_status=PipelineStatus.RUNNING,
        last_run_at=NOW - timedelta(hours=7),
        stuck_after=timedelta(hours=6),
    )

    assert [alert.condition for alert in alerts] == [AlertCondition.STUCK_RUN]


def test_a_run_running_within_the_grace_period_is_not_stuck() -> None:
    assert (
        _evaluate(
            last_run_status=PipelineStatus.RUNNING,
            last_run_at=NOW - timedelta(hours=5),
            stuck_after=timedelta(hours=6),
        )
        == []
    )


def test_a_run_running_exactly_the_grace_period_is_not_stuck() -> None:
    """Equal is still tolerated — the same rule the staleness threshold follows.

    Without this, flipping ``<=`` to ``<`` in ``_stuck_run`` passes every other
    test, because the neighbouring cases sit a clear hour either side of the
    boundary rather than on it.
    """
    assert (
        _evaluate(
            last_run_status=PipelineStatus.RUNNING,
            last_run_at=NOW - timedelta(hours=6),
            stuck_after=timedelta(hours=6),
        )
        == []
    )


def test_a_pipeline_that_never_ran_stays_silent() -> None:
    """Adding a catalog entry must not page anyone about unstarted work."""
    assert (
        _evaluate(
            last_run_status=None,
            last_run_at=None,
            last_success_at=None,
            data_age_days=None,
        )
        == []
    )


def test_a_disabled_pipeline_is_skipped_entirely() -> None:
    assert _evaluate(enabled=False, last_run_status=PipelineStatus.FAILED) == []


def test_a_failed_check_at_the_floor_alerts() -> None:
    checks = [
        LatestFailedCheck(
            pipeline_key="bcn_fx", check_name="range", severity=CheckSeverity.ERROR, failures=3
        )
    ]

    alerts = _evaluate(checks, floor=CheckSeverity.ERROR)

    assert [alert.condition for alert in alerts] == [AlertCondition.QUALITY]
    assert alerts[0].details["checks"] == [
        {"check_name": "range", "severity": "error", "failures": 3}
    ]


def test_a_failed_check_below_the_floor_does_not_alert() -> None:
    checks = [
        LatestFailedCheck(
            pipeline_key="bcn_fx", check_name="range", severity=CheckSeverity.WARNING, failures=1
        )
    ]

    assert _evaluate(checks, floor=CheckSeverity.ERROR) == []


def test_the_quality_alert_takes_the_worst_severity_present() -> None:
    checks = [
        LatestFailedCheck(
            pipeline_key="bcn_fx", check_name="range", severity=CheckSeverity.ERROR, failures=1
        ),
        LatestFailedCheck(
            pipeline_key="bcn_fx",
            check_name="freshness",
            severity=CheckSeverity.CRITICAL,
            failures=1,
        ),
    ]

    alerts = _evaluate(checks, floor=CheckSeverity.ERROR)

    assert alerts[0].severity is CheckSeverity.CRITICAL


def test_checks_belonging_to_another_pipeline_are_ignored() -> None:
    checks = [
        LatestFailedCheck(
            pipeline_key="somewhere_else",
            check_name="range",
            severity=CheckSeverity.ERROR,
            failures=1,
        )
    ]

    assert _evaluate(checks, floor=CheckSeverity.ERROR) == []


def test_a_down_database_produces_no_alerts() -> None:
    """A snapshot that could not be built says nothing about any pipeline."""
    assert (
        evaluate(
            MetricsSnapshot(database_up=False),
            [],
            severity_floor=CheckSeverity.ERROR,
            stuck_run_after=timedelta(hours=6),
            now=NOW,
        )
        == []
    )


def test_one_pipeline_can_raise_several_conditions() -> None:
    checks = [
        LatestFailedCheck(
            pipeline_key="bcn_fx", check_name="range", severity=CheckSeverity.ERROR, failures=1
        )
    ]

    alerts = _evaluate(checks, data_age_days=9, last_run_status=PipelineStatus.FAILED)

    assert {alert.condition for alert in alerts} == {
        AlertCondition.STALE,
        AlertCondition.FAILED_RUN,
        AlertCondition.QUALITY,
    }


def test_every_alert_carries_a_summary_sentence() -> None:
    """The webhook payload is read by a human, not only by a rule."""
    alerts = _evaluate(data_age_days=9, last_run_status=PipelineStatus.FAILED)

    for alert in alerts:
        assert alert.summary
        assert alert.pipeline_key in alert.summary
    assert len({alert.summary for alert in alerts}) == len(alerts)
