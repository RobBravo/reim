"""Nicaragua — total international reserves, from the World Bank."""

from __future__ import annotations

from typing import ClassVar

from reim.ingestion.connectors.common.worldbank import WorldBankConnector


class WorldBankNicaraguaReserves(WorldBankConnector):
    """World Bank series ``FI.RES.TOTL.CD`` for Nicaragua.

    Total reserves including gold, in current US dollars. Sourced by the World
    Bank from IMF International Financial Statistics.
    """

    connector_key = "worldbank_ni_reserves"
    version = "1.0.0"
    series_code: ClassVar[str] = "FI.RES.TOTL.CD"
    indicator_code: ClassVar[str] = "ni_international_reserves"
    unit: ClassVar[str] = "current USD"
    currency_code: ClassVar[str | None] = "USD"
