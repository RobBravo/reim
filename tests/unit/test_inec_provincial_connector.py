"""Unit tests for the INEC Panama provincial connector.

Every payload replayed here is a real recording; see tests/fixtures/.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from reim.domain.pipelines.models import RawDataset
from reim.domain.sources.catalog import load_catalog
from reim.ingestion.connectors.panama.inec_provincial import INECProvincialConnector
from tests.conftest import REPO_ROOT

VARIABLE_IDS = (232, 206, 207, 202, 203, 204, 205)
INDICATOR_CODES = {
    232: "pa_automobiles_per_1000_provincial_annual",
    206: "pa_residential_buildings_count_provincial_annual",
    207: "pa_nonresidential_buildings_count_provincial_annual",
    202: "pa_residential_construction_area_provincial_annual",
    203: "pa_nonresidential_construction_area_provincial_annual",
    204: "pa_residential_construction_value_provincial_annual",
    205: "pa_nonresidential_construction_value_provincial_annual",
}
#: The two variables whose unit is a currency ("balboas"), not a count or ratio.
CURRENCY_VARIABLE_IDS = (204, 205)


def build_connector() -> INECProvincialConnector:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    return INECProvincialConnector(catalog.get("inec_pa_provincial"))


def build_raw(catalogue: str, choropleths: dict[int, str]) -> RawDataset:
    return RawDataset(
        source_key="inec_pa_provincial",
        retrieved_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        source_url="https://www.inec.gob.pa/m_2/api/data/choropleth",
        payload={
            "catalogue": json.loads(catalogue),
            "choropleth": {
                variable_id: json.loads(payload) for variable_id, payload in choropleths.items()
            },
        },
        content_type="application/json",
        http_status=200,
        metadata={"operation": "choropleth"},
    )


@pytest.fixture
def raw(
    inec_catalogue_excerpt_json: str,
    inec_choropleth_232_json: str,
    inec_choropleth_206_json: str,
    inec_choropleth_207_json: str,
    inec_choropleth_202_json: str,
    inec_choropleth_203_json: str,
    inec_choropleth_204_json: str,
    inec_choropleth_205_json: str,
) -> RawDataset:
    return build_raw(
        inec_catalogue_excerpt_json,
        {
            232: inec_choropleth_232_json,
            206: inec_choropleth_206_json,
            207: inec_choropleth_207_json,
            202: inec_choropleth_202_json,
            203: inec_choropleth_203_json,
            204: inec_choropleth_204_json,
            205: inec_choropleth_205_json,
        },
    )


def test_each_variable_yields_eleven_observations(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)

    by_indicator: dict[str, int] = {}
    for obs in observations:
        by_indicator[obs.indicator_code] = by_indicator.get(obs.indicator_code, 0) + 1
    assert by_indicator == dict.fromkeys(INDICATOR_CODES.values(), 11)
    assert len(observations) == 77


def test_only_the_value_variables_carry_a_currency(raw: RawDataset) -> None:
    """202/203 (area, square metres) carry no currency; 204/205 (value, balboas) carry PAB.

    Guards the connector's own "store what's published, never convert" rule:
    balboas are pegged 1:1 to the dollar, but the source publishes balboas, so
    the observation must say PAB, never USD.
    """
    observations = build_connector().transform(raw)

    by_variable: dict[int, set[str | None]] = {}
    for obs in observations:
        variable_id = next(
            vid for vid, code in INDICATOR_CODES.items() if code == obs.indicator_code
        )
        by_variable.setdefault(variable_id, set()).add(obs.currency_code)

    for variable_id, currencies in by_variable.items():
        if variable_id in CURRENCY_VARIABLE_IDS:
            assert currencies == {"PAB"}, f"variable {variable_id}: {currencies}"
        else:
            assert currencies == {None}, f"variable {variable_id}: {currencies}"


def test_exactly_one_national_observation_per_indicator(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)

    for code in INDICATOR_CODES.values():
        national = [
            o
            for o in observations
            if o.indicator_code == code and o.administrative_area_code is None
        ]
        assert len(national) == 1


def test_exactly_ten_provincial_observations_per_indicator_with_no_duplicates(
    raw: RawDataset,
) -> None:
    observations = build_connector().transform(raw)

    for code in INDICATOR_CODES.values():
        codes = [
            o.administrative_area_code
            for o in observations
            if o.indicator_code == code and o.administrative_area_code is not None
        ]
        assert len(codes) == 10
        assert len(set(codes)) == 10


def test_every_observation_is_panama_2023(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)

    for obs in observations:
        assert obs.country_iso3 == "PAN"
        assert obs.period.label == "2023"


def test_the_year_comes_from_the_catalogue_not_a_constant(raw: RawDataset) -> None:
    """If the catalogue excerpt is edited to claim a different year, transform() must follow it.

    Guards against the year being silently hardcoded to 2023 in the connector
    despite the design requiring it to be read from anio_referencia.
    """
    catalogue = json.loads(
        (REPO_ROOT / "tests" / "fixtures" / "inec_catalogue_excerpt.json").read_text(
            encoding="utf-8"
        )
    )
    for entry in catalogue:
        entry["anio_referencia"] = 2030

    raw_with_future_year = RawDataset(
        source_key="inec_pa_provincial",
        retrieved_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        source_url="https://www.inec.gob.pa/m_2/api/data/choropleth",
        payload={
            "catalogue": catalogue,
            "choropleth": {
                variable_id: json.loads(
                    (
                        REPO_ROOT / "tests" / "fixtures" / f"inec_choropleth_{variable_id}.json"
                    ).read_text(encoding="utf-8")
                )
                for variable_id in VARIABLE_IDS
            },
        },
        content_type="application/json",
        http_status=200,
        metadata={},
    )
    observations = build_connector().transform(raw_with_future_year)
    assert all(o.period.label == "2030" for o in observations)


def test_the_national_row_carries_the_choropleths_own_total(raw: RawDataset) -> None:
    """The is_total row's value, not a sum computed from the ten provinces."""
    observations = build_connector().transform(raw)
    national = next(
        o
        for o in observations
        if o.indicator_code == "pa_automobiles_per_1000_provincial_annual"
        and o.administrative_area_code is None
    )
    provincial_total = sum(
        Decimal(str(o.value_numeric))
        for o in observations
        if o.indicator_code == "pa_automobiles_per_1000_provincial_annual"
        and o.administrative_area_code is not None
    )
    # The national figure is a rate (per 1,000 inhabitants), not a sum of the
    # provincial rates, so it must NOT equal the naive sum of the ten — this
    # pins that the connector reads is_total rather than computing one.
    assert national.value_numeric != provincial_total


def test_unit_comes_from_the_response_not_reinvented(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)
    automobiles = next(
        o for o in observations if o.indicator_code == "pa_automobiles_per_1000_provincial_annual"
    )
    assert automobiles.unit == "automóviles"
