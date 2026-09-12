"""``apps/web/routes.py``'s pure logic: the freshness formatter and the duration formatter.

``_format_freshness`` is the only piece of real logic the catalog view adds —
everything else is data already validated elsewhere, handed to a template.
It needs no session and no database, so it is tested directly here rather
than only indirectly through the page, where the six age branches (and the
boundaries between them) would otherwise go entirely unexercised.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.web.routes import _format_duration, _format_freshness


def _days_ago(days: int) -> datetime:
    """A timestamp `days` before now, at a fixed time of day.

    Anchored at noon UTC rather than "now" so a run close to local midnight
    cannot shift a boundary case (e.g. 14 days) into its neighbour because
    the date component rolled over between building the fixture and the
    function reading ``datetime.now(UTC)``.
    """
    reference = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    return reference - timedelta(days=days)


def test_never_run_is_worded_not_blank() -> None:
    assert _format_freshness(None) == "Never run"


@pytest.mark.parametrize(
    ("days", "expected_age"),
    [
        (0, "today"),
        (1, "yesterday"),
        (2, "2 days ago"),
        (13, "13 days ago"),
        (14, "2 weeks ago"),
        (59, "8 weeks ago"),
        (60, "2 months ago"),
        (729, "24 months ago"),
        (730, "2 years ago"),
    ],
)
def test_every_age_branch_and_its_boundary(days: int, expected_age: str) -> None:
    value = _days_ago(days)
    rendered = _format_freshness(value)

    assert rendered == f"{value.date().isoformat()} · {expected_age}"


def test_a_future_timestamp_still_reads_today() -> None:
    """``age_days <= 0`` covers zero and negative alike — clock skew, not a crash."""
    value = datetime.now(UTC) + timedelta(days=5)

    assert _format_freshness(value).endswith("today")


def test_a_run_with_no_duration_reads_as_a_dash() -> None:
    """A run still in flight has no duration — a dash, never "0 ms"."""
    assert _format_duration(None) == "—"


@pytest.mark.parametrize(
    ("milliseconds", "expected"),
    [
        (0, "0 ms"),
        (999, "999 ms"),
        (1000, "1.0 s"),
        (59_999, "60.0 s"),
        (60_000, "1m 0s"),
        (3_723_000, "62m 3s"),
    ],
)
def test_every_duration_branch_and_its_boundary(milliseconds: int, expected: str) -> None:
    assert _format_duration(milliseconds) == expected
