"""``render_snapshot``: every naming and absent-series rule, with no database.

Rendering is where Prometheus conventions get quietly broken — a counter named
``_total`` that renders ``_total_total``, milliseconds exported as seconds, a
zero standing in for a fact nobody measured. None of it needs a session, so all
of it is asserted directly here.

Assertions look for the series they name rather than comparing whole payloads,
which would break every time ``prometheus_client`` adds a default collector.
"""

from __future__ import annotations

from datetime import UTC, datetime

from reim.core.constants import PipelineStatus
from reim.repositories.pipeline_runs import FailedCheckCount
from reim.services.metrics import (
    RECORD_OUTCOMES,
    MetricsSnapshot,
    PipelineMetrics,
    render_snapshot,
)


def _metrics(**overrides: object) -> PipelineMetrics:
    """A fully-populated pipeline, so each test overrides only its own concern."""
    defaults: dict[str, object] = {
        "pipeline_key": "bcn_fx",
        "enabled": True,
        "observations": 1_200,
        "data_age_days": 3,
        "freshness_max_age_days": 7,
        "last_run_at": datetime(2026, 9, 12, 6, 0, tzinfo=UTC),
        "last_success_at": datetime(2026, 9, 12, 6, 0, tzinfo=UTC),
        "last_run_duration_ms": 2_500,
        "last_run_status": PipelineStatus.SUCCESS,
        "last_run_records": dict.fromkeys(RECORD_OUTCOMES, 4),
        "runs_by_status": {"success": 40, "failed": 2},
        "records_total": dict.fromkeys(RECORD_OUTCOMES, 100),
        "duration_ms_total": 90_000,
    }
    defaults.update(overrides)
    return PipelineMetrics(**defaults)  # type: ignore[arg-type]


def _render(**overrides: object) -> str:
    snapshot = MetricsSnapshot(
        database_up=True,
        pipelines=(_metrics(**overrides),),
        failed_checks=(),
    )
    return render_snapshot(snapshot).decode()


def test_the_counter_name_is_not_doubled() -> None:
    """The rendered counter name carries exactly one ``_total``.

    ``CounterMetricFamily`` strips a trailing ``_total`` before re-appending it,
    so this cannot fail while the family API is used — it pins the convention
    and would catch a switch to the ``Counter`` class, where the suffix is
    appended unconditionally and doubling is reachable.
    """
    text = _render()

    assert "reim_pipeline_runs_total{" in text
    assert "_total_total" not in text


def test_no_created_series_is_emitted() -> None:
    """``Counter`` would add one holding the process start time.

    For a counter rebuilt from the database on every scrape it would report
    "created just now" each time, which is noise at best.
    """
    assert "_created" not in _render()


def test_durations_are_exported_in_seconds() -> None:
    text = _render(last_run_duration_ms=2_500, duration_ms_total=90_000)

    assert 'reim_pipeline_last_run_duration_seconds{pipeline_key="bcn_fx"} 2.5' in text
    assert 'reim_pipeline_run_duration_seconds_total{pipeline_key="bcn_fx"} 90.0' in text


def test_the_types_are_declared_as_gauges_and_counters() -> None:
    text = _render()

    assert "# TYPE reim_pipeline_data_age_days gauge" in text
    assert "# TYPE reim_pipeline_runs_total counter" in text
    assert "# TYPE reim_quality_checks_failed_total counter" in text


def test_a_pipeline_with_no_threshold_has_no_threshold_series() -> None:
    """No policy configured must not read as "never overdue" or "always overdue"."""
    text = _render(freshness_max_age_days=None)

    assert "reim_pipeline_freshness_max_age_days{" not in text
    assert "reim_pipeline_data_age_days{" in text


def test_a_pipeline_with_no_data_has_no_age_series_but_reports_zero_observations() -> None:
    text = _render(data_age_days=None, observations=0)

    assert "reim_pipeline_data_age_days{" not in text
    assert 'reim_pipeline_observations{pipeline_key="bcn_fx"} 0.0' in text


def test_a_pipeline_that_never_ran_omits_last_run_series_but_keeps_counters_at_zero() -> None:
    """A counter's zero is a reading; a last-run gauge's zero is an invention."""
    text = _render(
        last_run_at=None,
        last_success_at=None,
        last_run_duration_ms=None,
        last_run_records=None,
        runs_by_status={},
        records_total=dict.fromkeys(RECORD_OUTCOMES, 0),
        duration_ms_total=0,
    )

    assert "reim_pipeline_last_run_timestamp_seconds{" not in text
    assert "reim_pipeline_last_success_timestamp_seconds{" not in text
    assert "reim_pipeline_last_run_duration_seconds{" not in text
    assert "reim_pipeline_last_run_records{" not in text
    assert "reim_pipeline_runs_total{" not in text
    assert 'reim_pipeline_records_total{outcome="inserted",pipeline_key="bcn_fx"} 0.0' in text


def test_every_record_outcome_is_labelled_separately() -> None:
    text = _render()

    for outcome in RECORD_OUTCOMES:
        assert f'outcome="{outcome}"' in text


def test_each_run_status_gets_its_own_series() -> None:
    text = _render(runs_by_status={"success": 40, "failed": 2})

    assert 'reim_pipeline_runs_total{pipeline_key="bcn_fx",status="success"} 40.0' in text
    assert 'reim_pipeline_runs_total{pipeline_key="bcn_fx",status="failed"} 2.0' in text


def test_a_disabled_pipeline_reports_zero_rather_than_disappearing() -> None:
    """An alert rule excludes it by reading the gauge; it cannot read an absence."""
    text = _render(enabled=False)

    assert 'reim_pipeline_enabled{pipeline_key="bcn_fx"} 0.0' in text


def test_failed_checks_are_labelled_by_pipeline_and_name() -> None:
    snapshot = MetricsSnapshot(
        database_up=True,
        pipelines=(),
        failed_checks=(
            FailedCheckCount(pipeline_key="a", check_name="freshness", failures=3),
            FailedCheckCount(pipeline_key="b", check_name="freshness", failures=1),
        ),
    )

    text = render_snapshot(snapshot).decode()

    assert 'reim_quality_checks_failed_total{check_name="freshness",pipeline_key="a"} 3.0' in text
    assert 'reim_quality_checks_failed_total{check_name="freshness",pipeline_key="b"} 1.0' in text


def test_a_down_snapshot_reports_the_outage_and_no_pipeline_series() -> None:
    """No *series*, which is not the same as no mention of the metric.

    An empty family still emits its ``# HELP`` and ``# TYPE`` lines, and that is
    correct — Prometheus reads metadata-only families and records nothing. So
    the assertion looks for a labelled sample (the ``{``), not for the metric
    name appearing anywhere in the payload.
    """
    text = render_snapshot(MetricsSnapshot(database_up=False)).decode()

    assert "reim_database_up 0.0" in text
    assert "reim_pipeline_enabled{" not in text
    assert "reim_pipeline_runs_total{" not in text
    assert "reim_quality_checks_failed_total{" not in text


def test_a_healthy_snapshot_reports_the_database_as_up() -> None:
    assert "reim_database_up 1.0" in _render()
