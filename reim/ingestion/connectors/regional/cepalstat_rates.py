"""Central America — monthly interest rates published through CEPALSTAT.

The API, its lack of documentation and the way its routes were recovered are
documented in ``cepalstat.py``, which this connector's base class comes from;
only what differs is recorded here.

This family carries the same period-within-year dimension as the monetary
aggregates, handled in the base class — including that ``lang=en`` returns all
seventeen of its members as the untranslated string ``descripcion_ingles``,
which is why a Spanish member table is fetched at all.

**Four things differ from the monetary family:**

1. **One dimensions request, not three.** The member table belongs to
   dimension 3981, not to an indicator, and was measured byte-identical across
   856, 857 and 1206 on 2026-09-07.
2. **The annual and quarterly members are means of their months, not
   restatements of a period end.** For the monetary aggregates the annual
   figure *is* December's stock and each quarter *is* its closing month, which
   is why dropping them loses nothing. Here the annual figure equals the mean
   of its twelve months in 202 of 202 checkable cases on indicator 856, and
   each quarter the mean of its three in 693 of 693. They are dropped for the
   opposite reason: storing a mean beside its own inputs would publish a
   derived figure as if CEPAL had published it.
3. **Nothing is scaled.** These are percentages, stored exactly as published.
   Indicator 856 declares ``decimals: 0`` and publishes two in 2,065 of 2,490
   cells, so the declared precision is not usable as a rounding instruction.
4. **Panama has no monetary policy rate.** It is dollarised and has no central
   bank. CEPAL nonetheless publishes sixteen rows for it on indicator 1206,
   every one ``'0'`` and every one with a null ``source_id``, all inside 2022.
   That is an artifact of the table rather than a measurement, and REIM stores
   none of it. Nicaragua's two zeros in 2010-03 and 2010-04 are a different
   thing — real cells in a live attributed series — and are stored.

CEPAL states in its own ``calculation_methodology`` that each country's rate
is defined "according to the definition from each country", and the
``definition`` field spells that out: Panama's lending rate is the rate on
one-year trade credit, Belize's "policy rate" is its central bank's lending
rate. The three indicators therefore declare
``methodology_varies_by_country``, and ``/compare`` states it as a note.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from reim.core.constants import Frequency
from reim.domain.pipelines.models import (
    NormalizedObservation,
    QualityResult,
    RawDataset,
)
from reim.ingestion.connectors.regional.cepalstat import CepalstatConnector
from reim.ingestion.http import ensure_ok, fetch, http_client

CENTRAL_AMERICA = frozenset({"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"})

#: Whose dimensions response is fetched. Any of the three would serve; 856 is
#: named so the request is deterministic and the fixture has one origin.
DIMENSIONS_INDICATOR = 856

#: Published as "Annual percentage"; stored under REIM's own name for it.
UNIT = "percent per annum"

#: Panama is dollarised, has no central bank and therefore no policy rate.
#: CEPAL's sixteen zero-valued, unattributed 2022 rows are an artifact.
NO_POLICY_RATE = frozenset({"PAN"})


@dataclass(frozen=True, slots=True)
class SeriesSpec:
    """One CEPAL indicator id, the REIM code it feeds, and who it excludes."""

    cepal_id: int
    indicator_code: str
    excluded_countries: frozenset[str] = frozenset()


SERIES: tuple[SeriesSpec, ...] = (
    SeriesSpec(856, "lending_rate_nominal_monthly"),
    SeriesSpec(857, "deposit_rate_nominal_monthly"),
    SeriesSpec(1206, "policy_rate_monthly", NO_POLICY_RATE),
)

#: Countries each series covers, measured 2026-09-07. Encoded so that a
#: disappearance is visible and Panama's absence is stated rather than
#: discovered.
EXPECTED_COUNTRIES: dict[str, frozenset[str]] = {
    "lending_rate_nominal_monthly": CENTRAL_AMERICA,
    "deposit_rate_nominal_monthly": CENTRAL_AMERICA,
    "policy_rate_monthly": CENTRAL_AMERICA - NO_POLICY_RATE,
}

#: Largest calendar-adjacent move the family may make without comment, in
#: percentage points. The largest measured anywhere in 6,523 adjacent pairs is
#: Belize's policy rate stepping 18 -> 11 in 2010-12, which is 7. Percentage
#: change cannot do this job: these series sit near zero, where 0.5 -> 1.7 is
#: +240% and 1.2 points.
MAX_STEP_POINTS = Decimal("8")


class CepalstatRatesConnector(CepalstatConnector):
    """Monthly lending, deposit and policy rates for Central America."""

    connector_key = "cepalstat_rates_monthly"
    version = "1.0.0"
    expected_frequency = Frequency.MONTHLY

    async def extract(self) -> RawDataset:
        """Fetch the three data responses and one Spanish member table.

        Four requests. The dimensions request is made once because dimension
        3981's members belong to the dimension rather than to an indicator;
        ``_month_of_period_dimension`` raises on any member id the table does
        not hold, so a future divergence between the three surfaces as a
        failure rather than as a silent drop.

        Raises:
            ExtractionError: The API was unreachable, answered with something
                other than JSON, reported ``success: false`` in its envelope,
                or returned an empty data array.
        """
        base = str(self.source.base_url).rstrip("/")
        retrieved_at = datetime.now(UTC)
        data: dict[int, str] = {}
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

            url = f"{base}/indicator/{DIMENSIONS_INDICATOR}/dimensions"
            response = await fetch(client, url, params={"lang": "es"})
            ensure_ok(response, expected_content_type="json")
            dimensions = response.text

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
                "dimensions_indicator_id": DIMENSIONS_INDICATOR,
            },
        )

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Normalize the three responses into monthly observations.

        Not yet implemented; the module docstring describes what this will
        do once it exists.
        """
        raise NotImplementedError  # Task 6

    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Run this family's own quality checks.

        Not yet implemented; the module docstring describes what this will
        do once it exists.
        """
        raise NotImplementedError  # Task 7
