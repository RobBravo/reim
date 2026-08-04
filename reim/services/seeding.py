"""Seeding of reference data.

Countries, organizations and indicators come from the in-code registries;
data sources come from ``sources/catalog.yml``. Seeding is idempotent: it
inserts what is missing and updates what has drifted, and never deletes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from reim.core.exceptions import UnknownReferenceError
from reim.core.logging import get_logger
from reim.database.models import Country, DataSource, Indicator, Organization
from reim.domain.countries.registry import COUNTRIES
from reim.domain.indicators.registry import INDICATORS
from reim.domain.sources.catalog import SourceCatalog, get_catalog
from reim.domain.sources.organizations import ORGANIZATIONS

logger = get_logger(__name__)


@dataclass(slots=True)
class SeedReport:
    """Counts of what seeding created and updated."""

    countries_created: int = 0
    countries_updated: int = 0
    organizations_created: int = 0
    organizations_updated: int = 0
    indicators_created: int = 0
    indicators_updated: int = 0
    sources_created: int = 0
    sources_updated: int = 0

    @property
    def total_created(self) -> int:
        """Rows inserted across all reference tables."""
        return (
            self.countries_created
            + self.organizations_created
            + self.indicators_created
            + self.sources_created
        )

    @property
    def total_updated(self) -> int:
        """Rows modified across all reference tables."""
        return (
            self.countries_updated
            + self.organizations_updated
            + self.indicators_updated
            + self.sources_updated
        )


def _sync(entity: object, values: Mapping[str, object]) -> bool:
    """Apply ``values`` to ``entity``; return True when something changed."""
    changed = False
    for field, value in values.items():
        if getattr(entity, field) != value:
            setattr(entity, field, value)
            changed = True
    return changed


def seed_countries(session: Session, report: SeedReport) -> None:
    """Insert or refresh every country in the registry."""
    existing = {country.iso2: country for country in session.scalars(select(Country))}
    for definition in COUNTRIES:
        values = {
            "iso3": definition.iso3,
            "name": definition.name,
            "name_local": definition.name_local,
            "region": definition.region,
            "currency_code": definition.currency_code,
            "currency_name": definition.currency_name,
            "is_active": definition.is_active,
        }
        current = existing.get(definition.iso2)
        if current is None:
            session.add(Country(iso2=definition.iso2, **values))
            report.countries_created += 1
        elif _sync(current, values):
            report.countries_updated += 1
    session.flush()


def seed_organizations(session: Session, report: SeedReport) -> None:
    """Insert or refresh every organization in the registry."""
    countries = {country.iso2: country for country in session.scalars(select(Country))}
    existing = {org.code: org for org in session.scalars(select(Organization))}

    for definition in ORGANIZATIONS:
        country_id = None
        if definition.country_iso2:
            country = countries.get(definition.country_iso2)
            if country is None:
                msg = (
                    f"Organization {definition.code} references unseeded country "
                    f"{definition.country_iso2}"
                )
                raise UnknownReferenceError(msg, organization=definition.code)
            country_id = country.id

        values = {
            "name": definition.name,
            "short_name": definition.short_name,
            "country_id": country_id,
            "organization_type": definition.organization_type,
            "website_url": definition.website_url,
            "is_official": definition.is_official,
        }
        current = existing.get(definition.code)
        if current is None:
            session.add(Organization(code=definition.code, **values))
            report.organizations_created += 1
        elif _sync(current, values):
            report.organizations_updated += 1
    session.flush()


def seed_indicators(session: Session, report: SeedReport) -> None:
    """Insert or refresh every indicator in the registry."""
    existing = {indicator.code: indicator for indicator in session.scalars(select(Indicator))}
    for definition in INDICATORS:
        values = {
            "name": definition.name,
            "description": definition.description,
            "category": definition.category,
            "frequency": definition.frequency,
            "unit": definition.unit,
            "value_type": definition.value_type,
            "seasonal_adjustment": definition.seasonal_adjustment,
            "methodology_url": definition.methodology_url,
            "is_active": definition.is_active,
        }
        current = existing.get(definition.code)
        if current is None:
            session.add(Indicator(code=definition.code, **values))
            report.indicators_created += 1
        elif _sync(current, values):
            report.indicators_updated += 1
    session.flush()


def seed_sources(session: Session, report: SeedReport, catalog: SourceCatalog) -> None:
    """Materialise the catalog into the ``data_sources`` table.

    The catalog stays the source of truth; entries removed from it are left in
    the database (never deleted) so historical observations keep a valid
    foreign key. Removing a source therefore requires a deliberate migration.
    """
    countries = {country.iso2: country for country in session.scalars(select(Country))}
    organizations = {org.code: org for org in session.scalars(select(Organization))}
    existing = {source.source_key: source for source in session.scalars(select(DataSource))}

    for entry in catalog.sources:
        organization = organizations.get(entry.organization)
        if organization is None:
            msg = f"Source {entry.key} references unseeded organization {entry.organization}"
            raise UnknownReferenceError(msg, source_key=entry.key)

        country_id = None
        if entry.country_iso2:
            country = countries.get(entry.country_iso2)
            if country is None:
                msg = f"Source {entry.key} references unseeded country {entry.country_iso2}"
                raise UnknownReferenceError(msg, source_key=entry.key)
            country_id = country.id

        values = {
            "organization_id": organization.id,
            "country_id": country_id,
            "name": entry.name,
            "description": entry.description,
            "category": entry.category,
            "access_type": entry.access_type,
            "base_url": str(entry.base_url),
            "frequency": entry.frequency,
            "source_format": entry.format,
            "connector_path": entry.connector,
            "license": entry.license,
            "documentation_url": str(entry.documentation_url) if entry.documentation_url else None,
            "is_official": entry.official,
            "is_active": entry.enabled,
            "disabled_reason": entry.disabled_reason,
        }
        current = existing.get(entry.key)
        if current is None:
            session.add(DataSource(source_key=entry.key, **values))
            report.sources_created += 1
        elif _sync(current, values):
            report.sources_updated += 1
    session.flush()


def seed_all(session: Session, catalog: SourceCatalog | None = None) -> SeedReport:
    """Seed every reference table, in dependency order.

    Args:
        session: Active session; the caller owns the transaction.
        catalog: Catalog to materialise. Defaults to the process-wide catalog.
    """
    report = SeedReport()
    seed_countries(session, report)
    seed_organizations(session, report)
    seed_indicators(session, report)
    seed_sources(session, report, catalog or get_catalog())
    logger.info(
        "seed.completed",
        created=report.total_created,
        updated=report.total_updated,
    )
    return report
