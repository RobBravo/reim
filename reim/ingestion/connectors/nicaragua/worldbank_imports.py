"""Nicaragua — imports of goods and services, from the World Bank."""

from __future__ import annotations

from typing import ClassVar

from reim.ingestion.connectors.common.worldbank import WorldBankConnector


class WorldBankNicaraguaImports(WorldBankConnector):
    """World Bank series ``NE.IMP.GNFS.CD`` for Nicaragua.

    Imports of goods and services in current US dollars.
    """

    connector_key = "worldbank_ni_imports"
    version = "1.0.0"
    series_code: ClassVar[str] = "NE.IMP.GNFS.CD"
    indicator_code: ClassVar[str] = "ni_imports_goods_services"
    unit: ClassVar[str] = "current USD"
    currency_code: ClassVar[str | None] = "USD"
