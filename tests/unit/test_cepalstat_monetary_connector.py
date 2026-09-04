"""Unit tests for the CEPALSTAT monthly monetary-aggregates connector.

Every payload replayed here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from reim.core.constants import CheckSeverity, CheckStatus, Frequency
from reim.core.exceptions import ExtractionError, TransformationError
from reim.domain.pipelines.models import NormalizedObservation, QualityResult, RawDataset
from reim.domain.sources.catalog import load_catalog
from reim.ingestion.connectors.regional.cepalstat_monetary import (
    CENTRAL_AMERICA,
    CepalstatMonetaryConnector,
)
from tests.conftest import REPO_ROOT

PERIOD_DIMENSION = 3981
YEARS_DIMENSION = 29117

#: What the recordings hold, measured on 2026-08-19.
MONTHLY_CELLS = {862: 2026, 868: 1611, 869: 1746}
ABSENT = {862: set(), 868: {"BLZ"}, 869: {"SLV"}}

SPANISH_MONTHS = {
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


def period_members(dimensions_text: str) -> dict[int, str]:
    body = json.loads(dimensions_text)["body"]
    dimension = next(d for d in body["dimensions"] if d["id"] == PERIOD_DIMENSION)
    return {member["id"]: member["name"] for member in dimension["members"]}


def monthly_cells(data_text: str, members: dict[int, str]) -> dict[tuple[str, int, int], Decimal]:
    """Flatten one response to ``(iso3, year, month) -> value`` for the seven."""
    body = json.loads(data_text, parse_float=Decimal)["body"]
    years = next(d for d in body["dimensions"] if d["id"] == YEARS_DIMENSION)
    labels = {member["id"]: member["name"] for member in years["members"]}
    cells = {}
    for row in body["data"]:
        if row.get("iso3") not in CENTRAL_AMERICA:
            continue
        name = members[row[f"dim_{PERIOD_DIMENSION}"]]
        if name not in SPANISH_MONTHS:
            continue
        key = (row["iso3"], int(labels[row[f"dim_{YEARS_DIMENSION}"]]), SPANISH_MONTHS[name])
        cells[key] = Decimal(str(row["value"]))
    return cells


def test_the_english_period_members_are_all_untranslated(
    cepalstat_monetary_862_json: str,
) -> None:
    """The whole reason a second request is made in Spanish."""
    body = json.loads(cepalstat_monetary_862_json)["body"]
    dimension = next(d for d in body["dimensions"] if d["id"] == PERIOD_DIMENSION)

    names = {member["name"] for member in dimension["members"]}

    assert names == {"descripcion_ingles"}
    assert len(dimension["members"]) == 17


def test_the_spanish_dimensions_name_every_month(
    cepalstat_dimensions_862_json: str,
) -> None:
    members = period_members(cepalstat_dimensions_862_json)

    assert len(members) == 17
    assert set(members.values()) == set(SPANISH_MONTHS) | {
        "Anual",
        "Trimestre 1",
        "Trimestre 2",
        "Trimestre 3",
        "Trimestre 4",
    }


def test_the_member_ids_are_not_in_calendar_order(
    cepalstat_dimensions_862_json: str,
) -> None:
    """Pinning or inferring the ids was never an option: 3993 is September."""
    members = period_members(cepalstat_dimensions_862_json)
    by_name = {name: member_id for member_id, name in members.items()}

    assert by_name["Septiembre"] < by_name["Julio"] < by_name["Agosto"]
    assert by_name["Diciembre"] < by_name["Octubre"] < by_name["Noviembre"]


@pytest.mark.parametrize("cepal_id", [862, 868, 869])
def test_each_recording_holds_its_measured_monthly_count(
    cepal_id: int, request: pytest.FixtureRequest
) -> None:
    data = request.getfixturevalue(f"cepalstat_monetary_{cepal_id}_json")
    members = period_members(request.getfixturevalue(f"cepalstat_dimensions_{cepal_id}_json"))

    cells = monthly_cells(data, members)

    assert len(cells) == MONTHLY_CELLS[cepal_id]
    assert {iso3 for iso3, _, _ in cells} == CENTRAL_AMERICA - ABSENT[cepal_id]


@pytest.mark.parametrize("cepal_id", [862, 868, 869])
def test_no_country_has_a_gap_inside_its_own_span(
    cepal_id: int, request: pytest.FixtureRequest
) -> None:
    """Zero gaps in all 19 country-indicator series, measured 2026-08-19."""
    data = request.getfixturevalue(f"cepalstat_monetary_{cepal_id}_json")
    members = period_members(request.getfixturevalue(f"cepalstat_dimensions_{cepal_id}_json"))
    cells = monthly_cells(data, members)

    for iso3 in sorted({country for country, _, _ in cells}):
        months = sorted((y, m) for country, y, m in cells if country == iso3)
        first, last = months[0], months[-1]
        span = (last[0] - first[0]) * 12 + (last[1] - first[1]) + 1
        assert len(months) == span, f"{iso3} has {span - len(months)} gap(s)"


@pytest.mark.parametrize("cepal_id", [862, 868, 869])
def test_the_annual_member_only_restates_december(
    cepal_id: int, request: pytest.FixtureRequest
) -> None:
    """453 cells, zero exceptions. This is why only the month is stored."""
    data = request.getfixturevalue(f"cepalstat_monetary_{cepal_id}_json")
    dims = request.getfixturevalue(f"cepalstat_dimensions_{cepal_id}_json")
    members = period_members(dims)
    body = json.loads(data, parse_float=Decimal)["body"]
    years = next(d for d in body["dimensions"] if d["id"] == YEARS_DIMENSION)
    labels = {member["id"]: member["name"] for member in years["members"]}

    by_kind: dict[tuple[str, str, str], Decimal] = {}
    for row in body["data"]:
        if row.get("iso3") not in CENTRAL_AMERICA:
            continue
        key = (
            row["iso3"],
            labels[row[f"dim_{YEARS_DIMENSION}"]],
            members[row[f"dim_{PERIOD_DIMENSION}"]],
        )
        by_kind[key] = Decimal(str(row["value"]))

    compared = 0
    for (iso3, year, kind), value in by_kind.items():
        if kind != "Anual":
            continue
        december = by_kind.get((iso3, year, "Diciembre"))
        assert december == value, f"{iso3} {year}: annual {value} != December {december}"
        compared += 1
    assert compared > 0


def build_connector() -> CepalstatMonetaryConnector:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    return CepalstatMonetaryConnector(catalog.get("cepalstat_monetary_monthly"))


def build_raw(data: dict[int, str], dimensions: dict[int, str]) -> RawDataset:
    return RawDataset(
        source_key="cepalstat_monetary_monthly",
        retrieved_at=datetime(2026, 8, 19, 12, 0, tzinfo=UTC),
        source_url="https://api-cepalstat.cepal.org/cepalstat/api/v1",
        payload={"data": data, "dimensions": dimensions},
        content_type="application/json",
        http_status=200,
    )


@pytest.fixture
def raw(
    cepalstat_monetary_862_json: str,
    cepalstat_monetary_868_json: str,
    cepalstat_monetary_869_json: str,
    cepalstat_dimensions_862_json: str,
    cepalstat_dimensions_868_json: str,
    cepalstat_dimensions_869_json: str,
) -> RawDataset:
    return build_raw(
        {
            862: cepalstat_monetary_862_json,
            868: cepalstat_monetary_868_json,
            869: cepalstat_monetary_869_json,
        },
        {
            862: cepalstat_dimensions_862_json,
            868: cepalstat_dimensions_868_json,
            869: cepalstat_dimensions_869_json,
        },
    )


def test_transform_produces_every_monthly_cell(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)

    assert len(observations) == 5383
    counts = Counter(obs.indicator_code for obs in observations)
    assert counts["money_m1_monthly"] == 2026
    assert counts["money_m2_monthly"] == 1611
    assert counts["money_m3_monthly"] == 1746


def test_the_annual_and_quarterly_members_are_discarded(raw: RawDataset) -> None:
    """Exact restatements of a month; storing them would triple-count."""
    observations = build_connector().transform(raw)

    assert all(obs.period.frequency is Frequency.MONTHLY for obs in observations)
    assert all(obs.period.days <= 31 for obs in observations)


def test_only_the_seven_countries_survive(raw: RawDataset) -> None:
    """145 countries and the regional aggregates come back; seven are kept."""
    observations = build_connector().transform(raw)

    assert {obs.country_iso3 for obs in observations} == CENTRAL_AMERICA


def test_belize_is_absent_from_m2_and_el_salvador_from_m3(raw: RawDataset) -> None:
    """The source's own asymmetry, carried through rather than papered over."""
    by_indicator: dict[str, set[str]] = {}
    for obs in build_connector().transform(raw):
        by_indicator.setdefault(obs.indicator_code, set()).add(obs.country_iso3)

    assert by_indicator["money_m1_monthly"] == CENTRAL_AMERICA
    assert by_indicator["money_m2_monthly"] == CENTRAL_AMERICA - {"BLZ"}
    assert by_indicator["money_m3_monthly"] == CENTRAL_AMERICA - {"SLV"}


def test_each_country_carries_its_own_currency(raw: RawDataset) -> None:
    """REIM's first indicator whose unit changes with the country."""
    expected = {
        "NIC": "NIO",
        "GTM": "GTQ",
        "SLV": "USD",
        "HND": "HNL",
        "CRI": "CRC",
        "PAN": "PAB",
        "BLZ": "BZD",
    }

    for obs in build_connector().transform(raw):
        assert obs.currency_code == expected[obs.country_iso3]
        assert obs.unit == expected[obs.country_iso3]


def test_the_published_millions_are_scaled_to_whole_units(raw: RawDataset) -> None:
    """Nicaragua's M1 for December 2023: 73,214.4 millions of cordobas."""
    observations = build_connector().transform(raw)
    cell = next(
        obs
        for obs in observations
        if obs.indicator_code == "money_m1_monthly"
        and obs.country_iso3 == "NIC"
        and obs.period.label == "2023-12"
    )

    assert cell.value_numeric == Decimal("73214400000")
    assert cell.raw_metadata["cepalstat_published_value"] == "73214.4"
    assert cell.raw_metadata["cepalstat_scale_applied"] == "1e6"


def test_periods_are_calendar_months(raw: RawDataset) -> None:
    cell = next(
        obs
        for obs in build_connector().transform(raw)
        if obs.country_iso3 == "NIC" and obs.period.label == "2023-12"
    )

    assert cell.period.start == date(2023, 12, 1)
    assert cell.period.end == date(2023, 12, 31)


def test_source_record_ids_are_unique_and_readable(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)
    ids = [obs.source_record_id for obs in observations]

    assert len(set(ids)) == len(ids)
    assert "cepalstat:862:NIC:2023-12" in ids


def test_an_unknown_period_member_raises(raw: RawDataset) -> None:
    """A renamed or added member must fail loudly, not drop rows in silence."""
    dimensions = json.loads(raw.payload["dimensions"][862])
    for dimension in dimensions["body"]["dimensions"]:
        if dimension["id"] == PERIOD_DIMENSION:
            dimension["members"] = [m for m in dimension["members"] if m["name"] != "Enero"]

    broken = build_raw(
        dict(raw.payload["data"]),
        {**raw.payload["dimensions"], 862: json.dumps(dimensions)},
    )

    with pytest.raises(TransformationError, match="unknown period member"):
        build_connector().transform(broken)


def test_a_missing_period_dimension_raises(raw: RawDataset) -> None:
    dimensions = json.loads(raw.payload["dimensions"][862])
    dimensions["body"]["dimensions"] = [
        d for d in dimensions["body"]["dimensions"] if d["id"] != PERIOD_DIMENSION
    ]

    broken = build_raw(
        dict(raw.payload["data"]),
        {**raw.payload["dimensions"], 862: json.dumps(dimensions)},
    )

    with pytest.raises(TransformationError, match="no period dimension"):
        build_connector().transform(broken)


def test_a_renamed_period_member_raises(raw: RawDataset) -> None:
    """The bug this covers: a rename used to fall through as 'not a month'.

    Only a *removed* member id reached `_month_of`'s raise; a member whose
    label changed kept its id, so `MONTHS_BY_SPANISH_NAME.get(label)` just
    returned `None` and the row was dropped in silence, indistinguishable
    from a legitimate non-month member such as "Anual".
    """
    dimensions = json.loads(raw.payload["dimensions"][862])
    for dimension in dimensions["body"]["dimensions"]:
        if dimension["id"] == PERIOD_DIMENSION:
            for member in dimension["members"]:
                if member["name"] == "Enero":
                    member["name"] = "Jan"

    broken = build_raw(
        dict(raw.payload["data"]),
        {**raw.payload["dimensions"], 862: json.dumps(dimensions)},
    )

    with pytest.raises(TransformationError, match="'Jan'"):
        build_connector().transform(broken)


def test_an_added_unknown_period_member_raises(raw: RawDataset) -> None:
    """A member CEPAL adds is neither a known month nor a known non-month one."""
    dimensions = json.loads(raw.payload["dimensions"][862])
    for dimension in dimensions["body"]["dimensions"]:
        if dimension["id"] == PERIOD_DIMENSION:
            dimension["members"].append({"id": 4000, "name": "Semestre 1"})

    broken = build_raw(
        dict(raw.payload["data"]),
        {**raw.payload["dimensions"], 862: json.dumps(dimensions)},
    )

    with pytest.raises(TransformationError, match="'Semestre 1'"):
        build_connector().transform(broken)


# The legitimate non-month members ("Anual" and the four "Trimestre N"
# members) still skip silently on the unmodified fixtures: that is exactly
# what `test_transform_produces_every_monthly_cell` already asserts (5,383
# observations, none of them an annual or quarterly restatement), so it is
# not duplicated here.


def results_of(observations: list[NormalizedObservation]) -> dict[str, QualityResult]:
    return {result.check_name: result for result in build_connector().validate(observations)}


def test_all_three_checks_pass_on_the_real_recordings(raw: RawDataset) -> None:
    results = results_of(build_connector().transform(raw))

    assert set(results) == {
        "cepalstat_monetary_nesting",
        "cepalstat_monetary_expected_countries",
        "cepalstat_monthly_continuity",
    }
    assert all(result.status is CheckStatus.PASSED for result in results.values())


def test_the_nesting_holds_on_the_real_data_despite_rounding(raw: RawDataset) -> None:
    """229 cells invert by up to 0.014% because CEPAL rounds some series."""
    result = results_of(build_connector().transform(raw))["cepalstat_monetary_nesting"]

    assert result.status is CheckStatus.PASSED


def test_a_real_inversion_fails_the_nesting_check(raw: RawDataset) -> None:
    """Move one M1 cell above its M2: a percent-scale break, not rounding."""
    observations = build_connector().transform(raw)
    for index, obs in enumerate(observations):
        if (
            obs.indicator_code == "money_m1_monthly"
            and obs.country_iso3 == "NIC"
            and obs.period.label == "2023-12"
        ):
            assert obs.value_numeric is not None
            observations[index] = replace(obs, value_numeric=obs.value_numeric * Decimal("10"))

    result = results_of(observations)["cepalstat_monetary_nesting"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.ERROR
    assert "NIC 2023-12" in result.message


def test_rounding_alone_never_fails_the_nesting_check(raw: RawDataset) -> None:
    """The tolerance must admit the source's own rounding, and no more."""
    observations = build_connector().transform(raw)
    for index, obs in enumerate(observations):
        if obs.indicator_code == "money_m2_monthly":
            assert obs.value_numeric is not None
            observations[index] = replace(obs, value_numeric=obs.value_numeric * Decimal("0.9999"))

    assert results_of(observations)["cepalstat_monetary_nesting"].status is CheckStatus.PASSED


def test_a_missing_country_fails_critically(raw: RawDataset) -> None:
    observations = [
        obs
        for obs in build_connector().transform(raw)
        if not (obs.indicator_code == "money_m1_monthly" and obs.country_iso3 == "NIC")
    ]

    result = results_of(observations)["cepalstat_monetary_expected_countries"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.CRITICAL
    assert "NIC" in result.message


def test_belize_appearing_in_m2_is_reported_too(raw: RawDataset) -> None:
    """The expectation is a set, not a floor: an arrival is news as well."""
    observations = build_connector().transform(raw)
    extra = next(obs for obs in observations if obs.indicator_code == "money_m1_monthly")
    observations.append(replace(extra, indicator_code="money_m2_monthly", country_iso3="BLZ"))

    result = results_of(observations)["cepalstat_monetary_expected_countries"]

    assert result.status is CheckStatus.FAILED
    assert "BLZ" in result.message


def test_a_hole_in_one_country_is_reported_as_a_warning(raw: RawDataset) -> None:
    """Pooling the seven would hide it: the others published that month."""
    observations = [
        obs
        for obs in build_connector().transform(raw)
        if not (
            obs.indicator_code == "money_m1_monthly"
            and obs.country_iso3 == "NIC"
            and obs.period.label == "2015-06"
        )
    ]

    result = results_of(observations)["cepalstat_monthly_continuity"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.WARNING
    assert "NIC 2015-06" in result.message


def test_every_check_is_dataset_level(raw: RawDataset) -> None:
    results = build_connector().validate(build_connector().transform(raw))

    assert all(result.observation_index is None for result in results)


BASE_URL = "https://api-cepalstat.cepal.org/cepalstat/api/v1"


def data_url(cepal_id: int) -> str:
    return f"{BASE_URL}/indicator/{cepal_id}/data"


def dimensions_url(cepal_id: int) -> str:
    return f"{BASE_URL}/indicator/{cepal_id}/dimensions"


def json_response(text: str) -> httpx.Response:
    return httpx.Response(200, text=text, headers={"content-type": "application/json"})


@respx.mock
async def test_a_run_makes_two_requests_per_indicator(
    cepalstat_monetary_862_json: str,
    cepalstat_monetary_868_json: str,
    cepalstat_monetary_869_json: str,
    cepalstat_dimensions_862_json: str,
    cepalstat_dimensions_868_json: str,
    cepalstat_dimensions_869_json: str,
) -> None:
    data = {
        862: cepalstat_monetary_862_json,
        868: cepalstat_monetary_868_json,
        869: cepalstat_monetary_869_json,
    }
    dims = {
        862: cepalstat_dimensions_862_json,
        868: cepalstat_dimensions_868_json,
        869: cepalstat_dimensions_869_json,
    }
    routes = []
    for cepal_id in (862, 868, 869):
        routes.append(
            respx.get(data_url(cepal_id)).mock(return_value=json_response(data[cepal_id]))
        )
        routes.append(
            respx.get(dimensions_url(cepal_id)).mock(return_value=json_response(dims[cepal_id]))
        )

    raw = await build_connector().extract()

    assert all(route.call_count == 1 for route in routes)
    assert set(raw.payload["data"]) == {862, 868, 869}
    assert set(raw.payload["dimensions"]) == {862, 868, 869}


@respx.mock
async def test_the_data_is_english_and_the_dimensions_are_spanish(
    cepalstat_monetary_862_json: str, cepalstat_dimensions_862_json: str
) -> None:
    """The whole point of the split: nothing stored comes back translated."""
    for cepal_id in (862, 868, 869):
        respx.get(data_url(cepal_id)).mock(return_value=json_response(cepalstat_monetary_862_json))
        respx.get(dimensions_url(cepal_id)).mock(
            return_value=json_response(cepalstat_dimensions_862_json)
        )

    await build_connector().extract()

    by_path = {call.request.url.path: call.request.url for call in respx.calls}
    assert by_path["/cepalstat/api/v1/indicator/862/data"].params["lang"] == "en"
    assert by_path["/cepalstat/api/v1/indicator/862/dimensions"].params["lang"] == "es"


@respx.mock
async def test_a_failing_envelope_raises_even_on_http_200() -> None:
    """CEPAL answers an unknown id with 500 and success:false, never 404."""
    envelope = json.dumps(
        {
            "header": {"success": False, "code": 404, "message": "Not found"},
            "body": {"data": []},
        }
    )
    respx.get(data_url(862)).mock(return_value=json_response(envelope))

    with pytest.raises(ExtractionError, match="reported failure 404"):
        await build_connector().extract()


@respx.mock
async def test_an_empty_data_array_raises(cepalstat_monetary_862_json: str) -> None:
    body = json.loads(cepalstat_monetary_862_json)
    body["body"]["data"] = []
    respx.get(data_url(862)).mock(return_value=json_response(json.dumps(body)))

    with pytest.raises(ExtractionError, match="no rows"):
        await build_connector().extract()


@pytest.mark.live
async def test_the_real_api_still_answers_as_recorded() -> None:
    """Opt-in. Proves the contract, not the data: shape, not values."""
    connector = build_connector()
    observations = connector.transform(await connector.extract())

    assert len(observations) >= 5000
    assert {obs.country_iso3 for obs in observations} == CENTRAL_AMERICA
    assert all(result.status is CheckStatus.PASSED for result in connector.validate(observations))
