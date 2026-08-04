"""Typed domain exceptions.

Every REIM failure derives from :class:`REIMError` and carries a stable
``code`` used verbatim in API error envelopes and in structured logs.
"""

from __future__ import annotations

from typing import Any


class REIMError(Exception):
    """Base class for every error raised by REIM."""

    code: str = "reim_error"
    http_status: int = 500

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-serializable payload used by the API error envelope."""
        return {"code": self.code, "message": self.message, "details": self.details}


# --------------------------------------------------------------------------
# Configuration / catalog
# --------------------------------------------------------------------------
class ConfigurationError(REIMError):
    """Invalid or missing application configuration."""

    code = "configuration_error"


class CatalogError(REIMError):
    """The source catalog could not be loaded."""

    code = "catalog_error"


class CatalogValidationError(CatalogError):
    """The source catalog is syntactically valid YAML but semantically invalid."""

    code = "catalog_validation_error"


# --------------------------------------------------------------------------
# Ingestion
# --------------------------------------------------------------------------
class IngestionError(REIMError):
    """Base class for failures during ingestion."""

    code = "ingestion_error"


class ConnectorNotFoundError(IngestionError):
    """No connector is registered under the requested key."""

    code = "connector_not_found"
    http_status = 404


class ConnectorLoadError(IngestionError):
    """A connector module exists but could not be imported or instantiated."""

    code = "connector_load_error"


class ExtractionError(IngestionError):
    """The source could not be reached or returned an unusable response."""

    code = "extraction_error"


class TransformationError(IngestionError):
    """A payload was retrieved but could not be normalized."""

    code = "transformation_error"


class CriticalQualityError(IngestionError):
    """A ``critical`` quality check failed; the load must be rolled back."""

    code = "critical_quality_failure"

    def __init__(
        self, message: str, failed_checks: list[str] | None = None, **details: Any
    ) -> None:
        super().__init__(message, failed_checks=failed_checks or [], **details)
        self.failed_checks = failed_checks or []


# --------------------------------------------------------------------------
# Domain / persistence
# --------------------------------------------------------------------------
class DomainError(REIMError):
    """Base class for domain rule violations."""

    code = "domain_error"
    http_status = 400


class InvalidPeriodError(DomainError):
    """A reporting period could not be parsed or is internally inconsistent."""

    code = "invalid_period"


class UnknownReferenceError(DomainError):
    """An observation references a country, indicator or source that does not exist."""

    code = "unknown_reference"


class ResourceNotFoundError(REIMError):
    """A requested resource does not exist."""

    code = "not_found"
    http_status = 404


class InvalidRequestError(REIMError):
    """The caller supplied an invalid combination of query parameters."""

    code = "invalid_request"
    http_status = 400
