# Schedule Emitter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `reim pipeline schedule` — a crontab fragment an operator can review and install, running each cadence's pipelines on the cadence the catalog already records, plus the alert check.

**Architecture:** One pure module, `reim/domain/pipelines/schedule.py`, turns a catalog into `ScheduleEntry` objects and renders them as crontab text. No session, no clock, no filesystem — so every rule is unit-tested directly and the CLI command is a thin wrapper. `run-all` gains a `--frequency` filter, which needs no change to `PipelineRunner` because `run_all` already accepts `keys`.

**Tech Stack:** Typer, Pydantic (the existing `SourceCatalog`), pytest. No new dependency, no model, no migration.

**Spec:** `docs/superpowers/specs/2026-09-13-schedule-emitter-design.md`

## Global Constraints

* **The emitter rewrites only the minute field** of `DEFAULT_CRON_BY_FREQUENCY`'s expression (spec D4). That constant stays the sole authority on which *days* a cadence runs. Every offset is under 60 so a day field can never be perturbed.
* **Iterate the frequencies present among enabled sources, never the `Frequency` enum** (spec D3). The enabled catalog uses four of seven today; blocks for unused cadences are noise the operator must read and delete.
* **Print to stdout. Never install, never write a file, never touch a crontab** (spec D6).
* **`PipelineScheduler` stays unimplemented** (spec D1) and no systemd renderer is written (spec D2). If you find yourself adding either, stop.
* **`--frequency` filters in the CLI, not in `ConnectorRegistry`** (spec D5).
* **Disabled sources are omitted, not commented out** (spec D8).
* **Every block names the pipelines it will run** (spec D7), and that list must match what `--frequency` would actually select — a comment that drifts from its command is worse than no comment.
* **The verification gate, which must pass before every commit:**
  ```bash
  .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q
  ```
* **No `pip` in the venv** — use `.venv/bin/<tool>`. The full suite needs `REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim` exported **in the same shell command**; if tests skip, the URL was not exported and nothing was proven.
* **mypy strict** over `reim` and `apps`; `ruff` enforces a 100-character line limit and isort ordering. Test functions need `-> None`.
* **The CLI is invoked as `python -m reim.cli`**, never `python -m reim` — `reim` is a package with no `__main__`.
* `ruff format` rewrites ` ```python ` blocks in Markdown that are not valid standalone modules; fence such fragments as ` ```text `.

---

## File Structure

| File | Responsibility |
|---|---|
| `reim/cli/main.py` *(modify)* | `--frequency` on `run-all` (Task 1); the `schedule` command (Task 3) |
| `reim/domain/pipelines/schedule.py` *(create)* | `ScheduleEntry`, `FREQUENCY_MINUTES`, `build_schedule`, `render_crontab` — all pure |
| `reim/domain/pipelines/__init__.py` *(modify)* | Export the new names beside `PipelineScheduler` |
| `tests/unit/test_schedule.py` *(create)* | Every rule above, no database |
| `tests/integration/test_cli_schedule.py` *(create)* | The two CLI surfaces against the real catalog |
| `README.md`, `ROADMAP.md` *(modify)* | Replace the hand-written cron example; mark the item done |

---

### Task 1: `--frequency` on `run-all`

Ordered first because Task 2 emits commands that use this option; writing the emitter first would mean emitting a flag that does not exist yet.

**Files:**
- Modify: `reim/cli/main.py`
- Test: `tests/integration/test_cli_schedule.py` (create)

**Interfaces:**
- Produces, relied on by Task 2: the CLI accepts `reim pipeline run-all --frequency <value>` for any `Frequency` value.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_cli_schedule.py`. The repository has **no CLI test harness at all** — `CliRunner` appears nowhere — so this file introduces one. Keep it to Typer's own `CliRunner`, which needs no database:

```python
"""The two scheduling CLI surfaces.

The repository had no CLI tests before this file; these use Typer's own
``CliRunner``, which runs the command in-process and needs no database. They
assert what an operator sees — the emitted text and the accepted options — not
how it is computed, which ``tests/unit/test_schedule.py`` covers.
"""

from __future__ import annotations

from typer.testing import CliRunner

from reim.cli.main import app

runner = CliRunner()


def test_run_all_accepts_a_frequency() -> None:
    """``--help`` is enough: actually running it would hit the network."""
    result = runner.invoke(app, ["pipeline", "run-all", "--help"])

    assert result.exit_code == 0
    assert "--frequency" in result.stdout


def test_run_all_rejects_a_frequency_that_is_not_one() -> None:
    result = runner.invoke(app, ["pipeline", "run-all", "--frequency", "fortnightly"])

    assert result.exit_code != 0
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/pytest tests/integration/test_cli_schedule.py -q
```

Expected: the first test fails because `--frequency` is absent from the help text. If `typer.testing` cannot be imported, check whether `pytest` needs `typer[all]`; report rather than adding a dependency.

- [ ] **Step 3: Add the option**

In `reim/cli/main.py`, give `pipeline_run_all` a `frequency` option and filter the keys. `run_all` already accepts `keys`, so `PipelineRunner` is untouched:

```python
@pipeline_app.command("run-all")
def pipeline_run_all(
    include_disabled: Annotated[
        bool, typer.Option("--include-disabled", help="Also run disabled pipelines.")
    ] = False,
    frequency: Annotated[
        Frequency | None,
        typer.Option("--frequency", help="Only run pipelines published at this cadence."),
    ] = None,
) -> None:
    """Run every enabled pipeline. Exits 1 if any of them fails.

    ``--frequency`` restricts the run to one cadence, which is what the crontab
    emitted by ``pipeline schedule`` installs — and what an operator wants when
    re-running just the daily sources after a network problem, rather than
    sweeping all 23.
    """
    try:
        registry = ConnectorRegistry(load_catalog())
    except REIMError as exc:
        err(f"✗ {exc.message}", err=True)
        raise typer.Exit(EXIT_INVALID) from exc

    keys: list[str] | None = None
    if frequency is not None:
        entries = registry.catalog.sources if include_disabled else registry.catalog.enabled_sources
        keys = [entry.key for entry in entries if entry.frequency is frequency]
        if not keys:
            typer.echo(f"No pipelines are published at {frequency.value} cadence.")
            raise typer.Exit(EXIT_OK)

    outcomes = asyncio.run(
        PipelineRunner(registry).run_all(enabled_only=not include_disabled, keys=keys)
    )
    for outcome in outcomes:
        _print_outcome(outcome)

    failed = [outcome for outcome in outcomes if not outcome.succeeded]
    typer.echo(f"\n{len(outcomes) - len(failed)}/{len(outcomes)} pipeline(s) succeeded")
    raise typer.Exit(EXIT_FAILURE if failed else EXIT_OK)
```

Import `Frequency` from `reim.core.constants` if it is not already imported.

**An empty selection exits 0, not 1.** Asking for a cadence no source uses is not a failure — it is a correct answer to a reasonable question, and a cron line that exits 1 every night on an empty cadence would train the operator to ignore the mailer.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/integration/test_cli_schedule.py -q
```

Expected: 2 passed.

- [ ] **Step 5: Run the whole gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
git add reim/cli/main.py tests/integration/test_cli_schedule.py
git commit -m "feat(schedule): run one cadence at a time"
```

---

### Task 2: The emitter

**Files:**
- Create: `reim/domain/pipelines/schedule.py`
- Modify: `reim/domain/pipelines/__init__.py`
- Test: `tests/unit/test_schedule.py` (create)

**Interfaces:**
- Consumes: `SourceCatalog`, `SourceEntry` (`reim/domain/sources/catalog.py`), `Frequency` (`reim/core/constants.py`), `DEFAULT_CRON_BY_FREQUENCY` (`reim/domain/pipelines/scheduling.py`).
- Produces, relied on by Task 3:
  ```text
  FREQUENCY_MINUTES: dict[Frequency, int]
  ScheduleEntry(comment: str, expression: str, command: str)
  build_schedule(catalog, *, working_dir, python=".venv/bin/python") -> list[ScheduleEntry]
  render_crontab(entries) -> str
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_schedule.py`:

```python
"""``schedule.py``: turning a catalog into a crontab an operator can read.

Pure — a catalog and some strings in, text out — so all of it runs without a
database, a clock or a filesystem. The catalog-derived cases build their own
``SourceCatalog`` rather than reading the real one: the real catalog's frequency
mix is data that will change, and a test asserting "four blocks" would fail the
day someone adds a weekly source. One test below deliberately does read the real
catalog, for the one invariant worth pinning against real data.
"""

from __future__ import annotations

from pathlib import Path

from reim.core.constants import Frequency
from reim.domain.pipelines.schedule import (
    FREQUENCY_MINUTES,
    ScheduleEntry,
    build_schedule,
    render_crontab,
)
from reim.domain.pipelines.scheduling import DEFAULT_CRON_BY_FREQUENCY
from reim.domain.sources.catalog import SourceCatalog, SourceEntry, get_catalog

WORKING_DIR = Path("/opt/reim")


def _entry(key: str, frequency: Frequency, *, enabled: bool = True) -> SourceEntry:
    """A catalog entry that validates, varying only the key, cadence and state.

    Three of these values are load-bearing and cannot be swapped for
    plausible-looking alternatives: the host must not be a placeholder
    (``example.org`` and friends are rejected on an *enabled* source), a
    disabled source must carry a ``disabled_reason``, and ``connector`` is an
    all-lowercase **module** path — the field's pattern forbids a class name.
    """
    return SourceEntry(
        key=key,
        name=f"Source {key}",
        organization="BCN",
        category="exchange_rate",
        access_type="http_api",
        frequency=frequency,
        format="json",
        base_url="https://bcn.gob.ni/estadisticas",
        connector="reim.ingestion.connectors.nicaragua.bcn_exchange_rate",
        indicators=["ni_exchange_rate_official_daily"],
        enabled=enabled,
        disabled_reason=None if enabled else "licence forbids redistribution",
    )


def _catalog(*entries: SourceEntry) -> SourceCatalog:
    return SourceCatalog(version=1, sources=list(entries))


def _schedule(*entries: SourceEntry) -> list[ScheduleEntry]:
    return build_schedule(_catalog(*entries), working_dir=WORKING_DIR)


def test_only_cadences_present_in_the_catalog_get_a_block() -> None:
    """Seven frequencies exist; a crontab should carry only the ones in use.

    Blocks for cadences no source uses are noise the operator has to read and
    then delete.
    """
    entries = _schedule(_entry("a", Frequency.MONTHLY), _entry("b", Frequency.MONTHLY))

    ingestion = [entry for entry in entries if "run-all" in entry.command]
    assert len(ingestion) == 1
    assert "--frequency monthly" in ingestion[0].command


def test_each_cadence_gets_its_own_block() -> None:
    entries = _schedule(
        _entry("a", Frequency.DAILY),
        _entry("b", Frequency.MONTHLY),
        _entry("c", Frequency.ANNUAL),
    )

    cadences = [
        entry.command.split("--frequency ")[1] for entry in entries if "run-all" in entry.command
    ]
    assert sorted(cadences) == ["annual", "daily", "monthly"]


def test_the_emitter_rewrites_the_minute_and_nothing_else() -> None:
    """``DEFAULT_CRON_BY_FREQUENCY`` stays the authority on which days.

    A future edit that reformats more of the expression — the hour, or the day
    fields — fails here, which is the point: staggering is a minute-level
    concern and must not silently become a scheduling one.
    """
    for frequency in (Frequency.DAILY, Frequency.MONTHLY, Frequency.QUARTERLY):
        entries = _schedule(_entry("a", frequency))
        emitted = entries[0].expression.split()
        default = DEFAULT_CRON_BY_FREQUENCY[frequency].split()

        assert emitted[0] == str(FREQUENCY_MINUTES[frequency])
        assert emitted[1:] == default[1:]


def test_every_cadence_has_a_distinct_minute_inside_the_hour() -> None:
    """Two blocks sharing a minute would defeat the staggering entirely."""
    minutes = list(FREQUENCY_MINUTES.values())

    assert len(set(minutes)) == len(minutes)
    assert all(0 <= minute < 60 for minute in minutes)
    assert set(FREQUENCY_MINUTES) == set(Frequency)


def test_daily_keeps_the_top_of_the_hour() -> None:
    """It runs most often, so it is the one that should never move."""
    assert FREQUENCY_MINUTES[Frequency.DAILY] == 0


def test_each_block_names_the_pipelines_it_will_run() -> None:
    """``--frequency monthly`` is opaque; this output exists to be read first."""
    entries = _schedule(_entry("alpha", Frequency.MONTHLY), _entry("beta", Frequency.MONTHLY))

    block = next(entry for entry in entries if "run-all" in entry.command)
    assert "alpha" in block.comment
    assert "beta" in block.comment
    assert "2" in block.comment


def test_disabled_sources_are_absent_rather_than_commented_out() -> None:
    """The catalog records why a source is off; a commented line invites
    uncommenting it without reading that."""
    entries = _schedule(
        _entry("on", Frequency.MONTHLY), _entry("off", Frequency.WEEKLY, enabled=False)
    )
    text = render_crontab(entries)

    assert "off" not in text
    assert "weekly" not in text


def test_the_alert_check_is_emitted_last_and_after_the_ingestion_window() -> None:
    """Staleness is only meaningful once the day's ingestion has finished."""
    entries = _schedule(_entry("a", Frequency.DAILY))

    assert "alert check" in entries[-1].command
    ingestion_hour = int(entries[0].expression.split()[1])
    alert_hour = int(entries[-1].expression.split()[1])
    assert alert_hour > ingestion_hour


def test_an_empty_catalog_still_emits_the_alert_line() -> None:
    """A deployment with every source disabled still wants to hear about it."""
    entries = _schedule(_entry("off", Frequency.MONTHLY, enabled=False))

    assert len(entries) == 1
    assert "alert check" in entries[0].command


def test_the_rendered_text_is_shaped_like_a_crontab() -> None:
    """Five schedule fields then a command, on every non-comment line."""
    entries = _schedule(_entry("a", Frequency.DAILY), _entry("b", Frequency.MONTHLY))

    for line in render_crontab(entries).splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split(maxsplit=5)
        assert len(fields) == 6
        assert all(field for field in fields[:5])


def test_the_working_directory_reaches_every_command() -> None:
    entries = _schedule(_entry("a", Frequency.DAILY))

    for entry in entries:
        assert str(WORKING_DIR) in entry.command


def test_every_frequency_the_real_catalog_uses_has_a_default_expression() -> None:
    """The one invariant worth pinning against real data.

    Everything else here builds its own catalog, because the real one's
    frequency mix will change. This assertion is the opposite: it must track
    reality, and it fails the day a source arrives with a cadence nothing knows
    how to schedule.
    """
    for entry in get_catalog().sources:
        assert entry.frequency in DEFAULT_CRON_BY_FREQUENCY
        assert entry.frequency in FREQUENCY_MINUTES
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_schedule.py -q
```

Expected: `ModuleNotFoundError: No module named 'reim.domain.pipelines.schedule'`.

The `_entry` helper's field values were validated by constructing one before this plan was written, so they work as given. Three of them are load-bearing and cannot be swapped for plausible-looking alternatives: `organization` must exist in `ORGANIZATIONS_BY_CODE`, each `indicators` entry in `INDICATORS_BY_CODE`, and `connector` must match `^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)+$` — an **all-lowercase module path**, never a class path. `access_type` is one of `http`, `http_api`, `soap`, `file_download`, `manual` (`public` is not a member), and an enabled source may not use a host in `PLACEHOLDER_HOSTS` (`example.org`, `example.com`, `localhost`, …). The helper uses `model_copy` nowhere, because it skips validation and would let an invalid entry through unnoticed.

- [ ] **Step 3: Write the module**

Create `reim/domain/pipelines/schedule.py`:

```python
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


def _stagger(frequency: Frequency) -> str:
    """Return this cadence's expression with only its minute rewritten."""
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

    Disabled sources are never scheduled, and there is no parameter to include
    them. The catalog records why each one is off, and ``disabled_reason`` may
    be a licence that forbids redistribution — a commented cron line invites
    uncommenting it without reading that, and a flag that emits one is worse,
    because a crontab runs unattended. An operator wanting to see what is
    disabled has ``reim pipeline list``.
    """
    sources = catalog.enabled_sources
    prefix = f"cd {working_dir} && {python} -m reim.cli"

    by_frequency: dict[Frequency, list[str]] = {}
    for source in sources:
        by_frequency.setdefault(source.frequency, []).append(source.key)

    entries = [
        ScheduleEntry(
            comment=(f"{frequency.value} — {len(keys)} pipeline(s): {', '.join(sorted(keys))}"),
            expression=_stagger(frequency),
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
```

Export `ScheduleEntry`, `build_schedule` and `render_crontab` from `reim/domain/pipelines/__init__.py`, beside the existing `PipelineScheduler` exports, keeping `__all__` alphabetical.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_schedule.py -q
```

Expected: 12 passed.

- [ ] **Step 5: Prove the minute-only rule has teeth**

Temporarily change `_stagger` to rewrite the hour as well (`fields[1] = "14"`), and confirm `test_the_emitter_rewrites_the_minute_and_nothing_else` fails. Restore it. That test is the only thing keeping staggering a minute-level concern rather than a silent rescheduling.

- [ ] **Step 6: Run the whole gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
git add reim/domain/pipelines/ tests/unit/test_schedule.py
git commit -m "feat(schedule): turn the catalog's cadences into a crontab"
```

---

### Task 3: The command, and the documentation

**Files:**
- Modify: `reim/cli/main.py`, `README.md`, `ROADMAP.md`
- Test: `tests/integration/test_cli_schedule.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_cli_schedule.py`:

```python
def test_schedule_emits_a_crontab_for_the_real_catalog() -> None:
    result = runner.invoke(app, ["pipeline", "schedule"])

    assert result.exit_code == 0
    assert "pipeline run-all --frequency" in result.stdout
    assert "alert check" in result.stdout


def test_schedule_honours_the_working_directory() -> None:
    result = runner.invoke(app, ["pipeline", "schedule", "--working-dir", "/srv/reim"])

    assert result.exit_code == 0
    assert "cd /srv/reim" in result.stdout


def test_schedule_output_is_installable_as_written() -> None:
    """Every non-comment line must be five schedule fields then a command.

    This command exists to be piped into ``crontab -``; text that is merely
    informative would be a different feature.
    """
    result = runner.invoke(app, ["pipeline", "schedule"])

    for line in result.stdout.splitlines():
        if not line or line.startswith("#"):
            continue
        assert len(line.split(maxsplit=5)) == 6
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/pytest tests/integration/test_cli_schedule.py -q
```

Expected: failures reporting no such command `schedule`.

- [ ] **Step 3: Add the command**

In `reim/cli/main.py`, beside the other `pipeline` commands:

```python
@pipeline_app.command("schedule")
def pipeline_schedule(
    working_dir: Annotated[
        Path | None,
        typer.Option("--working-dir", help="Directory the cron lines cd into."),
    ] = None,
) -> None:
    """Print a crontab fragment scheduling each cadence, plus the alert check.

    Nothing is installed and no file is written: the output goes to stdout for
    the operator to review and pipe where they want it. A tool that edits a live
    crontab is a tool that can silently delete one.
    """
    try:
        catalog = load_catalog()
    except REIMError as exc:
        err(f"✗ {exc.message}", err=True)
        raise typer.Exit(EXIT_INVALID) from exc

    entries = build_schedule(catalog, working_dir=working_dir or Path.cwd())
    typer.echo(render_crontab(entries), nl=False)
    raise typer.Exit(EXIT_OK)
```

Add the imports it needs (`Path` from `pathlib` if absent, and `build_schedule`/`render_crontab` from `reim.domain.pipelines.schedule`).

- [ ] **Step 4: Run the tests and see it for real**

```bash
.venv/bin/pytest tests/integration/test_cli_schedule.py -q
.venv/bin/python -m reim.cli pipeline schedule --working-dir /opt/reim
```

Expected: 5 passed, and a crontab with four ingestion blocks (daily, monthly, quarterly, annual — the cadences the enabled catalog uses today) plus the alert line. Paste the actual output into your report: this is the artefact the increment exists to produce, and it should be readable without explanation.

- [ ] **Step 5: Update the README**

Replace the hand-written cron example in the **Scheduling** section with the command. Keep the section's existing claim that REIM has no built-in scheduler by design — it is still true, and this command is why it stays true. Show `pipeline schedule` and a short excerpt of its output, explain that each line runs one cadence, note that `--frequency` also works on its own for re-running a subset, and say plainly that nothing is installed for you. Fence samples as ` ```text `, never ` ```python `.

Also update the **Operational alerts** section's suggested cron line to point at `pipeline schedule` rather than repeating a hand-written line, so there is one place that knows the schedule.

- [ ] **Step 6: Update the ROADMAP**

Replace the `**Scheduler integration**` bullet under `## v0.5.0 — Operations` with a struck-through `✅ **done** — ` entry. **Check the format against its siblings first**: 19 of 20 completed entries use `✅ **done** — ` with an em-dash, and the two entries already in this section follow it.

Convey: that the command emits an installable crontab rather than implementing a scheduler, and why — the operator's cron stays the scheduler, as the README has said since the MVP; that cadences come from the catalog, so the two daily sources stop waiting for a monthly sweep; that the emitter rewrites only the minute, staggering cadences that would otherwise all start at 13:00; and that `PipelineScheduler` remains an unimplemented seam, deliberately.

- [ ] **Step 7: Check the formatter and commit**

```bash
.venv/bin/ruff format . && git diff --stat
```

Expect no formatter change to `README.md` or `ROADMAP.md`. Then:

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
git add reim/cli/main.py tests/integration/test_cli_schedule.py README.md ROADMAP.md
git commit -m "feat(schedule): a crontab to review, not a scheduler to run"
```

---

## Done when

* `reim pipeline schedule` prints an installable crontab covering every cadence the enabled catalog uses, plus the alert check, and installs nothing.
* Each block names the pipelines it will run, and that list matches what `--frequency` selects.
* The emitter rewrites only the minute — pinned by a test whose mutation (also rewriting the hour) makes it fail.
* `reim pipeline run-all --frequency daily` runs only the daily sources, and exits 0 when a cadence has none.
* The full gate passes: `ruff check`, `ruff format --check`, `mypy reim apps`, `pytest -q`.
* `README.md` shows the command instead of a hand-written cron line, and `ROADMAP.md` marks the item done.
