"""Operational bookkeeping: pipeline runs and the quality checks they produce."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reim.core.constants import CheckSeverity, CheckStatus, CheckType, PipelineStatus
from reim.database.base import Base, UUIDPrimaryKeyMixin
from reim.database.types import enum_column

if TYPE_CHECKING:
    from reim.database.models.reference import DataSource


class PipelineRun(UUIDPrimaryKeyMixin, Base):
    """One execution of one ingestion pipeline.

    A row is created *before* extraction starts so that crashes are still
    observable, and finalised in a ``finally`` block.
    """

    __tablename__ = "pipeline_runs"

    pipeline_key: Mapped[str] = mapped_column(String(120), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    connector_version: Mapped[str | None] = mapped_column(String(20))
    pipeline_version: Mapped[str | None] = mapped_column(String(20))

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column()

    status: Mapped[PipelineStatus] = mapped_column(
        enum_column(PipelineStatus, "pipeline_status"),
        default=PipelineStatus.RUNNING,
        nullable=False,
    )

    records_extracted: Mapped[int] = mapped_column(default=0, nullable=False)
    records_inserted: Mapped[int] = mapped_column(default=0, nullable=False)
    records_updated: Mapped[int] = mapped_column(default=0, nullable=False)
    records_unchanged: Mapped[int] = mapped_column(default=0, nullable=False)
    records_rejected: Mapped[int] = mapped_column(default=0, nullable=False)

    error_type: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)

    run_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    source: Mapped[DataSource | None] = relationship(back_populates="pipeline_runs")
    quality_checks: Mapped[list[DataQualityCheck]] = relationship(
        back_populates="pipeline_run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_pipeline_runs_pipeline_key_started_at", "pipeline_key", "started_at"),
        Index("ix_pipeline_runs_status", "status"),
        Index("ix_pipeline_runs_source_id", "source_id"),
    )


class DataQualityCheck(UUIDPrimaryKeyMixin, Base):
    """Result of a single quality check evaluated during a pipeline run."""

    __tablename__ = "data_quality_checks"

    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False
    )
    check_name: Mapped[str] = mapped_column(String(120), nullable=False)
    check_type: Mapped[CheckType] = mapped_column(
        enum_column(CheckType, "check_type"), nullable=False
    )
    status: Mapped[CheckStatus] = mapped_column(
        enum_column(CheckStatus, "check_status"), nullable=False
    )
    severity: Mapped[CheckSeverity] = mapped_column(
        enum_column(CheckSeverity, "check_severity"), nullable=False
    )
    indicator_code: Mapped[str | None] = mapped_column(String(80))
    period_label: Mapped[str | None] = mapped_column(String(32))
    expected_value: Mapped[str | None] = mapped_column(String(200))
    actual_value: Mapped[str | None] = mapped_column(String(200))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    pipeline_run: Mapped[PipelineRun] = relationship(back_populates="quality_checks")

    __table_args__ = (
        Index("ix_data_quality_checks_pipeline_run_id", "pipeline_run_id"),
        Index("ix_data_quality_checks_status_severity", "status", "severity"),
    )
