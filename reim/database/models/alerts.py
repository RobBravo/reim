"""Alert bookkeeping: what has been notified, and whether it has recovered."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from reim.database.base import Base, UUIDPrimaryKeyMixin


class AlertState(UUIDPrimaryKeyMixin, Base):
    """One alert condition on one pipeline, and when it was last spoken about.

    Deliberately not a ``TimestampMixin`` table. That mixin's ``updated_at``
    refreshes on every flush, including the one that sets ``resolved_at``, so it
    would sit beside ``last_notified_at`` looking like the same fact while
    diverging from it. ``first_notified_at`` is this row's creation time.

    A row stays open until the condition stops holding; the partial unique index
    permits exactly one open row per ``(condition, pipeline_key)`` while letting
    resolved rows accumulate as history.
    """

    __tablename__ = "alert_states"

    condition: Mapped[str] = mapped_column(String(32), nullable=False)
    pipeline_key: Mapped[str] = mapped_column(String(120), nullable=False)

    first_notified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_notified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Figures sent with the last notification, so a resolution notice can
    #: quote what the problem had been without recomputing it.
    details: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)

    __table_args__ = (
        Index(
            "uq_alert_states_open_condition_pipeline",
            "condition",
            "pipeline_key",
            unique=True,
            postgresql_where=resolved_at.is_(None),
        ),
        Index("ix_alert_states_pipeline_key", "pipeline_key"),
    )
