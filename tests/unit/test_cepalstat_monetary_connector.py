"""Unit tests for the CEPALSTAT monthly monetary-aggregates connector.

Every payload replayed here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

PERIOD_DIMENSION = 3981
COUNTRY_DIMENSION = 208
YEARS_DIMENSION = 29117
CENTRAL_AMERICA = frozenset({"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"})

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
    """Zero gaps in all 21 country-indicator series, measured 2026-08-19."""
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
