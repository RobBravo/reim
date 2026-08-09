"""Comparability rules. No database, no network — pure logic."""

from __future__ import annotations

from reim.repositories.comparison import SeriesSummary
from reim.schemas.comparison import assess_comparability


def summary(
    iso3: str,
    *,
    units: tuple[str, ...] = ("current USD",),
    currencies: tuple[str | None, ...] = ("USD",),
    sources: tuple[str, ...] = ("imf_imts_nicaragua",),
    observations: int = 10,
) -> SeriesSummary:
    return SeriesSummary(
        country_iso2=iso3[:2],
        country_iso3=iso3,
        country_name=iso3,
        units=units,
        currency_codes=currencies,
        source_keys=sources,
        observations=observations,
        first_period="2024-01" if observations else None,
        last_period="2024-10" if observations else None,
    )


def test_identical_series_are_comparable() -> None:
    comparable, notes = assess_comparability([summary("NIC"), summary("GTM")])

    assert comparable is True
    assert notes == []


def test_differing_units_are_not_comparable() -> None:
    comparable, notes = assess_comparability(
        [summary("NIC"), summary("GTM", units=("quetzales",), currencies=("GTQ",))]
    )

    assert comparable is False
    assert any("nit" in note.lower() for note in notes)
    assert any("quetzales" in note for note in notes)


def test_differing_sources_are_noted_but_still_comparable() -> None:
    """Two publishers measuring the same thing in the same unit is normal."""
    comparable, notes = assess_comparability(
        [summary("NIC"), summary("GTM", sources=("banguat_trade",))]
    )

    assert comparable is True
    assert any("ource" in note for note in notes)


def test_a_country_with_no_data_is_named() -> None:
    _, notes = assess_comparability([summary("NIC"), summary("GTM", observations=0)])

    assert any("GTM" in note and "No observations" in note for note in notes)


def test_an_empty_country_does_not_by_itself_break_comparability() -> None:
    """Having no data is a gap to report, not a unit mismatch."""
    comparable, _ = assess_comparability(
        [summary("NIC"), summary("GTM", observations=0, units=(), currencies=())]
    )

    assert comparable is True


def test_one_country_carrying_two_units_is_not_comparable() -> None:
    comparable, notes = assess_comparability(
        [summary("NIC", units=("current USD", "quetzales")), summary("GTM")]
    )

    assert comparable is False
    assert any("NIC" in note for note in notes)
