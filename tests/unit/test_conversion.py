"""Conversion rules. No database, no network — pure logic."""

from __future__ import annotations

from decimal import Decimal

import pytest

from reim.core.exceptions import InvalidRequestError
from reim.domain.conversion import (
    ConvertedCell,
    convert,
    ensure_convertible,
    summarise,
)
from reim.domain.indicators.registry import INDICATORS_BY_CODE


def pair(
    value: Decimal | None, currency: str | None, rate: Decimal | None
) -> tuple[Decimal | None, ConvertedCell]:
    """A published value and what converting it produced — what summarise takes."""
    return (value, convert(value, currency, rate))


def test_a_figure_already_in_dollars_passes_through_untouched() -> None:
    """The regression test for the ninefold error.

    El Salvador's M1 carries `USD` while CEPAL still quotes the country at 8.8
    colones per dollar. Converting on the country rather than the observation
    would divide an already-dollar figure by 8.8 and look plausible doing it.
    """
    cell = convert(Decimal("9482300000"), "USD", Decimal("8.8"))

    assert cell == ConvertedCell(value=Decimal("9482300000"), rate=None, basis=None)


def test_a_local_currency_figure_is_divided_by_its_rate() -> None:
    cell = convert(Decimal("119875800000"), "NIO", Decimal("36.8"))

    assert cell.value == Decimal("3257494565.22")
    assert cell.rate == Decimal("36.8")
    assert cell.basis == "monthly average"


def test_a_missing_rate_yields_null_rather_than_a_guess() -> None:
    """D7: no nearest rate, no carry-forward."""
    cell = convert(Decimal("100"), "BZD", None)

    assert cell == ConvertedCell(value=None, rate=None, basis=None)


def test_an_observation_with_no_currency_is_not_converted() -> None:
    """Guessing from the country would be D3's bug wearing a different hat."""
    cell = convert(Decimal("100"), None, Decimal("2"))

    assert cell == ConvertedCell(value=None, rate=None, basis=None)


def test_a_cell_with_no_published_value_short_circuits() -> None:
    cell = convert(None, "NIO", Decimal("36.8"))

    assert cell == ConvertedCell(value=None, rate=None, basis=None)


def test_a_zero_rate_does_not_raise() -> None:
    """A published zero would be nonsense, but it must not become a crash."""
    cell = convert(Decimal("100"), "NIO", Decimal("0"))

    assert cell == ConvertedCell(value=None, rate=None, basis=None)


def test_the_summary_counts_the_three_outcomes_separately() -> None:
    cells = [
        pair(Decimal("100"), "NIO", Decimal("36.8")),
        pair(Decimal("200"), "USD", None),
        pair(Decimal("300"), "BZD", None),
    ]

    summary = summarise(cells, "cepalstat_exchange_rate_monthly")

    assert (summary.converted, summary.already_at_target, summary.no_rate) == (1, 1, 1)
    assert summary.rate_source_key == "cepalstat_exchange_rate_monthly"
    assert summary.basis == "monthly average"
    assert summary.target_currency == "USD"


def test_a_cell_with_no_published_value_is_counted_in_nothing() -> None:
    """/compare is rectangular, so most cells in a wide comparison are holes in
    the published data. Counting them as 'no rate' would blame the rate series
    for the publisher's gap."""
    summary = summarise([pair(None, "NIO", Decimal("36.8"))], "s")

    assert (summary.converted, summary.already_at_target, summary.no_rate) == (0, 0, 0)


def test_the_summary_always_states_both_caveats() -> None:
    summary = summarise([], None)

    assert len(summary.caveats) == 2
    assert any("indicative" in c for c in summary.caveats)
    assert any("one decimal" in c for c in summary.caveats)


def test_a_convertible_indicator_is_accepted() -> None:
    ensure_convertible(INDICATORS_BY_CODE["money_m1_monthly"])


@pytest.mark.parametrize(
    "code", ["ni_exchange_rate_official_daily", "exchange_rate_nominal_monthly"]
)
def test_a_rate_indicator_is_refused_by_name(code: str) -> None:
    with pytest.raises(InvalidRequestError) as caught:
        ensure_convertible(INDICATORS_BY_CODE[code])

    assert caught.value.http_status == 400
    assert code in str(caught.value)
