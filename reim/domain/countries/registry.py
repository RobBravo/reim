"""Canonical country definitions for the Central American region.

All seven countries are active. Six carry IMF merchandise-trade data; Belize
carries none, because it reports nothing to that dataflow, and is active on
the strength of CEPALSTAT's national accounts instead. Enabling a country is
a data change, not a code change.
"""

from __future__ import annotations

from dataclasses import dataclass

from reim.core.constants import REGION_CENTRAL_AMERICA


@dataclass(frozen=True, slots=True)
class CountryDefinition:
    """Static description of a country covered (or planned) by REIM."""

    iso2: str
    iso3: str
    name: str
    name_local: str
    currency_code: str
    currency_name: str
    is_active: bool
    region: str = REGION_CENTRAL_AMERICA


COUNTRIES: tuple[CountryDefinition, ...] = (
    CountryDefinition(
        iso2="NI",
        iso3="NIC",
        name="Nicaragua",
        name_local="Nicaragua",
        currency_code="NIO",
        currency_name="Córdoba nicaragüense",
        is_active=True,
    ),
    CountryDefinition(
        iso2="GT",
        iso3="GTM",
        name="Guatemala",
        name_local="Guatemala",
        currency_code="GTQ",
        currency_name="Quetzal",
        is_active=True,
    ),
    CountryDefinition(
        iso2="SV",
        iso3="SLV",
        name="El Salvador",
        name_local="El Salvador",
        currency_code="USD",
        currency_name="US dollar",
        is_active=True,
    ),
    CountryDefinition(
        iso2="HN",
        iso3="HND",
        name="Honduras",
        name_local="Honduras",
        currency_code="HNL",
        currency_name="Lempira",
        is_active=True,
    ),
    CountryDefinition(
        iso2="CR",
        iso3="CRI",
        name="Costa Rica",
        name_local="Costa Rica",
        currency_code="CRC",
        currency_name="Colón costarricense",
        is_active=True,
    ),
    CountryDefinition(
        iso2="PA",
        iso3="PAN",
        name="Panama",
        name_local="Panamá",
        currency_code="PAB",
        currency_name="Balboa",
        is_active=True,
    ),
    CountryDefinition(
        iso2="BZ",
        iso3="BLZ",
        name="Belize",
        name_local="Belize",
        currency_code="BZD",
        currency_name="Belize dollar",
        # Belize still reports nothing to the IMF's IMTS dataflow at any
        # frequency, so REIM holds no trade data for it. CEPALSTAT publishes
        # its national accounts in full — 1990 onwards, no gaps — which is
        # where Belize's data comes from. See docs/sources.md.
        is_active=True,
    ),
)

COUNTRIES_BY_ISO2: dict[str, CountryDefinition] = {c.iso2: c for c in COUNTRIES}
COUNTRIES_BY_ISO3: dict[str, CountryDefinition] = {c.iso3: c for c in COUNTRIES}
