"""Central America — the monthly consumer price index published through CEPALSTAT.

The API and the way its routes were recovered are documented in
``cepalstat.py``; only what differs is recorded here. The request shape is the
exchange rate's exactly: one call, with the month names read from the data
response's own dimension table.

What differs is the data, and it is unusually treacherous:

1. **Every country is on its own base period, and CEPAL's declared bases are
   wrong.** ``body.metadata.comments`` names a base year per country; checked
   against the data, three of the five it declares do not read 100 at that
   period — Guatemala's declared December 2010 reads 56.69. So REIM stores no
   base and puts none in the unit. **Levels are not comparable across
   countries**; only movements are.
2. **Guatemala's series is spliced at 2010-01 without normalisation.**
   December 2009 reads 94.882 and January 2010 reads 54.4831537, a 42.58% fall
   that is a change of base rather than deflation. It is Guatemala's only move
   beyond 15% in forty-six years, and anything computing inflation across it
   gets a meaningless answer.
3. **El Salvador has one corrupt cell**, 1985-08, reading 7.157 between 11.473
   and 11.928. That is a different defect from Guatemala's: a single bad value
   the series steps around, not a permanent level shift. Both are stored as
   published and both are pinned by ``_check_known_splices``.
4. **Nicaragua's 1980s are real and enormous** — 58 moves beyond 15% and values
   down to ``2E-9``, from hyperinflation and two córdoba redenominations seen
   through an index rebased twenty years later.

Together those make ``max_period_change_pct`` unsettable: any threshold that
tolerates Nicaragua's +261% detects nothing, and any that catches Guatemala's
splice rejects real history. The rule is null and this module checks instead.

Nicaragua also has ``ni_cpi_index_monthly`` from INIDE. The two disagree by a
median 4.2% in level while their year-on-year rates differ by more than 0.5
points in only 15 of 198 shared months — a rebasing difference between two
official compilers. REIM stores both and chooses between neither.
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

#: This family's period dimension — the same one the exchange rate uses, and
#: like it, translated in the English data response.
PERIOD_DIMENSION = 515

CEPAL_ID = 365

INDICATOR_CODE = "cpi_index_monthly"


#: The member ids are not in calendar order — May is 825, after April's 519 —
#: so the name is the only key.
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

#: A month-on-month move beyond this is a series break rather than inflation,
#: everywhere except the exceptions below.
SPLICE_THRESHOLD = Decimal("15")

#: The breaks measured on 2026-09-06, keyed on the month moved **into**.
#: El Salvador needs two entries because one corrupt cell produces two moves:
#: the fall into August and the recovery into September.
KNOWN_SPLICES = frozenset({("GTM", "2010-01"), ("SLV", "1985-08"), ("SLV", "1985-09")})

#: Nicaragua's hyperinflation is excluded by date rather than enumerated: it
#: contains 58 legitimate moves beyond the threshold, and its worst from 1992
#: onward is 9.28%, so the cut is clean.
HYPERINFLATION_BEFORE = {"NIC": "1992-01"}


class CepalstatCpiConnector(CepalstatConnector):
    """Monthly consumer price indices for the seven Central American countries."""

    connector_key = "cepalstat_cpi_monthly"
    version = "1.0.0"
    expected_frequency = Frequency.MONTHLY

    async def extract(self) -> RawDataset:
        """Fetch the index matrix. One request.

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

        Pure function of ``raw``. Values are stored exactly as published: no
        scaling, and no rounding to the two decimals CEPAL declares but does
        not keep to.

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
            observations.append(
                NormalizedObservation(
                    country_iso3=str(iso3),
                    indicator_code=INDICATOR_CODE,
                    source_key=self.source.key,
                    period=parse_period(label, Frequency.MONTHLY),
                    # No base year: CEPAL declares one per country and three of
                    # the five it declares do not hold.
                    unit="index",
                    currency_code=None,
                    value_numeric=value,
                    retrieved_at=raw.retrieved_at,
                    source_url=f"{raw.source_url}/indicator/{CEPAL_ID}/data",
                    source_record_id=f"cepalstat:{CEPAL_ID}:{iso3}:{label}",
                    raw_metadata={
                        "cepalstat_indicator_id": CEPAL_ID,
                        # str(), not format(value.normalize(), "f"): normalize
                        # strips trailing zeros, and this series publishes up
                        # to eight decimals whose count is itself evidence.
                        "cepalstat_published_value": str(row["value"]),
                        "cepalstat_published_unit": published_unit,
                        "cepalstat_data_features": data_features,
                        # Null on the freshest rows; stored empty rather than
                        # given an attribution REIM would be inventing.
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

        Every member is a month, so the mapping is total and nothing is
        dropped. A label that is not a known month name means CEPAL renamed a
        member or stopped translating this dimension — either is a contract
        break, not a row to skip.

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
                observations, {INDICATOR_CODE: CENTRAL_AMERICA}, "cepalstat_cpi_expected_countries"
            ),
            self._check_known_splices(observations),
            self._check_monthly_continuity(observations),
        ]

    def _check_known_splices(self, observations: list[NormalizedObservation]) -> QualityResult:
        """Report any series break that is not one of the three already measured.

        A consumer price index does not move 15% in a month outside
        hyperinflation. Where it appears to, the cause is almost always a
        rebased segment spliced in without normalisation, and inflation
        computed across such a point is meaningless.

        Three things are skipped before a move is judged:

        * **Non-adjacent months.** Belize published quarterly until 2011;
          comparing March against the following December would manufacture
          breaks that are really gaps.
        * **Nicaragua before 1992**, which holds 58 legitimate moves beyond the
          threshold. Its worst from 1992 onward is 9.28%, so the cut is clean.
        * **The three measured breaks** in ``KNOWN_SPLICES`` — Guatemala
          2010-01, and El Salvador's 1985-08 and 1985-09, which are one corrupt
          cell seen as two moves.
        """
        series: dict[str, dict[tuple[int, int], Decimal]] = {}
        for obs in observations:
            if obs.value_numeric is None:
                continue
            key = (obs.period.start.year, obs.period.start.month)
            series.setdefault(obs.country_iso3, {})[key] = obs.value_numeric

        found: list[str] = []
        allowed = 0
        compared = 0
        for iso3, months in sorted(series.items()):
            cutoff = HYPERINFLATION_BEFORE.get(iso3)
            for (year, month), value in sorted(months.items()):
                previous = (year - 1, 12) if month == 1 else (year, month - 1)
                if previous not in months or not months[previous]:
                    continue
                label = f"{year}-{month:02d}"
                if cutoff is not None and label < cutoff:
                    continue
                compared += 1
                change = abs(value - months[previous]) / months[previous] * 100
                if change <= SPLICE_THRESHOLD:
                    continue
                if (iso3, label) in KNOWN_SPLICES:
                    allowed += 1
                    continue
                found.append(f"{iso3} {label} ({change:.1f}%)")

        if not found:
            return QualityResult.passed(
                "cepalstat_cpi_known_splices",
                CheckType.CONSISTENCY,
                f"No unrecorded break across {compared} adjacent month(s); "
                f"{allowed} of the 3 known breaks seen",
                expected_value="0 unrecorded",
                actual_value="0",
            )

        shown = ", ".join(found[:5])
        suffix = f" (+{len(found) - 5} more)" if len(found) > 5 else ""
        return QualityResult.failure(
            "cepalstat_cpi_known_splices",
            CheckType.CONSISTENCY,
            CheckSeverity.ERROR,
            f"{len(found)} unrecorded series break(s): {shown}{suffix}",
            expected_value="0 unrecorded",
            actual_value=str(len(found)),
        )
