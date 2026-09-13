"""Comparing what is true now against what has already been said.

Pure: evaluated alerts, the open rows, an interval and a ``now`` in; four
disjoint groups out. The service does the I/O either side of this function,
which is what lets the whole notification lifecycle be tested without a
database.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from reim.repositories.alerts import OpenAlert
from reim.services.alert_rules import Alert


@dataclass(frozen=True)
class Reconciliation:
    """What this run should say, and what it should keep to itself."""

    #: Firing, never notified before.
    new: tuple[Alert, ...] = ()
    #: Firing, last notified longer ago than the repeat interval.
    repeat: tuple[Alert, ...] = ()
    #: Previously notified, no longer firing.
    resolved: tuple[OpenAlert, ...] = ()
    #: Firing, but notified recently enough to stay quiet about.
    suppressed: tuple[Alert, ...] = ()

    @property
    def has_changes(self) -> bool:
        """Whether there is anything worth delivering."""
        return bool(self.new or self.repeat or self.resolved)

    @property
    def firing(self) -> tuple[Alert, ...]:
        """Everything currently true, whether or not it is being notified.

        The command's exit code turns on this rather than on ``has_changes``: a
        problem that is merely being suppressed is still a problem, and a cron
        job checking the exit status should keep seeing a failure.
        """
        return self.new + self.repeat + self.suppressed


def reconcile(
    alerts: Sequence[Alert],
    open_alerts: Sequence[OpenAlert],
    *,
    repeat_after: timedelta,
    now: datetime,
) -> Reconciliation:
    """Sort the evaluated alerts against the open rows into four groups.

    Matching is on ``(condition, pipeline_key)``: one pipeline can hold several
    conditions at once and each is tracked on its own, so a stale pipeline does
    not silence the same pipeline's failed run.

    An alert notified exactly ``repeat_after`` ago repeats rather than staying
    quiet. At a boundary the safer failure is to speak twice, not to fall
    silent.
    """
    open_by_key = {(row.condition, row.pipeline_key): row for row in open_alerts}
    seen: set[tuple[str, str]] = set()

    new: list[Alert] = []
    repeat: list[Alert] = []
    suppressed: list[Alert] = []

    for alert in alerts:
        key = (alert.condition.value, alert.pipeline_key)
        seen.add(key)
        existing = open_by_key.get(key)
        if existing is None:
            new.append(alert)
        elif now - existing.last_notified_at >= repeat_after:
            repeat.append(alert)
        else:
            suppressed.append(alert)

    resolved = tuple(row for key, row in open_by_key.items() if key not in seen)

    return Reconciliation(
        new=tuple(new),
        repeat=tuple(repeat),
        resolved=resolved,
        suppressed=tuple(suppressed),
    )
