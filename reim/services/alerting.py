"""Evaluating, delivering and remembering alerts.

The interesting logic is not here: evaluation lives in
``reim.services.alert_rules`` and reconciliation in
``reim.services.alert_reconcile``, both pure. This module does the I/O around
them, and owns one ordering decision that matters more than the rest of it —
state is recorded only after a delivery succeeds.

The webhook ``POST`` happens inside the caller's open read transaction (the
one ``session_scope`` holds for the CLI command), so a hung webhook holds an
idle-in-transaction connection for up to the HTTP timeout times the retry
count. Acceptable for an hourly cron command; this note exists so nobody later
moves this under a web request without thinking about it.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.orm import Session

from reim.core.config import Settings, get_settings
from reim.core.exceptions import ExtractionError, REIMError
from reim.ingestion.http import http_client, post
from reim.repositories import alerts as alert_repo
from reim.repositories import pipeline_runs as run_repo
from reim.repositories.alerts import OpenAlert
from reim.services.alert_reconcile import Reconciliation, reconcile
from reim.services.alert_rules import Alert, evaluate
from reim.services.metrics import build_metrics_snapshot

#: Version of the webhook payload shape. Bump only for a breaking change.
PAYLOAD_VERSION = 1

#: A delivery mechanism: hand it an encoded body, it gets there or raises.
Sender = Callable[[bytes], Awaitable[None]]


class AlertDeliveryError(REIMError):
    """An alert could not be delivered."""

    code = "alert_delivery_error"


def _redact_url(url: str) -> str:
    """Return only the scheme, host and port of ``url``, marking any path.

    An operator-controlled webhook URL carries a secret, and this URL is
    interpolated into an exception message a human reads — in cron mail, or on
    a terminal whose history is kept. Everything after the host is dropped.

    Keeping the path was the obvious thing and it was wrong: Slack and Discord
    put the token *in the path*, not the query string, so
    ``hooks.slack.com/services/T00/B00/XXXX`` would have leaked in full. There
    is no part of a webhook URL below the host that can be assumed safe to
    print, so none of it is. A trailing ``/…`` records that a path existed, so
    the message cannot be misread as naming a bare host.

    The host is enough to say which endpoint failed; an operator running
    several webhooks on one host has them in their own configuration.
    """
    parts = urlsplit(url)
    netloc = parts.hostname or ""
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    suffix = "/…" if parts.path.strip("/") else ""
    return f"{urlunsplit((parts.scheme, netloc, '', '', ''))}{suffix}"


def _first_notified_at(
    alert: Alert, open_by_key: dict[tuple[str, str], OpenAlert], now: datetime
) -> datetime:
    """The moment this alert was first notified, for a firing payload entry.

    Matches reconciliation's own key: ``(condition, pipeline_key)``. A repeat
    carries the original open row's ``first_notified_at``; a genuinely new
    alert has no row yet, so it is first notified now.
    """
    existing = open_by_key.get((alert.condition.value, alert.pipeline_key))
    return existing.first_notified_at if existing is not None else now


def build_payload(
    reconciliation: Reconciliation,
    *,
    environment: str,
    now: datetime,
    open_alerts: Sequence[OpenAlert] = (),
) -> bytes:
    """Render one run's changes as the webhook body.

    One digest per run rather than one request per alert: a database that was
    down during the nightly sweep is one message, not twenty-three.

    ``open_alerts`` are the rows loaded before reconciliation, used only to
    look up each firing alert's original ``first_notified_at`` — otherwise day
    22 of an outage would look identical to day 1's in the payload.
    """
    open_by_key = {(row.condition, row.pipeline_key): row for row in open_alerts}
    payload = {
        "version": PAYLOAD_VERSION,
        "generated_at": now.isoformat(),
        "environment": environment,
        "firing": [
            {
                "condition": alert.condition.value,
                "pipeline_key": alert.pipeline_key,
                "severity": alert.severity.value,
                "summary": alert.summary,
                "details": alert.details,
                "first_notified_at": _first_notified_at(alert, open_by_key, now).isoformat(),
            }
            for alert in reconciliation.new + reconciliation.repeat
        ],
        "resolved": [
            {
                "condition": row.condition,
                "pipeline_key": row.pipeline_key,
                "summary": f"{row.pipeline_key} no longer reports {row.condition}.",
                "first_notified_at": row.first_notified_at.isoformat(),
                "details": row.details,
            }
            for row in reconciliation.resolved
        ],
    }
    return json.dumps(payload, sort_keys=True).encode()


async def _post_to_webhook(url: str, body: bytes, settings: Settings) -> None:
    """Deliver one payload, translating ingestion failures at the boundary.

    ``post`` raises :class:`ExtractionError` — an ingestion concept, and the
    wrong thing to surface from an alerting stack trace — so it is translated
    here. Reusing it means the retry policy is not written twice.

    Redirects are not followed: a misconfigured URL should fail visibly rather
    than succeed ambiguously after a hop that may not have carried the body.
    """
    try:
        async with http_client(settings) as client:
            client.follow_redirects = False
            response = await post(
                client,
                url,
                content=body,
                headers={"Content-Type": "application/json"},
                settings=settings,
            )
    except ExtractionError as exc:
        raise AlertDeliveryError(
            f"Could not deliver alerts to {_redact_url(url)}: {exc.message}"
        ) from exc

    if response.status_code >= 300:
        msg = f"Webhook at {_redact_url(url)} answered HTTP {response.status_code}"
        raise AlertDeliveryError(msg, status_code=response.status_code)


async def run_alert_check(
    session: Session,
    *,
    settings: Settings | None = None,
    send: Sender | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
) -> Reconciliation:
    """Evaluate every condition, deliver what changed, and record what was said.

    Returns the reconciliation so a caller can print it and choose an exit
    code. Nothing is recorded when there is nothing to say, when ``dry_run`` is
    set, or when no webhook is configured — in that last case the command still
    evaluates and reports, so alerting being off does not make it broken.

    An unreachable database returns an empty reconciliation immediately after
    the snapshot is built, before any further query runs on a transaction
    Postgres has already aborted. This also protects reconciliation itself: an
    empty evaluated set would otherwise read as every open alert having
    resolved.

    **State is written only after the delivery succeeds.** A webhook that is
    down must cost noise, never an alert: nothing is marked notified, so the
    next run says it again. Recording first and delivering after would lose an
    alert permanently on a transient failure.

    The trailing ``session.flush()`` is deliberate, not a leftover:
    ``record_notified``'s update path (an alert that is already open) mutates
    the existing row and returns without flushing on its own, so this call is
    what pushes that particular change out.
    """
    resolved_settings = settings or get_settings()
    moment = now or datetime.now(UTC)

    snapshot = build_metrics_snapshot(session, today=moment.date())
    if not snapshot.database_up:
        # ``evaluate`` already returns nothing for this snapshot, which would
        # leave every open row looking unfired — and reconciliation would
        # read that as every one of them having resolved, announcing a false
        # recovery for each while clearing the state table. Stopping here,
        # before the next query runs on a transaction Postgres has already
        # aborted, makes that unreachable rather than merely avoided.
        return Reconciliation()
    failed_checks = run_repo.latest_run_failed_checks(session)

    alerts = evaluate(
        snapshot,
        failed_checks,
        severity_floor=resolved_settings.alert_severity_floor,
        stuck_run_after=timedelta(hours=resolved_settings.alert_stuck_run_hours),
        now=moment,
    )
    open_alerts = alert_repo.list_open(session)
    evaluated_keys = frozenset(
        pipeline.pipeline_key for pipeline in snapshot.pipelines if pipeline.enabled
    )
    result = reconcile(
        alerts,
        open_alerts,
        repeat_after=timedelta(hours=resolved_settings.alert_repeat_hours),
        now=moment,
        evaluated_keys=evaluated_keys,
    )

    if not result.has_changes or dry_run:
        return result

    url = resolved_settings.alert_webhook_url
    if send is None and not url:
        return result

    body = build_payload(
        result,
        environment=resolved_settings.environment.value,
        now=moment,
        open_alerts=open_alerts,
    )
    if send is not None:
        await send(body)
    else:
        if url is None:  # pragma: no cover - narrowed by the guard above
            raise AlertDeliveryError("No alert webhook URL is configured.")
        await _post_to_webhook(url, body, resolved_settings)

    for alert in result.new + result.repeat:
        alert_repo.record_notified(
            session,
            condition=alert.condition.value,
            pipeline_key=alert.pipeline_key,
            details=alert.details,
            now=moment,
        )
    for row in result.resolved + result.withdrawn:
        alert_repo.mark_resolved(
            session, condition=row.condition, pipeline_key=row.pipeline_key, now=moment
        )
    session.flush()
    return result
