"""Central America — annual GDP published by CEPAL through CEPALSTAT.

The API itself — its lack of documentation, how its routes were recovered, its
envelope and its numeric dimension ids — is documented in ``cepalstat.py``,
which this connector's base class comes from. Only what is GDP's own is
recorded here.

**The constant-price base year lives in a footnote, not the unit.** 2204 and
2206 declare ``Millions of dollars`` and ``Dollars per inhabitant``; only
``footnotes`` names 2018. A rebasing would change every value while the unit
stood still, which is why ``validate`` checks the footnote.

One request returns the whole matrix — 33 countries and 3 regional aggregates
by 36 years — so a rebuild is complete by default, as with Banguat and SIECA.

CEPAL's English translation of indicator 2204 spells "dolllars" with three
l's. REIM stores its own names, so it does not propagate; it is noted here so
it does not read as a transcription error.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar

from reim.core.constants import CheckSeverity, CheckType, Frequency
from reim.core.exceptions import TransformationError
from reim.domain.observations.periods import parse_period
from reim.domain.pipelines.models import (
    NormalizedObservation,
    QualityResult,
    RawDataset,
)
from reim.ingestion.connectors.regional.cepalstat import (
    YEARS_DIMENSION,
    CepalstatConnector,
)
from reim.ingestion.http import ensure_ok, fetch, http_client

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


class CepalstatGdpConnector(CepalstatConnector):
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

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Normalize the four payloads into one observation per country-year.

        Pure function of ``raw``.

        Raises:
            TransformationError: The payload is not a mapping of indicator id
                to response text, its years dimension is missing, or a row
                names a year member that does not exist. A payload missing an
                indicator key, a missing ``body``, or a missing
                ``metadata.unit`` is not caught here and surfaces as a bare
                ``KeyError`` instead.
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
        years = self._members_of(body, YEARS_DIMENSION, "years", spec.cepal_id)
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
            year = self._label_of(row, years, YEARS_DIMENSION, "year", spec.cepal_id)
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

    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert CEPALSTAT-specific expectations beyond the standard battery."""
        by_key: dict[str, dict[tuple[str, str], Decimal]] = {
            spec.indicator_code: {
                (obs.country_iso3, obs.period.label): obs.value_numeric
                for obs in observations
                if obs.indicator_code == spec.indicator_code and obs.value_numeric is not None
            }
            for spec in SERIES
        }

        return [
            self._check_seven_countries(observations),
            self._check_population_identity(by_key),
            self._check_base_year(observations),
            self._check_annual_continuity(observations),
        ]

    def _check_seven_countries(self, observations: list[NormalizedObservation]) -> QualityResult:
        """All seven must appear. Belize's absence is the failure that matters."""
        seen = {obs.country_iso3 for obs in observations}
        missing = sorted(CENTRAL_AMERICA - seen)

        if not missing:
            return QualityResult.passed(
                "cepalstat_seven_countries_present",
                CheckType.COMPLETENESS,
                f"All {len(CENTRAL_AMERICA)} countries returned figures",
                expected_value=str(len(CENTRAL_AMERICA)),
                actual_value=str(len(seen & CENTRAL_AMERICA)),
            )
        return QualityResult.failure(
            "cepalstat_seven_countries_present",
            CheckType.COMPLETENESS,
            CheckSeverity.CRITICAL,
            f"{len(missing)} country/countries returned nothing: {', '.join(missing)}",
            expected_value=str(len(CENTRAL_AMERICA)),
            actual_value=str(len(seen & CENTRAL_AMERICA)),
        )

    def _check_population_identity(
        self, by_key: dict[str, dict[tuple[str, str], Decimal]]
    ) -> QualityResult:
        """Total over per capita must recover the same population both ways.

        The current-price pair and the constant-price pair each imply a
        population. CEPAL divides by one CELADE series, so the two must agree;
        a disagreement means two of the four series stopped describing the
        same country-year.
        """
        current_total = by_key["gdp_current_usd_annual"]
        constant_total = by_key["gdp_constant_usd_annual"]
        current_pc = by_key["gdp_per_capita_current_usd_annual"]
        constant_pc = by_key["gdp_per_capita_constant_usd_annual"]

        shared = sorted(
            set(current_total) & set(constant_total) & set(current_pc) & set(constant_pc)
        )
        broken = []
        for key in shared:
            if not current_pc[key] or not constant_pc[key]:
                broken.append(key)
                continue
            from_current = current_total[key] / current_pc[key]
            from_constant = constant_total[key] / constant_pc[key]
            if abs(from_current - from_constant) / from_current > POPULATION_TOLERANCE:
                broken.append(key)

        if not broken:
            return QualityResult.passed(
                "cepalstat_population_identity",
                CheckType.CONSISTENCY,
                f"The implied population agrees between the current and constant "
                f"pairs on all {len(shared)} cell(s), within {POPULATION_TOLERANCE}",
                expected_value="0 beyond tolerance",
                actual_value="0",
            )

        shown = ", ".join(f"{country} {year}" for country, year in broken[:5])
        suffix = f" (+{len(broken) - 5} more)" if len(broken) > 5 else ""
        return QualityResult.failure(
            "cepalstat_population_identity",
            CheckType.CONSISTENCY,
            CheckSeverity.ERROR,
            f"{len(broken)} cell(s) imply two different populations: {shown}{suffix}",
            expected_value="0 beyond tolerance",
            actual_value=str(len(broken)),
        )

    def _check_base_year(self, observations: list[NormalizedObservation]) -> QualityResult:
        """The constant-price series must still be expressed at 2018 prices.

        CEPAL states the base year only in a footnote; the published unit is
        just "Millions of dollars". A rebasing would therefore change every
        constant value while REIM went on storing it as constant 2018 USD.
        """
        constant_codes = {
            "gdp_constant_usd_annual",
            "gdp_per_capita_constant_usd_annual",
        }
        footnotes = {
            note
            for obs in observations
            if obs.indicator_code in constant_codes
            for note in obs.raw_metadata.get("cepalstat_footnotes", [])
        }
        wrong = sorted(note for note in footnotes if CONSTANT_PRICE_BASE_YEAR not in note)

        if footnotes and not wrong:
            return QualityResult.passed(
                "cepalstat_constant_price_base_year",
                CheckType.VALIDITY,
                f"The constant-price series still state base year "
                f"{CONSTANT_PRICE_BASE_YEAR}: {', '.join(sorted(footnotes))}",
                expected_value=CONSTANT_PRICE_BASE_YEAR,
                actual_value=CONSTANT_PRICE_BASE_YEAR,
            )

        detail = ", ".join(wrong) if wrong else "no base-year footnote at all"
        return QualityResult.failure(
            "cepalstat_constant_price_base_year",
            CheckType.VALIDITY,
            CheckSeverity.ERROR,
            f"The constant-price series no longer state base year "
            f"{CONSTANT_PRICE_BASE_YEAR}: {detail}. A rebasing changes every "
            f"constant value and leaves the published unit untouched.",
            expected_value=CONSTANT_PRICE_BASE_YEAR,
            actual_value=detail,
        )

    def _check_annual_continuity(self, observations: list[NormalizedObservation]) -> QualityResult:
        """CEPAL publishes every year; a hole is worth a human look.

        Each country's span is walked on its own. Pooling the years of all seven
        would leave a hole invisible whenever some other country published that
        year — and six of the seven usually did.
        """
        years_by_country: dict[str, set[int]] = defaultdict(set)
        for obs in observations:
            years_by_country[obs.country_iso3].add(int(obs.period.label))

        spans = {
            iso3: (min(years), max(years))
            for iso3, years in years_by_country.items()
            if len(years) > 1
        }
        if not spans:
            return QualityResult.passed(
                "cepalstat_annual_continuity",
                CheckType.COMPLETENESS,
                "Too few years ingested to assess continuity",
                actual_value=str(sum(len(y) for y in years_by_country.values())),
            )

        expected = sum(last - first + 1 for first, last in spans.values())
        present = sum(len(years_by_country[iso3]) for iso3 in spans)
        missing = [
            f"{iso3} {year}"
            for iso3, (first, last) in sorted(spans.items())
            for year in range(first, last + 1)
            if year not in years_by_country[iso3]
        ]

        if not missing:
            earliest = min(first for first, _ in spans.values())
            latest = max(last for _, last in spans.values())
            return QualityResult.passed(
                "cepalstat_annual_continuity",
                CheckType.COMPLETENESS,
                f"No gaps in any of the {len(spans)} countries, {earliest} to {latest}",
                expected_value=str(expected),
                actual_value=str(present),
            )

        shown = ", ".join(missing[:5])
        suffix = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
        return QualityResult.failure(
            "cepalstat_annual_continuity",
            CheckType.COMPLETENESS,
            CheckSeverity.WARNING,
            f"{len(missing)} country-year(s) missing: {shown}{suffix}",
            expected_value=str(expected),
            actual_value=str(present),
        )
