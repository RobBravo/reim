"""Period normalization."""

from __future__ import annotations

from datetime import date

import pytest

from reim.core.constants import Frequency
from reim.core.exceptions import InvalidPeriodError
from reim.domain.observations.periods import Period, parse_period, period_from_date


@pytest.mark.parametrize(
    ("label", "start", "end", "frequency", "canonical"),
    [
        ("2024", date(2024, 1, 1), date(2024, 12, 31), Frequency.ANNUAL, "2024"),
        ("2024-H1", date(2024, 1, 1), date(2024, 6, 30), Frequency.SEMIANNUAL, "2024-H1"),
        ("2024-H2", date(2024, 7, 1), date(2024, 12, 31), Frequency.SEMIANNUAL, "2024-H2"),
        ("2024-Q1", date(2024, 1, 1), date(2024, 3, 31), Frequency.QUARTERLY, "2024-Q1"),
        ("2024-Q3", date(2024, 7, 1), date(2024, 9, 30), Frequency.QUARTERLY, "2024-Q3"),
        ("2024-Q4", date(2024, 10, 1), date(2024, 12, 31), Frequency.QUARTERLY, "2024-Q4"),
        ("2024-02", date(2024, 2, 1), date(2024, 2, 29), Frequency.MONTHLY, "2024-02"),
        ("2023-02", date(2023, 2, 1), date(2023, 2, 28), Frequency.MONTHLY, "2023-02"),
        ("2024-07-15", date(2024, 7, 15), date(2024, 7, 15), Frequency.DAILY, "2024-07-15"),
    ],
)
def test_parse_period_covers_the_whole_interval(
    label: str, start: date, end: date, frequency: Frequency, canonical: str
) -> None:
    period = parse_period(label)
    assert (period.start, period.end) == (start, end)
    assert period.frequency is frequency
    assert period.label == canonical


def test_leap_year_february_has_29_days() -> None:
    assert parse_period("2024-02").days == 29
    assert parse_period("2023-02").days == 28


def test_iso_week_runs_monday_to_sunday() -> None:
    period = parse_period("2024-W27")
    assert period.start.isoweekday() == 1
    assert period.end.isoweekday() == 7
    assert period.days == 7
    assert period.frequency is Frequency.WEEKLY


def test_annual_period_is_not_collapsed_into_a_single_day() -> None:
    """An annual figure must keep its full 366/365-day span."""
    period = parse_period("2024")
    assert period.start != period.end
    assert period.days == 366


@pytest.mark.parametrize(
    "label",
    ["", "   ", "not-a-period", "2024-13", "2024-Q5", "24", "2024-00", "1899", "2201"],
)
def test_invalid_labels_are_rejected(label: str) -> None:
    with pytest.raises(InvalidPeriodError):
        parse_period(label)


def test_invalid_calendar_date_is_rejected() -> None:
    with pytest.raises(InvalidPeriodError):
        parse_period("2023-02-30")


def test_declared_frequency_mismatch_is_an_error() -> None:
    """A source silently changing granularity must not pass unnoticed."""
    with pytest.raises(InvalidPeriodError, match="declared as monthly"):
        parse_period("2024", Frequency.MONTHLY)


def test_matching_declared_frequency_is_accepted() -> None:
    assert parse_period("2024-03", Frequency.MONTHLY).days == 31


@pytest.mark.parametrize(
    ("frequency", "expected_label"),
    [
        (Frequency.DAILY, "2024-05-17"),
        (Frequency.MONTHLY, "2024-05"),
        (Frequency.QUARTERLY, "2024-Q2"),
        (Frequency.SEMIANNUAL, "2024-H1"),
        (Frequency.ANNUAL, "2024"),
    ],
)
def test_period_from_date(frequency: Frequency, expected_label: str) -> None:
    assert period_from_date(date(2024, 5, 17), frequency).label == expected_label


def test_irregular_frequency_cannot_be_derived_from_a_date() -> None:
    with pytest.raises(InvalidPeriodError):
        period_from_date(date(2024, 5, 17), Frequency.IRREGULAR)


def test_inverted_interval_is_rejected_at_construction() -> None:
    with pytest.raises(InvalidPeriodError):
        Period(date(2024, 12, 31), date(2024, 1, 1), "bad", Frequency.ANNUAL)
