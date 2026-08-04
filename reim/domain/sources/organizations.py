"""Canonical publishing organizations referenced by the source catalog."""

from __future__ import annotations

from dataclasses import dataclass

from reim.core.constants import OrganizationType


@dataclass(frozen=True, slots=True)
class OrganizationDefinition:
    """Static description of an institution that publishes economic data."""

    code: str
    name: str
    short_name: str
    organization_type: OrganizationType
    website_url: str
    #: ISO2 of the country the organization belongs to; ``None`` for
    #: multilateral and regional bodies.
    country_iso2: str | None
    is_official: bool = True


ORGANIZATIONS: tuple[OrganizationDefinition, ...] = (
    # -- Nicaragua --------------------------------------------------------
    OrganizationDefinition(
        code="BCN",
        name="Banco Central de Nicaragua",
        short_name="BCN",
        organization_type=OrganizationType.CENTRAL_BANK,
        website_url="https://www.bcn.gob.ni",
        country_iso2="NI",
    ),
    OrganizationDefinition(
        code="INIDE",
        name="Instituto Nacional de Información de Desarrollo",
        short_name="INIDE",
        organization_type=OrganizationType.STATISTICS_OFFICE,
        website_url="https://www.inide.gob.ni",
        country_iso2="NI",
    ),
    OrganizationDefinition(
        code="MHCP",
        name="Ministerio de Hacienda y Crédito Público",
        short_name="MHCP",
        organization_type=OrganizationType.MINISTRY,
        website_url="https://www.mhcp.gob.ni",
        country_iso2="NI",
    ),
    OrganizationDefinition(
        code="SIBOIF",
        name="Superintendencia de Bancos y de Otras Instituciones Financieras",
        short_name="SIBOIF",
        organization_type=OrganizationType.SUPERVISORY_AUTHORITY,
        website_url="https://www.siboif.gob.ni",
        country_iso2="NI",
    ),
    # -- Regional ---------------------------------------------------------
    OrganizationDefinition(
        code="SIECA",
        name="Secretaría de Integración Económica Centroamericana",
        short_name="SIECA",
        organization_type=OrganizationType.REGIONAL_BODY,
        website_url="https://www.sieca.int",
        country_iso2=None,
    ),
    OrganizationDefinition(
        code="BCIE",
        name="Banco Centroamericano de Integración Económica",
        short_name="BCIE",
        organization_type=OrganizationType.REGIONAL_BODY,
        website_url="https://www.bcie.org",
        country_iso2=None,
    ),
    # -- Multilateral -----------------------------------------------------
    OrganizationDefinition(
        code="WORLDBANK",
        name="World Bank",
        short_name="World Bank",
        organization_type=OrganizationType.MULTILATERAL,
        website_url="https://data.worldbank.org",
        country_iso2=None,
    ),
    OrganizationDefinition(
        code="IMF",
        name="International Monetary Fund",
        short_name="IMF",
        organization_type=OrganizationType.MULTILATERAL,
        website_url="https://www.imf.org",
        country_iso2=None,
    ),
    OrganizationDefinition(
        code="CEPAL",
        name="Comisión Económica para América Latina y el Caribe",
        short_name="CEPAL",
        organization_type=OrganizationType.MULTILATERAL,
        website_url="https://www.cepal.org",
        country_iso2=None,
    ),
)

ORGANIZATIONS_BY_CODE: dict[str, OrganizationDefinition] = {o.code: o for o in ORGANIZATIONS}
