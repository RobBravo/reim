"""Scheduling interface.

The MVP triggers pipelines from the CLI only (see decision D13). This module
defines the seam an external scheduler — cron, systemd timers, GitHub Actions,
or a workflow engine added later — plugs into, without pulling any scheduling
infrastructure into the MVP.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from reim.core.constants import Frequency
from reim.domain.pipelines.models import PipelineOutcome


@dataclass(frozen=True, slots=True)
class ScheduledPipeline:
    """A pipeline together with the cadence at which it should run."""

    pipeline_key: str
    frequency: Frequency
    cron: str | None = None
    enabled: bool = True


@runtime_checkable
class PipelineScheduler(Protocol):
    """Contract an external scheduler must satisfy.

    Implementations live outside the MVP; the CLI is the only caller today.
    """

    def list_scheduled(self) -> list[ScheduledPipeline]:
        """Return every pipeline known to the scheduler."""
        ...

    async def trigger(self, pipeline_key: str) -> PipelineOutcome:
        """Run one pipeline immediately and return its outcome."""
        ...


#: Default cron expressions per frequency, offered as a starting point for
#: operators wiring REIM into cron. Times are UTC.
DEFAULT_CRON_BY_FREQUENCY: dict[Frequency, str] = {
    Frequency.DAILY: "0 13 * * *",
    Frequency.WEEKLY: "0 13 * * 1",
    Frequency.MONTHLY: "0 13 5 * *",
    Frequency.QUARTERLY: "0 13 10 1,4,7,10 *",
    Frequency.SEMIANNUAL: "0 13 15 1,7 *",
    Frequency.ANNUAL: "0 13 15 4 *",
    Frequency.IRREGULAR: "0 13 * * 1",
}
