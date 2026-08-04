"""Data contracts exchanged between connectors, the quality layer and the runner.

These are plain dataclasses rather than ORM objects on purpose: a connector must
be testable and reasoned about without a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from reim.core.constants import (
    CheckSeverity,
    CheckStatus,
    CheckType,
    PipelineStatus,
)
from reim.domain.observations.hashing import content_hash
from reim.domain.observations.periods import Period


@dataclass(slots=True)
class RawDataset:
    """Untransformed payload returned by :meth:`BaseConnector.extract`.

    Args:
        source_key: Catalog key of the source that produced the payload.
        retrieved_at: UTC timestamp of retrieval.
        source_url: The exact URL that was requested, kept for provenance.
        payload: Decoded payload (parsed JSON, CSV rows, raw XML text, ...).
        content_type: Content type reported by the server, when known.
        http_status: HTTP status code, when the source is HTTP-based.
        metadata: Anything else worth keeping for traceability.
    """

    source_key: str
    retrieved_at: datetime
    source_url: str
    payload: Any
    content_type: str | None = None
    http_status: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedObservation:
    """A datapoint after transformation, before persistence.

    ``country_iso3``, ``indicator_code`` and ``source_key`` are resolved to
    database identifiers by the runner, so connectors never touch the ORM.
    """

    country_iso3: str
    indicator_code: str
    source_key: str
    period: Period
    unit: str
    retrieved_at: datetime
    source_url: str
    value_numeric: Decimal | None = None
    value_text: str | None = None
    currency_code: str | None = None
    published_at: datetime | None = None
    source_record_id: str | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def compute_content_hash(self) -> str:
        """Return the canonical content hash for this observation."""
        return content_hash(
            country_iso3=self.country_iso3,
            indicator_code=self.indicator_code,
            source_key=self.source_key,
            period_start=self.period.start,
            period_end=self.period.end,
            value_numeric=self.value_numeric,
            value_text=self.value_text,
            unit=self.unit,
            currency_code=self.currency_code,
        )

    @property
    def natural_key(self) -> tuple[str, str, str, str, str]:
        """Return the natural key tuple identifying this datapoint."""
        return (
            self.country_iso3.upper(),
            self.indicator_code.lower(),
            self.source_key.lower(),
            self.period.start.isoformat(),
            self.period.end.isoformat(),
        )


@dataclass(slots=True)
class QualityResult:
    """Outcome of a single quality check.

    ``observation_index`` points at the offending element of the transformed
    list when the check is per-observation, and is ``None`` for dataset-level
    checks.
    """

    check_name: str
    check_type: CheckType
    status: CheckStatus
    severity: CheckSeverity
    message: str
    expected_value: str | None = None
    actual_value: str | None = None
    observation_index: int | None = None
    indicator_code: str | None = None
    period_label: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        """True when the check ran and did not pass."""
        return self.status is CheckStatus.FAILED

    @classmethod
    def passed(
        cls,
        check_name: str,
        check_type: CheckType,
        message: str,
        **kwargs: Any,
    ) -> QualityResult:
        """Build a passing result (severity is informational by definition)."""
        return cls(
            check_name=check_name,
            check_type=check_type,
            status=CheckStatus.PASSED,
            severity=CheckSeverity.INFO,
            message=message,
            **kwargs,
        )

    @classmethod
    def failure(
        cls,
        check_name: str,
        check_type: CheckType,
        severity: CheckSeverity,
        message: str,
        **kwargs: Any,
    ) -> QualityResult:
        """Build a failing result at the given severity."""
        return cls(
            check_name=check_name,
            check_type=check_type,
            status=CheckStatus.FAILED,
            severity=severity,
            message=message,
            **kwargs,
        )

    @classmethod
    def skipped(
        cls,
        check_name: str,
        check_type: CheckType,
        message: str,
        **kwargs: Any,
    ) -> QualityResult:
        """Build a skipped result, e.g. when a rule is not configured."""
        return cls(
            check_name=check_name,
            check_type=check_type,
            status=CheckStatus.SKIPPED,
            severity=CheckSeverity.INFO,
            message=message,
            **kwargs,
        )


@dataclass(slots=True)
class PipelineOutcome:
    """Summary of one pipeline execution, returned by the runner."""

    pipeline_key: str
    run_id: str
    status: PipelineStatus
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    records_extracted: int = 0
    records_inserted: int = 0
    records_updated: int = 0
    records_unchanged: int = 0
    records_rejected: int = 0
    quality_results: list[QualityResult] = field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None

    @property
    def succeeded(self) -> bool:
        """True when the run finished without a failure status."""
        return self.status in (PipelineStatus.SUCCESS, PipelineStatus.PARTIAL)

    def log_fields(self) -> dict[str, Any]:
        """Return the canonical structured-logging fields for this run."""
        return {
            "pipeline_key": self.pipeline_key,
            "run_id": self.run_id,
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "records_extracted": self.records_extracted,
            "records_inserted": self.records_inserted,
            "records_updated": self.records_updated,
            "records_unchanged": self.records_unchanged,
            "records_rejected": self.records_rejected,
        }
