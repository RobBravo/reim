"""INEC Panama — provincial economic indicators.

REIM's first subnational data. Seven variables from INEC's "Panamá en
Cifras Digital" choropleth API, each yielding one national observation
(the response's own ``is_total`` row) and ten provincial ones.

See docs/sources.md's "INEC Panama" entry and
docs/superpowers/specs/2026-09-20-inec-panama-provincial-design.md for the
research this is built from. Variables 202-205 (construction area and
value) were the "reasonable second increment" that design's own excluded
table named; added here unchanged in shape from the original three.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from reim.core.constants import CheckSeverity, CheckType, Frequency
from reim.core.exceptions import ExtractionError, TransformationError
from reim.domain.observations.periods import parse_period
from reim.domain.pipelines.models import NormalizedObservation, QualityResult, RawDataset
from reim.ingestion.base import BaseConnector
from reim.ingestion.http import ensure_ok, fetch, http_client

#: Variable id -> REIM indicator code. Order doesn't matter; this is the
#: authority on which seven of INEC's 218 catalogue entries this connector
#: reads.
VARIABLE_INDICATORS: dict[int, str] = {
    232: "pa_automobiles_per_1000_provincial_annual",
    206: "pa_residential_buildings_count_provincial_annual",
    207: "pa_nonresidential_buildings_count_provincial_annual",
    202: "pa_residential_construction_area_provincial_annual",
    203: "pa_nonresidential_construction_area_provincial_annual",
    204: "pa_residential_construction_value_provincial_annual",
    205: "pa_nonresidential_construction_value_provincial_annual",
}

#: Variable ids whose ``unidad_medida`` is a currency ("balboas") rather than
#: a count or ratio. Their observations carry ``currency_code`` — the
#: source's own stated currency, never converted, the same "store what's
#: published" rule REIM applies everywhere else.
_CURRENCY_VARIABLE_IDS: frozenset[int] = frozenset({204, 205})


class INECProvincialConnector(BaseConnector):
    """Provincial-level figures from INEC Panama, plus each variable's national total."""

    connector_key = "inec_pa_provincial"
    version = "1.0.0"
    expected_frequency = Frequency.ANNUAL

    async def extract(self) -> RawDataset:
        """Fetch the catalogue, then one choropleth payload per variable.

        Eight requests (one catalogue, seven choropleths). The year comes
        from the catalogue's own ``anio_referencia`` rather than a constant,
        so a future INEC republication is picked up without a code change —
        the same principle ``sieca_services_trade.py``'s ``extract()``
        applies to its quarter window.

        Raises:
            ExtractionError: The service was unreachable, kept failing, or
                answered with something other than JSON.
        """
        base = str(self.source.base_url).rstrip("/")
        retrieved_at = self.now()

        async with http_client(user_agent=self.source.user_agent) as client:
            catalogue_response = await fetch(client, f"{base}/meta/estructura-completa")
            ensure_ok(catalogue_response, expected_content_type="json")
            catalogue = _flatten_catalogue(catalogue_response.json())
            years = {
                variable_id: _year_for(catalogue, variable_id)
                for variable_id in VARIABLE_INDICATORS
            }

            choropleths: dict[int, list[dict[str, Any]]] = {}
            for variable_id, year in years.items():
                response = await fetch(
                    client,
                    f"{base}/data/choropleth",
                    params={
                        "nivel_geografico": "Provincia",
                        "id_variable": variable_id,
                        "anio": year,
                    },
                )
                ensure_ok(response, expected_content_type="json")
                choropleths[variable_id] = response.json()

        return RawDataset(
            source_key=self.connector_key,
            retrieved_at=retrieved_at,
            source_url=f"{base}/data/choropleth",
            payload={
                "catalogue": [entry for entry in catalogue if entry["id"] in VARIABLE_INDICATORS],
                "choropleth": choropleths,
            },
            content_type="application/json",
            http_status=200,
            metadata={"variable_ids": list(VARIABLE_INDICATORS)},
        )

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Normalize each variable's choropleth rows into observations.

        Pure function of ``raw``. Every row (10 provinces + 1 national total)
        becomes one observation; the national row's own ``is_total`` value is
        kept as-is, never recomputed from the ten provincial rows.

        Raises:
            TransformationError: The payload produced zero observations.
        """
        payload = raw.payload
        catalogue_by_id = {entry["id"]: entry for entry in payload["catalogue"]}
        observations: list[NormalizedObservation] = []

        for variable_id, indicator_code in VARIABLE_INDICATORS.items():
            rows = payload["choropleth"][variable_id]
            year = catalogue_by_id[variable_id]["anio_referencia"]
            period = parse_period(str(year), Frequency.ANNUAL)

            for row in rows:
                value = row.get("valor")
                if value is None:
                    continue
                observations.append(
                    NormalizedObservation(
                        country_iso3="PAN",
                        indicator_code=indicator_code,
                        source_key=self.connector_key,
                        period=period,
                        unit=row["unidad_medida"],
                        retrieved_at=raw.retrieved_at,
                        source_url=raw.source_url,
                        value_numeric=Decimal(str(value).strip()),
                        source_record_id=f"{variable_id}:{row.get('id_provincia') or 'total'}",
                        administrative_area_code=(
                            None if row.get("is_total") else row.get("id_provincia")
                        ),
                        currency_code=("PAB" if variable_id in _CURRENCY_VARIABLE_IDS else None),
                        raw_metadata={
                            "inec_variable_id": variable_id,
                            "is_total": row.get("is_total", False),
                        },
                    )
                )

        if not observations:
            msg = "INEC provincial connector produced zero observations"
            raise TransformationError(msg)

        return observations

    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert each variable produced exactly 11 rows: 10 provinces + 1 national."""
        return [self._check_eleven_rows_per_variable(observations)]

    def _check_eleven_rows_per_variable(
        self, observations: list[NormalizedObservation]
    ) -> QualityResult:
        """All 11 rows (10 provinces + 1 national) must appear per variable.

        Follows the same idiom as ``sieca_services_trade.py``'s
        ``_check_six_countries`` — a short count means a broken request, not
        a soft data-quality issue, so this fails at ``CRITICAL`` like that
        check does, not ``ERROR``.
        """
        counts: dict[str, int] = {}
        for obs in observations:
            counts[obs.indicator_code] = counts.get(obs.indicator_code, 0) + 1

        short = {code: count for code, count in counts.items() if count != 11}
        if not short:
            return QualityResult.passed(
                "inec_eleven_rows_per_variable",
                CheckType.COMPLETENESS,
                "every variable produced 10 provincial rows and 1 national row",
                expected_value="11",
                actual_value="11",
            )
        return QualityResult.failure(
            "inec_eleven_rows_per_variable",
            CheckType.COMPLETENESS,
            CheckSeverity.CRITICAL,
            f"expected 11 observations (10 provinces + 1 national) per variable, got {short}",
            expected_value="11",
            actual_value=str(short),
        )


def _flatten_catalogue(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten INEC's theme -> category -> variables nesting into one list."""
    flat: list[dict[str, Any]] = []
    for theme in payload["data"]:
        for category in theme.get("categorias", []):
            flat.extend(category.get("variables", []))
    return flat


def _year_for(catalogue: list[dict[str, Any]], variable_id: int) -> int:
    for entry in catalogue:
        if entry["id"] == variable_id:
            year: int = entry["anio_referencia"]
            return year
    msg = f"Variable {variable_id} not found in INEC's catalogue"
    raise ExtractionError(msg)
