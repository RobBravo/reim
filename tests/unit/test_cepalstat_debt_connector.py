"""Unit tests for the CEPALSTAT public debt connector.

Every payload replayed here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

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
