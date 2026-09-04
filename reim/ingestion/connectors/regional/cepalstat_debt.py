"""Central America — central government public debt, published by CEPAL.

The API, its lack of documentation and the way its routes were recovered are
documented in ``cepalstat.py``, which this connector's base class comes from;
only what differs is recorded here.

What differs is the shape of the cube. These two indicators carry four
dimensions rather than two: country and year as usual, plus a debt
classification with six members and an institutional coverage with four. A
country-year cell is not identified until both are pinned, so this connector
pins them and stores one slice.

1. **Only three of the six classification members carry rows** — Total public
   debt by residence, Internal debt and External debt. Currency, rate and
   maturity classification are grouping nodes in CEPAL's tree, published as
   members with nothing behind them, empty for all 145 countries.
2. **Only central government covers all seven countries.** Nonfinancial public
   sector omits Guatemala and Honduras, public sector mostly stops in 2011, and
   state and local governments exists for Honduras alone. CEPAL's own
   methodology note says the published figure "is refered to the central
   government gross public debt stock".
3. **The internal and external series do not sum to the total** — in 1239 only
   303 of 415 complete triples are exact, and three are off by more than 1%.
   That is why only the total is stored: publishing the split would invite a
   subtraction the source does not support.

The ratio in 1240 is *not* this dollar figure divided by REIM's
``gdp_current_usd_annual``. CEPAL divides by each country's GDP in local
currency converted at the IMF's 31 December rate; across the 225 shared
country-years the two disagree by 5% or more in 52 of them, worst 23.7%. Both
series are stored as published and nothing reconciles them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from reim.core.constants import CheckSeverity, CheckType, Frequency
from reim.core.exceptions import TransformationError
from reim.domain.observations.periods import parse_period
from reim.domain.pipelines.models import NormalizedObservation, QualityResult, RawDataset
from reim.ingestion.connectors.regional.cepalstat import (
    YEARS_DIMENSION,
    CepalstatConnector,
)
from reim.ingestion.http import ensure_ok, fetch, http_client

#: This family's own dimensions; country and years come from the base module.
DEBT_CLASSIFICATION = 10590
INSTITUTIONAL_COVERAGE = 10690

#: The one slice REIM stores, selected by id and asserted by name.
CENTRAL_GOVERNMENT = 10692
CENTRAL_GOVERNMENT_NAME = "Central government"
TOTAL_BY_RESIDENCE = 10609
TOTAL_BY_RESIDENCE_NAME = "Total public debt (classification by residence)"

#: Published in millions of dollars, stored in whole dollars, matching the GDP
#: totals so the two line up.
MILLIONS = Decimal("1000000")

CENTRAL_AMERICA = frozenset({"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"})


@dataclass(frozen=True, slots=True)
class SeriesSpec:
    """One CEPAL indicator id, the REIM code it feeds, and how it is stored."""

    cepal_id: int
    indicator_code: str
    unit: str
    scale: Decimal
    currency: str | None


SERIES: tuple[SeriesSpec, ...] = (
    SeriesSpec(1239, "public_debt_usd_annual", "current USD", MILLIONS, "USD"),
    SeriesSpec(1240, "public_debt_pct_gdp_annual", "percent of GDP", Decimal(1), None),
)


class CepalstatDebtConnector(CepalstatConnector):
    """Central government gross public debt, in dollars and as a share of GDP."""

    connector_key = "cepalstat_debt_annual"
    version = "1.0.0"
    expected_frequency = Frequency.ANNUAL

    async def extract(self) -> RawDataset:
        """Fetch both indicators in English.

        Two requests. No Spanish request: this family's English member names
        are real translations, unlike the monetary family's.

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
                "institutional_coverage": CENTRAL_GOVERNMENT_NAME,
                "debt_classification": TOTAL_BY_RESIDENCE_NAME,
            },
        )

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Filter the four-dimensional cube down to one series per indicator.

        Pure function of ``raw``.

        Raises:
            TransformationError: The payload is not the expected mapping, a
                dimension is missing, a selected member has been renamed, or a
                row names a year member that does not exist.
        """
        payload = raw.payload
        if not isinstance(payload, dict):
            msg = "CEPALSTAT payload must be a mapping of indicator id to response text"
            raise TransformationError(msg, source_key=self.source.key)

        observations: list[NormalizedObservation] = []
        for spec in SERIES:
            text = payload.get(spec.cepal_id) or payload.get(str(spec.cepal_id))
            if text is None:
                msg = f"CEPALSTAT payload is missing indicator {spec.cepal_id}"
                raise TransformationError(msg, source_key=self.source.key)
            observations.extend(self._read_series(spec, str(text), raw))

        observations.sort(key=lambda obs: (obs.indicator_code, obs.country_iso3, obs.period.start))
        return observations

    def _read_series(
        self, spec: SeriesSpec, text: str, raw: RawDataset
    ) -> list[NormalizedObservation]:
        """Turn one indicator's payload into its Central American observations."""
        body = self._decode(text, spec.cepal_id)["body"]
        self._assert_selected_members(body, spec.cepal_id)
        years = self._members_of(body, YEARS_DIMENSION, "years", spec.cepal_id)
        published_unit = str(body["metadata"]["unit"])
        sources = {source["id"]: source["description"] for source in body["sources"]}
        credits = [entry["description"] for entry in body["credits"] if entry["id"] != 0]
        scale = "1e6" if spec.scale == MILLIONS else "1"

        observations: list[NormalizedObservation] = []
        for row in body["data"]:
            iso3 = row.get("iso3")
            if iso3 not in CENTRAL_AMERICA:
                continue
            if row.get(f"dim_{INSTITUTIONAL_COVERAGE}") != CENTRAL_GOVERNMENT:
                continue
            if row.get(f"dim_{DEBT_CLASSIFICATION}") != TOTAL_BY_RESIDENCE:
                continue
            year = self._label_of(row, years, YEARS_DIMENSION, "year", spec.cepal_id)
            value = self._value_of(row, spec.cepal_id)
            notes_ids = [part for part in str(row.get("notes_ids") or "").split(",") if part]
            observations.append(
                NormalizedObservation(
                    country_iso3=str(iso3),
                    indicator_code=spec.indicator_code,
                    source_key=self.source.key,
                    period=parse_period(year, Frequency.ANNUAL),
                    unit=spec.unit,
                    currency_code=spec.currency,
                    value_numeric=value * spec.scale,
                    retrieved_at=raw.retrieved_at,
                    source_url=f"{raw.source_url}/indicator/{spec.cepal_id}/data",
                    source_record_id=f"cepalstat:{spec.cepal_id}:{iso3}:{year}",
                    raw_metadata={
                        "cepalstat_indicator_id": spec.cepal_id,
                        "cepalstat_published_value": format(value.normalize(), "f"),
                        "cepalstat_published_unit": published_unit,
                        "cepalstat_scale_applied": scale,
                        "cepalstat_institutional_coverage": CENTRAL_GOVERNMENT_NAME,
                        "cepalstat_debt_classification": TOTAL_BY_RESIDENCE_NAME,
                        "cepalstat_source": sources.get(row.get("source_id"), ""),
                        "cepalstat_notes_ids": notes_ids,
                        # credits[0] is CEPAL's own fetch date and changes
                        # between runs; only the citation is kept.
                        "cepalstat_credits": credits,
                        "contract_status": "verified",
                    },
                )
            )
        return observations

    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert CEPALSTAT-specific expectations beyond the standard battery.

        Deliberately absent: any reconciliation of the ratio against REIM's
        own GDP series. CEPAL's denominator is a local-currency GDP converted
        at the IMF's 31 December rate, and across the 225 shared country-years
        the two disagree by 5% or more in 52 of them. A check would fail
        permanently by design, so the mismatch is documented instead.
        """
        return [
            self._check_seven_countries(observations),
            self._check_annual_continuity(observations),
        ]

    def _check_seven_countries(self, observations: list[NormalizedObservation]) -> QualityResult:
        """All seven must appear in EACH series, not merely somewhere across both.

        A country present in one series and absent from the other must fail
        this check by name: pooling both series' countries into one ``seen``
        set would let CEPAL drop a country from one indicator entirely
        without this check ever noticing, so long as the other still carries
        it.
        """
        seen_by_series: dict[str, set[str]] = {spec.indicator_code: set() for spec in SERIES}
        for obs in observations:
            seen_by_series.setdefault(obs.indicator_code, set()).add(obs.country_iso3)

        missing = sorted(
            f"{iso3} ({code})"
            for code, seen in seen_by_series.items()
            for iso3 in sorted(CENTRAL_AMERICA - seen)
        )
        expected = len(CENTRAL_AMERICA) * len(SERIES)
        present = sum(len(CENTRAL_AMERICA & seen) for seen in seen_by_series.values())

        if not missing:
            return QualityResult.passed(
                "cepalstat_debt_seven_countries",
                CheckType.COMPLETENESS,
                f"All {len(CENTRAL_AMERICA)} countries returned figures in both series",
                expected_value=str(expected),
                actual_value=str(present),
            )
        return QualityResult.failure(
            "cepalstat_debt_seven_countries",
            CheckType.COMPLETENESS,
            CheckSeverity.CRITICAL,
            f"{len(missing)} country/series combination(s) missing: {', '.join(missing)}",
            expected_value=str(expected),
            actual_value=str(present),
        )

    def _check_annual_continuity(self, observations: list[NormalizedObservation]) -> QualityResult:
        """Holes inside each country's own span, per indicator.

        Walked per country and per series: pooling them would hide a hole
        whenever another country published that year, and six of the seven
        usually did. Belize's shorter span is not a hole — the walk starts at
        each country's own first year.
        """
        spans: dict[tuple[str, str], set[int]] = {}
        for obs in observations:
            spans.setdefault((obs.indicator_code, obs.country_iso3), set()).add(
                int(obs.period.label)
            )

        missing: list[str] = []
        expected = present = walked = 0
        for (code, iso3), years in sorted(spans.items()):
            if len(years) < 2:
                continue
            walked += 1
            first, last = min(years), max(years)
            expected += last - first + 1
            present += len(years)
            missing.extend(
                f"{iso3} {year} ({code})" for year in range(first, last + 1) if year not in years
            )

        if not missing:
            return QualityResult.passed(
                "cepalstat_debt_annual_continuity",
                CheckType.COMPLETENESS,
                f"No gaps in any of the {walked} country-series",
                expected_value=str(expected),
                actual_value=str(present),
            )

        shown = ", ".join(missing[:5])
        suffix = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
        return QualityResult.failure(
            "cepalstat_debt_annual_continuity",
            CheckType.COMPLETENESS,
            CheckSeverity.WARNING,
            f"{len(missing)} missing year(s) inside a country's own span: {shown}{suffix}",
            expected_value=str(expected),
            actual_value=str(present),
        )

    def _assert_selected_members(self, body: Any, cepal_id: int) -> None:
        """Confirm the two ids REIM selects still mean what they meant.

        Rows are filtered by member id, which is silent when CEPAL relabels a
        member: the filter would keep matching and REIM would store a different
        series under the same indicator code. Reading the names back turns that
        into a message that says what changed.

        Raises:
            TransformationError: A dimension is absent or a selected member has
                been renamed.
        """
        for dimension_id, name, member_id, expected in (
            (
                INSTITUTIONAL_COVERAGE,
                "institutional coverage",
                CENTRAL_GOVERNMENT,
                CENTRAL_GOVERNMENT_NAME,
            ),
            (
                DEBT_CLASSIFICATION,
                "debt classification",
                TOTAL_BY_RESIDENCE,
                TOTAL_BY_RESIDENCE_NAME,
            ),
        ):
            members = self._members_of(body, dimension_id, name, cepal_id)
            actual = members.get(member_id)
            if actual != expected:
                msg = (
                    f"CEPALSTAT {name} member {member_id} for indicator {cepal_id} "
                    f"is now {actual!r}, not {expected!r}; the stored series would "
                    f"change meaning silently"
                )
                raise TransformationError(msg, source_key=self.source.key)
