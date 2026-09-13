"""``alert_states``: the memory that turns 500 notifications into 21.

The partial unique index is PostgreSQL behaviour, so these run against the real
database rather than being mocked into agreement with themselves.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from reim.repositories import alerts as alert_repo
from tests.conftest import requires_db


@requires_db
def test_a_recorded_alert_comes_back_as_open(session: Session) -> None:
    now = datetime.now(UTC)

    alert_repo.record_notified(
        session, condition="stale", pipeline_key="a", details={"data_age_days": 9}, now=now
    )

    open_alerts = alert_repo.list_open(session)
    assert len(open_alerts) == 1
    assert open_alerts[0].condition == "stale"
    assert open_alerts[0].pipeline_key == "a"
    assert open_alerts[0].first_notified_at == open_alerts[0].last_notified_at


@requires_db
def test_re_recording_advances_the_last_notified_time_only(session: Session) -> None:
    """The first notification's time is what tells an operator how long."""
    first = datetime.now(UTC)
    later = first + timedelta(days=1)

    alert_repo.record_notified(session, condition="stale", pipeline_key="a", details={}, now=first)
    alert_repo.record_notified(session, condition="stale", pipeline_key="a", details={}, now=later)

    open_alerts = alert_repo.list_open(session)
    assert len(open_alerts) == 1
    assert open_alerts[0].first_notified_at == first
    assert open_alerts[0].last_notified_at == later


@requires_db
def test_a_resolved_alert_is_no_longer_open(session: Session) -> None:
    now = datetime.now(UTC)
    alert_repo.record_notified(session, condition="stale", pipeline_key="a", details={}, now=now)

    alert_repo.mark_resolved(session, condition="stale", pipeline_key="a", now=now)

    assert alert_repo.list_open(session) == []


@requires_db
def test_the_same_condition_can_fire_again_after_resolving(session: Session) -> None:
    """The partial index is scoped to open rows, so history accumulates."""
    first = datetime.now(UTC)
    alert_repo.record_notified(session, condition="stale", pipeline_key="a", details={}, now=first)
    alert_repo.mark_resolved(session, condition="stale", pipeline_key="a", now=first)

    again = first + timedelta(days=7)
    alert_repo.record_notified(session, condition="stale", pipeline_key="a", details={}, now=again)

    open_alerts = alert_repo.list_open(session)
    assert len(open_alerts) == 1
    assert open_alerts[0].first_notified_at == again


@requires_db
def test_conditions_and_pipelines_are_tracked_independently(session: Session) -> None:
    now = datetime.now(UTC)
    alert_repo.record_notified(session, condition="stale", pipeline_key="a", details={}, now=now)
    alert_repo.record_notified(
        session, condition="failed_run", pipeline_key="a", details={}, now=now
    )
    alert_repo.record_notified(session, condition="stale", pipeline_key="b", details={}, now=now)

    assert len(alert_repo.list_open(session)) == 3
