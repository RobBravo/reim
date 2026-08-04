"""Response schemas for pipeline operations and system status."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from reim.core.constants import (
    CheckSeverity,
    CheckStatus,
    CheckType,
    Frequency,
    PipelineStatus,
)


class QualityCheckRead(BaseModel):
    """One recorded quality-check result."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    check_name: str
    check_type: CheckType
    status: CheckStatus
    severity: CheckSeverity
    indicator_code: str | None
    period_label: str | None
    expected_value: str | None
    actual_value: str | None
    details: dict[str, object]
    created_at: datetime


class PipelineRunRead(BaseModel):
    """A pipeline execution record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pipeline_key: str
    source_id: uuid.UUID | None
    connector_version: str | None
    pipeline_version: str | None
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    status: PipelineStatus
    records_extracted: int
    records_inserted: int
    records_updated: int
    records_unchanged: int
    records_rejected: int
    error_type: str | None
    error_message: str | None
    run_metadata: dict[str, object]
    created_at: datetime


class PipelineRunDetail(PipelineRunRead):
    """A pipeline run together with the checks it produced."""

    quality_checks: list[QualityCheckRead] = Field(default_factory=list)


class PipelineSummary(BaseModel):
    """Operational health of one registered pipeline."""

    pipeline_key: str
    source_key: str
    enabled: bool = Field(description="Whether the catalog marks this source active.")
    disabled_reason: str | None = None
    frequency: Frequency
    indicators: list[str]

    last_run_at: datetime | None = None
    last_run_status: PipelineStatus | None = None
    last_run_duration_ms: int | None = None
    last_success_at: datetime | None = None
    last_error_type: str | None = None
    last_error_message: str | None = None

    records_inserted_last_run: int | None = None
    records_updated_last_run: int | None = None
    records_rejected_last_run: int | None = None

    observation_count: int = Field(default=0, description="Rows currently stored for this source.")
    latest_period_end: date | None = Field(
        default=None, description="Newest reporting period stored for this source."
    )
    data_age_days: int | None = Field(
        default=None, description="Days between the newest stored period and today."
    )
    is_stale: bool | None = Field(
        default=None,
        description=(
            "True when the newest stored period is older than the configured "
            "freshness threshold for the primary indicator."
        ),
    )


class SystemStatus(BaseModel):
    """Aggregate platform status."""

    version: str
    environment: str
    database_connected: bool
    countries: int
    indicators: int
    sources_registered: int
    sources_enabled: int
    observations: int
    pipeline_runs: int
    last_ingestion_at: datetime | None
    failed_checks_last_7_days: dict[str, int]
    generated_at: datetime


class HealthStatus(BaseModel):
    """Liveness response."""

    status: str = "ok"
    version: str


class ReadinessStatus(BaseModel):
    """Readiness response, including dependency checks."""

    status: str
    version: str
    checks: dict[str, bool]
