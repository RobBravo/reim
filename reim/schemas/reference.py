"""Response schemas for the reference resources."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reim.core.constants import (
    AccessType,
    Frequency,
    IndicatorCategory,
    OrganizationType,
    SeasonalAdjustment,
    SourceFormat,
    ValueType,
)
from reim.domain.indicators.registry import INDICATORS_BY_CODE


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

    #: Both come from the indicator registry, not from the database. The
    #: registry is the authority for what an indicator *is*; the tables are a
    #: projection for querying, and neither flag has a column.
    currency_convertible: bool = Field(
        default=False,
        description=(
            "Whether this indicator's values are amounts denominated in a currency "
            "and may therefore be converted. False for rates, indices and ratios, "
            "which are expressed *per* a currency rather than *in* it. "
            "`/compare?convert_to=USD` rejects an indicator that is false here, so "
            "a client can tell before asking."
        ),
    )
    methodology_varies_by_country: bool = Field(
        default=False,
        description=(
            "Whether the publisher defines this indicator differently in each "
            "country, so that levels may not be read against each other even when "
            "the unit and currency match. Movements over time remain comparable."
        ),
    )

    @model_validator(mode="after")
    def _fill_registry_flags(self) -> IndicatorRead:
        """Read the two registry flags for this code, if the registry knows it.

        Filled here rather than left to each caller so that no future
        constructor of an ``IndicatorRead`` can omit them.

        An indicator can exist in the database and not in the registry — a
        catalog entry removed from the code but not from a deployed database,
        say. Both flags then stay at their defaults: the registry saying
        nothing is not the same as it saying no, but a client asking after a
        capability REIM cannot describe is better served by the conservative
        answer than by an invented one.
        """
        definition = INDICATORS_BY_CODE.get(self.code)
        if definition is not None:
            self.currency_convertible = definition.currency_convertible
            self.methodology_varies_by_country = definition.methodology_varies_by_country
        return self
