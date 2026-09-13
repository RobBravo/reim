"""``run_alert_check``: the whole lifecycle, and the ordering that protects it.

Delivery is injected rather than monkeypatched — the service takes a sender,
which is also what ``--dry-run`` uses, so the seam earns its keep twice. No
test makes a real HTTP request.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from reim.core.config import Settings
from reim.core.constants import PipelineStatus
from reim.database.models import PipelineRun
from reim.repositories import alerts as alert_repo
from reim.services.alerting import AlertDeliveryError, run_alert_check
from tests.conftest import requires_db

NOW = datetime(2026, 9, 12, 18, 0, tzinfo=UTC)
PIPELINE = "worldbank_ni_cpi_inflation"


class _Recorder:
    """A sender that remembers what it was handed."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def __call__(self, body: bytes) -> None:
        self.payloads.append(json.loads(body))


class _Broken:
    """A sender that fails, the way a webhook being down fails."""

    async def __call__(self, body: bytes) -> None:
        raise AlertDeliveryError("webhook unreachable")


def _settings(**overrides: Any) -> Settings:
    return Settings(alert_webhook_url="https://hooks.example.org/reim", **overrides)


def _failed_run(session: Session, *, started_at: datetime) -> None:
    session.add(
        PipelineRun(
            id=uuid.uuid4(),
            pipeline_key=PIPELINE,
            started_at=started_at,
            status=PipelineStatus.FAILED,
            duration_ms=100,
            created_at=started_at,
        )
    )
    session.flush()


@requires_db
async def test_a_new_condition_is_delivered_and_recorded(seeded_session: Session) -> None:
    _failed_run(seeded_session, started_at=NOW - timedelta(hours=1))
    recorder = _Recorder()

    result = await run_alert_check(seeded_session, settings=_settings(), send=recorder, now=NOW)

    assert [alert.pipeline_key for alert in result.new] == [PIPELINE]
    assert len(recorder.payloads) == 1
    assert recorder.payloads[0]["firing"][0]["condition"] == "failed_run"
    assert [row.pipeline_key for row in alert_repo.list_open(seeded_session)] == [PIPELINE]


@requires_db
async def test_the_second_run_says_nothing_and_sends_nothing(seeded_session: Session) -> None:
    """Hourly cron must not mean hourly messages."""
    _failed_run(seeded_session, started_at=NOW - timedelta(hours=1))
    recorder = _Recorder()

    await run_alert_check(seeded_session, settings=_settings(), send=recorder, now=NOW)
    result = await run_alert_check(
        seeded_session, settings=_settings(), send=recorder, now=NOW + timedelta(hours=1)
    )

    assert len(recorder.payloads) == 1
    assert result.has_changes is False
    assert result.firing


@requires_db
async def test_it_speaks_again_once_the_repeat_interval_passes(seeded_session: Session) -> None:
    _failed_run(seeded_session, started_at=NOW - timedelta(hours=1))
    recorder = _Recorder()
    settings = _settings(alert_repeat_hours=24)

    await run_alert_check(seeded_session, settings=settings, send=recorder, now=NOW)
    await run_alert_check(
        seeded_session, settings=settings, send=recorder, now=NOW + timedelta(hours=25)
    )

    assert len(recorder.payloads) == 2


@requires_db
async def test_a_condition_that_clears_sends_one_resolution_notice(
    seeded_session: Session,
) -> None:
    """Knowing a scrape works again is worth as much as knowing it broke."""
    _failed_run(seeded_session, started_at=NOW - timedelta(hours=2))
    recorder = _Recorder()
    await run_alert_check(seeded_session, settings=_settings(), send=recorder, now=NOW)

    seeded_session.add(
        PipelineRun(
            id=uuid.uuid4(),
            pipeline_key=PIPELINE,
            started_at=NOW,
            status=PipelineStatus.SUCCESS,
            duration_ms=100,
            created_at=NOW,
        )
    )
    seeded_session.flush()

    result = await run_alert_check(
        seeded_session, settings=_settings(), send=recorder, now=NOW + timedelta(hours=1)
    )

    assert [row.pipeline_key for row in result.resolved] == [PIPELINE]
    assert recorder.payloads[-1]["resolved"][0]["condition"] == "failed_run"
    assert alert_repo.list_open(seeded_session) == []

    quiet = await run_alert_check(
        seeded_session, settings=_settings(), send=recorder, now=NOW + timedelta(hours=2)
    )
    assert quiet.has_changes is False
    assert len(recorder.payloads) == 2


@requires_db
async def test_a_failed_delivery_records_nothing_so_the_next_run_retries(
    seeded_session: Session,
) -> None:
    """The one failure mode alerting may not have is losing the alert."""
    _failed_run(seeded_session, started_at=NOW - timedelta(hours=1))

    with pytest.raises(AlertDeliveryError):
        await run_alert_check(seeded_session, settings=_settings(), send=_Broken(), now=NOW)

    assert alert_repo.list_open(seeded_session) == []

    recorder = _Recorder()
    result = await run_alert_check(
        seeded_session, settings=_settings(), send=recorder, now=NOW + timedelta(minutes=5)
    )

    assert [alert.pipeline_key for alert in result.new] == [PIPELINE]
    assert len(recorder.payloads) == 1


@requires_db
async def test_a_quiet_run_delivers_nothing_at_all(seeded_session: Session) -> None:
    recorder = _Recorder()

    result = await run_alert_check(seeded_session, settings=_settings(), send=recorder, now=NOW)

    assert result.has_changes is False
    assert recorder.payloads == []


@requires_db
async def test_dry_run_evaluates_without_delivering_or_recording(
    seeded_session: Session,
) -> None:
    _failed_run(seeded_session, started_at=NOW - timedelta(hours=1))
    recorder = _Recorder()

    result = await run_alert_check(
        seeded_session, settings=_settings(), send=recorder, now=NOW, dry_run=True
    )

    assert result.new
    assert recorder.payloads == []
    assert alert_repo.list_open(seeded_session) == []


@requires_db
async def test_no_configured_webhook_still_evaluates(seeded_session: Session) -> None:
    """Alerting off must not mean the command is broken."""
    _failed_run(seeded_session, started_at=NOW - timedelta(hours=1))

    result = await run_alert_check(
        seeded_session, settings=Settings(alert_webhook_url=None), now=NOW
    )

    assert result.new
    assert alert_repo.list_open(seeded_session) == []


@requires_db
async def test_the_payload_names_the_environment_and_its_own_version(
    seeded_session: Session,
) -> None:
    _failed_run(seeded_session, started_at=NOW - timedelta(hours=1))
    recorder = _Recorder()

    await run_alert_check(seeded_session, settings=_settings(), send=recorder, now=NOW)

    payload = recorder.payloads[0]
    assert payload["version"] == 1
    assert payload["environment"]
    assert payload["generated_at"] == NOW.isoformat()
