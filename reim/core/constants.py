"""Enumerations shared across the domain, persistence and API layers.

Every enum inherits from :class:`str` so values round-trip through JSON, YAML,
SQL and query parameters without conversion helpers.
"""

from __future__ import annotations

from enum import StrEnum

REGION_CENTRAL_AMERICA = "Central America"


class Frequency(StrEnum):
    """Publication cadence of a source or indicator series."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMIANNUAL = "semiannual"
    ANNUAL = "annual"
    IRREGULAR = "irregular"


#: Nominal length of one period, used by freshness and frequency checks.
FREQUENCY_DAYS: dict[Frequency, int] = {
    Frequency.DAILY: 1,
    Frequency.WEEKLY: 7,
    Frequency.MONTHLY: 31,
    Frequency.QUARTERLY: 92,
    Frequency.SEMIANNUAL: 184,
    Frequency.ANNUAL: 366,
    Frequency.IRREGULAR: 3650,
}


class AccessType(StrEnum):
    """How a source is technically reached."""

    HTTP = "http"
    HTTP_API = "http_api"
    SOAP = "soap"
    FILE_DOWNLOAD = "file_download"
    MANUAL = "manual"


class SourceFormat(StrEnum):
    """Payload format returned by a source."""

    JSON = "json"
    CSV = "csv"
    XML = "xml"
    XLSX = "xlsx"
    XLS = "xls"
    HTML = "html"
    PDF = "pdf"


class OrganizationType(StrEnum):
    """Institutional category of a publishing organization."""

    CENTRAL_BANK = "central_bank"
    STATISTICS_OFFICE = "statistics_office"
    MINISTRY = "ministry"
    SUPERVISORY_AUTHORITY = "supervisory_authority"
    REGIONAL_BODY = "regional_body"
    MULTILATERAL = "multilateral"
    OTHER = "other"


class IndicatorCategory(StrEnum):
    """Thematic grouping used by the indicator catalog and API filters."""

    EXCHANGE_RATE = "exchange_rate"
    PRICES = "prices"
    EXTERNAL_SECTOR = "external_sector"
    MONETARY = "monetary"
    FISCAL = "fiscal"
    REAL_SECTOR = "real_sector"
    LABOR = "labor"
    FINANCIAL = "financial"


class ValueType(StrEnum):
    """Semantics of the stored numeric value."""

    LEVEL = "level"
    INDEX = "index"
    RATE = "rate"
    PERCENT = "percent"
    PERCENT_CHANGE = "percent_change"
    RATIO = "ratio"


class SeasonalAdjustment(StrEnum):
    """Whether a series is seasonally adjusted."""

    NOT_ADJUSTED = "not_adjusted"
    SEASONALLY_ADJUSTED = "seasonally_adjusted"
    UNKNOWN = "unknown"


class ObservationStatus(StrEnum):
    """Lifecycle status of a stored observation."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class ValidationStatus(StrEnum):
    """Outcome of the quality gate for a single observation."""

    PASSED = "passed"
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    REJECTED = "rejected"
    UNVALIDATED = "unvalidated"


class PipelineStatus(StrEnum):
    """Terminal (or current) state of a pipeline run."""

    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class CheckType(StrEnum):
    """Family a quality check belongs to."""

    COMPLETENESS = "completeness"
    VALIDITY = "validity"
    UNIQUENESS = "uniqueness"
    CONSISTENCY = "consistency"
    TIMELINESS = "timeliness"
    ACCURACY = "accuracy"
    INTEGRITY = "integrity"


class CheckStatus(StrEnum):
    """Result of running a quality check."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class CheckSeverity(StrEnum):
    """How much a failing check matters.

    ``CRITICAL`` aborts the whole load (transaction rollback); ``ERROR`` rejects
    the affected observations; ``WARNING`` and ``INFO`` are recorded only.
    """

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


#: Ordering used to decide the most severe outcome of a check set.
SEVERITY_ORDER: dict[CheckSeverity, int] = {
    CheckSeverity.INFO: 0,
    CheckSeverity.WARNING: 1,
    CheckSeverity.ERROR: 2,
    CheckSeverity.CRITICAL: 3,
}


class Environment(StrEnum):
    """Deployment environment."""

    LOCAL = "local"
    TEST = "test"
    CI = "ci"
    STAGING = "staging"
    PRODUCTION = "production"
