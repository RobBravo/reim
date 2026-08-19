"""Unit tests for the CEPALSTAT annual GDP connector.

Every payload replayed here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

import json
from decimal import Decimal

#: What the recorded responses hold, measured on 2026-08-18.
YEARS_DIMENSION = 29117
COUNTRY_DIMENSION = 208
CENTRAL_AMERICA = frozenset({"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"})
CELLS_PER_INDICATOR = 252


def cells_of(payload: str) -> dict[tuple[str, str], Decimal]:
    """Flatten one response into ``(iso3, year label) -> value`` for the seven."""
    body = json.loads(payload, parse_float=Decimal)["body"]
    years = next(d for d in body["dimensions"] if d["id"] == YEARS_DIMENSION)
    labels = {member["id"]: member["name"] for member in years["members"]}
    return {
        (row["iso3"], labels[row[f"dim_{YEARS_DIMENSION}"]]): Decimal(str(row["value"]))
        for row in body["data"]
        if row.get("iso3") in CENTRAL_AMERICA
    }


def test_each_fixture_covers_the_seven_countries_completely(
    cepalstat_gdp_2203_json: str,
    cepalstat_gdp_2204_json: str,
    cepalstat_gdp_2205_json: str,
    cepalstat_gdp_2206_json: str,
) -> None:
    """252 cells, 36 years each, no holes. A re-recording with gaps fails here."""
    for payload in (
        cepalstat_gdp_2203_json,
        cepalstat_gdp_2204_json,
        cepalstat_gdp_2205_json,
        cepalstat_gdp_2206_json,
    ):
        cells = cells_of(payload)
        assert len(cells) == CELLS_PER_INDICATOR
        assert {iso3 for iso3, _ in cells} == CENTRAL_AMERICA
        for iso3 in CENTRAL_AMERICA:
            assert sum(1 for c, _ in cells if c == iso3) == 36


#: 33 countries + 3 regional aggregates ("Caribbean", "Latin America", and
#: "Latin America and the Caribbean"), counted directly from a complete
#: recording of indicator 2203 on 2026-08-18 (`in == 1` members of the
#: country dimension, id 208).
INCLUDED_COUNTRY_DIMENSION_MEMBERS = 36


def test_the_fixtures_hold_the_other_countries_and_the_aggregates(
    cepalstat_gdp_2203_json: str,
    cepalstat_gdp_2204_json: str,
    cepalstat_gdp_2205_json: str,
    cepalstat_gdp_2206_json: str,
) -> None:
    """Not trimmed to seven: the filter has to have something to filter.

    Checked on all four fixtures independently — a re-recording of just one
    of 2204, 2205 or 2206 trimmed to the seven would otherwise pass unnoticed,
    since `test_each_fixture_covers_the_seven_countries_completely` pre-filters
    to Central America and cannot see whether the other countries survived.
    """
    for payload in (
        cepalstat_gdp_2203_json,
        cepalstat_gdp_2204_json,
        cepalstat_gdp_2205_json,
        cepalstat_gdp_2206_json,
    ):
        body = json.loads(payload)["body"]
        countries = next(d for d in body["dimensions"] if d["id"] == COUNTRY_DIMENSION)
        included = [m["name"] for m in countries["members"] if m["in"] == 1]

        assert len(included) == INCLUDED_COUNTRY_DIMENSION_MEMBERS
        assert "Mexico" in included
        assert "Brazil" in included
        assert "Latin America" in included
        assert any(row.get("iso3") is None for row in body["data"])


def test_the_fixtures_keep_their_exact_published_digits(
    cepalstat_gdp_2203_json: str, cepalstat_gdp_2206_json: str
) -> None:
    """parse_float=Decimal, not float, all the way through."""
    assert cells_of(cepalstat_gdp_2203_json)[("NIC", "2024")] == Decimal("19696.31184918235")
    assert cells_of(cepalstat_gdp_2206_json)[("NIC", "2024")] == Decimal("2142.334639853647")
    assert cells_of(cepalstat_gdp_2203_json)[("BLZ", "1990")] == Decimal("546.75091228848")


def test_the_constant_price_fixtures_carry_the_base_year_footnote(
    cepalstat_gdp_2204_json: str, cepalstat_gdp_2206_json: str, cepalstat_gdp_2203_json: str
) -> None:
    """The base year is in a footnote, not the unit. That is why it is checked."""
    for payload in (cepalstat_gdp_2204_json, cepalstat_gdp_2206_json):
        footnotes = json.loads(payload)["body"]["footnotes"]
        assert [f["description"] for f in footnotes] == ["At prices 2018"]

    assert json.loads(cepalstat_gdp_2203_json)["body"]["footnotes"] == []
