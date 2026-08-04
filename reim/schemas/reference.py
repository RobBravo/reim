"""Response schemas for the reference resources."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from reim.core.constants import (
    AccessType,
    Frequency,
    IndicatorCategory,
    OrganizationType,
    SeasonalAdjustment,
    SourceFormat,
    ValueType,
)


class CountryRead(BaseModel):
    """A country covered by REIM."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    iso2: str
    iso3: str
    name: str
    name_local: str | None = None
    region: str
    currency_code: str
    currency_name: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class OrganizationRead(BaseModel):
    """An institution that publishes economic data."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    short_name: str | None = None
    organization_type: OrganizationType
    website_url: str | None = None
    is_official: bool
    country_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class DataSourceRead(BaseModel):
    """A registered data source."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_key: str
    name: str
    description: str | None = None
    category: IndicatorCategory
    access_type: AccessType
    base_url: str
    frequency: Frequency
    source_format: SourceFormat = Field(serialization_alias="format")
    connector_path: str | None = None
    license: str | None = None
    documentation_url: str | None = None
    is_official: bool
    is_active: bool
    disabled_reason: str | None = Field(
        default=None,
        description="Why an inactive source is not being ingested.",
    )
    organization_id: uuid.UUID
    country_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class IndicatorRead(BaseModel):
    """A tracked economic concept."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None = None
    category: IndicatorCategory
    frequency: Frequency
    unit: str
    value_type: ValueType
    seasonal_adjustment: SeasonalAdjustment
    methodology_url: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
