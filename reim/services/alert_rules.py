"""The four conditions REIM alerts on, evaluated without touching anything.

Pure by construction: a :class:`~reim.services.metrics.MetricsSnapshot`, the
latest run's failed checks, and an injected ``now`` in; alerts out. No session,
no clock, no settings, which is why every boundary is asserted directly against
this function rather than inferred from a delivered notification.

Staleness is read from the snapshot rather than recomputed. The threshold
comparison is policy, and that policy lives in ``sources/quality_rules.yml``
alone — deriving it a second time here would put it in two places that could
disagree.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from reim.core.constants import SEVERITY_ORDER, CheckSeverity, PipelineStatus
from reim.repositories.pipeline_runs import LatestFailedCheck
from reim.services.metrics import MetricsSnapshot, PipelineMetrics


class AlertCondition(StrEnum):
    """What REIM will speak up about."""

    STALE = "stale"
    FAILED_RUN = "failed_run"
    STUCK_RUN = "stuck_run"
    QUALITY = "quality"


@dataclass(frozen=True)
class Alert:
    """One condition holding on one pipeline, ready to be notified."""

    condition: AlertCondition
    pipeline_key: str
    severity: CheckSeverity
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


def _stale(metrics: PipelineMetrics) -> Alert | None:
    """Data older than the maximum age configured for its indicators.

    Both figures must be present: no configured threshold means no policy, and
    no stored data means no age. Equality is not stale — the threshold is a
    maximum tolerated age, so being exactly at it is still tolerated.
    """
    age = metrics.data_age_days
    threshold = metrics.freshness_max_age_days
    if age is None or threshold is None or age <= threshold:
        return None
    return Alert(
        condition=AlertCondition.STALE,
        pipeline_key=metrics.pipeline_key,
        severity=CheckSeverity.WARNING,
        summary=(
            f"{metrics.pipeline_key} has no data newer than {age} days, "
            f"past its {threshold}-day threshold."
        ),
        details={"data_age_days": age, "freshness_max_age_days": threshold},
    )


def _failed_run(metrics: PipelineMetrics) -> Alert | None:
    """The most recent run failed outright.

    ``partial`` is not a failure: it wrote data, which is why freshness already
    counts it as a success.
    """
    if metrics.last_run_status is not PipelineStatus.FAILED:
        return None
    return Alert(
        condition=AlertCondition.FAILED_RUN,
        pipeline_key=metrics.pipeline_key,
        severity=CheckSeverity.ERROR,
        summary=f"{metrics.pipeline_key}'s most recent run failed.",
        details={"last_run_at": _iso(metrics.last_run_at)},
    )


def _stuck_run(
    metrics: PipelineMetrics, *, stuck_run_after: timedelta, now: datetime
) -> Alert | None:
    """A run still marked ``running`` long after it started.

    The runner writes its row before extraction and finalises it in a
    ``finally`` block, so a process killed outright leaves ``running`` forever.
    It never becomes ``failed``, so nothing else notices it.
    """
    if metrics.last_run_status is not PipelineStatus.RUNNING or metrics.last_run_at is None:
        return None
    stuck_for = now - metrics.last_run_at
    if stuck_for <= stuck_run_after:
        return None
    hours = int(stuck_for.total_seconds() // 3600)
    return Alert(
        condition=AlertCondition.STUCK_RUN,
        pipeline_key=metrics.pipeline_key,
        severity=CheckSeverity.ERROR,
        summary=(
            f"{metrics.pipeline_key} has a run still marked running after {hours} hours, "
            "which usually means the process was killed."
        ),
        details={"last_run_at": _iso(metrics.last_run_at), "stuck_hours": hours},
    )


def _quality(
    metrics: PipelineMetrics,
    checks: Sequence[LatestFailedCheck],
    *,
    severity_floor: CheckSeverity,
) -> Alert | None:
    """The latest run recorded a failed check at or above the floor."""
    floor = SEVERITY_ORDER[severity_floor]
    relevant = [
        check
        for check in checks
        if check.pipeline_key == metrics.pipeline_key and SEVERITY_ORDER[check.severity] >= floor
    ]
    if not relevant:
        return None
    worst = max(relevant, key=lambda check: SEVERITY_ORDER[check.severity])
    names = ", ".join(sorted(check.check_name for check in relevant))
    return Alert(
        condition=AlertCondition.QUALITY,
        pipeline_key=metrics.pipeline_key,
        severity=worst.severity,
        summary=(
            f"{metrics.pipeline_key}'s most recent run failed {len(relevant)} quality "
            f"check(s) at {worst.severity.value} or worse: {names}."
        ),
        details={
            "checks": [
                {
                    "check_name": check.check_name,
                    "severity": check.severity.value,
                    "failures": check.failures,
                }
                for check in relevant
            ]
        },
    )


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat()


def evaluate(
    snapshot: MetricsSnapshot,
    failed_checks: Sequence[LatestFailedCheck],
    *,
    severity_floor: CheckSeverity,
    stuck_run_after: timedelta,
    now: datetime,
) -> list[Alert]:
    """Return every condition currently holding, across every enabled pipeline.

    A snapshot whose database was unreachable says nothing about any pipeline,
    so it produces nothing: reporting 23 pipelines as broken because one query
    failed would be worse than silence, and the outage is already visible as
    ``reim_database_up 0``.

    Disabled pipelines are skipped entirely — the catalog records the intent
    that nobody should be paged about them.
    """
    if not snapshot.database_up:
        return []

    alerts: list[Alert] = []
    for metrics in snapshot.pipelines:
        if not metrics.enabled:
            continue
        candidates = (
            _stale(metrics),
            _failed_run(metrics),
            _stuck_run(metrics, stuck_run_after=stuck_run_after, now=now),
            _quality(metrics, failed_checks, severity_floor=severity_floor),
        )
        alerts.extend(alert for alert in candidates if alert is not None)
    return alerts
