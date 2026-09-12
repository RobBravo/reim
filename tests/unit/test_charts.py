"""``apps/web/charts.py``: everything the series page computes without a session.

Axis ticks, scales and path building are where chart bugs actually live —
ticks at 0.0000001 intervals, a division by zero on a constant series, a line
drawn straight across a gap the publisher never filled. None of it needs a
database, a request or a template, so all of it is tested directly here
rather than inferred from a rendered page.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.web.charts import (
    Chart,
    Scale,
    SeriesRow,
    build_chart,
    nice_ticks,
    pivot_cells,
    series_path,
    value_domain,
)
from reim.repositories.comparison import ComparisonCell


def _cell(iso3: str, year: int, value: str | None) -> ComparisonCell:
    return ComparisonCell(
        period_start=date(year, 1, 1),
        period_end=date(year, 12, 31),
        period_label=str(year),
        country_iso3=iso3,
        value_numeric=None if value is None else Decimal(value),
        currency_code=None,
    )


def test_pivot_gives_every_country_a_key_in_every_row() -> None:
    """A gap is stated, never implied by a missing key.

    ``/compare`` makes the same promise in JSON; the page must not quietly
    reintroduce the ambiguity by leaving a country out of a row.
    """
    cells = [_cell("NIC", 2020, "1"), _cell("GTM", 2020, "2"), _cell("NIC", 2021, "3")]

    rows = pivot_cells(cells, ["NIC", "GTM"])

    assert [row.period_label for row in rows] == ["2020", "2021"]
    assert rows[0].values == {"NIC": Decimal("1"), "GTM": Decimal("2")}
    assert rows[1].values == {"NIC": Decimal("3"), "GTM": None}


def test_pivot_orders_rows_oldest_first() -> None:
    """A time axis reads left to right; the caller must not have to sort."""
    rows = pivot_cells([_cell("NIC", 2022, "1"), _cell("NIC", 2020, "2")], ["NIC"])

    assert [row.period_label for row in rows] == ["2020", "2022"]


def test_pivot_of_nothing_is_no_rows() -> None:
    assert pivot_cells([], ["NIC"]) == []


def test_the_domain_spans_every_country_shown() -> None:
    rows = [
        SeriesRow(date(2020, 1, 1), "2020", {"NIC": Decimal("5"), "GTM": Decimal("-2")}),
        SeriesRow(date(2021, 1, 1), "2021", {"NIC": Decimal("9"), "GTM": None}),
    ]

    assert value_domain(rows, ["NIC", "GTM"]) == (-2.0, 9.0)


def test_the_domain_ignores_countries_not_being_shown() -> None:
    """Small multiples scale each panel on its own country, not on all of them."""
    rows = [SeriesRow(date(2020, 1, 1), "2020", {"NIC": Decimal("5"), "GTM": Decimal("900")})]

    assert value_domain(rows, ["NIC"]) == (5.0, 5.0)


def test_a_series_with_no_values_has_no_domain() -> None:
    """``None`` rather than a fabricated ``(0, 1)``: there is nothing to scale."""
    rows = [SeriesRow(date(2020, 1, 1), "2020", {"NIC": None})]

    assert value_domain(rows, ["NIC"]) is None


def test_a_scale_maps_the_domain_onto_the_pixels() -> None:
    scale = Scale(domain_min=0.0, domain_max=10.0, pixel_min=0.0, pixel_max=100.0)

    assert scale.to_pixel(0.0) == 0.0
    assert scale.to_pixel(5.0) == 50.0
    assert scale.to_pixel(10.0) == 100.0


def test_a_scale_inverts_when_the_pixels_run_backwards() -> None:
    """SVG's y axis grows downward, so the value axis is built inverted."""
    scale = Scale(domain_min=0.0, domain_max=10.0, pixel_min=200.0, pixel_max=0.0)

    assert scale.to_pixel(0.0) == 200.0
    assert scale.to_pixel(10.0) == 0.0


def test_a_constant_series_lands_in_the_middle_rather_than_dividing_by_zero() -> None:
    scale = Scale(domain_min=7.0, domain_max=7.0, pixel_min=0.0, pixel_max=100.0)

    assert scale.to_pixel(7.0) == 50.0


@pytest.mark.parametrize(
    ("minimum", "maximum", "expected"),
    [
        (0.0, 100.0, [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]),
        (0.0, 1.0, [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]),
        (-5.0, 5.0, [-4.0, -2.0, 0.0, 2.0, 4.0]),
        (0.001, 0.005, [0.001, 0.002, 0.003, 0.004, 0.005]),
        (
            1_000_000.0,
            3_000_000.0,
            [1_000_000.0, 1_500_000.0, 2_000_000.0, 2_500_000.0, 3_000_000.0],
        ),
    ],
)
def test_ticks_are_round_numbers_at_every_magnitude(
    minimum: float, maximum: float, expected: list[float]
) -> None:
    assert nice_ticks(minimum, maximum) == expected


def test_a_constant_series_gets_one_tick_saying_what_the_value_is() -> None:
    """There is no range to divide, but the reader still needs the number."""
    assert nice_ticks(42.0, 42.0) == [42.0]


def test_ticks_never_run_outside_the_domain() -> None:
    ticks = nice_ticks(3.3, 7.7)

    assert ticks
    assert min(ticks) >= 3.3
    assert max(ticks) <= 7.7


def test_a_reversed_domain_is_read_the_right_way_round() -> None:
    assert nice_ticks(100.0, 0.0) == nice_ticks(0.0, 100.0)


def test_a_path_of_nothing_is_empty() -> None:
    scale = Scale(0.0, 1.0, 0.0, 1.0)

    assert series_path([], scale, scale) == ""


def test_a_gap_breaks_the_line_instead_of_being_bridged() -> None:
    """The whole reason this function exists.

    REIM never fills a gap. Joining the points either side of a missing
    period would draw a value the publisher never reported — indistinguishable,
    to the eye, from data.
    """
    x_scale = Scale(domain_min=0.0, domain_max=2.0, pixel_min=0.0, pixel_max=200.0)
    y_scale = Scale(domain_min=0.0, domain_max=10.0, pixel_min=100.0, pixel_max=0.0)

    path = series_path([(0.0, 1.0), (1.0, None), (2.0, 3.0)], x_scale, y_scale)

    assert path.count("M") == 2, f"the gap did not break the line: {path}"
    assert path.count("L") == 0


def test_a_run_of_values_is_one_stroke() -> None:
    x_scale = Scale(0.0, 2.0, 0.0, 200.0)
    y_scale = Scale(0.0, 10.0, 100.0, 0.0)

    path = series_path([(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)], x_scale, y_scale)

    assert path.count("M") == 1
    assert path.count("L") == 2


def test_a_series_that_is_entirely_gaps_draws_nothing() -> None:
    scale = Scale(0.0, 1.0, 0.0, 1.0)

    assert series_path([(0.0, None), (1.0, None)], scale, scale) == ""


def test_a_chart_has_one_path_per_country_with_values() -> None:
    rows = [
        SeriesRow(date(2020, 1, 1), "2020", {"NIC": Decimal("1"), "GTM": Decimal("2")}),
        SeriesRow(date(2021, 1, 1), "2021", {"NIC": Decimal("3"), "GTM": Decimal("4")}),
    ]

    chart: Chart | None = build_chart(rows, ["NIC", "GTM"])

    assert chart is not None
    assert set(chart.paths) == {"NIC", "GTM"}
    assert chart.paths["NIC"].startswith("M")


def test_a_chart_of_gaps_only_is_no_chart() -> None:
    """``None`` rather than an axis around nothing."""
    rows = [SeriesRow(date(2020, 1, 1), "2020", {"NIC": None})]

    assert build_chart(rows, ["NIC"]) is None


def test_a_single_period_still_draws_its_point() -> None:
    """One observation is data; an empty chart would say it is not."""
    rows = [SeriesRow(date(2020, 1, 1), "2020", {"NIC": Decimal("4")})]

    chart: Chart | None = build_chart(rows, ["NIC"])

    assert chart is not None
    assert chart.paths["NIC"].count("M") == 1
