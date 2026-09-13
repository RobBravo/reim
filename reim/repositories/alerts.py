"""Query helpers for alert state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reim.database.models import AlertState


@dataclass(frozen=True)
class OpenAlert:
    """An alert that has been notified and has not yet resolved."""

    condition: str
    pipeline_key: str
    first_notified_at: datetime
    last_notified_at: datetime


def list_open(session: Session) -> list[OpenAlert]:
    """Return every alert still considered firing, oldest first."""
    statement = (
        select(AlertState)
        .where(AlertState.resolved_at.is_(None))
        .order_by(AlertState.first_notified_at, AlertState.condition, AlertState.pipeline_key)
    )
    return [
        OpenAlert(
            condition=row.condition,
            pipeline_key=row.pipeline_key,
            first_notified_at=row.first_notified_at,
            last_notified_at=row.last_notified_at,
        )
        for row in session.scalars(statement)
    ]


def record_notified(
    session: Session,
    *,
    condition: str,
    pipeline_key: str,
    details: dict[str, Any],
    now: datetime,
) -> None:
    """Open a new alert, or advance an existing one's last-notified time.

    ``first_notified_at`` is never moved on an open row: it is what tells an
    operator how long this has been broken.
    """
    existing = session.scalar(
        select(AlertState).where(
            AlertState.condition == condition,
            AlertState.pipeline_key == pipeline_key,
            AlertState.resolved_at.is_(None),
        )
    )
    if existing is not None:
        existing.last_notified_at = now
        existing.details = details
        return

    session.add(
        AlertState(
            condition=condition,
            pipeline_key=pipeline_key,
            first_notified_at=now,
            last_notified_at=now,
            details=details,
        )
    )
    session.flush()


def mark_resolved(session: Session, *, condition: str, pipeline_key: str, now: datetime) -> None:
    """Close the open alert for this condition and pipeline, if there is one."""
    existing = session.scalar(
        select(AlertState).where(
            AlertState.condition == condition,
            AlertState.pipeline_key == pipeline_key,
            AlertState.resolved_at.is_(None),
        )
    )
    if existing is not None:
        existing.resolved_at = now
        session.flush()
