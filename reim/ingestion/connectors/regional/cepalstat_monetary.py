"""Central America — monthly monetary aggregates published through CEPALSTAT.

The API, its lack of documentation and the way its routes were recovered are
documented in ``cepalstat.py``, which this connector's base class comes from;
only what differs is recorded here.

Two things differ, and both come from one dimension:

1. **Dimension 3981 selects a period inside the year** — twelve months, four
   quarters and an annual figure. Only the twelve months are stored: the annual
   figure is exactly December's and each quarter is exactly its closing month,
   verified across 2,253 cells with no exceptions. These are end-of-period
   stocks, so the restatement is definitional.
2. **In ``lang=en`` all seventeen of its members are the string
   ``descripcion_ingles``** — the untranslated column name of CEPAL's own
   database, surfacing through the API. The ids cannot be pinned either: they
   run 3982-3998 but not in calendar order, with September at 3993 and July at
   3994. So the member table is fetched separately in Spanish, and only the
   member table: the data itself stays ``lang=en`` and every string REIM stores
   stays English.

The figures are published in millions of each country's own currency. REIM
stores whole units of that currency, and the currency comes from the country
registry rather than from the payload, which says only "local currency". Two
of the seven are dollarised, so their series alone are comparable with each
other; none of the others is comparable with anything without a conversion
REIM does not perform.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from reim.core.constants import CheckSeverity, CheckType, Frequency
from reim.core.exceptions import TransformationError
from reim.domain.countries.registry import COUNTRIES_BY_ISO3
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

#: Published in millions of local currency, stored in whole units.
MILLIONS = Decimal("1000000")

CENTRAL_AMERICA = frozenset({"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"})


@dataclass(frozen=True, slots=True)
class SeriesSpec:
    """One CEPAL indicator id and the REIM code it feeds."""

    cepal_id: int
    indicator_code: str


SERIES: tuple[SeriesSpec, ...] = (
    SeriesSpec(862, "money_m1_monthly"),
    SeriesSpec(868, "money_m2_monthly"),
    SeriesSpec(869, "money_m3_monthly"),
)

#: Countries each series covers, measured 2026-08-19. Encoded so that a
#: disappearance is visible and the two known absences are stated rather
#: than discovered.
EXPECTED_COUNTRIES: dict[str, frozenset[str]] = {
    "money_m1_monthly": CENTRAL_AMERICA,
    "money_m2_monthly": CENTRAL_AMERICA - {"BLZ"},
    "money_m3_monthly": CENTRAL_AMERICA - {"SLV"},
}

#: Relative tolerance for the M1 <= M2 <= M3 nesting. CEPAL declares zero
#: decimals and publishes some series rounded to whole millions and others to
#: one decimal, which inverts the ordering by at most 0.014% in 229 of 2,942
#: shared cells. This sits seven times above that and far below any real
#: inversion, which would be percent-scale.
NESTING_TOLERANCE = Decimal("0.001")


class CepalstatMonetaryConnector(CepalstatConnector):
    """Monthly M1, M2 and M3 for the seven Central American countries."""

    connector_key = "cepalstat_monetary_monthly"
    version = "1.0.0"
    expected_frequency = Frequency.MONTHLY

    async def extract(self) -> RawDataset:
        """Fetch each indicator's data and its Spanish member table.

        Six requests: three for data in English, three for dimensions in
        Spanish. The Spanish request exists only because the English period
        members are untranslated; nothing from it is stored.

        Raises:
            ExtractionError: The API was unreachable, answered with something
                other than JSON, reported ``success: false`` in its envelope,
                or returned an empty data array.
        """
        base = str(self.source.base_url).rstrip("/")
        retrieved_at = datetime.now(UTC)
        data: dict[int, str] = {}
        dimensions: dict[int, str] = {}
        status: int | None = None
        content_type: str | None = None

        async with http_client() as client:
            for spec in SERIES:
                url = f"{base}/indicator/{spec.cepal_id}/data"
                response = await fetch(client, url, params={"lang": "en"})
                ensure_ok(response, expected_content_type="json")
                self._ensure_envelope_ok(response.text, spec.cepal_id, url)
                data[spec.cepal_id] = response.text
                status = response.status_code
                content_type = response.headers.get("content-type")

                url = f"{base}/indicator/{spec.cepal_id}/dimensions"
                response = await fetch(client, url, params={"lang": "es"})
                ensure_ok(response, expected_content_type="json")
                dimensions[spec.cepal_id] = response.text

        return RawDataset(
            source_key=self.source.key,
            retrieved_at=retrieved_at,
            source_url=base,
            payload={"data": data, "dimensions": dimensions},
            content_type=content_type,
            http_status=status,
            metadata={
                "indicator_ids": [spec.cepal_id for spec in SERIES],
                "lang": "en",
                "dimensions_lang": "es",
            },
        )

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Normalize the three payloads into one observation per country-month.

        Pure function of ``raw``.

        Raises:
            TransformationError: The payload is not the expected mapping, a
                period or years dimension is missing, or a row names a member
                that does not exist.
        """
        payload = raw.payload
        if not isinstance(payload, dict) or "data" not in payload:
            msg = "CEPALSTAT payload must carry 'data' and 'dimensions' mappings"
            raise TransformationError(msg, source_key=self.source.key)

        observations: list[NormalizedObservation] = []
        for spec in SERIES:
            observations.extend(
                self._read_series(
                    spec,
                    str(payload["data"][spec.cepal_id]),
                    str(payload["dimensions"][spec.cepal_id]),
                    raw,
                )
            )
        observations.sort(key=lambda obs: (obs.indicator_code, obs.country_iso3, obs.period.start))
        return observations

    def _read_series(
        self, spec: SeriesSpec, text: str, dimensions_text: str, raw: RawDataset
    ) -> list[NormalizedObservation]:
        """Turn one indicator's payload into its Central American observations."""
        body = self._decode(text, spec.cepal_id)["body"]
        months = self._months_of_period_dimension(
            self._decode(dimensions_text, spec.cepal_id), spec.cepal_id
        )
        years = self._members_of(body, YEARS_DIMENSION, "years", spec.cepal_id)
        published_unit = str(body["metadata"]["unit"])
        sources = {source["id"]: source["description"] for source in body["sources"]}
        credits = [entry["description"] for entry in body["credits"] if entry["id"] != 0]

        observations: list[NormalizedObservation] = []
        for row in body["data"]:
            iso3 = row.get("iso3")
            if iso3 not in CENTRAL_AMERICA:
                continue
            month = self._month_of_period_dimension(row, months, spec.cepal_id)
            if month is None:
                continue
            year = self._label_of(row, years, YEARS_DIMENSION, "year", spec.cepal_id)
            value = self._value_of(row, spec.cepal_id)
            label = f"{year}-{month:02d}"
            currency = COUNTRIES_BY_ISO3[str(iso3)].currency_code
            observations.append(
                NormalizedObservation(
                    country_iso3=str(iso3),
                    indicator_code=spec.indicator_code,
                    source_key=self.source.key,
                    period=parse_period(label, Frequency.MONTHLY),
                    unit=currency,
                    currency_code=currency,
                    value_numeric=value * MILLIONS,
                    retrieved_at=raw.retrieved_at,
                    source_url=f"{raw.source_url}/indicator/{spec.cepal_id}/data",
                    source_record_id=f"cepalstat:{spec.cepal_id}:{iso3}:{label}",
                    raw_metadata={
                        "cepalstat_indicator_id": spec.cepal_id,
                        "cepalstat_published_value": format(value.normalize(), "f"),
                        "cepalstat_published_unit": published_unit,
                        "cepalstat_scale_applied": "1e6",
                        "cepalstat_source": sources.get(row.get("source_id"), ""),
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
            self._check_nesting(by_key),
            self._check_country_coverage(
                observations, EXPECTED_COUNTRIES, "cepalstat_monetary_expected_countries"
            ),
            self._check_monthly_continuity(observations),
        ]

    def _check_nesting(self, by_key: dict[str, dict[tuple[str, str], Decimal]]) -> QualityResult:
        """M1 <= M2 <= M3, which is how CEPAL defines the family.

        ``calculation_methodology`` states M2 = M1 + savings deposits and
        M3 = M2 + foreign currency deposits, so the ordering is definitional.
        The tolerance exists because CEPAL declares zero decimals and publishes
        some series rounded to whole millions and others to one decimal, which
        inverts 229 of 2,942 shared cells by at most 0.014%.
        """
        pairs = (
            ("money_m1_monthly", "money_m2_monthly"),
            ("money_m2_monthly", "money_m3_monthly"),
        )
        broken: list[tuple[str, str]] = []
        compared = 0
        for narrow_code, wide_code in pairs:
            narrow, wide = by_key[narrow_code], by_key[wide_code]
            for key in sorted(set(narrow) & set(wide)):
                compared += 1
                if not wide[key]:
                    continue
                excess = (narrow[key] - wide[key]) / wide[key]
                if excess > NESTING_TOLERANCE:
                    broken.append(key)

        if not broken:
            return QualityResult.passed(
                "cepalstat_monetary_nesting",
                CheckType.CONSISTENCY,
                f"M1 <= M2 <= M3 holds on all {compared} shared cell(s), "
                f"within {NESTING_TOLERANCE}",
                expected_value="0 beyond tolerance",
                actual_value="0",
            )

        shown = ", ".join(f"{country} {period}" for country, period in broken[:5])
        suffix = f" (+{len(broken) - 5} more)" if len(broken) > 5 else ""
        return QualityResult.failure(
            "cepalstat_monetary_nesting",
            CheckType.CONSISTENCY,
            CheckSeverity.ERROR,
            f"{len(broken)} cell(s) break the M1 <= M2 <= M3 ordering: {shown}{suffix}",
            expected_value="0 beyond tolerance",
            actual_value=str(len(broken)),
        )
