"""Normalization of economic reporting periods.

REIM stores a period as a closed date interval ``[start, end]`` plus the label
the source used. This preserves the original economic meaning: an annual figure
for 2024 covers ``2024-01-01 .. 2024-12-31`` and is *not* silently converted
into a single calendar date.

Supported label forms:

===============  ==========  ==========================================
Label            Frequency   Interval
===============  ==========  ==========================================
``2024``         annual      2024-01-01 .. 2024-12-31
``2024-H1``      semiannual  2024-01-01 .. 2024-06-30
``2024-Q3``      quarterly   2024-07-01 .. 2024-09-30
``2024-07``      monthly     2024-07-01 .. 2024-07-31
``2024-W27``     weekly      ISO week, Monday .. Sunday
``2024-07-15``   daily       2024-07-15 .. 2024-07-15
===============  ==========  ==========================================
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

from reim.core.constants import Frequency
from reim.core.exceptions import InvalidPeriodError

_ANNUAL = re.compile(r"^(?P<year>\d{4})$")
_SEMIANNUAL = re.compile(r"^(?P<year>\d{4})-?[Hh](?P<half>[12])$")
_QUARTERLY = re.compile(r"^(?P<year>\d{4})-?[Qq](?P<quarter>[1-4])$")
_MONTHLY = re.compile(r"^(?P<year>\d{4})-(?P<month>0[1-9]|1[0-2])$")
_WEEKLY = re.compile(r"^(?P<year>\d{4})-?[Ww](?P<week>\d{1,2})$")
_DAILY = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})$")

MIN_YEAR = 1900
MAX_YEAR = 2200


@dataclass(frozen=True, slots=True)
class Period:
    """A normalized reporting period."""

    start: date
    end: date
    label: str
    frequency: Frequency

    def __post_init__(self) -> None:
        """Reject an interval whose end precedes its start."""
        if self.end < self.start:
            msg = f"Period end {self.end} precedes start {self.start}"
            raise InvalidPeriodError(msg, label=self.label)

    @property
    def days(self) -> int:
        """Inclusive length of the period in days."""
        return (self.end - self.start).days + 1


def _check_year(year: int, label: str) -> None:
    if not MIN_YEAR <= year <= MAX_YEAR:
        msg = f"Year {year} outside supported range {MIN_YEAR}-{MAX_YEAR}"
        raise InvalidPeriodError(msg, label=label)


def _end_of_month(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def parse_period(label: str, frequency: Frequency | None = None) -> Period:
    """Parse a period label into a :class:`Period`.

    Args:
        label: The label as published by the source, e.g. ``"2024-Q3"``.
        frequency: Expected frequency. When given, a mismatch with the parsed
            label is an error — this catches sources that silently change
            granularity.

    Raises:
        InvalidPeriodError: If the label is unrecognised, out of range, or its
            implied frequency contradicts ``frequency``.
    """
    raw = label.strip()
    if not raw:
        msg = "Period label is empty"
        raise InvalidPeriodError(msg, label=label)

    period = _dispatch(raw)
    if frequency is not None and period.frequency is not frequency:
        msg = (
            f"Period {raw!r} is {period.frequency.value} but the series is "
            f"declared as {frequency.value}"
        )
        raise InvalidPeriodError(msg, label=raw, expected=frequency.value)
    return period


def _dispatch(raw: str) -> Period:
    if match := _ANNUAL.match(raw):
        year = int(match["year"])
        _check_year(year, raw)
        return Period(date(year, 1, 1), date(year, 12, 31), str(year), Frequency.ANNUAL)

    if match := _SEMIANNUAL.match(raw):
        year, half = int(match["year"]), int(match["half"])
        _check_year(year, raw)
        start = date(year, 1, 1) if half == 1 else date(year, 7, 1)
        end = date(year, 6, 30) if half == 1 else date(year, 12, 31)
        return Period(start, end, f"{year}-H{half}", Frequency.SEMIANNUAL)

    if match := _QUARTERLY.match(raw):
        year, quarter = int(match["year"]), int(match["quarter"])
        _check_year(year, raw)
        first_month = 3 * (quarter - 1) + 1
        return Period(
            date(year, first_month, 1),
            _end_of_month(year, first_month + 2),
            f"{year}-Q{quarter}",
            Frequency.QUARTERLY,
        )

    if match := _MONTHLY.match(raw):
        year, month = int(match["year"]), int(match["month"])
        _check_year(year, raw)
        return Period(
            date(year, month, 1),
            _end_of_month(year, month),
            f"{year}-{month:02d}",
            Frequency.MONTHLY,
        )

    if match := _WEEKLY.match(raw):
        year, week = int(match["year"]), int(match["week"])
        _check_year(year, raw)
        try:
            start = date.fromisocalendar(year, week, 1)
        except ValueError as exc:
            msg = f"Invalid ISO week {raw!r}: {exc}"
            raise InvalidPeriodError(msg, label=raw) from exc
        return Period(start, start + timedelta(days=6), f"{year}-W{week:02d}", Frequency.WEEKLY)

    if _DAILY.match(raw):
        try:
            day = date.fromisoformat(raw)
        except ValueError as exc:
            msg = f"Invalid calendar date {raw!r}: {exc}"
            raise InvalidPeriodError(msg, label=raw) from exc
        _check_year(day.year, raw)
        return Period(day, day, day.isoformat(), Frequency.DAILY)

    msg = f"Unrecognised period label {raw!r}"
    raise InvalidPeriodError(msg, label=raw)


def period_from_date(day: date, frequency: Frequency) -> Period:
    """Build the period of ``frequency`` that contains ``day``.

    Useful for sources that publish a single reference date for what is really
    a monthly or quarterly figure.
    """
    match frequency:
        case Frequency.DAILY:
            return parse_period(day.isoformat())
        case Frequency.WEEKLY:
            iso_year, iso_week, _ = day.isocalendar()
            return parse_period(f"{iso_year}-W{iso_week:02d}")
        case Frequency.MONTHLY:
            return parse_period(f"{day.year}-{day.month:02d}")
        case Frequency.QUARTERLY:
            return parse_period(f"{day.year}-Q{(day.month - 1) // 3 + 1}")
        case Frequency.SEMIANNUAL:
            return parse_period(f"{day.year}-H{1 if day.month <= 6 else 2}")
        case Frequency.ANNUAL:
            return parse_period(str(day.year))
        case Frequency.IRREGULAR:
            msg = "Cannot derive an irregular period from a single date"
            raise InvalidPeriodError(msg, date=day.isoformat())
