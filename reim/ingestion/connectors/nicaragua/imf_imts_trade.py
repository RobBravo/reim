"""Nicaragua — monthly merchandise trade from the IMF's IMTS dataflow."""

from __future__ import annotations

from reim.ingestion.connectors.common.imf_imts import ImfImtsTradeConnector


class ImfImtsNicaragua(ImfImtsTradeConnector):
    """IMF IMTS merchandise trade for Nicaragua.

    Everything but the catalog key comes from the base: the country is read
    from the catalog entry, so this class carries no country of its own.
    """

    connector_key = "imf_imts_nicaragua"
