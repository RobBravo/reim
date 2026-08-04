"""Nicaragua — official exchange rate (annual average), from the World Bank."""

from __future__ import annotations

from typing import ClassVar

from reim.ingestion.connectors.common.worldbank import WorldBankConnector


class WorldBankNicaraguaExchangeRate(WorldBankConnector):
    """World Bank series ``PA.NUS.FCRF`` for Nicaragua.

    Official exchange rate in local currency units per US dollar, period
    average. This is the *annual* view; the daily official rate comes from the
    BCN connector, which is currently disabled (see ``docs/sources.md``).
    """

    connector_key = "worldbank_ni_exchange_rate"
    version = "1.0.0"
    series_code: ClassVar[str] = "PA.NUS.FCRF"
    indicator_code: ClassVar[str] = "ni_exchange_rate_official_annual_avg"
    unit: ClassVar[str] = "NIO per USD"
    currency_code: ClassVar[str | None] = "NIO"
