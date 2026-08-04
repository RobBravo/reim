"""Nicaragua — exports of goods and services, from the World Bank."""

from __future__ import annotations

from typing import ClassVar

from reim.ingestion.connectors.common.worldbank import WorldBankConnector


class WorldBankNicaraguaExports(WorldBankConnector):
    """World Bank series ``NE.EXP.GNFS.CD`` for Nicaragua.

    Exports of goods and services in current US dollars. Paired with the imports
    connector, this gives the trade balance without REIM computing a derived
    figure the source does not publish.
    """

    connector_key = "worldbank_ni_exports"
    version = "1.0.0"
    series_code: ClassVar[str] = "NE.EXP.GNFS.CD"
    indicator_code: ClassVar[str] = "ni_exports_goods_services"
    unit: ClassVar[str] = "current USD"
    currency_code: ClassVar[str | None] = "USD"
