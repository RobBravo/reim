"""Unit tests for the CEPALSTAT public debt connector.

Every payload replayed here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from reim.core.constants import CheckSeverity, CheckStatus, Frequency
from reim.core.exceptions import TransformationError
from reim.domain.pipelines.models import NormalizedObservation, QualityResult, RawDataset
from reim.domain.sources.catalog import load_catalog
from reim.ingestion.connectors.regional.cepalstat_debt import CepalstatDebtConnector
from tests.conftest import REPO_ROOT

COUNTRY_DIMENSION = 208
YEARS_DIMENSION = 29117
DEBT_CLASSIFICATION = 10590
INSTITUTIONAL_COVERAGE = 10690

CENTRAL_GOVERNMENT = 10692
TOTAL_BY_RESIDENCE = 10609
INTERNAL_DEBT = 10612
EXTERNAL_DEBT = 10613

#: Carry no rows anywhere in the response, for any of the 145 countries.
EMPTY_CLASSIFICATIONS = {10610, 10611, 10614}

CENTRAL_AMERICA = frozenset({"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"})

#: What the recordings hold, measured on 2026-09-03.
STORED_CELLS = {1239: 226, 1240: 230}
ROWS_TOTAL = {1239: 4351, 1240: 4494}

#: The two series do not cover exactly the same country-years.
SPANS = {
    1239: {
        "BLZ": (2011, 2020),
        "CRI": (1990, 2025),
        "GTM": (1990, 2025),
        "HND": (1990, 2025),
        "NIC": (1990, 2025),
        "PAN": (1990, 2025),
        "SLV": (1990, 2025),
    },
    1240: {
        "BLZ": (2011, 2025),
        "CRI": (1990, 2025),
        "GTM": (1990, 2025),
        "HND": (1990, 2025),
        "NIC": (1991, 2025),
        "PAN": (1990, 2025),
        "SLV": (1990, 2025),
    },
}


def body_of(text: str) -> dict:
    return json.loads(text, parse_float=Decimal)["body"]


def members_of(body: dict, dimension_id: int) -> dict[int, str]:
    dimension = next(d for d in body["dimensions"] if d["id"] == dimension_id)
    return {member["id"]: member["name"] for member in dimension["members"]}


def slice_of(text: str) -> dict[tuple[str, int], Decimal]:
    """Flatten one response to the central-government total, for the seven."""
    body = body_of(text)
    years = members_of(body, YEARS_DIMENSION)
    cells = {}
    for row in body["data"]:
        if row.get("iso3") not in CENTRAL_AMERICA:
            continue
        if row[f"dim_{INSTITUTIONAL_COVERAGE}"] != CENTRAL_GOVERNMENT:
            continue
        if row[f"dim_{DEBT_CLASSIFICATION}"] != TOTAL_BY_RESIDENCE:
            continue
        cells[(row["iso3"], int(years[row[f"dim_{YEARS_DIMENSION}"]]))] = Decimal(str(row["value"]))
    return cells


@pytest.fixture(params=[1239, 1240])
def recording(request, cepalstat_debt_1239_json, cepalstat_debt_1240_json):
    return request.param, {1239: cepalstat_debt_1239_json, 1240: cepalstat_debt_1240_json}[
        request.param
    ]


def test_each_recording_is_the_complete_response(recording) -> None:
    """Not an excerpt: 145 countries, every coverage, every classification."""
    cepal_id, text = recording
    body = body_of(text)

    assert len(body["data"]) == ROWS_TOTAL[cepal_id]
    assert len(members_of(body, COUNTRY_DIMENSION)) == 145
    assert len(members_of(body, INSTITUTIONAL_COVERAGE)) == 4
    assert len(members_of(body, DEBT_CLASSIFICATION)) == 6


def test_the_english_member_names_are_really_translated(recording) -> None:
    """Unlike the monetary family, so no Spanish request is needed here."""
    _, text = recording
    coverage = members_of(body_of(text), INSTITUTIONAL_COVERAGE)
    classification = members_of(body_of(text), DEBT_CLASSIFICATION)

    assert coverage[CENTRAL_GOVERNMENT] == "Central government"
    assert classification[TOTAL_BY_RESIDENCE] == ("Total public debt (classification by residence)")
    assert "descripcion_ingles" not in set(coverage.values()) | set(classification.values())


def test_three_classification_members_carry_no_rows_at_all(recording) -> None:
    """Currency, rate and maturity are grouping nodes, not data."""
    _, text = recording
    used = {row[f"dim_{DEBT_CLASSIFICATION}"] for row in body_of(text)["data"]}

    assert used & EMPTY_CLASSIFICATIONS == set()
    assert used == {TOTAL_BY_RESIDENCE, INTERNAL_DEBT, EXTERNAL_DEBT}


def test_the_stored_slice_has_its_measured_size(recording) -> None:
    cepal_id, text = recording

    assert len(slice_of(text)) == STORED_CELLS[cepal_id]


def test_every_country_span_is_gapless(recording) -> None:
    """Belize and Nicaragua are shorter; none of the seven has a hole."""
    cepal_id, text = recording
    cells = slice_of(text)

    for iso3, (first, last) in SPANS[cepal_id].items():
        years = sorted(year for country, year in cells if country == iso3)
        assert years == list(range(first, last + 1)), iso3


def test_the_two_series_differ_by_exactly_six_cells(
    cepalstat_debt_1239_json: str, cepalstat_debt_1240_json: str
) -> None:
    """NIC 1990 has a dollar figure and no ratio; BLZ 2021-2025 the reverse."""
    usd = set(slice_of(cepalstat_debt_1239_json))
    pct = set(slice_of(cepalstat_debt_1240_json))

    assert usd - pct == {("NIC", 1990)}
    assert pct - usd == {("BLZ", year) for year in range(2021, 2026)}


def test_the_internal_and_external_split_does_not_sum_to_the_total(
    cepalstat_debt_1239_json: str,
) -> None:
    """The measured reason the split is not stored as REIM indicators."""
    body = body_of(cepalstat_debt_1239_json)
    years = members_of(body, YEARS_DIMENSION)
    triples: dict[tuple[str, int], dict[int, Decimal]] = {}
    for row in body["data"]:
        if row.get("iso3") not in CENTRAL_AMERICA:
            continue
        key = (row["iso3"], int(years[row[f"dim_{YEARS_DIMENSION}"]]))
        triples.setdefault((key, row[f"dim_{INSTITUTIONAL_COVERAGE}"]), {})[
            row[f"dim_{DEBT_CLASSIFICATION}"]
        ] = Decimal(str(row["value"]))

    complete = [
        v for v in triples.values() if {TOTAL_BY_RESIDENCE, INTERNAL_DEBT, EXTERNAL_DEBT} <= set(v)
    ]
    exact = [v for v in complete if v[TOTAL_BY_RESIDENCE] == v[INTERNAL_DEBT] + v[EXTERNAL_DEBT]]

    assert len(complete) == 415
    assert len(exact) == 303


def test_nicaragua_1996_is_the_largest_real_move(cepalstat_debt_1240_json: str) -> None:
    """HIPC and Paris Club relief. Every threshold is set to clear it."""
    cells = slice_of(cepalstat_debt_1240_json)

    assert cells[("NIC", 1995)] == Decimal("185.3")
    assert cells[("NIC", 1996)] == Decimal("96.7")


def test_the_ratio_exceeds_one_hundred_percent(cepalstat_debt_1240_json: str) -> None:
    """Why max_value stays null in the quality rules."""
    values = list(slice_of(cepalstat_debt_1240_json).values())

    assert max(values) == Decimal("222.1")
    assert min(values) == Decimal("14")


MILLIONS = Decimal("1000000")


def build_connector() -> CepalstatDebtConnector:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    return CepalstatDebtConnector(catalog.get("cepalstat_debt_annual"))


def build_raw(payload: dict[int, str]) -> RawDataset:
    return RawDataset(
        source_key="cepalstat_debt_annual",
        retrieved_at=datetime(2026, 9, 3, 12, 0, tzinfo=UTC),
        source_url="https://api-cepalstat.cepal.org/cepalstat/api/v1",
        payload=payload,
        content_type="application/json",
        http_status=200,
    )


@pytest.fixture
def raw(cepalstat_debt_1239_json: str, cepalstat_debt_1240_json: str) -> RawDataset:
    return build_raw({1239: cepalstat_debt_1239_json, 1240: cepalstat_debt_1240_json})


def by_code(observations: list[NormalizedObservation]) -> dict[str, list[NormalizedObservation]]:
    out: dict[str, list[NormalizedObservation]] = {}
    for obs in observations:
        out.setdefault(obs.indicator_code, []).append(obs)
    return out


def test_transform_produces_every_stored_cell(raw: RawDataset) -> None:
    grouped = by_code(build_connector().transform(raw))

    assert len(grouped["public_debt_usd_annual"]) == 226
    assert len(grouped["public_debt_pct_gdp_annual"]) == 230


def test_only_central_government_totals_survive(raw: RawDataset) -> None:
    """The other eleven non-empty combinations are discarded."""
    observations = build_connector().transform(raw)
    usd = {
        (obs.country_iso3, obs.period.label)
        for obs in observations
        if obs.indicator_code == "public_debt_usd_annual"
    }

    assert ("NIC", "1990") in usd
    assert ("BLZ", "2020") in usd
    assert ("BLZ", "2021") not in usd
    assert len(usd) == 226


def test_only_the_seven_countries_survive(raw: RawDataset) -> None:
    """Mexico and the regional aggregates with iso3 null both fall out."""
    observations = build_connector().transform(raw)

    assert {obs.country_iso3 for obs in observations} == CENTRAL_AMERICA


def test_the_published_millions_are_scaled_to_whole_usd(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)
    costa_rica = next(
        obs
        for obs in observations
        if obs.indicator_code == "public_debt_usd_annual"
        and obs.country_iso3 == "CRI"
        and obs.period.label == "2025"
    )

    assert costa_rica.value_numeric == Decimal("62777") * MILLIONS
    assert costa_rica.unit == "current USD"
    assert costa_rica.currency_code == "USD"
    assert costa_rica.raw_metadata["cepalstat_scale_applied"] == "1e6"


def test_the_ratio_is_stored_exactly_as_published(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)
    costa_rica = next(
        obs
        for obs in observations
        if obs.indicator_code == "public_debt_pct_gdp_annual"
        and obs.country_iso3 == "CRI"
        and obs.period.label == "2025"
    )

    assert costa_rica.value_numeric == Decimal("60.4")
    assert costa_rica.unit == "percent of GDP"
    assert costa_rica.currency_code is None
    assert costa_rica.raw_metadata["cepalstat_scale_applied"] == "1"


def test_periods_are_calendar_years(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)
    sample = next(obs for obs in observations if obs.period.label == "2024")

    assert sample.period.frequency is Frequency.ANNUAL
    assert sample.period.start.isoformat() == "2024-01-01"
    assert sample.period.end.isoformat() == "2024-12-31"


def test_source_record_ids_are_unique_and_readable(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)
    ids = [obs.source_record_id for obs in observations]

    assert len(set(ids)) == len(ids) == 456
    assert "cepalstat:1239:CRI:2025" in ids


def test_the_fetch_date_never_reaches_stored_metadata(raw: RawDataset) -> None:
    """credits[0] moves between runs; only the citation is kept."""
    observations = build_connector().transform(raw)
    credits = observations[0].raw_metadata["cepalstat_credits"]

    assert "CEPALSTAT" in credits
    assert not any(credit.startswith("202") for credit in credits)


def test_a_renamed_coverage_member_raises(raw: RawDataset) -> None:
    """Selecting by id is silent on a relabel; the assertion is not."""
    document = json.loads(raw.payload[1239])
    for dimension in document["body"]["dimensions"]:
        if dimension["id"] == INSTITUTIONAL_COVERAGE:
            for member in dimension["members"]:
                if member["id"] == CENTRAL_GOVERNMENT:
                    member["name"] = "General government"

    doctored = build_raw({1239: json.dumps(document), 1240: raw.payload[1240]})

    with pytest.raises(TransformationError, match="General government"):
        build_connector().transform(doctored)


def test_a_renamed_classification_member_raises(raw: RawDataset) -> None:
    document = json.loads(raw.payload[1239])
    for dimension in document["body"]["dimensions"]:
        if dimension["id"] == DEBT_CLASSIFICATION:
            for member in dimension["members"]:
                if member["id"] == TOTAL_BY_RESIDENCE:
                    member["name"] = "Total public debt"

    doctored = build_raw({1239: json.dumps(document), 1240: raw.payload[1240]})

    with pytest.raises(TransformationError, match="Total public debt"):
        build_connector().transform(doctored)


def test_a_missing_coverage_dimension_raises(raw: RawDataset) -> None:
    document = json.loads(raw.payload[1239])
    document["body"]["dimensions"] = [
        d for d in document["body"]["dimensions"] if d["id"] != INSTITUTIONAL_COVERAGE
    ]

    doctored = build_raw({1239: json.dumps(document), 1240: raw.payload[1240]})

    with pytest.raises(TransformationError, match="institutional coverage dimension"):
        build_connector().transform(doctored)


def results_of(observations: list[NormalizedObservation]) -> dict[str, QualityResult]:
    return {r.check_name: r for r in build_connector().validate(observations)}


def test_both_checks_pass_on_the_real_recordings(raw: RawDataset) -> None:
    results = build_connector().validate(build_connector().transform(raw))

    assert len(results) == 2
    assert all(result.status is CheckStatus.PASSED for result in results)


def test_a_missing_country_fails_critically(raw: RawDataset) -> None:
    observations = [obs for obs in build_connector().transform(raw) if obs.country_iso3 != "BLZ"]

    result = results_of(observations)["cepalstat_debt_seven_countries"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.CRITICAL
    assert "BLZ" in result.message


def test_a_hole_in_one_country_is_reported_as_a_warning(raw: RawDataset) -> None:
    """Pooling the seven would hide it: the others published that year."""
    observations = [
        obs
        for obs in build_connector().transform(raw)
        if not (
            obs.indicator_code == "public_debt_usd_annual"
            and obs.country_iso3 == "GTM"
            and obs.period.label == "2010"
        )
    ]

    result = results_of(observations)["cepalstat_debt_annual_continuity"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.WARNING
    assert "GTM 2010" in result.message


def test_a_shorter_span_is_not_itself_a_gap(raw: RawDataset) -> None:
    """Belize starts in 2011 and ends in 2020; neither is a hole."""
    result = results_of(build_connector().transform(raw))["cepalstat_debt_annual_continuity"]

    assert result.status is CheckStatus.PASSED


def test_every_check_is_dataset_level(raw: RawDataset) -> None:
    results = build_connector().validate(build_connector().transform(raw))

    assert all(result.observation_index is None for result in results)
