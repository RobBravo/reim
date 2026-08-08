"""Declarative source catalog: schema, loader and validation.

``sources/catalog.yml`` is the single source of truth for which sources exist,
who publishes them, how they are reached and which connector implements them.
The application refuses to start on an invalid catalog rather than silently
ingesting from an unknown source.
"""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError, model_validator

from reim.core.config import get_settings
from reim.core.constants import (
    AccessType,
    Frequency,
    IndicatorCategory,
    SourceFormat,
    TlsProfile,
)
from reim.core.exceptions import CatalogError, CatalogValidationError
from reim.domain.countries.registry import COUNTRIES_BY_ISO2
from reim.domain.indicators.registry import INDICATORS_BY_CODE
from reim.domain.sources.organizations import ORGANIZATIONS_BY_CODE

#: Hosts reserved by RFC 2606 / RFC 6761 for documentation. A source that is
#: marked enabled must point at a real host.
PLACEHOLDER_HOSTS = ("example.invalid", "example.com", "example.org", "example.net", "localhost")

SourceKey = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$", max_length=120)]


class SourceEntry(BaseModel):
    """One entry of ``sources/catalog.yml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: SourceKey
    name: str = Field(min_length=3, max_length=200)
    description: str | None = None
    country: str | None = Field(default=None, min_length=2, max_length=2)
    organization: str = Field(min_length=2, max_length=40)
    category: IndicatorCategory
    access_type: AccessType
    frequency: Frequency
    format: SourceFormat
    base_url: HttpUrl
    documentation_url: HttpUrl | None = None
    connector: str = Field(pattern=r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)+$")
    indicators: list[str] = Field(min_length=1)
    license: str = "public_official_data"
    official: bool = True
    enabled: bool = True
    disabled_reason: str | None = None
    #: TLS policy this host requires. ``LEGACY`` must justify itself.
    tls_profile: TlsProfile = TlsProfile.MODERN
    tls_note: str | None = None
    #: Free-form connector configuration, passed through unchanged.
    options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_entry(self) -> Self:
        if self.country is not None:
            iso2 = self.country.upper()
            if iso2 not in COUNTRIES_BY_ISO2:
                msg = f"unknown country {self.country!r}"
                raise ValueError(msg)

        if self.organization not in ORGANIZATIONS_BY_CODE:
            known = ", ".join(sorted(ORGANIZATIONS_BY_CODE))
            msg = f"unknown organization {self.organization!r} (known: {known})"
            raise ValueError(msg)

        unknown = [code for code in self.indicators if code not in INDICATORS_BY_CODE]
        if unknown:
            msg = f"unknown indicator code(s): {', '.join(sorted(unknown))}"
            raise ValueError(msg)

        if len(set(self.indicators)) != len(self.indicators):
            msg = "duplicate indicator codes in 'indicators'"
            raise ValueError(msg)

        host = (self.base_url.host or "").lower()
        if self.enabled and any(host == p or host.endswith(f".{p}") for p in PLACEHOLDER_HOSTS):
            msg = f"enabled source must not use the placeholder host {host!r}"
            raise ValueError(msg)

        if not self.enabled and not self.disabled_reason:
            msg = "a disabled source must document 'disabled_reason'"
            raise ValueError(msg)

        if self.tls_profile is TlsProfile.LEGACY and not self.tls_note:
            msg = "a source with tls_profile 'legacy' must document 'tls_note'"
            raise ValueError(msg)

        return self

    @property
    def country_iso2(self) -> str | None:
        """Uppercase ISO-3166 alpha-2 code, or ``None`` for global sources."""
        return self.country.upper() if self.country else None


class SourceCatalog(BaseModel):
    """The whole catalog file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(default=1, ge=1)
    sources: list[SourceEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_keys(self) -> Self:
        counts = Counter(source.key for source in self.sources)
        duplicates = sorted(key for key, count in counts.items() if count > 1)
        if duplicates:
            msg = f"duplicate source key(s): {', '.join(duplicates)}"
            raise ValueError(msg)
        return self

    @property
    def enabled_sources(self) -> list[SourceEntry]:
        """Sources that should actually be executed."""
        return [source for source in self.sources if source.enabled]

    def get(self, key: str) -> SourceEntry:
        """Return the entry for ``key``.

        Raises:
            CatalogError: If no source is registered under that key.
        """
        for source in self.sources:
            if source.key == key:
                return source
        msg = f"Source {key!r} is not registered in the catalog"
        raise CatalogError(msg, available=[s.key for s in self.sources])


def load_catalog(path: Path | None = None) -> SourceCatalog:
    """Load and validate the source catalog.

    Args:
        path: Catalog location. Defaults to ``REIM_CATALOG_PATH``.

    Raises:
        CatalogError: The file is missing or is not valid YAML.
        CatalogValidationError: The file is valid YAML but violates the schema.
    """
    catalog_path = path or get_settings().catalog_path
    if not catalog_path.is_file():
        msg = f"Source catalog not found at {catalog_path}"
        raise CatalogError(msg, path=str(catalog_path))

    try:
        raw = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        msg = f"Source catalog at {catalog_path} is not valid YAML: {exc}"
        raise CatalogError(msg, path=str(catalog_path)) from exc

    if not isinstance(raw, dict):
        msg = f"Source catalog at {catalog_path} must be a YAML mapping"
        raise CatalogValidationError(msg, path=str(catalog_path))

    try:
        return SourceCatalog.model_validate(raw)
    except ValidationError as exc:
        msg = f"Source catalog at {catalog_path} is invalid:\n{_format_errors(exc)}"
        raise CatalogValidationError(
            msg, path=str(catalog_path), error_count=exc.error_count()
        ) from exc


def _format_errors(exc: ValidationError) -> str:
    lines = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        lines.append(f"  - {location}: {error['msg']}")
    return "\n".join(lines)


@lru_cache(maxsize=1)
def get_catalog() -> SourceCatalog:
    """Return the process-wide catalog singleton."""
    return load_catalog()


def reset_catalog_cache() -> None:
    """Clear the cached catalog (used by tests and the CLI)."""
    get_catalog.cache_clear()
