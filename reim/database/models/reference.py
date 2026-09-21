"""Reference entities: countries, organizations, data sources and indicators."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reim.core.constants import (
    AccessType,
    Frequency,
    IndicatorCategory,
    OrganizationType,
    SeasonalAdjustment,
    SourceFormat,
    ValueType,
)
from reim.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from reim.database.types import enum_column

if TYPE_CHECKING:
    from reim.database.models.observation import Observation
    from reim.database.models.pipeline import PipelineRun


class Country(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A sovereign country covered by REIM."""

    __tablename__ = "countries"

    iso2: Mapped[str] = mapped_column(String(2), unique=True, nullable=False)
    iso3: Mapped[str] = mapped_column(String(3), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_local: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str] = mapped_column(String(80), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    currency_name: Mapped[str | None] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: GeoJSON Geometry (Polygon/MultiPolygon) for this country's outline, or
    #: None if not yet recorded. Never a Feature — every other field a
    #: Feature's properties would carry already exists on this row. Built
    #: offline; see reim/domain/geography/boundaries/README.md.
    geometry_geojson: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    organizations: Mapped[list[Organization]] = relationship(back_populates="country")
    data_sources: Mapped[list[DataSource]] = relationship(back_populates="country")
    observations: Mapped[list[Observation]] = relationship(back_populates="country")
    administrative_areas: Mapped[list[AdministrativeArea]] = relationship(back_populates="country")

    __table_args__ = (Index("ix_countries_is_active", "is_active"),)


class AdministrativeArea(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A geographic subdivision below the country level.

    REIM's first geography below ``Country``. ``level`` names the kind of
    subdivision ("province" is the only value today); ``code`` is the
    publisher's own identifier, kept verbatim rather than re-derived, so a
    connector's fixture and REIM's stored row are traceably the same thing.
    """

    __tablename__ = "administrative_areas"

    country_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("countries.id", ondelete="RESTRICT"), nullable=False
    )
    level: Mapped[str] = mapped_column(String(40), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    #: GeoJSON Geometry (Polygon/MultiPolygon) for this area's outline, or
    #: None if not yet recorded. Same shape and provenance as
    #: Country.geometry_geojson.
    geometry_geojson: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    country: Mapped[Country] = relationship(back_populates="administrative_areas")
    observations: Mapped[list[Observation]] = relationship(back_populates="administrative_area")

    __table_args__ = (
        UniqueConstraint("country_id", "level", "code", name="uq_administrative_area_natural_key"),
        Index("ix_administrative_areas_country_id", "country_id"),
    )


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An institution that publishes economic information.

    ``country_id`` is null for multilateral and regional bodies.
    """

    __tablename__ = "organizations"

    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(80))
    country_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("countries.id", ondelete="RESTRICT")
    )
    organization_type: Mapped[OrganizationType] = mapped_column(
        enum_column(OrganizationType, "organization_type"), nullable=False
    )
    website_url: Mapped[str | None] = mapped_column(String(500))
    is_official: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    country: Mapped[Country | None] = relationship(back_populates="organizations")
    data_sources: Mapped[list[DataSource]] = relationship(back_populates="organization")


class DataSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A concrete, addressable dataset published by an organization.

    Rows are synchronised from ``sources/catalog.yml``; the catalog is the source
    of truth and the table is its materialisation.
    """

    __tablename__ = "data_sources"

    source_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    country_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("countries.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[IndicatorCategory] = mapped_column(
        enum_column(IndicatorCategory, "source_category"), nullable=False
    )
    access_type: Mapped[AccessType] = mapped_column(
        enum_column(AccessType, "access_type"), nullable=False
    )
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    frequency: Mapped[Frequency] = mapped_column(
        enum_column(Frequency, "source_frequency"), nullable=False
    )
    source_format: Mapped[SourceFormat] = mapped_column(
        enum_column(SourceFormat, "source_format"), nullable=False
    )
    connector_path: Mapped[str | None] = mapped_column(String(300))
    license: Mapped[str | None] = mapped_column(String(120))
    documentation_url: Mapped[str | None] = mapped_column(String(500))
    is_official: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    disabled_reason: Mapped[str | None] = mapped_column(Text)

    organization: Mapped[Organization] = relationship(back_populates="data_sources")
    country: Mapped[Country | None] = relationship(back_populates="data_sources")
    observations: Mapped[list[Observation]] = relationship(back_populates="source")
    pipeline_runs: Mapped[list[PipelineRun]] = relationship(back_populates="source")

    __table_args__ = (
        Index("ix_data_sources_country_id", "country_id"),
        Index("ix_data_sources_is_active", "is_active"),
    )


class Indicator(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A canonical economic concept, independent of who publishes it.

    The same indicator can be fed by several sources; ``Observation`` keeps the
    provenance so competing series remain distinguishable.
    """

    __tablename__ = "indicators"

    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[IndicatorCategory] = mapped_column(
        enum_column(IndicatorCategory, "indicator_category"), nullable=False
    )
    frequency: Mapped[Frequency] = mapped_column(
        enum_column(Frequency, "indicator_frequency"), nullable=False
    )
    unit: Mapped[str] = mapped_column(String(80), nullable=False)
    value_type: Mapped[ValueType] = mapped_column(
        enum_column(ValueType, "value_type"), nullable=False
    )
    seasonal_adjustment: Mapped[SeasonalAdjustment] = mapped_column(
        enum_column(SeasonalAdjustment, "seasonal_adjustment"),
        default=SeasonalAdjustment.NOT_ADJUSTED,
        nullable=False,
    )
    methodology_url: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    observations: Mapped[list[Observation]] = relationship(back_populates="indicator")

    __table_args__ = (
        Index("ix_indicators_category", "category"),
        Index("ix_indicators_frequency", "frequency"),
    )
