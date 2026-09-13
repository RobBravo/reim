"""``reconcile``: the difference between what is true and what has been said.

This is the whole reason for the state table, and it is pure, so the full
lifecycle — fire, suppress, re-notify, resolve — is asserted here without a
database or a webhook.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from reim.core.constants import CheckSeverity
from reim.repositories.alerts import OpenAlert
from reim.services.alert_reconcile import reconcile
from reim.services.alert_rules import Alert, AlertCondition

NOW = datetime(2026, 9, 12, 18, 0, tzinfo=UTC)
DAY = timedelta(hours=24)


def _alert(pipeline_key: str = "bcn_fx", condition: AlertCondition = AlertCondition.STALE) -> Alert:
    return Alert(
        condition=condition,
        pipeline_key=pipeline_key,
        severity=CheckSeverity.WARNING,
        summary=f"{pipeline_key} is {condition.value}",
        details={"data_age_days": 9},
    )


def _open(
    pipeline_key: str = "bcn_fx",
    condition: AlertCondition = AlertCondition.STALE,
    *,
    last_notified_at: datetime = NOW,
) -> OpenAlert:
    return OpenAlert(
        condition=condition.value,
        pipeline_key=pipeline_key,
        first_notified_at=NOW - timedelta(days=30),
        last_notified_at=last_notified_at,
    )


def test_a_condition_nobody_has_been_told_about_is_new() -> None:
    result = reconcile([_alert()], [], repeat_after=DAY, now=NOW)

    assert [alert.pipeline_key for alert in result.new] == ["bcn_fx"]
    assert result.repeat == ()
    assert result.resolved == ()
    assert result.has_changes is True


def test_a_condition_just_notified_is_suppressed() -> None:
    """The reason the table exists: hourly cron must not mean hourly messages."""
    result = reconcile([_alert()], [_open(last_notified_at=NOW)], repeat_after=DAY, now=NOW)

    assert result.new == ()
    assert result.repeat == ()
    assert [alert.pipeline_key for alert in result.suppressed] == ["bcn_fx"]
    assert result.has_changes is False


def test_a_condition_notified_longer_ago_than_the_interval_repeats() -> None:
    stale_notice = _open(last_notified_at=NOW - timedelta(hours=25))

    result = reconcile([_alert()], [stale_notice], repeat_after=DAY, now=NOW)

    assert [alert.pipeline_key for alert in result.repeat] == ["bcn_fx"]
    assert result.suppressed == ()
    assert result.has_changes is True


def test_a_condition_notified_exactly_the_interval_ago_repeats() -> None:
    """At the boundary, speak: a silent alerting system is the failure mode."""
    result = reconcile([_alert()], [_open(last_notified_at=NOW - DAY)], repeat_after=DAY, now=NOW)

    assert [alert.pipeline_key for alert in result.repeat] == ["bcn_fx"]


def test_a_condition_that_stopped_holding_resolves() -> None:
    result = reconcile([], [_open()], repeat_after=DAY, now=NOW)

    assert [row.pipeline_key for row in result.resolved] == ["bcn_fx"]
    assert result.has_changes is True


def test_a_resolved_condition_is_reported_once_and_not_again() -> None:
    """Second run: the row is closed, so there is nothing left to resolve."""
    first = reconcile([], [_open()], repeat_after=DAY, now=NOW)
    assert first.resolved

    second = reconcile([], [], repeat_after=DAY, now=NOW)

    assert second.resolved == ()
    assert second.has_changes is False


def test_conditions_are_matched_on_both_condition_and_pipeline() -> None:
    """A stale pipeline does not silence the same pipeline's failed run."""
    alerts = [
        _alert(condition=AlertCondition.STALE),
        _alert(condition=AlertCondition.FAILED_RUN),
    ]

    result = reconcile(alerts, [_open(condition=AlertCondition.STALE)], repeat_after=DAY, now=NOW)

    assert [alert.condition for alert in result.new] == [AlertCondition.FAILED_RUN]
    assert [alert.condition for alert in result.suppressed] == [AlertCondition.STALE]


def test_the_same_condition_on_another_pipeline_is_its_own_alert() -> None:
    result = reconcile(
        [_alert(pipeline_key="a"), _alert(pipeline_key="b")],
        [_open(pipeline_key="a")],
        repeat_after=DAY,
        now=NOW,
    )

    assert [alert.pipeline_key for alert in result.new] == ["b"]
    assert [alert.pipeline_key for alert in result.suppressed] == ["a"]


def test_firing_covers_everything_currently_true() -> None:
    """The exit code turns on this, not on whether anything was delivered."""
    result = reconcile(
        [_alert(pipeline_key="a"), _alert(pipeline_key="b")],
        [_open(pipeline_key="a", last_notified_at=NOW)],
        repeat_after=DAY,
        now=NOW,
    )

    assert sorted(alert.pipeline_key for alert in result.firing) == ["a", "b"]


def test_nothing_true_and_nothing_open_is_a_quiet_run() -> None:
    result = reconcile([], [], repeat_after=DAY, now=NOW)

    assert result.has_changes is False
    assert result.firing == ()
