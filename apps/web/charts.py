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
