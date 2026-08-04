"""Nicaragua — annual consumer price inflation, from the World Bank."""

from __future__ import annotations

from typing import ClassVar

from reim.ingestion.connectors.common.worldbank import WorldBankConnector


class WorldBankNicaraguaCpiInflation(WorldBankConnector):
    """World Bank series ``FP.CPI.TOTL.ZG`` for Nicaragua.

    Annual percentage change of the consumer price index, compiled by the World
    Bank from national statistics. It is the annual counterpart of the monthly
    IPC published by INIDE, which has no stable machine-readable endpoint yet.
    """

    connector_key = "worldbank_ni_cpi_inflation"
    version = "1.0.0"
    series_code: ClassVar[str] = "FP.CPI.TOTL.ZG"
    indicator_code: ClassVar[str] = "ni_cpi_inflation_annual"
    unit: ClassVar[str] = "percent"
