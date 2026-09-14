"""Turning the catalog's cadences into a crontab an operator can install.

``pipeline list`` has printed a suggested cron expression per source since the
MVP and nothing consumed it, so the documented deployment runs every pipeline
monthly — fetching two daily exchange rates far too rarely and eight annual
series far too often. This module closes that gap.

Pure by construction: a catalog and some strings in, text out. No session, no
clock, no filesystem, which is why every rule here is asserted directly rather
than inferred from a rendered command.

REIM still has no built-in scheduler. The operator's cron is the scheduler; this
only writes down what to give it.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from reim.core.constants import Frequency
from reim.domain.pipelines.scheduling import DEFAULT_CRON_BY_FREQUENCY
from reim.domain.sources.catalog import SourceCatalog

#: Minute each cadence runs at, so overlapping schedules do not start together.
#:
#: Every default expression in ``DEFAULT_CRON_BY_FREQUENCY`` fires at 13:00 and
#: ``daily`` fires every day, so installed verbatim they collide by
#: construction — daily with monthly on the 5th, with quarterly on 10 January,
#: with annual on 15 April. Ordered by how often the cadence runs, so ``daily``
#: keeps the top of the hour: it fires most often and should never move.
#:
#: Every value is under 60, so rewriting the minute can never perturb a day
#: field. ``DEFAULT_CRON_BY_FREQUENCY`` stays the sole authority on which days a
#: cadence runs.
FREQUENCY_MINUTES: dict[Frequency, int] = {
    Frequency.DAILY: 0,
    Frequency.WEEKLY: 5,
    Frequency.MONTHLY: 15,
    Frequency.QUARTERLY: 25,
    Frequency.SEMIANNUAL: 35,
    Frequency.ANNUAL: 45,
    Frequency.IRREGULAR: 55,
}

#: Hour the alert check runs, after the 13:00 ingestion window has cleared.
ALERT_HOUR = 15


@dataclass(frozen=True)
class ScheduleEntry:
    """One crontab line, with the comment that explains it."""

    comment: str
    expression: str
    command: str


def stagger_expression(frequency: Frequency) -> str:
    """Return this cadence's default expression with only its minute rewritten.

    Public because ``pipeline list``'s ``SUGGESTED CRON`` column and the
    crontab this module emits must show the same expression for a given
    cadence — if the column kept reading ``DEFAULT_CRON_BY_FREQUENCY``
    directly, it would teach an operator to hand-install the very 13:00
    collision this module exists to remove. One function, called from both
    places, is the only way they cannot drift apart.
    """
    fields = DEFAULT_CRON_BY_FREQUENCY[frequency].split()
    fields[0] = str(FREQUENCY_MINUTES[frequency])
    return " ".join(fields)


def build_schedule(
    catalog: SourceCatalog,
    *,
    working_dir: Path,
    python: str = ".venv/bin/python",
) -> list[ScheduleEntry]:
    """Return one entry per cadence in use, then the alert check.

    Iterates the frequencies **present in the catalog**, not the ``Frequency``
    enum: a crontab carrying blocks for cadences no source uses is noise an
    operator has to read and then delete.

    Only enabled sources are scheduled. Disabled sources are never included,
    because a crontab is unattended and ``disabled_reason`` may record a licence
    constraint that must not be silently bypassed.

    ``working_dir`` is shell-quoted, so a path containing spaces still reaches
    ``cd`` as one argument. A ``%`` in the path is a known limitation this does
    not handle: cron treats an unescaped ``%`` as a newline inside the command
    field, which would silently truncate everything after it. Quoting cannot
    fix that — it is cron's own escaping rule, not the shell's — so a path
    containing ``%`` still needs to be avoided or escaped by the operator.
    """
    sources = catalog.enabled_sources
    prefix = f"cd {shlex.quote(str(working_dir))} && {python} -m reim.cli"

    by_frequency: dict[Frequency, list[str]] = {}
    for source in sources:
        by_frequency.setdefault(source.frequency, []).append(source.key)

    entries = [
        ScheduleEntry(
            comment=(f"{frequency.value} — {len(keys)} pipeline(s): {', '.join(sorted(keys))}"),
            expression=stagger_expression(frequency),
            command=f"{prefix} pipeline run-all --frequency {frequency.value}",
        )
        # Sorted by minute so the rendered crontab reads in the order it runs.
        for frequency, keys in sorted(
            by_frequency.items(), key=lambda item: FREQUENCY_MINUTES[item[0]]
        )
    ]

    entries.append(
        ScheduleEntry(
            comment=(
                "Alerting — after the ingestion window, since staleness is only "
                "meaningful once the day's ingestion has finished."
            ),
            expression=f"0 {ALERT_HOUR} * * *",
            command=f"{prefix} alert check",
        )
    )
    return entries


def render_crontab(entries: list[ScheduleEntry]) -> str:
    """Render entries as a crontab fragment, ready to review and install."""
    lines = [
        "# REIM — generated by `reim pipeline schedule`. Review before installing.",
        "# Times follow the cron daemon's timezone; the defaults were written as UTC.",
    ]
    for entry in entries:
        lines.extend(["", f"# {entry.comment}", f"{entry.expression} {entry.command}"])
    return "\n".join(lines) + "\n"
