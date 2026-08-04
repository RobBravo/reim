"""Idempotent persistence of normalized observations.

Three outcomes are possible for each incoming observation:

``inserted``
    The natural key is new.
``unchanged``
    The natural key exists and the content hash matches — nothing is written.
    This is what makes re-running a pipeline a no-op.
``updated``
    The natural key exists but the content hash differs: the source revised the
    datapoint. The previous values are snapshotted into
    ``observation_revisions`` before the row is updated. Nothing is ever deleted.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy.orm import Session

from reim import PIPELINE_VERSION
from reim.core.constants import ObservationStatus, ValidationStatus
from reim.core.logging import get_logger
from reim.database.models import Country, DataSource, Indicator, Observation, ObservationRevision
from reim.domain.pipelines.models import NormalizedObservation
from reim.repositories.observations import get_by_natural_key
from reim.repositories.reference import (
    require_country_by_iso3,
    require_indicator_by_code,
    require_source_by_key,
)

logger = get_logger(__name__)


class WriteOutcome(StrEnum):
    """What happened to a single observation during a write."""

    INSERTED = "inserted"
    UNCHANGED = "unchanged"
    UPDATED = "updated"


@dataclass(slots=True)
class WriteReport:
    """Aggregated result of writing a batch."""

    inserted: int = 0
    unchanged: int = 0
    updated: int = 0
    rejected: int = 0
    revised_keys: list[str] = field(default_factory=list)

    @property
    def written(self) -> int:
        """Number of rows actually created or modified."""
        return self.inserted + self.updated

    def record(self, outcome: WriteOutcome) -> None:
        """Increment the counter matching ``outcome``."""
        match outcome:
            case WriteOutcome.INSERTED:
                self.inserted += 1
            case WriteOutcome.UNCHANGED:
                self.unchanged += 1
            case WriteOutcome.UPDATED:
                self.updated += 1


@dataclass(slots=True)
class _ReferenceCache:
    """Per-batch cache so reference lookups do not hit the DB once per row."""

    countries: dict[str, Country] = field(default_factory=dict)
    indicators: dict[str, Indicator] = field(default_factory=dict)
    sources: dict[str, DataSource] = field(default_factory=dict)

    def country(self, session: Session, iso3: str) -> Country:
        """Return (and memoise) the country for ``iso3``."""
        if iso3 not in self.countries:
            self.countries[iso3] = require_country_by_iso3(session, iso3)
        return self.countries[iso3]

    def indicator(self, session: Session, code: str) -> Indicator:
        """Return (and memoise) the indicator for ``code``."""
        if code not in self.indicators:
            self.indicators[code] = require_indicator_by_code(session, code)
        return self.indicators[code]

    def source(self, session: Session, key: str) -> DataSource:
        """Return (and memoise) the data source for ``key``."""
        if key not in self.sources:
            self.sources[key] = require_source_by_key(session, key)
        return self.sources[key]


def write_observations(
    session: Session,
    observations: list[NormalizedObservation],
    *,
    connector_version: str,
    validation_status_by_index: dict[int, ValidationStatus] | None = None,
    rejected_indices: set[int] | None = None,
    pipeline_run_id: uuid.UUID | None = None,
    pipeline_version: str = PIPELINE_VERSION,
) -> WriteReport:
    """Persist a batch idempotently within the caller's transaction.

    The caller owns the transaction: this function only flushes. A critical
    failure upstream therefore rolls the whole batch back.

    Args:
        session: Active session inside an open transaction.
        observations: Transformed observations, in extraction order.
        connector_version: Stamped on every row written.
        validation_status_by_index: Per-observation validation outcome. Missing
            entries default to ``PASSED``.
        rejected_indices: Indices that failed an ``error``-level check and must
            not be persisted at all.
        pipeline_run_id: Recorded on any revision rows created.
        pipeline_version: Stamped on every row written.

    Returns:
        A :class:`WriteReport` with the per-outcome counts.
    """
    rejected = rejected_indices or set()
    statuses = validation_status_by_index or {}
    cache = _ReferenceCache()
    report = WriteReport(rejected=len(rejected))
    now = datetime.now(UTC)

    for index, incoming in enumerate(observations):
        if index in rejected:
            continue

        country = cache.country(session, incoming.country_iso3)
        indicator = cache.indicator(session, incoming.indicator_code)
        source = cache.source(session, incoming.source_key)
        digest = incoming.compute_content_hash()

        existing = get_by_natural_key(
            session,
            country_id=country.id,
            indicator_id=indicator.id,
            source_id=source.id,
            period_start=incoming.period.start,
            period_end=incoming.period.end,
        )
        status = statuses.get(index, ValidationStatus.PASSED)

        if existing is None:
            session.add(
                _build_observation(
                    incoming,
                    country=country,
                    indicator=indicator,
                    source=source,
                    content_hash=digest,
                    validation_status=status,
                    connector_version=connector_version,
                    pipeline_version=pipeline_version,
                )
            )
            report.record(WriteOutcome.INSERTED)
            continue

        if existing.content_hash == digest:
            # Same datapoint, same payload: touch nothing so updated_at and the
            # revision history stay meaningful.
            report.record(WriteOutcome.UNCHANGED)
            continue

        _record_revision(
            session,
            existing,
            incoming=incoming,
            new_hash=digest,
            revised_at=now,
            pipeline_run_id=pipeline_run_id,
        )
        _apply_revision(
            existing,
            incoming,
            content_hash=digest,
            validation_status=status,
            connector_version=connector_version,
            pipeline_version=pipeline_version,
        )
        report.record(WriteOutcome.UPDATED)
        report.revised_keys.append(f"{incoming.indicator_code}@{incoming.period.label}")

    session.flush()
    logger.info(
        "observations.written",
        inserted=report.inserted,
        updated=report.updated,
        unchanged=report.unchanged,
        rejected=report.rejected,
    )
    return report


def _build_observation(
    incoming: NormalizedObservation,
    *,
    country: Country,
    indicator: Indicator,
    source: DataSource,
    content_hash: str,
    validation_status: ValidationStatus,
    connector_version: str,
    pipeline_version: str,
) -> Observation:
    return Observation(
        country_id=country.id,
        indicator_id=indicator.id,
        source_id=source.id,
        period_start=incoming.period.start,
        period_end=incoming.period.end,
        period_label=incoming.period.label,
        value_numeric=incoming.value_numeric,
        value_text=incoming.value_text,
        unit=incoming.unit,
        currency_code=incoming.currency_code,
        published_at=incoming.published_at,
        retrieved_at=incoming.retrieved_at,
        source_url=incoming.source_url,
        source_record_id=incoming.source_record_id,
        content_hash=content_hash,
        status=ObservationStatus.ACTIVE,
        validation_status=validation_status,
        revision_count=0,
        connector_version=connector_version,
        pipeline_version=pipeline_version,
        raw_metadata=incoming.raw_metadata,
    )


def _record_revision(
    session: Session,
    existing: Observation,
    *,
    incoming: NormalizedObservation,
    new_hash: str,
    revised_at: datetime,
    pipeline_run_id: uuid.UUID | None,
) -> None:
    """Snapshot the current values before they are overwritten."""
    session.add(
        ObservationRevision(
            observation_id=existing.id,
            revision_number=existing.revision_count + 1,
            revised_at=revised_at,
            previous_value_numeric=existing.value_numeric,
            previous_value_text=existing.value_text,
            previous_unit=existing.unit,
            previous_currency_code=existing.currency_code,
            previous_content_hash=existing.content_hash,
            previous_published_at=existing.published_at,
            previous_retrieved_at=existing.retrieved_at,
            new_value_numeric=incoming.value_numeric,
            new_content_hash=new_hash,
            pipeline_run_id=pipeline_run_id,
            change_reason="Upstream source republished this period with different values",
            created_at=revised_at,
        )
    )
    logger.info(
        "observation.revised",
        indicator=incoming.indicator_code,
        period=incoming.period.label,
        previous_value=str(existing.value_numeric),
        new_value=str(incoming.value_numeric),
        revision_number=existing.revision_count + 1,
    )


def _apply_revision(
    existing: Observation,
    incoming: NormalizedObservation,
    *,
    content_hash: str,
    validation_status: ValidationStatus,
    connector_version: str,
    pipeline_version: str,
) -> None:
    """Update the stored row in place; ``created_at`` is preserved."""
    existing.value_numeric = incoming.value_numeric
    existing.value_text = incoming.value_text
    existing.unit = incoming.unit
    existing.currency_code = incoming.currency_code
    existing.published_at = incoming.published_at
    existing.retrieved_at = incoming.retrieved_at
    existing.source_url = incoming.source_url
    existing.source_record_id = incoming.source_record_id
    existing.content_hash = content_hash
    existing.validation_status = validation_status
    existing.connector_version = connector_version
    existing.pipeline_version = pipeline_version
    existing.raw_metadata = incoming.raw_metadata
    existing.revision_count += 1
    existing.period_label = incoming.period.label
