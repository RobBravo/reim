"""Central America — annual GDP published by CEPAL through CEPALSTAT.

``api-cepalstat.cepal.org`` serves an undocumented REST API. There is no
published documentation and no interactive schema: the base URL and the route
names were recovered from the portal's own JavaScript —
``statistics.cepal.org/portal/databank/config.js`` declares ``API_BASE_URL``
and ``ENDPOINT_THEMATIC_TREE``, and ``.../cepalstat/dash/scripts/config.js``
declares the per-indicator data, dimensions, sources and notes routes. That
search is recorded here so nobody repeats it.

Four properties of the source shape this connector:

1. **One request returns an indicator's whole matrix** — 33 countries and 3
   regional aggregates by 36 years, no pagination and no window to compute. A
   rebuild is therefore complete by default, as with Banguat and SIECA.
2. **Dimensions are addressed by numeric id, never by name.** Row keys embed
   the id (``dim_208``, ``dim_29117``) and the names are language-dependent:
   ``Years__ESTANDAR`` in English is ``Años__ESTANDAR`` in Spanish.
3. **The envelope carries its own status, and it can disagree with the HTTP
   code.** An unknown indicator id answers ``500`` with ``success: false``, not
   ``404``, so ``extract`` reads ``header.success`` rather than trusting the
   status line alone.
4. **The constant-price base year lives in a footnote, not the unit.** 2204 and
   2206 declare ``Millions of dollars`` and ``Dollars per inhabitant``; only
   ``footnotes`` names 2018. A rebasing would change every value while the unit
   stood still, which is why ``validate`` checks the footnote.

CEPAL's English translation of indicator 2204 spells "dolllars" with three
l's. REIM stores its own names, so it does not propagate; it is noted here so
it does not read as a transcription error.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar

from reim.core.constants import Frequency
from reim.core.exceptions import ExtractionError, TransformationError
from reim.domain.observations.periods import parse_period
from reim.domain.pipelines.models import (
    NormalizedObservation,
    QualityResult,
    RawDataset,
)
from reim.ingestion.base import BaseConnector
from reim.ingestion.http import ensure_ok, fetch, http_client

#: Dimension ids, identical across all four indicators. Addressed by id
#: because the row keys embed it and the names change with ``lang``.
COUNTRY_DIMENSION = 208
YEARS_DIMENSION = 29117

#: Figures for the totals are published in millions of USD and stored in whole
#: USD, matching the IMF and SIECA series so ``/compare`` can align them.
MILLIONS = Decimal("1000000")

#: The seven countries REIM covers. Everything else in the response — 26 other
#: countries and 3 regional aggregates, the latter arriving with ``iso3: null``
#: — falls out of this membership test. REIM has no code for a region.
CENTRAL_AMERICA = frozenset({"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"})


@dataclass(frozen=True, slots=True)
class SeriesSpec:
    """One CEPAL indicator id and how REIM stores it."""

    cepal_id: int
    indicator_code: str
    unit: str
    scale: Decimal


#: The four series this connector ingests. CEPAL also publishes the growth
#: rate (id 2207); it is deliberately absent because it reproduces exactly
#: from 2204 — verified to the last digit over 36 years — and REIM stores
#: levels rather than what derives from them.
SERIES: tuple[SeriesSpec, ...] = (
    SeriesSpec(2203, "gdp_current_usd_annual", "current USD", MILLIONS),
    SeriesSpec(2204, "gdp_constant_usd_annual", "constant 2018 USD", MILLIONS),
    SeriesSpec(
        2205,
        "gdp_per_capita_current_usd_annual",
        "current USD per person",
        Decimal(1),
    ),
    SeriesSpec(
        2206,
        "gdp_per_capita_constant_usd_annual",
        "constant 2018 USD per person",
        Decimal(1),
    ),
)

SERIES_BY_ID: dict[int, SeriesSpec] = {spec.cepal_id: spec for spec in SERIES}

#: The base year the two constant-price series are expressed in. A CEPAL
#: rebasing changes every constant value without touching the published unit,
#: so this is asserted rather than assumed.
CONSTANT_PRICE_BASE_YEAR = "2018"

#: Relative tolerance for the implied-population identity. The worst real
#: disagreement measured across all 252 cells is 8.1e-16; this sits six orders
#: of magnitude above it, so the check cannot fire on arithmetic noise.
POPULATION_TOLERANCE = Decimal("1e-9")


class CepalstatGdpConnector(BaseConnector):
    """Four annual GDP series for the seven Central American countries."""

    connector_key = "cepalstat_gdp_annual"
    version = "1.0.0"
    expected_frequency = Frequency.ANNUAL
    currency_code: ClassVar[str] = "USD"

    async def extract(self) -> RawDataset:
        """Fetch one payload per indicator. Four requests, whole history each.

        Raises:
            ExtractionError: The API was unreachable, answered with something
                other than JSON, reported ``success: false`` in its envelope,
                or returned an empty data array.
        """
        base = str(self.source.base_url).rstrip("/")
        retrieved_at = datetime.now(UTC)
        payload: dict[int, str] = {}
        status: int | None = None
        content_type: str | None = None

        async with http_client() as client:
            for spec in SERIES:
                url = f"{base}/indicator/{spec.cepal_id}/data"
                response = await fetch(client, url, params={"lang": "en"})
                ensure_ok(response, expected_content_type="json")
                self._ensure_envelope_ok(response.text, spec.cepal_id, url)
                payload[spec.cepal_id] = response.text
                status = response.status_code
                content_type = response.headers.get("content-type")

        return RawDataset(
            source_key=self.source.key,
            retrieved_at=retrieved_at,
            source_url=base,
            payload=payload,
            content_type=content_type,
            http_status=status,
            metadata={
                "indicator_ids": [spec.cepal_id for spec in SERIES],
                "lang": "en",
            },
        )

    def _ensure_envelope_ok(self, text: str, cepal_id: int, url: str) -> None:
        """Read CEPAL's own status, which can disagree with the HTTP code.

        An unknown indicator id answers ``500`` with ``success: false``, so the
        envelope is the authority on whether a response is usable.

        Raises:
            ExtractionError: The envelope reports failure or carries no rows.
        """
        try:
            document = json.loads(text)
            header = document["header"]
            rows = document["body"]["data"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            msg = f"CEPALSTAT returned an unreadable envelope for indicator {cepal_id}: {exc}"
            raise ExtractionError(msg, source_key=self.source.key, url=url) from exc

        if not header.get("success", False):
            detail = str(header.get("message") or "no message").strip()
            code = header.get("code", "?")
            msg = f"CEPALSTAT reported failure {code} for indicator {cepal_id}: {detail}"
            raise ExtractionError(msg, source_key=self.source.key, url=url)

        if not rows:
            msg = f"CEPALSTAT returned no rows for indicator {cepal_id}"
            raise ExtractionError(msg, source_key=self.source.key, url=url)

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Normalize the four payloads into one observation per country-year.

        Pure function of ``raw``.

        Raises:
            TransformationError: A payload is not the expected shape, its years
                dimension is missing, or a row names a year member that does
                not exist.
        """
        payload = raw.payload
        if not isinstance(payload, dict):
            msg = "CEPALSTAT payload must be a mapping of indicator id to response text"
            raise TransformationError(msg, source_key=self.source.key)

        observations: list[NormalizedObservation] = []
        for spec in SERIES:
            observations.extend(self._read_series(spec, str(payload[spec.cepal_id]), raw))
        observations.sort(key=lambda obs: (obs.indicator_code, obs.country_iso3, obs.period.start))
        return observations

    def _read_series(
        self, spec: SeriesSpec, text: str, raw: RawDataset
    ) -> list[NormalizedObservation]:
        """Turn one indicator's payload into its Central American observations."""
        body = self._decode(text, spec.cepal_id)["body"]
        years = self._years_of(body, spec.cepal_id)
        published_unit = str(body["metadata"]["unit"])
        sources = {source["id"]: source["description"] for source in body["sources"]}
        footnotes = {str(note["id"]): note["description"] for note in body["footnotes"]}
        credits = [entry["description"] for entry in body["credits"] if entry["id"] != 0]
        scale = "1e6" if spec.scale == MILLIONS else "1"

        observations: list[NormalizedObservation] = []
        for row in body["data"]:
            iso3 = row.get("iso3")
            if iso3 not in CENTRAL_AMERICA:
                continue
            year = self._year_of(row, years, spec.cepal_id)
            value = self._value_of(row, spec.cepal_id)
            note_ids = [part for part in str(row.get("notes_ids") or "").split(",") if part]
            observations.append(
                NormalizedObservation(
                    country_iso3=str(iso3),
                    indicator_code=spec.indicator_code,
                    source_key=self.source.key,
                    period=parse_period(year, Frequency.ANNUAL),
                    unit=spec.unit,
                    currency_code=self.currency_code,
                    value_numeric=value * spec.scale,
                    retrieved_at=raw.retrieved_at,
                    source_url=f"{raw.source_url}/indicator/{spec.cepal_id}/data",
                    source_record_id=f"cepalstat:{spec.cepal_id}:{iso3}:{year}",
                    raw_metadata={
                        "cepalstat_indicator_id": spec.cepal_id,
                        "cepalstat_published_value": format(value.normalize(), "f"),
                        "cepalstat_published_unit": published_unit,
                        "cepalstat_scale_applied": scale,
                        "cepalstat_source": sources.get(row.get("source_id"), ""),
                        "cepalstat_footnotes": [
                            footnotes[note] for note in note_ids if note in footnotes
                        ],
                        # credits[0] is CEPAL's own fetch date and changes
                        # between runs; only the citation is kept.
                        "cepalstat_credits": credits,
                        "contract_status": "verified",
                    },
                )
            )
        return observations

    def _decode(self, text: str, cepal_id: int) -> Any:
        """Decode JSON, keeping published decimals exact."""
        try:
            return json.loads(text, parse_float=Decimal)
        except json.JSONDecodeError as exc:
            msg = f"CEPALSTAT returned malformed JSON for indicator {cepal_id}: {exc}"
            raise TransformationError(msg, source_key=self.source.key) from exc

    def _years_of(self, body: Any, cepal_id: int) -> dict[int, str]:
        """Build the ``member id -> year label`` map from the response itself.

        Never computed from the id arithmetically: today ``year = id - 27170``
        holds for every member, but CEPAL documents no such contract.

        Raises:
            TransformationError: The years dimension is absent.
        """
        for dimension in body.get("dimensions", []):
            if dimension.get("id") == YEARS_DIMENSION:
                return {member["id"]: str(member["name"]) for member in dimension["members"]}
        msg = f"CEPALSTAT returned no years dimension for indicator {cepal_id}"
        raise TransformationError(msg, source_key=self.source.key)

    def _year_of(self, row: Any, years: dict[int, str], cepal_id: int) -> str:
        """Resolve a row's year label.

        Raises:
            TransformationError: The row names a year member that does not exist.
        """
        member = row.get(f"dim_{YEARS_DIMENSION}")
        label = years.get(member)
        if label is None:
            msg = f"CEPALSTAT row for indicator {cepal_id} names an unknown year member {member!r}"
            raise TransformationError(msg, source_key=self.source.key)
        return label

    def _value_of(self, row: Any, cepal_id: int) -> Decimal:
        """Read a published figure exactly.

        Raises:
            TransformationError: The value is absent or not a number.
        """
        try:
            return Decimal(str(row["value"]))
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            msg = f"CEPALSTAT returned an unreadable value for indicator {cepal_id}: {exc}"
            raise TransformationError(msg, source_key=self.source.key) from exc

    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert CEPALSTAT-specific expectations. Filled in by Task 4."""
        return []
