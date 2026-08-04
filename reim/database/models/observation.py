"""Observations — the fact table — and their revision audit trail."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reim.core.constants import ObservationStatus, ValidationStatus
from reim.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from reim.database.types import EconomicNumeric, enum_column

if TYPE_CHECKING:
    from reim.database.models.reference import Country, DataSource, Indicator

#: Natural key of an observation. A source may publish exactly one value for a
#: given indicator, country and reporting period; a second arrival for the same
#: key is either a no-op (identical payload) or a revision.
NATURAL_KEY_COLUMNS = ("country_id", "indicator_id", "source_id", "period_start", "period_end")


class Observation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single economic datapoint with complete provenance.

    The reporting period is stored as an explicit closed interval
    ``[period_start, period_end]`` plus a human-readable ``period_label``. A
    monthly figure is never collapsed into a single calendar day.
    """

    __tablename__ = "observations"

    # -- Dimensions -------------------------------------------------------
    country_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("countries.id", ondelete="RESTRICT"), nullable=False
    )
    indicator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("indicators.id", ondelete="RESTRICT"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )

    # -- Reporting period -------------------------------------------------
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    period_label: Mapped[str] = mapped_column(String(32), nullable=False)

    # -- Measurement ------------------------------------------------------
    value_numeric: Mapped[Decimal | None] = mapped_column(EconomicNumeric)
    value_text: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(80), nullable=False)
    currency_code: Mapped[str | None] = mapped_column(String(3))

    # -- Provenance -------------------------------------------------------
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(200))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # -- Lifecycle --------------------------------------------------------
    status: Mapped[ObservationStatus] = mapped_column(
        enum_column(ObservationStatus, "observation_status"),
        default=ObservationStatus.ACTIVE,
        nullable=False,
    )
    validation_status: Mapped[ValidationStatus] = mapped_column(
        enum_column(ValidationStatus, "validation_status"),
        default=ValidationStatus.UNVALIDATED,
        nullable=False,
    )
    revision_count: Mapped[int] = mapped_column(default=0, nullable=False)

    connector_version: Mapped[str] = mapped_column(String(20), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # -- Relationships ----------------------------------------------------
    country: Mapped[Country] = relationship(back_populates="observations")
    indicator: Mapped[Indicator] = relationship(back_populates="observations")
    source: Mapped[DataSource] = relationship(back_populates="observations")
    revisions: Mapped[list[ObservationRevision]] = relationship(
        back_populates="observation",
        cascade="all, delete-orphan",
        order_by="ObservationRevision.revised_at.desc()",
    )

    __table_args__ = (
        UniqueConstraint(*NATURAL_KEY_COLUMNS, name="uq_observations_natural_key"),
        CheckConstraint("period_end >= period_start", name="period_range_valid"),
        CheckConstraint(
            "value_numeric IS NOT NULL OR value_text IS NOT NULL",
            name="value_present",
        ),
        Index(
            "ix_observations_country_indicator_period", "country_id", "indicator_id", "period_start"
        ),
        Index("ix_observations_indicator_period", "indicator_id", "period_start"),
        Index("ix_observations_source_id", "source_id"),
        Index("ix_observations_validation_status", "validation_status"),
        Index("ix_observations_content_hash", "content_hash"),
        Index("ix_observations_retrieved_at", "retrieved_at"),
    )


class ObservationRevision(UUIDPrimaryKeyMixin, Base):
    """Snapshot of an observation's values *before* an upstream revision.

    Written whenever a source republishes a datapoint with a different payload.
    Nothing is ever deleted: the current row holds the latest official value and
    the full previous history is recoverable from this table.
    """

    __tablename__ = "observation_revisions"

    observation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("observations.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(nullable=False)
    revised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    previous_value_numeric: Mapped[Decimal | None] = mapped_column(EconomicNumeric)
    previous_value_text: Mapped[str | None] = mapped_column(Text)
    previous_unit: Mapped[str | None] = mapped_column(String(80))
    previous_currency_code: Mapped[str | None] = mapped_column(String(3))
    previous_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    previous_retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    new_value_numeric: Mapped[Decimal | None] = mapped_column(EconomicNumeric)
    new_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_runs.id", ondelete="SET NULL")
    )
    change_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    observation: Mapped[Observation] = relationship(back_populates="revisions")

    __table_args__ = (
        UniqueConstraint(
            "observation_id", "revision_number", name="uq_observation_revisions_observation_id"
        ),
        Index("ix_observation_revisions_revised_at", "revised_at"),
    )
