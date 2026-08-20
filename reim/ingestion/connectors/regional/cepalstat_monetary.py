"""Central America — monthly monetary aggregates published through CEPALSTAT.

The API, its lack of documentation and the way its routes were recovered are
documented in ``cepalstat_gdp.py``; only what differs is recorded here.

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

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from reim.core.constants import Frequency
from reim.core.exceptions import ExtractionError, TransformationError
from reim.domain.countries.registry import COUNTRIES_BY_ISO3
from reim.domain.observations.periods import parse_period
from reim.domain.pipelines.models import (
    NormalizedObservation,
    QualityResult,
    RawDataset,
)
from reim.ingestion.base import BaseConnector
from reim.ingestion.http import ensure_ok, fetch, http_client

#: Shared with the GDP connector; the period dimension is this family's own.
COUNTRY_DIMENSION = 208
YEARS_DIMENSION = 29117
PERIOD_DIMENSION = 3981

#: Published in millions of local currency, stored in whole units.
MILLIONS = Decimal("1000000")

CENTRAL_AMERICA = frozenset({"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"})

#: The only member names that become observations. Read from the Spanish
#: dimensions response; "Anual" and the four "Trimestre N" members are
#: restatements of a month and are dropped.
MONTHS_BY_SPANISH_NAME = {
    "Enero": 1,
    "Febrero": 2,
    "Marzo": 3,
    "Abril": 4,
    "Mayo": 5,
    "Junio": 6,
    "Julio": 7,
    "Agosto": 8,
    "Septiembre": 9,
    "Octubre": 10,
    "Noviembre": 11,
    "Diciembre": 12,
}


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


class CepalstatMonetaryConnector(BaseConnector):
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
        months = self._months_of(self._decode(dimensions_text, spec.cepal_id), spec.cepal_id)
        years = self._members_of(body, YEARS_DIMENSION, "years", spec.cepal_id)
        published_unit = str(body["metadata"]["unit"])
        sources = {source["id"]: source["description"] for source in body["sources"]}
        credits = [entry["description"] for entry in body["credits"] if entry["id"] != 0]

        observations: list[NormalizedObservation] = []
        for row in body["data"]:
            iso3 = row.get("iso3")
            if iso3 not in CENTRAL_AMERICA:
                continue
            month = self._month_of(row, months, spec.cepal_id)
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

    def _decode(self, text: str, cepal_id: int) -> Any:
        """Decode JSON, keeping published decimals exact."""
        try:
            return json.loads(text, parse_float=Decimal)
        except json.JSONDecodeError as exc:
            msg = f"CEPALSTAT returned malformed JSON for indicator {cepal_id}: {exc}"
            raise TransformationError(msg, source_key=self.source.key) from exc

    def _members_of(self, body: Any, dimension_id: int, name: str, cepal_id: int) -> dict[int, str]:
        """Build the ``member id -> label`` map from the response itself.

        Raises:
            TransformationError: The dimension is absent.
        """
        for dimension in body.get("dimensions", []):
            if dimension.get("id") == dimension_id:
                return {member["id"]: str(member["name"]) for member in dimension["members"]}
        msg = f"CEPALSTAT returned no {name} dimension for indicator {cepal_id}"
        raise TransformationError(msg, source_key=self.source.key)

    def _months_of(self, dimensions_document: Any, cepal_id: int) -> dict[int, int | None]:
        """Map each period member id to a month number, or ``None`` to skip.

        ``None`` marks the annual and quarterly members, which restate a month
        exactly and are not stored.

        Raises:
            TransformationError: The period dimension is absent.
        """
        members = self._members_of(
            dimensions_document["body"], PERIOD_DIMENSION, "period", cepal_id
        )
        return {
            member_id: MONTHS_BY_SPANISH_NAME.get(label) for member_id, label in members.items()
        }

    def _month_of(self, row: Any, months: dict[int, int | None], cepal_id: int) -> int | None:
        """Resolve a row's month, or ``None`` when it is a restatement.

        Raises:
            TransformationError: The row names a period member that does not
                exist, which means CEPAL renamed or added one.
        """
        member = row.get(f"dim_{PERIOD_DIMENSION}")
        if member not in months:
            msg = (
                f"CEPALSTAT row for indicator {cepal_id} names an unknown period member {member!r}"
            )
            raise TransformationError(msg, source_key=self.source.key)
        return months[member]

    def _label_of(
        self, row: Any, labels: dict[int, str], dimension_id: int, name: str, cepal_id: int
    ) -> str:
        """Resolve a row's label for one dimension.

        Raises:
            TransformationError: The row names a member that does not exist.
        """
        member = row.get(f"dim_{dimension_id}")
        label = labels.get(member)
        if label is None:
            msg = (
                f"CEPALSTAT row for indicator {cepal_id} names an unknown {name} member {member!r}"
            )
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
