"""Unit tests for the SIECA quarterly services-trade connector.

Every payload replayed here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

import json
from decimal import Decimal

#: What the recorded responses hold, measured on 2026-08-09.
QUARTERS = 69
COUNTRIES = 6
CELLS_PER_FLOW = 414


def cells_of(payload: str) -> dict[tuple[str, str], Decimal | None]:
    """Flatten one LoadData payload into ``(country, quarter label) -> value``."""
    block = json.loads(payload, parse_float=Decimal)["Data"][0]
    rows = json.loads(block["Data"], parse_float=Decimal)
    columns = [c["data"] for c in block["Columnas"]][4:]
    return {(row["Pais"], column): row[column] for row in rows for column in columns}


def test_the_filters_fixture_holds_every_quarter(sieca_filters_json: str) -> None:
    filters = json.loads(sieca_filters_json)

    assert len(filters["Periodo"]) == QUARTERS
    labels = {f"{p['Trimestre']} {p['Anio']}" for p in filters["Periodo"]}
    assert "I Trim 2009" in labels
    assert "I Trim 2026" in labels


def test_the_filters_fixture_lists_the_six_countries_and_the_aggregate(
    sieca_filters_json: str,
) -> None:
    names = {p["Nombre"] for p in json.loads(sieca_filters_json)["Pais"]}

    assert names == {
        "Centroamérica",
        "Costa Rica",
        "El Salvador",
        "Guatemala",
        "Honduras",
        "Nicaragua",
        "Panamá",
    }


def test_each_flow_fixture_is_complete(
    sieca_exports_json: str, sieca_imports_json: str, sieca_balance_json: str
) -> None:
    """Zero nulls. A re-recording that introduces holes must fail here."""
    for payload in (sieca_exports_json, sieca_imports_json, sieca_balance_json):
        cells = cells_of(payload)
        assert len(cells) == CELLS_PER_FLOW
        assert sum(1 for v in cells.values() if v is None) == 0


def test_the_fixtures_keep_their_exact_published_digits(sieca_exports_json: str) -> None:
    """parse_float=Decimal, not float: 1131.7 must not become 1131.6999999999998."""
    cells = cells_of(sieca_exports_json)

    assert cells[("Costa Rica", "I Trim 2009")] == Decimal("1131.7")
    assert cells[("Costa Rica", "I Trim 2026")] == Decimal("4941.8")
