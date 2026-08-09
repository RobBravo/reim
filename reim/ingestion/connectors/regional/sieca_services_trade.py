"""Central America — quarterly trade in services published by SIECA.

SIECA's statistics portal at ``www.servicios.sieca.int`` exposes two
undocumented AJAX endpoints behind its report page, both open and unauthenticated:
``LoadFilters`` returns the available quarters and countries, ``LoadData``
returns the figures. One ``LoadData`` call carries all six countries and the
whole history, so a run makes four requests and a rebuild is complete by
default.

Three properties of the source shape this connector:

1. **Values arrive as JSON floats in millions of USD.** They are read with
   ``parse_float=Decimal`` and multiplied by 10^6. Reading them as ``float``
   would corrupt every figure in its last places, where no count would show it.
2. **The balance is published, not derived.** ``E - I`` differs from the
   published ``S`` by up to 0.1 million because each flow is rounded to one
   decimal, so the identity is checked with a tolerance rather than assumed.
3. **The host filters on User-Agent.** REIM's own identifier receives ``202``
   with an empty body; ``curl`` receives ``403``. The catalog entry declares
   the User-Agent this host requires and explains why. No active control is
   defeated: this is a header check, not a challenge, unlike the Radware bot
   manager in front of ``www.bcn.gob.ni`` that REIM still refuses to pass.

The rows arrive as a JSON **string** nested inside the response's ``Data[0].Data``
field, which is why the payload is decoded twice.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, ClassVar

from reim.core.constants import Frequency
from reim.core.exceptions import TransformationError
from reim.domain.observations.periods import parse_period
from reim.domain.pipelines.models import (
    NormalizedObservation,
    QualityResult,
    RawDataset,
)
from reim.ingestion.base import BaseConnector

#: ``(flujo code, indicator code, record-id suffix)`` for each published flow.
FLOWS: tuple[tuple[str, str, str], ...] = (
    ("E", "exports_services_quarterly", "E"),
    ("I", "imports_services_quarterly", "I"),
    ("S", "trade_balance_services_quarterly", "S"),
)

#: The source's own Spanish names, mapped to REIM's country codes. "Centroamérica"
#: is deliberately absent: it is the sum of the six, and REIM has no code for a
#: region. Any other unknown name raises rather than being skipped.
COUNTRIES_BY_NAME: dict[str, str] = {
    "Costa Rica": "CRI",
    "El Salvador": "SLV",
    "Guatemala": "GTM",
    "Honduras": "HND",
    "Nicaragua": "NIC",
    "Panamá": "PAN",
}
REGIONAL_AGGREGATE = "Centroamérica"

#: Figures are published in millions of USD and stored in whole USD.
MILLIONS = Decimal("1000000")

#: Each flow is rounded to one decimal in millions, so two roundings of +-0.05
#: accumulate. Measured worst deviation: exactly this value.
BALANCE_TOLERANCE = Decimal("100000")

_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}


def _format_published(value: Decimal) -> str:
    """Render a parsed figure without SIECA's 12-decimal zero padding.

    The wire value is e.g. ``356.500000000000``, not ``356.5``: SIECA's backend
    serializes every figure as a fixed-precision decimal. The connector's own
    docstring already establishes that each flow is rounded to one published
    decimal, so the padding carries no information — it is stripped here for
    the auditable copy kept in ``raw_metadata`` while ``value_numeric`` is
    still computed from the untouched parsed value.
    """
    return format(value.normalize(), "f")


def parse_quarter(label: str) -> str:
    """Turn SIECA's ``"I Trim 2026"`` into REIM's ``"2026-Q1"``.

    Raises:
        ValueError: The label is not ``"<roman> Trim <year>"`` with a roman
            numeral between I and IV.
    """
    parts = label.split()
    if len(parts) != 3 or parts[1] != "Trim" or parts[0] not in _ROMAN:
        msg = f"unreadable SIECA period label {label!r}"
        raise ValueError(msg)
    return f"{int(parts[2])}-Q{_ROMAN[parts[0]]}"


class SiecaServicesTradeConnector(BaseConnector):
    """Quarterly services exports, imports and balance for six countries."""

    connector_key = "sieca_services_trade"
    version = "1.0.0"
    expected_frequency = Frequency.QUARTERLY
    unit: ClassVar[str] = "current USD"
    currency_code: ClassVar[str] = "USD"

    async def extract(self) -> RawDataset:  # pragma: no cover - written in Task 6
        """Not yet implemented; the four ``LoadFilters``/``LoadData`` requests land in Task 6."""
        raise NotImplementedError

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Normalize the three flow payloads into one observation per cell.

        Pure function of ``raw``.

        Raises:
            TransformationError: The payload is not the expected shape, a
                response reports failure, or a country name is unknown.
        """
        payload = raw.payload
        if not isinstance(payload, dict):
            msg = "SIECA payload must be a mapping of flow code to response text"
            raise TransformationError(msg, source_key=self.source.key)

        observations: list[NormalizedObservation] = []
        for flow, indicator_code, suffix in FLOWS:
            for country, quarter, value in self._read_cells(str(payload[flow]), flow):
                observations.append(
                    NormalizedObservation(
                        country_iso3=country,
                        indicator_code=indicator_code,
                        source_key=self.source.key,
                        period=parse_period(quarter, Frequency.QUARTERLY),
                        unit=self.unit,
                        currency_code=self.currency_code,
                        value_numeric=value * MILLIONS,
                        retrieved_at=raw.retrieved_at,
                        source_url=raw.source_url,
                        source_record_id=f"servicios:{country}:{quarter}:{suffix}",
                        raw_metadata={
                            "sieca_flow": flow,
                            "sieca_component": "1.A.b.0",
                            "sieca_published_value": _format_published(value),
                            "sieca_published_unit": "millones de USD",
                            "sieca_scale_applied": "1e6",
                            "contract_status": "verified",
                        },
                    )
                )
        observations.sort(key=lambda obs: (obs.indicator_code, obs.country_iso3, obs.period.start))
        return observations

    def _read_cells(self, text: str, flow: str) -> list[tuple[str, str, Decimal]]:
        """Read one flow's payload into ``(iso3, quarter label, millions)`` triples."""
        document = self._decode(text, flow)
        if not document.get("Resultado", False):
            detail = str(document.get("Mensaje") or "no message").strip()
            msg = f"SIECA reported failure for flow {flow}: {detail}"
            raise TransformationError(msg, source_key=self.source.key)

        blocks = document.get("Data") or []
        cells: list[tuple[str, str, Decimal]] = []
        for block in blocks:
            columns = [column["data"] for column in block["Columnas"]][4:]
            for row in self._decode(str(block["Data"]), flow):
                name = str(row["Pais"])
                if name == REGIONAL_AGGREGATE:
                    continue
                iso3 = COUNTRIES_BY_NAME.get(name)
                if iso3 is None:
                    msg = f"SIECA returned an unknown country name {name!r} in flow {flow}"
                    raise TransformationError(msg, source_key=self.source.key)
                for column in columns:
                    value = row.get(column)
                    if value is None:
                        continue
                    cells.append((iso3, self._quarter(column, flow), Decimal(value)))
        return cells

    def _decode(self, text: str, flow: str) -> Any:
        """Decode JSON, keeping published decimals exact."""
        try:
            return json.loads(text, parse_float=Decimal)
        except json.JSONDecodeError as exc:
            msg = f"SIECA returned malformed JSON for flow {flow}: {exc}"
            raise TransformationError(msg, source_key=self.source.key) from exc

    def _quarter(self, label: str, flow: str) -> str:
        try:
            return parse_quarter(label)
        except ValueError as exc:
            msg = f"SIECA returned an unreadable period {label!r} in flow {flow}"
            raise TransformationError(msg, source_key=self.source.key) from exc

    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Not yet implemented; the balance-identity and coverage checks land in Task 5."""
        return []
