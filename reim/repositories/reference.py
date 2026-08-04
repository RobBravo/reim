"""Read/lookup helpers for the reference tables."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from reim.core.exceptions import UnknownReferenceError
from reim.database.models import Country, DataSource, Indicator, Organization


def get_country_by_iso2(session: Session, iso2: str) -> Country | None:
    """Return the country with this ISO alpha-2 code, if it exists."""
    return session.scalar(select(Country).where(Country.iso2 == iso2.upper()))


def get_country_by_iso3(session: Session, iso3: str) -> Country | None:
    """Return the country with this ISO alpha-3 code, if it exists."""
    return session.scalar(select(Country).where(Country.iso3 == iso3.upper()))


def require_country_by_iso3(session: Session, iso3: str) -> Country:
    """Return the country or raise :class:`UnknownReferenceError`."""
    country = get_country_by_iso3(session, iso3)
    if country is None:
        msg = f"Country {iso3!r} is not registered; run 'reim db seed' first"
        raise UnknownReferenceError(msg, iso3=iso3)
    return country


def get_indicator_by_code(session: Session, code: str) -> Indicator | None:
    """Return the indicator with this code, if it exists."""
    return session.scalar(select(Indicator).where(Indicator.code == code))


def require_indicator_by_code(session: Session, code: str) -> Indicator:
    """Return the indicator or raise :class:`UnknownReferenceError`."""
    indicator = get_indicator_by_code(session, code)
    if indicator is None:
        msg = f"Indicator {code!r} is not registered; run 'reim db seed' first"
        raise UnknownReferenceError(msg, indicator_code=code)
    return indicator


def get_source_by_key(session: Session, source_key: str) -> DataSource | None:
    """Return the data source with this catalog key, if it exists."""
    return session.scalar(select(DataSource).where(DataSource.source_key == source_key))


def require_source_by_key(session: Session, source_key: str) -> DataSource:
    """Return the data source or raise :class:`UnknownReferenceError`."""
    source = get_source_by_key(session, source_key)
    if source is None:
        msg = f"Source {source_key!r} is not registered; run 'reim db seed' first"
        raise UnknownReferenceError(msg, source_key=source_key)
    return source


def get_organization_by_code(session: Session, code: str) -> Organization | None:
    """Return the organization with this code, if it exists."""
    return session.scalar(select(Organization).where(Organization.code == code))


def list_countries(session: Session, *, active_only: bool = False) -> list[Country]:
    """Return countries ordered by name."""
    statement = select(Country).order_by(Country.name)
    if active_only:
        statement = statement.where(Country.is_active.is_(True))
    return list(session.scalars(statement))


def list_organizations(session: Session, *, country_iso2: str | None = None) -> list[Organization]:
    """Return organizations ordered by code, optionally filtered by country."""
    statement = select(Organization).order_by(Organization.code)
    if country_iso2:
        statement = statement.join(Country, Organization.country_id == Country.id).where(
            Country.iso2 == country_iso2.upper()
        )
    return list(session.scalars(statement))
