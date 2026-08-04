"""Response schemas for observations."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

from reim.core.constants import ObservationStatus, ValidationStatus
from reim.database.models import Observation


class ObservationRead(BaseModel):
    """A single economic datapoint with its provenance.

    The reporting period is exposed as an explicit interval; ``period_label``
    carries the label the source itself used.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID

    country_iso2: str
    country_iso3: str
    country_name: str
    indicator_code: str
    indicator_name: str
    source_key: str

    period_start: date
    period_end: date
    period_label: str

    value_numeric: Decimal | None
    value_text: str | None
    unit: str
    currency_code: str | None

    published_at: datetime | None
    retrieved_at: datetime
    source_url: str
    source_record_id: str | None
    content_hash: str

    status: ObservationStatus
    validation_status: ValidationStatus
    revision_count: int = Field(description="How many times the source has revised this datapoint.")
    connector_version: str
    pipeline_version: str
    raw_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, observation: Observation) -> ObservationRead:
        """Flatten an ORM observation and its joined reference rows."""
        return cls(
            id=observation.id,
            country_iso2=observation.country.iso2,
            country_iso3=observation.country.iso3,
            country_name=observation.country.name,
            indicator_code=observation.indicator.code,
            indicator_name=observation.indicator.name,
            source_key=observation.source.source_key,
            period_start=observation.period_start,
            period_end=observation.period_end,
            period_label=observation.period_label,
            value_numeric=observation.value_numeric,
            value_text=observation.value_text,
            unit=observation.unit,
            currency_code=observation.currency_code,
            published_at=observation.published_at,
            retrieved_at=observation.retrieved_at,
            source_url=observation.source_url,
            source_record_id=observation.source_record_id,
            content_hash=observation.content_hash,
            status=observation.status,
            validation_status=observation.validation_status,
            revision_count=observation.revision_count,
            connector_version=observation.connector_version,
            pipeline_version=observation.pipeline_version,
            raw_metadata=observation.raw_metadata,
            created_at=observation.created_at,
            updated_at=observation.updated_at,
        )


class ObservationRevisionRead(BaseModel):
    """A recorded upstream revision of an observation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    observation_id: uuid.UUID
    revision_number: int
    revised_at: datetime
    previous_value_numeric: Decimal | None
    new_value_numeric: Decimal | None
    previous_content_hash: str
    new_content_hash: str
    change_reason: str | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def value_delta(self) -> Decimal | None:
        """New value minus previous value, when both are numeric."""
        if self.previous_value_numeric is None or self.new_value_numeric is None:
            return None
        return self.new_value_numeric - self.previous_value_numeric


#: Column order used by the CSV export. Kept explicit so the file format is a
#: deliberate, stable contract rather than a side effect of the schema.
CSV_COLUMNS: tuple[str, ...] = (
    "country_iso3",
    "country_name",
    "indicator_code",
    "indicator_name",
    "period_label",
    "period_start",
    "period_end",
    "value_numeric",
    "unit",
    "currency_code",
    "source_key",
    "source_url",
    "published_at",
    "retrieved_at",
    "validation_status",
    "revision_count",
    "connector_version",
    "pipeline_version",
    "content_hash",
)
