"""Nicaragua — personal remittances received, from the World Bank."""

from __future__ import annotations

from typing import ClassVar

from reim.ingestion.connectors.common.worldbank import WorldBankConnector


class WorldBankNicaraguaRemittances(WorldBankConnector):
    """World Bank series ``BX.TRF.PWKR.CD.DT`` for Nicaragua.

    Personal remittances received in current US dollars. Remittances are one of
    the largest external flows into the Nicaraguan economy, which makes this a
    headline series for the MVP.
    """

    connector_key = "worldbank_ni_remittances"
    version = "1.0.0"
    series_code: ClassVar[str] = "BX.TRF.PWKR.CD.DT"
    indicator_code: ClassVar[str] = "ni_remittances_received"
    unit: ClassVar[str] = "current USD"
    currency_code: ClassVar[str | None] = "USD"
