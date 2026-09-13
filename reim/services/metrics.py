"""The figures behind ``/metrics``, and their Prometheus rendering.

Two halves on purpose. ``build_metrics_snapshot`` needs a session and is tested
against the database; ``render_snapshot`` needs nothing at all and is where the
exhaustive naming and absent-series tests live.

Every figure is derived from ``pipeline_runs`` at scrape time, because ingestion
runs in a CLI process that has exited long before a scrape arrives — an
in-process counter would never be visible to the process answering Prometheus,
and a Pushgateway is infrastructure this project does not take on.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime

from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from reim.core.constants import PipelineStatus
from reim.database.models import PipelineRun
from reim.domain.quality.rules import QualityRuleSet, get_quality_rules
from reim.domain.sources.catalog import SourceCatalog, SourceEntry, get_catalog
from reim.repositories import observations as observation_repo
from reim.repositories import pipeline_runs as run_repo
from reim.repositories import reference as reference_repo
from reim.repositories.observations import SourceVolume
from reim.repositories.pipeline_runs import FailedCheckCount, RunStatusAggregate

#: The five record counters a run reports, in the order they happen.
RECORD_OUTCOMES = ("extracted", "inserted", "updated", "unchanged", "rejected")


@dataclass(frozen=True)
class PipelineMetrics:
    """Everything ``/metrics`` reports about one pipeline.

    ``None`` means "no series": no threshold configured, no data stored, no run
    yet. A zero would assert something the data does not support — that a
    pipeline is perfectly fresh, or that its last run inserted nothing.
    """

    pipeline_key: str
    enabled: bool
    observations: int
    data_age_days: int | None
    freshness_max_age_days: int | None
    last_run_at: datetime | None
    last_success_at: datetime | None
    last_run_duration_ms: int | None
    last_run_status: PipelineStatus | None
    last_run_records: dict[str, int] | None
    runs_by_status: dict[str, int]
    records_total: dict[str, int]
    duration_ms_total: int


@dataclass(frozen=True)
class MetricsSnapshot:
    """One scrape's worth of figures, or the fact that the database is down."""

    database_up: bool
    pipelines: tuple[PipelineMetrics, ...] = ()
    failed_checks: tuple[FailedCheckCount, ...] = ()


@dataclass(frozen=True)
class _PipelineTotals:
    """One pipeline's cumulative totals, folded across statuses."""

    runs_by_status: dict[str, int]
    records_total: dict[str, int]
    duration_ms_total: int


def _fold_aggregates(rows: list[RunStatusAggregate]) -> dict[str, _PipelineTotals]:
    """Collapse the per-status rows into one set of totals per pipeline.

    The query groups by pipeline *and* status because the run counter needs the
    status label; the record and duration counters do not, so they are summed
    back across statuses here rather than in a second query.
    """
    runs: dict[str, dict[str, int]] = {}
    records: dict[str, dict[str, int]] = {}
    durations: dict[str, int] = {}

    for row in rows:
        key = row.pipeline_key
        # (pipeline, status) is unique per group, so this assigns rather than adds.
        runs.setdefault(key, {})[row.status.value] = row.runs
        outcomes = records.setdefault(key, dict.fromkeys(RECORD_OUTCOMES, 0))
        outcomes["extracted"] += row.records_extracted
        outcomes["inserted"] += row.records_inserted
        outcomes["updated"] += row.records_updated
        outcomes["unchanged"] += row.records_unchanged
        outcomes["rejected"] += row.records_rejected
        durations[key] = durations.get(key, 0) + row.duration_ms

    return {
        key: _PipelineTotals(
            runs_by_status=runs[key],
            records_total=records[key],
            duration_ms_total=durations[key],
        )
        for key in runs
    }


def _freshness_threshold(entry: SourceEntry, rules: QualityRuleSet) -> int | None:
    """Return the strictest freshness threshold across a pipeline's indicators.

    Freshness is per source — ``latest_period_end`` is keyed on ``source_id`` —
    but thresholds are per indicator, and 14 of the 23 catalog entries declare
    more than one. None of them disagree today, so this is the same number
    ``build_pipeline_summaries`` derives from ``indicators[0]``
    (``reim/services/status.py:53``). When they do disagree the strictest wins:
    a freshness gauge that fires early beats one that never fires.

    An indicator with no threshold is skipped rather than read as zero, so "no
    policy here" cannot silence a sibling indicator that does have one.
    """
    configured = [
        threshold
        for threshold in (
            rules.for_indicator(code).freshness_max_age_days for code in entry.indicators
        )
        if threshold is not None
    ]
    return min(configured) if configured else None


def _pipeline_metrics(
    *,
    entry: SourceEntry,
    rules: QualityRuleSet,
    today: date,
    last_run: PipelineRun | None,
    last_success: PipelineRun | None,
    totals: _PipelineTotals | None,
    volume: SourceVolume | None,
) -> PipelineMetrics:
    """Assemble one pipeline's figures from the aggregates already fetched."""
    age: int | None = None
    if volume is not None and volume.latest_period_end is not None:
        age = (today - volume.latest_period_end).days

    last_records: dict[str, int] | None = None
    if last_run is not None:
        last_records = {
            "extracted": last_run.records_extracted,
            "inserted": last_run.records_inserted,
            "updated": last_run.records_updated,
            "unchanged": last_run.records_unchanged,
            "rejected": last_run.records_rejected,
        }

    return PipelineMetrics(
        pipeline_key=entry.key,
        enabled=entry.enabled,
        observations=volume.observations if volume is not None else 0,
        data_age_days=age,
        freshness_max_age_days=_freshness_threshold(entry, rules),
        last_run_at=last_run.started_at if last_run is not None else None,
        last_success_at=last_success.started_at if last_success is not None else None,
        last_run_duration_ms=last_run.duration_ms if last_run is not None else None,
        last_run_status=last_run.status if last_run is not None else None,
        last_run_records=last_records,
        runs_by_status=totals.runs_by_status if totals is not None else {},
        records_total=(
            totals.records_total if totals is not None else dict.fromkeys(RECORD_OUTCOMES, 0)
        ),
        duration_ms_total=totals.duration_ms_total if totals is not None else 0,
    )


def build_metrics_snapshot(
    session: Session,
    *,
    catalog: SourceCatalog | None = None,
    rules: QualityRuleSet | None = None,
    today: date | None = None,
) -> MetricsSnapshot:
    """Return every figure ``/metrics`` exports, in six queries.

    Availability is discovered by running the queries and catching the failure,
    never by pre-checking the connection: a pre-check cannot speak for the query
    that follows it. A failure yields ``database_up=False`` and no pipeline
    series, so the scrape still answers — the scrape during an outage being the
    one that matters most.

    Every catalog entry gets a row, including one that has never run. Dropping
    it would hide a pipeline that stopped being scheduled, which is exactly the
    failure worth paging about.
    """
    resolved_catalog = catalog or get_catalog()
    resolved_rules = rules or get_quality_rules()
    reference_day = today or datetime.now(UTC).date()

    try:
        latest_runs = run_repo.latest_runs_by_pipeline(session)
        latest_successes = run_repo.latest_successful_runs_by_pipeline(session)
        aggregates = run_repo.aggregate_runs_by_pipeline(session)
        failed_checks = run_repo.summarize_failed_checks_by_pipeline(session)
        volumes = observation_repo.summarize_sources(session)
        source_ids = reference_repo.source_ids_by_key(session)
    except SQLAlchemyError:
        return MetricsSnapshot(database_up=False)

    totals = _fold_aggregates(aggregates)

    pipelines: list[PipelineMetrics] = []
    for entry in resolved_catalog.sources:
        source_id = source_ids.get(entry.key)
        pipelines.append(
            _pipeline_metrics(
                entry=entry,
                rules=resolved_rules,
                today=reference_day,
                last_run=latest_runs.get(entry.key),
                last_success=latest_successes.get(entry.key),
                totals=totals.get(entry.key),
                volume=volumes.get(source_id) if source_id is not None else None,
            )
        )

    return MetricsSnapshot(
        database_up=True,
        pipelines=tuple(pipelines),
        failed_checks=tuple(failed_checks),
    )


class _SnapshotCollector:
    """Yields one snapshot's metric families. Registered, scraped, discarded."""

    def __init__(self, snapshot: MetricsSnapshot) -> None:
        self._snapshot = snapshot

    def collect(self) -> Iterator[Metric]:
        yield GaugeMetricFamily(
            "reim_database_up",
            "1 when the metrics queries reached the database, 0 when they failed.",
            value=1.0 if self._snapshot.database_up else 0.0,
        )
        yield from _pipeline_families(self._snapshot.pipelines)
        yield _failed_check_family(self._snapshot.failed_checks)


def _pipeline_families(pipelines: tuple[PipelineMetrics, ...]) -> Iterator[Metric]:
    """Build one family per metric, adding a series per pipeline.

    Counter families are constructed with their base name: the client appends
    ``_total``, so ``reim_pipeline_runs`` renders ``reim_pipeline_runs_total``
    and passing the suffix here would render it twice.
    """
    enabled = GaugeMetricFamily(
        "reim_pipeline_enabled",
        "1 when the pipeline is enabled in the source catalog, 0 when disabled.",
        labels=["pipeline_key"],
    )
    observations = GaugeMetricFamily(
        "reim_pipeline_observations",
        "Observations currently stored for this pipeline's source.",
        labels=["pipeline_key"],
    )
    age = GaugeMetricFamily(
        "reim_pipeline_data_age_days",
        "Days between today and the newest period this pipeline holds data for.",
        labels=["pipeline_key"],
    )
    threshold = GaugeMetricFamily(
        "reim_pipeline_freshness_max_age_days",
        "Configured maximum tolerated data age, from sources/quality_rules.yml.",
        labels=["pipeline_key"],
    )
    last_run = GaugeMetricFamily(
        "reim_pipeline_last_run_timestamp_seconds",
        "Start of the most recent run, in Unix seconds.",
        labels=["pipeline_key"],
    )
    last_success = GaugeMetricFamily(
        "reim_pipeline_last_success_timestamp_seconds",
        "Start of the most recent run that did not fail, in Unix seconds.",
        labels=["pipeline_key"],
    )
    last_duration = GaugeMetricFamily(
        "reim_pipeline_last_run_duration_seconds",
        "How long the most recent run took.",
        labels=["pipeline_key"],
    )
    last_records = GaugeMetricFamily(
        "reim_pipeline_last_run_records",
        "Records the most recent run reported, by outcome.",
        labels=["pipeline_key", "outcome"],
    )
    runs = CounterMetricFamily(
        "reim_pipeline_runs",
        "Runs recorded, by terminal status.",
        labels=["pipeline_key", "status"],
    )
    records = CounterMetricFamily(
        "reim_pipeline_records",
        "Records reported across every run, by outcome.",
        labels=["pipeline_key", "outcome"],
    )
    duration = CounterMetricFamily(
        "reim_pipeline_run_duration_seconds",
        "Time spent running this pipeline across every run.",
        labels=["pipeline_key"],
    )

    for metrics in pipelines:
        key = [metrics.pipeline_key]
        enabled.add_metric(key, 1.0 if metrics.enabled else 0.0)
        observations.add_metric(key, metrics.observations)
        if metrics.data_age_days is not None:
            age.add_metric(key, metrics.data_age_days)
        if metrics.freshness_max_age_days is not None:
            threshold.add_metric(key, metrics.freshness_max_age_days)
        if metrics.last_run_at is not None:
            last_run.add_metric(key, metrics.last_run_at.timestamp())
        if metrics.last_success_at is not None:
            last_success.add_metric(key, metrics.last_success_at.timestamp())
        if metrics.last_run_duration_ms is not None:
            last_duration.add_metric(key, metrics.last_run_duration_ms / 1000)
        if metrics.last_run_records is not None:
            for outcome, count in metrics.last_run_records.items():
                last_records.add_metric([metrics.pipeline_key, outcome], count)
        for status, count in metrics.runs_by_status.items():
            runs.add_metric([metrics.pipeline_key, status], count)
        for outcome, count in metrics.records_total.items():
            records.add_metric([metrics.pipeline_key, outcome], count)
        duration.add_metric(key, metrics.duration_ms_total / 1000)

    yield enabled
    yield observations
    yield age
    yield threshold
    yield last_run
    yield last_success
    yield last_duration
    yield last_records
    yield runs
    yield records
    yield duration


def _failed_check_family(counts: tuple[FailedCheckCount, ...]) -> Metric:
    """Build the failed-check counter, one series per pipeline and check name."""
    family = CounterMetricFamily(
        "reim_quality_checks_failed",
        "Quality checks recorded as failed, by pipeline and check name.",
        labels=["pipeline_key", "check_name"],
    )
    for count in counts:
        family.add_metric([count.pipeline_key, count.check_name], count.failures)
    return family


def render_snapshot(snapshot: MetricsSnapshot) -> bytes:
    """Render a snapshot as Prometheus text exposition.

    Pure: snapshot in, bytes out, no session, no clock, no settings — which is
    why every naming and absent-series rule is tested against this function
    rather than inferred from a scraped endpoint.

    A fresh registry per call, rather than module-level metric objects, so a
    label set that stops existing — a source dropped from the catalog — stops
    being exported instead of lingering at its last value forever.
    """
    registry = CollectorRegistry()
    registry.register(_SnapshotCollector(snapshot))
    return generate_latest(registry)
