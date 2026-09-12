"""Central America — monthly nominal exchange rates published through CEPALSTAT.

The API, its lack of documentation and the way its routes were recovered are
documented in ``cepalstat.py``, which this connector's base class comes from;
only what differs is recorded here.

Three things differ from the monetary family this connector otherwise mirrors:

1. **Dimension 515 carries twelve members, and it is translated.** The
   monetary family's period dimension mixes months with an annual figure and
   four quarters that restate a month, and in ``lang=en`` all seventeen of its
   members come back as the untranslated string ``descripcion_ingles`` — which
   is why that connector makes a second request in Spanish. Dimension 515 does
   neither: twelve members, all months, named ``January`` through ``December``
   in the English data response itself. **One request is enough**, and the
   member table comes from the response already fetched.
2. **Values are stored exactly as published.** There is no factor of a million.
3. **The currency is the one the rate prices, not the one the country
   transacts in.** These are not the same question, and for El Salvador they
   give different answers: CEPAL quotes it at 8.7-8.8 colones per dollar
   through 2025, twenty-four years after it adopted the dollar, because that is
   the colón's fixed legal conversion rate and CEPAL never stopped publishing
   it. The country registry would say ``USD``, which would label these
   observations ``USD per USD``. So the quoted currency comes from this
   module's own table.

Two things about the series are worth knowing before anything is built on it.

Its ``calculation_methodology`` is "Daily exchange rate, monthly average", so it
is an average across the month and not a rate measured at its close. Anything
converting an end-of-period stock with it inherits that mismatch; CEPAL
publishes no end-of-period alternative.

And its ``data_features`` says "Source Bloomberg" while its ``sources`` array
says "On the basis of official figures". The payload contradicts itself, both
strings are stored in ``raw_metadata``, and REIM repeats neither claim as its
own. The clearest symptom is Belize: pegged at 2:1 since 1976, it nevertheless
reads 1.9 in ten months of the recording, which is a market quote rounded to
CEPAL's one published decimal rather than a currency event. ``_check_pegs_hold``
is a band rather than an equality because of it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from reim.core.constants import CheckSeverity, CheckType, Frequency
from reim.core.exceptions import TransformationError
from reim.domain.countries.registry import CENTRAL_AMERICA
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

#: This family's own period dimension. Twelve members, all months.
PERIOD_DIMENSION = 515

#: The single indicator this connector reads.
CEPAL_ID = 2179

#: The REIM indicator this feeds.
INDICATOR_CODE = "exchange_rate_nominal_monthly"


#: The currency each country's rate is **quoted in**, which is not what
#: ``reim.domain.countries.registry`` answers. El Salvador is the case that
#: forces the distinction: it transacts in dollars and is quoted in colones.
QUOTED_CURRENCY = {
    "BLZ": "BZD",
    "CRI": "CRC",
    "GTM": "GTQ",
    "HND": "HNL",
    "NIC": "NIO",
    "PAN": "PAB",
    "SLV": "SVC",
}

#: Read from the English data response. The member ids are **not** in calendar
#: order — May is 825, after April's 519 — so the name is the only key.
MONTHS_BY_NAME = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}

#: The two legal parities, and the month from which the recording verifies them.
PEGS = {"PAN": Decimal("1"), "BLZ": Decimal("2")}
PEGS_HOLD_FROM = (1993, 6)

#: How far off its parity a pegged rate may read before it is a defect rather
#: than a rounding artefact. Belize reads 1.9 against 2 in ten months — exactly
#: 5% — because a market quote was averaged and rounded to one decimal. This
#: sits at twice that, and still far below any real misreading: the next
#: smallest rate in the matrix is Guatemala's ~7.7, some 285% off Belize's peg.
PEG_TOLERANCE = Decimal("0.10")


class CepalstatExchangeRateConnector(CepalstatConnector):
    """Monthly nominal exchange rates for the seven Central American countries."""

    connector_key = "cepalstat_exchange_rate_monthly"
    version = "1.0.0"
    expected_frequency = Frequency.MONTHLY

    async def extract(self) -> RawDataset:
        """Fetch the rate matrix. One request.

        The response carries its own dimension member table with the months
        named in English, so unlike the monetary family this connector needs
        no second request in Spanish.

        Raises:
            ExtractionError: The API was unreachable, answered with something
                other than JSON, reported ``success: false`` in its envelope,
                or returned an empty data array.
        """
        base = str(self.source.base_url).rstrip("/")
        retrieved_at = datetime.now(UTC)

        async with http_client() as client:
            url = f"{base}/indicator/{CEPAL_ID}/data"
            response = await fetch(client, url, params={"lang": "en"})
            ensure_ok(response, expected_content_type="json")
            self._ensure_envelope_ok(response.text, CEPAL_ID, url)

        return RawDataset(
            source_key=self.source.key,
            retrieved_at=retrieved_at,
            source_url=base,
            payload={"data": response.text},
            content_type=response.headers.get("content-type"),
            http_status=response.status_code,
            metadata={"indicator_id": CEPAL_ID, "lang": "en"},
        )

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Normalize the matrix into one observation per country-month.

        Pure function of ``raw``.

        Raises:
            TransformationError: The payload is not the expected mapping, a
                dimension is missing, or a row names a member that does not
                exist.
        """
        payload = raw.payload
        if not isinstance(payload, dict) or "data" not in payload:
            msg = "CEPALSTAT payload must carry a 'data' mapping"
            raise TransformationError(msg, source_key=self.source.key)

        body = self._decode(str(payload["data"]), CEPAL_ID)["body"]
        months = self._months_of(body)
        years = self._members_of(body, YEARS_DIMENSION, "years", CEPAL_ID)
        metadata = body["metadata"]
        published_unit = str(metadata["unit"])
        methodology = str(metadata["calculation_methodology"])
        data_features = str(metadata["data_features"])
        sources = {source["id"]: source["description"] for source in body["sources"]}
        # credits[0] is CEPAL's own fetch date and changes between runs; only
        # the citation is kept.
        credits = [entry["description"] for entry in body["credits"] if entry["id"] != 0]

        observations: list[NormalizedObservation] = []
        for row in body["data"]:
            iso3 = row.get("iso3")
            if iso3 not in CENTRAL_AMERICA:
                continue
            month = self._month_of(row, months)
            year = self._label_of(row, years, YEARS_DIMENSION, "year", CEPAL_ID)
            value = self._value_of(row, CEPAL_ID)
            label = f"{year}-{month:02d}"
            currency = QUOTED_CURRENCY[str(iso3)]
            observations.append(
                NormalizedObservation(
                    country_iso3=str(iso3),
                    indicator_code=INDICATOR_CODE,
                    source_key=self.source.key,
                    period=parse_period(label, Frequency.MONTHLY),
                    unit=f"{currency} per USD",
                    currency_code=currency,
                    value_numeric=value,
                    retrieved_at=raw.retrieved_at,
                    source_url=f"{raw.source_url}/indicator/{CEPAL_ID}/data",
                    source_record_id=f"cepalstat:{CEPAL_ID}:{iso3}:{label}",
                    raw_metadata={
                        "cepalstat_indicator_id": CEPAL_ID,
                        "cepalstat_published_value": format(value.normalize(), "f"),
                        "cepalstat_published_unit": published_unit,
                        "cepalstat_methodology": methodology,
                        # CEPAL's own two answers about where this comes from.
                        # They disagree; both are kept rather than picked between.
                        "cepalstat_data_features": data_features,
                        "cepalstat_source": sources.get(row.get("source_id"), ""),
                        "cepalstat_credits": credits,
                        "contract_status": "verified",
                    },
                )
            )
        observations.sort(key=lambda obs: (obs.country_iso3, obs.period.start))
        return observations

    def _months_of(self, body: Any) -> dict[int, int]:
        """Map each period member id to a month number, from the data response.

        Unlike the monetary family every member is a month, so the mapping is
        total and nothing is dropped. A label that is not a known month name
        means CEPAL renamed a member or stopped translating this dimension —
        either is a contract break, not a row to skip.

        Raises:
            TransformationError: The period dimension is absent, or a member
                carries a label that is not an English month name.
        """
        members = self._members_of(body, PERIOD_DIMENSION, "period", CEPAL_ID)
        months: dict[int, int] = {}
        for member_id, label in members.items():
            if label not in MONTHS_BY_NAME:
                msg = (
                    f"CEPALSTAT period member {member_id} for indicator {CEPAL_ID} "
                    f"carries the unrecognized label {label!r}"
                )
                raise TransformationError(msg, source_key=self.source.key)
            months[member_id] = MONTHS_BY_NAME[label]
        return months

    def _month_of(self, row: Any, months: dict[int, int]) -> int:
        """Resolve a row's month.

        Raises:
            TransformationError: The row names a period member id that is not
                in the dimension's member table.
        """
        member = row.get(f"dim_{PERIOD_DIMENSION}")
        if member not in months:
            msg = (
                f"CEPALSTAT row for indicator {CEPAL_ID} names an unknown period member {member!r}"
            )
            raise TransformationError(msg, source_key=self.source.key)
        return months[member]

    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert CEPALSTAT-specific expectations beyond the standard battery."""
        return [
            self._check_country_coverage(
                observations,
                {INDICATOR_CODE: CENTRAL_AMERICA},
                "cepalstat_fx_expected_countries",
            ),
            self._check_pegs_hold(observations),
            self._check_monthly_continuity(observations),
        ]

    def _check_pegs_hold(self, observations: list[NormalizedObservation]) -> QualityResult:
        """Panama near 1 and Belize near 2, from the month the recording verified.

        Both parities are legal facts rather than market outcomes, so a rate far
        off one means a dimension has been mis-keyed or a country column
        shifted, far more probably than that either country has floated its
        currency.

        It is a band and not an equality because the series is a market quote,
        not the parity: Belize reads 1.9 in ten months of the recording, exactly
        5% below its peg, from a monthly average rounded to CEPAL's one
        published decimal. ``PEG_TOLERANCE`` sits at twice that.

        The window starts at ``PEGS_HOLD_FROM`` because that is where the
        measurement starts; Panama's earlier rows are also 1, but asserting
        outside what was measured would be asserting something unverified.
        """
        broken: list[str] = []
        compared = 0
        for obs in observations:
            expected = PEGS.get(obs.country_iso3)
            if expected is None or obs.value_numeric is None:
                continue
            if (obs.period.start.year, obs.period.start.month) < PEGS_HOLD_FROM:
                continue
            compared += 1
            if abs(obs.value_numeric - expected) / expected > PEG_TOLERANCE:
                broken.append(f"{obs.country_iso3} {obs.period.label} = {obs.value_numeric}")

        if not broken:
            return QualityResult.passed(
                "cepalstat_fx_pegs_hold",
                CheckType.CONSISTENCY,
                f"Both parities hold within {PEG_TOLERANCE} across all "
                f"{compared} pegged country-month(s)",
                expected_value="0 outside tolerance",
                actual_value="0",
            )

        shown = ", ".join(broken[:5])
        suffix = f" (+{len(broken) - 5} more)" if len(broken) > 5 else ""
        return QualityResult.failure(
            "cepalstat_fx_pegs_hold",
            CheckType.CONSISTENCY,
            CheckSeverity.ERROR,
            f"{len(broken)} pegged rate(s) outside tolerance: {shown}{suffix}",
            expected_value="0 outside tolerance",
            actual_value=str(len(broken)),
        )
