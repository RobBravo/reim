"""Everything the series page computes without a session.

Nothing here touches a database, a request or a template, which is what makes
it testable directly rather than through a rendered page. Two
responsibilities, both pure: shaping the repository's flat cells into rows,
and the geometry that turns rows into an SVG.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from reim.repositories.comparison import ComparisonCell


@dataclass(frozen=True, slots=True)
class SeriesRow:
    """Every requested country's figure for one period.

    ``values`` holds a key for **every** requested country, ``None`` where
    that country published nothing. A missing key would make a gap
    indistinguishable from a country that was never asked for — the same
    promise ``/compare`` makes in JSON.
    """

    period_start: date
    period_label: str
    values: dict[str, Decimal | None]


def pivot_cells(cells: Iterable[ComparisonCell], iso3_order: Sequence[str]) -> list[SeriesRow]:
    """Turn the repository's flat cells into one row per period, oldest first.

    Oldest first because a time axis reads left to right, and sorting here
    means no caller has to remember to.
    """
    by_period: dict[date, SeriesRow] = {}
    for cell in cells:
        row = by_period.get(cell.period_start)
        if row is None:
            row = SeriesRow(
                period_start=cell.period_start,
                period_label=cell.period_label,
                values=dict.fromkeys(iso3_order),
            )
            by_period[cell.period_start] = row
        if cell.country_iso3 in row.values:
            row.values[cell.country_iso3] = cell.value_numeric
    return [by_period[key] for key in sorted(by_period)]


def value_domain(
    rows: Sequence[SeriesRow], iso3_codes: Sequence[str]
) -> tuple[float, float] | None:
    """Return the lowest and highest value among ``iso3_codes``, or ``None``.

    ``None`` when those countries published nothing at all: there is no range
    to scale, and inventing ``(0, 1)`` would draw an axis describing data that
    does not exist.

    Restricted to the countries being drawn, because a small-multiple panel
    scales on its own country — sharing one domain across panels would
    reintroduce exactly the cross-country comparison small multiples exist to
    prevent.
    """
    values = [
        float(value)
        for row in rows
        for code in iso3_codes
        if (value := row.values.get(code)) is not None
    ]
    if not values:
        return None
    return min(values), max(values)


@dataclass(frozen=True, slots=True)
class Scale:
    """Maps a value in the data's domain onto a pixel coordinate.

    ``pixel_min`` may be greater than ``pixel_max``: SVG's y axis grows
    downward, so the value axis is built inverted and the same arithmetic
    serves both.
    """

    domain_min: float
    domain_max: float
    pixel_min: float
    pixel_max: float

    def to_pixel(self, value: float) -> float:
        """Return the pixel coordinate for ``value``.

        A zero-width domain — a series that never changes — puts every point
        at the midpoint rather than dividing by zero. A flat line through the
        middle is the honest picture of a constant series.
        """
        span = self.domain_max - self.domain_min
        if span == 0:
            return (self.pixel_min + self.pixel_max) / 2
        ratio = (value - self.domain_min) / span
        return self.pixel_min + ratio * (self.pixel_max - self.pixel_min)


#: Step sizes a reader recognises as round, in units of the step's magnitude.
_NICE_MULTIPLES = (1.0, 2.0, 2.5, 5.0, 10.0)


def nice_ticks(minimum: float, maximum: float, count: int = 5) -> list[float]:
    """Return round tick values inside ``[minimum, maximum]``.

    Ticks stay strictly within the domain rather than extending past it: an
    axis labelled beyond the data invites the reader to believe the series
    reaches values it never does.

    A constant series returns the single value. There is no range to divide,
    and the reader still needs the number.
    """
    if count < 1:
        msg = f"count must be at least 1, got {count}"
        raise ValueError(msg)
    if minimum > maximum:
        minimum, maximum = maximum, minimum
    if minimum == maximum:
        return [minimum]

    raw_step = (maximum - minimum) / count
    magnitude = 10.0 ** math.floor(math.log10(raw_step))
    step = next(
        (multiple * magnitude for multiple in _NICE_MULTIPLES if raw_step <= multiple * magnitude),
        10.0 * magnitude,
    )
    first = math.ceil(minimum / step) * step
    # The 1e-9 epsilon guards against a float floor landing exactly on the
    # domain boundary and silently dropping the final tick; it is far below
    # any real step size.
    total = math.floor((maximum - first) / step + 1e-9) + 1
    return [round(first + index * step, 10) for index in range(max(total, 0))]


@dataclass(frozen=True, slots=True)
class Chart:
    """The geometry of one plotted panel, ready for a template to render."""

    paths: dict[str, str]
    ticks: list[float]
    x_positions: list[float]
    width: int
    height: int
    plot_left: float
    plot_right: float
    plot_top: float
    plot_bottom: float
    domain_min: float
    domain_max: float


#: Room for the value labels on the left and the period labels underneath.
_MARGIN_LEFT = 64.0
_MARGIN_RIGHT = 12.0
_MARGIN_TOP = 12.0
_MARGIN_BOTTOM = 32.0


#: Colours assigned by a country's position in the request, not its identity —
#: comparing NIC and GTM colours NIC first regardless of the registry's own
#: order. Luminance rises monotonically down the tuple (near-black to amber)
#: so the seven are still distinguishable printed in greyscale, not only in
#: colour.
CHART_PALETTE: tuple[str, ...] = (
    "#1a1a1a",
    "#1f4b99",
    "#b23c17",
    "#1b7a3d",
    "#0f7d8c",
    "#9c2f6b",
    "#c98a11",
)


def build_chart(
    rows: Sequence[SeriesRow],
    iso3_codes: Sequence[str],
    *,
    width: int = 760,
    height: int = 320,
) -> Chart | None:
    """Return the geometry for one panel, or ``None`` when there is nothing to draw.

    ``None`` rather than an empty axis: a chart drawn around no values tells
    the reader a series exists and is flat, when in fact it is absent.

    Periods are placed by their **index**, not by their date. The series is a
    sequence of published periods, and spacing them by calendar distance would
    imply REIM knows what happened in the intervals — which, for a publisher
    that skipped a quarter, it does not.
    """
    domain = value_domain(rows, iso3_codes)
    if domain is None or not rows:
        return None
    domain_min, domain_max = domain

    plot_left, plot_right = _MARGIN_LEFT, float(width) - _MARGIN_RIGHT
    plot_top, plot_bottom = _MARGIN_TOP, float(height) - _MARGIN_BOTTOM

    last_index = float(max(len(rows) - 1, 1))
    x_scale = Scale(0.0, last_index, plot_left, plot_right)
    y_scale = Scale(domain_min, domain_max, plot_bottom, plot_top)

    paths = {
        code: series_path(
            [
                (float(index), None if (value := row.values.get(code)) is None else float(value))
                for index, row in enumerate(rows)
            ],
            x_scale,
            y_scale,
        )
        for code in iso3_codes
    }
    return Chart(
        paths={code: path for code, path in paths.items() if path},
        ticks=nice_ticks(domain_min, domain_max),
        x_positions=[round(x_scale.to_pixel(float(index)), 2) for index in range(len(rows))],
        width=width,
        height=height,
        plot_left=plot_left,
        plot_right=plot_right,
        plot_top=plot_top,
        plot_bottom=plot_bottom,
        domain_min=domain_min,
        domain_max=domain_max,
    )


def series_path(
    points: Sequence[tuple[float, float | None]], x_scale: Scale, y_scale: Scale
) -> str:
    """Return the SVG ``d`` for one series, breaking the line at every gap.

    A ``None`` value is a period the publisher did not report. The stroke
    stops and restarts rather than joining its neighbours across it: a segment
    drawn over a gap invents a value REIM does not have, and to the eye it is
    indistinguishable from data. Not filling gaps is the project's oldest
    promise; here it is a drawing rule.
    """
    commands: list[str] = []
    pen_is_down = False
    for x_value, y_value in points:
        if y_value is None:
            pen_is_down = False
            continue
        x_pixel = round(x_scale.to_pixel(x_value), 2)
        y_pixel = round(y_scale.to_pixel(y_value), 2)
        commands.append(f"{'L' if pen_is_down else 'M'} {x_pixel} {y_pixel}")
        pen_is_down = True
    return " ".join(commands)
