"""Canonical administrative-area definitions below the country level.

REIM's first geography below ``Country``. Only Panama's provinces exist today
— INEC Panama is the only subnational source REIM reads — but nothing here is
Panama-specific: a second country's subnational source would add its own
tuple of definitions, not change this shape.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AdministrativeAreaDefinition:
    """Static description of a subdivision below one country."""

    country_iso2: str
    level: str
    code: str
    name: str


#: Panama's ten provinces, as INEC's own ``nivel_geografico=Provincia``
#: choropleth endpoint codes them. Codes "10"-"12" are the three indigenous
#: comarcas, a different administrative category and not provinces. Some
#: ``Provincia``-level responses include them; connectors reading this data
#: must filter them out rather than assume they are absent.
PANAMA_PROVINCES: tuple[AdministrativeAreaDefinition, ...] = (
    AdministrativeAreaDefinition(
        country_iso2="PA", level="province", code="01", name="Bocas del Toro"
    ),
    AdministrativeAreaDefinition(country_iso2="PA", level="province", code="02", name="Coclé"),
    AdministrativeAreaDefinition(country_iso2="PA", level="province", code="03", name="Colón"),
    AdministrativeAreaDefinition(country_iso2="PA", level="province", code="04", name="Chiriquí"),
    AdministrativeAreaDefinition(country_iso2="PA", level="province", code="05", name="Darién"),
    AdministrativeAreaDefinition(country_iso2="PA", level="province", code="06", name="Herrera"),
    AdministrativeAreaDefinition(country_iso2="PA", level="province", code="07", name="Los Santos"),
    AdministrativeAreaDefinition(country_iso2="PA", level="province", code="08", name="Panamá"),
    AdministrativeAreaDefinition(country_iso2="PA", level="province", code="09", name="Veraguas"),
    AdministrativeAreaDefinition(
        country_iso2="PA", level="province", code="13", name="Panamá Oeste"
    ),
)

#: Every registered administrative area, source of truth for seeding.
ADMINISTRATIVE_AREAS: tuple[AdministrativeAreaDefinition, ...] = PANAMA_PROVINCES
