"""Query helpers for pipeline runs and quality checks."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload

from reim.core.constants import SEVERITY_ORDER, CheckSeverity, CheckStatus, PipelineStatus
from reim.database.models import DataQualityCheck, PipelineRun
from reim.schemas.pipelines import FailedCheckGroup


def _apply(
    statement: Select[tuple[PipelineRun]],
    *,
    pipeline_key: str | None,
    status: PipelineStatus | None,
    since: datetime | None = None,
) -> Select[tuple[PipelineRun]]:
    if pipeline_key:
        statement = statement.where(PipelineRun.pipeline_key == pipeline_key)
    if status:
        statement = statement.where(PipelineRun.status == status)
    if since:
        statement = statement.where(PipelineRun.started_at >= since)
    return statement


def list_runs(
    session: Session,
    *,
    pipeline_key: str | None = None,
    status: PipelineStatus | None = None,
    since: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[PipelineRun]:
    """Return pipeline runs, newest first."""
    statement = _apply(
        select(PipelineRun).order_by(PipelineRun.started_at.desc()),
        pipeline_key=pipeline_key,
        status=status,
        since=since,
    )
    return list(session.scalars(statement.limit(limit).offset(offset)))


def count_runs(
    session: Session,
    *,
    pipeline_key: str | None = None,
    status: PipelineStatus | None = None,
    since: datetime | None = None,
) -> int:
    """Return how many runs match the filters."""
    statement = _apply(
        select(func.count(PipelineRun.id)).select_from(PipelineRun),  # type: ignore[arg-type]
        pipeline_key=pipeline_key,
        status=status,
        since=since,
    )
    return int(session.scalar(statement) or 0)


def get_run(session: Session, run_id: uuid.UUID) -> PipelineRun | None:
    """Return one run with its quality checks eagerly loaded."""
    return session.scalar(
        select(PipelineRun)
        .where(PipelineRun.id == run_id)
        .options(joinedload(PipelineRun.quality_checks))
    )


def latest_run(session: Session, pipeline_key: str) -> PipelineRun | None:
    """Return the most recent run of a pipeline."""
    return session.scalar(
        select(PipelineRun)
        .where(PipelineRun.pipeline_key == pipeline_key)
        .order_by(PipelineRun.started_at.desc())
        .limit(1)
    )


def latest_successful_run(session: Session, pipeline_key: str) -> PipelineRun | None:
    """Return the most recent run that did not fail."""
    return session.scalar(
        select(PipelineRun)
        .where(
            PipelineRun.pipeline_key == pipeline_key,
            PipelineRun.status.in_([PipelineStatus.SUCCESS, PipelineStatus.PARTIAL]),
        )
        .order_by(PipelineRun.started_at.desc())
        .limit(1)
    )


def list_checks(
    session: Session,
    *,
    run_id: uuid.UUID | None = None,
    status: CheckStatus | None = None,
    severity: CheckSeverity | None = None,
    since: datetime | None = None,
    limit: int = 200,
) -> list[DataQualityCheck]:
    """Return quality checks, newest first."""
    statement = select(DataQualityCheck).order_by(DataQualityCheck.created_at.desc())
    if run_id:
        statement = statement.where(DataQualityCheck.pipeline_run_id == run_id)
    if status:
        statement = statement.where(DataQualityCheck.status == status)
    if severity:
        statement = statement.where(DataQualityCheck.severity == severity)
    if since:
        statement = statement.where(DataQualityCheck.created_at >= since)
    return list(session.scalars(statement.limit(limit)))


def summarize_failed_checks(session: Session, *, since: datetime | None = None) -> dict[str, int]:
    """Return a count of failed checks grouped by severity."""
    statement = (
        select(DataQualityCheck.severity, func.count(DataQualityCheck.id))
        .where(DataQualityCheck.status == CheckStatus.FAILED)
        .group_by(DataQualityCheck.severity)
    )
    if since:
        statement = statement.where(DataQualityCheck.created_at >= since)
    return {severity.value: count for severity, count in session.execute(statement)}


def summarize_failed_checks_by_name(
    session: Session, *, since: datetime | None = None
) -> list[FailedCheckGroup]:
    """Return failed checks grouped by name and severity, worst first.

    Grouped in SQL rather than by folding ``list_checks`` in Python: that
    function caps its result at ``limit``, so a check failing more often than
    the cap would be reported as rarer than it is. A wrong number presented
    confidently is worse than no number.

    ``pipeline_keys`` comes from joining the run, whose ``pipeline_key`` is
    the catalog key — an invariant enforced by ``BaseConnector.__init__``,
    which refuses to construct a connector whose key differs from its
    catalog entry's.
    """
    statement = (
        select(
            DataQualityCheck.check_name,
            DataQualityCheck.check_type,
            DataQualityCheck.severity,
            func.count(DataQualityCheck.id).label("failures"),
            func.max(DataQualityCheck.created_at).label("last_failed_at"),
            func.array_agg(PipelineRun.pipeline_key.distinct()).label("pipeline_keys"),
        )
        .join(PipelineRun, DataQualityCheck.pipeline_run_id == PipelineRun.id)
        .where(DataQualityCheck.status == CheckStatus.FAILED)
        .group_by(
            DataQualityCheck.check_name,
            DataQualityCheck.check_type,
            DataQualityCheck.severity,
        )
    )
    if since:
        statement = statement.where(DataQualityCheck.created_at >= since)

    groups = [
        FailedCheckGroup(
            check_name=row.check_name,
            check_type=row.check_type,
            severity=row.severity,
            failures=int(row.failures),
            last_failed_at=row.last_failed_at,
            pipeline_keys=sorted(row.pipeline_keys),
        )
        for row in session.execute(statement)
    ]
    return order_failed_check_groups(groups)


def order_failed_check_groups(groups: list[FailedCheckGroup]) -> list[FailedCheckGroup]:
    """Order grouped failures worst-first, then most frequent, then by name.

    Ordered in Python rather than in SQL because ``CheckSeverity`` has no
    natural sort in the database — ordering it there means a ``CASE``
    expression restating ``SEVERITY_ORDER``, which would then be two
    definitions of one fact. The grouped result is at most a few dozen rows,
    so sorting it here costs nothing.

    The name is the final tie-break so that two renders of identical data
    produce identical pages; without it the order would depend on whatever
    the database happened to return.
    """
    return sorted(
        groups,
        key=lambda group: (-SEVERITY_ORDER[group.severity], -group.failures, group.check_name),
    )


@dataclass(frozen=True)
class RunStatusAggregate:
    """Cumulative totals for one pipeline in one status."""

    pipeline_key: str
    status: PipelineStatus
    runs: int
    records_extracted: int
    records_inserted: int
    records_updated: int
    records_unchanged: int
    records_rejected: int
    duration_ms: int


def _latest_by_pipeline(
    session: Session, *, statuses: Sequence[PipelineStatus] | None = None
) -> dict[str, PipelineRun]:
    """Return the newest run per pipeline in one query.

    Twenty-three ``latest_run`` calls is the right shape for one page load and
    the wrong one for a scrape every fifteen seconds. ``DISTINCT ON`` requires
    its ``ORDER BY`` to lead with the distinct column, which is why
    ``pipeline_key`` comes first and ``started_at`` descending still decides
    which row survives.
    """
    statement = (
        select(PipelineRun)
        .distinct(PipelineRun.pipeline_key)
        .order_by(PipelineRun.pipeline_key, PipelineRun.started_at.desc())
    )
    if statuses is not None:
        statement = statement.where(PipelineRun.status.in_(statuses))
    return {run.pipeline_key: run for run in session.scalars(statement)}


def latest_runs_by_pipeline(session: Session) -> dict[str, PipelineRun]:
    """Return every pipeline's most recent run, keyed by pipeline key."""
    return _latest_by_pipeline(session)


def latest_successful_runs_by_pipeline(session: Session) -> dict[str, PipelineRun]:
    """Return every pipeline's most recent run that did not fail.

    ``partial`` counts: it means some data was written, which is what a
    freshness gauge cares about.
    """
    return _latest_by_pipeline(session, statuses=[PipelineStatus.SUCCESS, PipelineStatus.PARTIAL])


def aggregate_runs_by_pipeline(session: Session) -> list[RunStatusAggregate]:
    """Return cumulative run, record and duration totals per pipeline and status.

    ``duration_ms`` is nullable — a run that crashed before finishing never got
    one — so its sum is coalesced, or a single crashed run would null the whole
    pipeline's total. The record counters are ``NOT NULL`` with a default of 0
    and every group holds at least one row, so their sums cannot be null;
    coalescing them too would imply a null is possible there.
    """
    statement = select(
        PipelineRun.pipeline_key,
        PipelineRun.status,
        func.count(PipelineRun.id).label("runs"),
        func.sum(PipelineRun.records_extracted).label("extracted"),
        func.sum(PipelineRun.records_inserted).label("inserted"),
        func.sum(PipelineRun.records_updated).label("updated"),
        func.sum(PipelineRun.records_unchanged).label("unchanged"),
        func.sum(PipelineRun.records_rejected).label("rejected"),
        func.coalesce(func.sum(PipelineRun.duration_ms), 0).label("duration_ms"),
    ).group_by(PipelineRun.pipeline_key, PipelineRun.status)

    return [
        RunStatusAggregate(
            pipeline_key=row.pipeline_key,
            status=row.status,
            runs=int(row.runs),
            records_extracted=int(row.extracted),
            records_inserted=int(row.inserted),
            records_updated=int(row.updated),
            records_unchanged=int(row.unchanged),
            records_rejected=int(row.rejected),
            duration_ms=int(row.duration_ms),
        )
        for row in session.execute(statement)
    ]
