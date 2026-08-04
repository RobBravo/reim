"""Query helpers for pipeline runs and quality checks."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload

from reim.core.constants import CheckSeverity, CheckStatus, PipelineStatus
from reim.database.models import DataQualityCheck, PipelineRun


def _apply(
    statement: Select[tuple[PipelineRun]],
    *,
    pipeline_key: str | None,
    status: PipelineStatus | None,
) -> Select[tuple[PipelineRun]]:
    if pipeline_key:
        statement = statement.where(PipelineRun.pipeline_key == pipeline_key)
    if status:
        statement = statement.where(PipelineRun.status == status)
    return statement


def list_runs(
    session: Session,
    *,
    pipeline_key: str | None = None,
    status: PipelineStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[PipelineRun]:
    """Return pipeline runs, newest first."""
    statement = _apply(
        select(PipelineRun).order_by(PipelineRun.started_at.desc()),
        pipeline_key=pipeline_key,
        status=status,
    )
    return list(session.scalars(statement.limit(limit).offset(offset)))


def count_runs(
    session: Session,
    *,
    pipeline_key: str | None = None,
    status: PipelineStatus | None = None,
) -> int:
    """Return how many runs match the filters."""
    statement = _apply(
        select(func.count(PipelineRun.id)).select_from(PipelineRun),  # type: ignore[arg-type]
        pipeline_key=pipeline_key,
        status=status,
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
