# Pipeline Alerting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `reim alert check` — a cron'd command that evaluates four conditions across every enabled pipeline, posts one digest to a webhook, and stays quiet until something changes.

**Architecture:** Staleness is read from the `MetricsSnapshot` the last increment built, never re-derived. Evaluation (`reim/services/alert_rules.py`) and reconciliation against stored state (`reim/services/alert_reconcile.py`) are **pure functions**, which is where the exhaustive tests go; the service does only session I/O, delivery and state writes. A new `alert_states` table gives suppression and recovery notices.

Both pure modules sit under `reim/services/` rather than `reim/domain/`, even though they hold no I/O, because they consume `MetricsSnapshot` — and a `reim/domain/` module importing from `reim/services/` would invert the layering the rest of the repository keeps. Purity is a property of the functions, stated in their docstrings and enforced by their tests needing no database; it is not a property of the directory. The flat module names also match `reim/services/`'s existing convention rather than introducing its first sub-package.

**Tech Stack:** SQLAlchemy 2 (PostgreSQL), Alembic, Typer, httpx + tenacity, Pydantic Settings, pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-12-pipeline-alerting-design.md`

## Global Constraints

* **Staleness comes from `build_metrics_snapshot`, never re-derived** (spec D4). The threshold comparison is policy, and that policy lives in `sources/quality_rules.yml` alone.
* **Evaluation and reconciliation are pure** — no session, no `datetime.now()` inside them. `now` is always injected, so every boundary is testable.
* **State is recorded ONLY after a successful delivery** (spec D10). A webhook outage must make REIM repeat itself, never swallow an alert. Recording first is the one failure mode alerting may not have.
* **An unset `REIM_ALERT_WEBHOOK_URL` means alerting is off, not broken** (spec D9): still evaluate, still print, still exit non-zero.
* **Redirects are not followed for delivery** (spec D11).
* **Disabled pipelines are skipped entirely** (spec D12); **a pipeline that has never run stays silent** (spec D13).
* **`partial` is not a failure** — it wrote data, and the metrics increment already treats it as a success for freshness.
* **One digest POST per run**, not one per alert (spec D8).
* **The migration must satisfy `alembic check`.** The partial unique index has to be declared in `__table_args__` with `postgresql_where`, never hand-written in the migration, or the next branch fails `make migrate-check`. `downgrade()` is a plain `drop_table` — `enum_column` sets `native_enum=False`, so there is no PostgreSQL `TYPE` to drop.
* **The model must be exported from `reim/database/models/__init__.py`** or Alembic autogeneration produces an empty migration.
* **The verification gate, which must pass before every commit:**
  ```bash
  .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q
  ```
* **No `pip` in the venv** — use `.venv/bin/<tool>`. Integration tests need `REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim` exported **in the same shell command** as pytest; if tests skip, the URL was not exported and nothing was proven.
* **mypy strict** over `reim` and `apps`; `ruff` enforces a 100-character line limit and isort ordering. Test functions need `-> None`.
* `ruff format` rewrites ` ```python ` blocks in Markdown that are not valid standalone modules; fence such fragments as ` ```text `.

---

## File Structure

| File | Responsibility |
|---|---|
| `reim/repositories/pipeline_runs.py` *(modify)* | `latest_run_failed_checks` — the latest run's failed checks, with severity |
| `reim/services/metrics.py` *(modify)* | One field: `last_run_status` on `PipelineMetrics` |
| `reim/database/models/alerts.py` *(create)* | `AlertState` |
| `reim/database/models/__init__.py` *(modify)* | Export it, so autogeneration sees it |
| `alembic/versions/…` *(create)* | The project's second migration |
| `reim/repositories/alerts.py` *(create)* | `list_open`, `record_notified`, `mark_resolved` |
| `reim/core/config.py` *(modify)* | Four settings |
| `reim/services/alert_rules.py` *(create)* | `AlertCondition`, `Alert`, `evaluate` — pure |
| `reim/services/alert_reconcile.py` *(create)* | `reconcile` — pure |
| `reim/services/alerting.py` *(create)* | Payload, delivery, state writes, ordering |
| `reim/cli/main.py` *(modify)* | The `alert` group |
| `tests/unit/test_alert_rules.py` *(create)* | Every condition and boundary, no database |
| `tests/unit/test_alert_reconcile.py` *(create)* | Every transition, no database |
| `tests/integration/test_alert_repository.py` *(create)* | The state queries |
| `tests/integration/test_alerting_service.py` *(create)* | The full cycle, with an injected sender |
| `ROADMAP.md`, `README.md`, `.env.example` *(modify)* | Mark the item done; document the command and settings |

---

### Task 1: The data the rules need

**Files:**
- Modify: `reim/services/metrics.py`, `reim/repositories/pipeline_runs.py`
- Test: `tests/integration/test_metrics_service.py`, `tests/integration/test_metrics_repository.py`

**Interfaces:**
- Produces, relied on by Tasks 3 and 5:
  ```text
  PipelineMetrics.last_run_status: PipelineStatus | None   (new field)
  LatestFailedCheck(pipeline_key: str, check_name: str,
                    severity: CheckSeverity, failures: int)
  latest_run_failed_checks(session) -> list[LatestFailedCheck]
  ```

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_metrics_service.py`:

```python
@requires_db
def test_the_snapshot_reports_the_last_runs_status(seeded_session: Session) -> None:
    """``runs_by_status`` counts all history; alerting needs the latest outcome.

    Without this field the "last run failed" and "a run is stuck" conditions
    cannot be evaluated from the snapshot at all.
    """
    now = datetime.now(UTC)
    _make_run(
        seeded_session,
        pipeline_key="worldbank_ni_cpi_inflation",
        started_at=now - timedelta(days=1),
    )
    _make_run(
        seeded_session,
        pipeline_key="worldbank_ni_cpi_inflation",
        started_at=now,
        status=PipelineStatus.FAILED,
    )
    seeded_session.flush()

    metrics = _for(build_metrics_snapshot(seeded_session), "worldbank_ni_cpi_inflation")

    assert metrics.last_run_status is PipelineStatus.FAILED
    assert metrics.runs_by_status == {"success": 1, "failed": 1}


@requires_db
def test_a_pipeline_that_never_ran_has_no_last_run_status(seeded_session: Session) -> None:
    metrics = _for(build_metrics_snapshot(seeded_session), "worldbank_ni_cpi_inflation")

    assert metrics.last_run_status is None
```

Append to `tests/integration/test_metrics_repository.py` (its `_make_run` and `_make_check` helpers already exist; `_make_check` needs a `severity` parameter — add one defaulting to `CheckSeverity.ERROR` if it does not already take one):

```python
@requires_db
def test_only_the_latest_runs_failed_checks_are_reported(session: Session) -> None:
    """A check that failed last month must not read as failing now.

    ``summarize_failed_checks_by_pipeline`` counts all history, which is right
    for a monotonic counter and wrong for "is this pipeline failing today".
    """
    now = datetime.now(UTC)
    old = _make_run(session, pipeline_key="a", started_at=now - timedelta(days=30))
    _make_check(session, run=old, check_name="freshness")
    latest = _make_run(session, pipeline_key="a", started_at=now)
    _make_check(session, run=latest, check_name="range")

    rows = run_repo.latest_run_failed_checks(session)

    assert [(row.pipeline_key, row.check_name) for row in rows] == [("a", "range")]


@requires_db
def test_the_latest_run_checks_carry_their_severity(session: Session) -> None:
    run = _make_run(session, pipeline_key="a", started_at=datetime.now(UTC))
    _make_check(session, run=run, check_name="range", severity=CheckSeverity.WARNING)

    rows = run_repo.latest_run_failed_checks(session)

    assert rows[0].severity is CheckSeverity.WARNING
    assert rows[0].failures == 1


@requires_db
def test_a_passing_latest_run_reports_nothing(session: Session) -> None:
    run = _make_run(session, pipeline_key="a", started_at=datetime.now(UTC))
    _make_check(session, run=run, check_name="range", status=CheckStatus.PASSED)

    assert run_repo.latest_run_failed_checks(session) == []


@requires_db
def test_each_pipeline_reports_its_own_latest_run(session: Session) -> None:
    """One pipeline's stale failure must not be attributed to another's run."""
    now = datetime.now(UTC)
    for key in ("a", "b"):
        run = _make_run(session, pipeline_key=key, started_at=now)
        _make_check(session, run=run, check_name="freshness")

    rows = run_repo.latest_run_failed_checks(session)

    assert sorted(row.pipeline_key for row in rows) == ["a", "b"]
```

- [ ] **Step 2: Run them to verify they fail**

```bash
REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest tests/integration/test_metrics_service.py tests/integration/test_metrics_repository.py -q
```

Expected: `AttributeError` on `last_run_status` and on `latest_run_failed_checks`. If anything **skips**, the URL was not exported.

- [ ] **Step 3: Add `last_run_status`**

In `reim/services/metrics.py`, add to `PipelineMetrics` (after `last_run_duration_ms`):

```text
last_run_status: PipelineStatus | None
```

Import `PipelineStatus` from `reim.core.constants`, and in `_pipeline_metrics` add one argument beside the other `last_run` reads:

```text
last_run_status=last_run.status if last_run is not None else None,
```

Update the field's docstring note so the dataclass says why it exists: `runs_by_status` is cumulative, this is the latest outcome. **No new query** — `latest_runs_by_pipeline` already fetches whole rows.

- [ ] **Step 4: Add `latest_run_failed_checks`**

Append to `reim/repositories/pipeline_runs.py`:

```python
@dataclass(frozen=True)
class LatestFailedCheck:
    """One check that failed in a pipeline's most recent run."""

    pipeline_key: str
    check_name: str
    severity: CheckSeverity
    failures: int


def latest_run_failed_checks(session: Session) -> list[LatestFailedCheck]:
    """Return the failed checks of each pipeline's most recent run.

    ``summarize_failed_checks_by_pipeline`` counts every failure ever recorded,
    which is right for a monotonic counter and wrong for "is this pipeline
    failing now" — a check that broke once in March would read as a live
    problem forever. This restricts to the latest run per pipeline and carries
    the severity, so a caller can apply a floor.

    Ordered so two evaluations of identical data produce identical output.
    """
    latest = (
        select(PipelineRun.id, PipelineRun.pipeline_key)
        .distinct(PipelineRun.pipeline_key)
        .order_by(PipelineRun.pipeline_key, PipelineRun.started_at.desc())
        .subquery()
    )
    statement = (
        select(
            latest.c.pipeline_key,
            DataQualityCheck.check_name,
            DataQualityCheck.severity,
            func.count(DataQualityCheck.id).label("failures"),
        )
        .join(latest, DataQualityCheck.pipeline_run_id == latest.c.id)
        .where(DataQualityCheck.status == CheckStatus.FAILED)
        .group_by(latest.c.pipeline_key, DataQualityCheck.check_name, DataQualityCheck.severity)
        .order_by(latest.c.pipeline_key, DataQualityCheck.check_name)
    )
    return [
        LatestFailedCheck(
            pipeline_key=row.pipeline_key,
            check_name=row.check_name,
            severity=row.severity,
            failures=int(row.failures),
        )
        for row in session.execute(statement)
    ]
```

`CheckSeverity` is already imported in that module.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest tests/integration/test_metrics_service.py tests/integration/test_metrics_repository.py -q
```

- [ ] **Step 6: Prove the latest-run restriction has teeth**

Temporarily drop the `.join(latest, …)` restriction (join `PipelineRun` directly instead), and confirm `test_only_the_latest_runs_failed_checks_are_reported` fails by reporting both `freshness` and `range`. Restore it. Record the observed failure in your report; if it does not fail, stop and say so.

- [ ] **Step 7: Run the whole gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
git add reim/services/metrics.py reim/repositories/pipeline_runs.py tests/integration/
git commit -m "feat(alerts): report the last run's status, and only its failed checks"
```

---

### Task 2: The table, the migration, and its queries

**Files:**
- Create: `reim/database/models/alerts.py`, `reim/repositories/alerts.py`, one Alembic revision
- Modify: `reim/database/models/__init__.py`
- Test: `tests/integration/test_alert_repository.py`

**Interfaces:**
- Produces, relied on by Tasks 4 and 5:
  ```text
  AlertState  (table alert_states)
  OpenAlert(condition: str, pipeline_key: str,
            first_notified_at: datetime, last_notified_at: datetime)
  list_open(session) -> list[OpenAlert]
  record_notified(session, *, condition, pipeline_key, details, now) -> None
  mark_resolved(session, *, condition, pipeline_key, now) -> None
  ```
  `condition` is passed as a `str` here so this layer does not import the domain enum; Task 3 owns `AlertCondition` and Task 5 converts.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_alert_repository.py`:

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

```bash
REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest tests/integration/test_alert_repository.py -q
```

Expected: `ModuleNotFoundError: No module named 'reim.repositories.alerts'`.

- [ ] **Step 3: Create the model**

Create `reim/database/models/alerts.py`:

```python
"""Alert bookkeeping: what has been notified, and whether it has recovered."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from reim.database.base import Base, UUIDPrimaryKeyMixin


class AlertState(UUIDPrimaryKeyMixin, Base):
    """One alert condition on one pipeline, and when it was last spoken about.

    Deliberately not a ``TimestampMixin`` table. That mixin's ``updated_at``
    refreshes on every flush, including the one that sets ``resolved_at``, so it
    would sit beside ``last_notified_at`` looking like the same fact while
    diverging from it. ``first_notified_at`` is this row's creation time.

    A row stays open until the condition stops holding; the partial unique index
    permits exactly one open row per ``(condition, pipeline_key)`` while letting
    resolved rows accumulate as history.
    """

    __tablename__ = "alert_states"

    condition: Mapped[str] = mapped_column(String(32), nullable=False)
    pipeline_key: Mapped[str] = mapped_column(String(120), nullable=False)

    first_notified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_notified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Figures sent with the last notification, so a resolution notice can
    #: quote what the problem had been without recomputing it.
    details: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)

    __table_args__ = (
        Index(
            "uq_alert_states_open_condition_pipeline",
            "condition",
            "pipeline_key",
            unique=True,
            postgresql_where=resolved_at.is_(None),
        ),
        Index("ix_alert_states_pipeline_key", "pipeline_key"),
    )
```

> **Note on `condition`:** it is a plain `String(32)`, not an `enum_column`. The
> four values are owned by `AlertCondition` in the domain layer (Task 3), and a
> database `CHECK` constraint restating them would be a second definition of one
> fact — the same reasoning `order_failed_check_groups` gives for ordering
> severity in Python rather than in SQL. If you find the `postgresql_where`
> expression above does not type-check against the column defined in the same
> class body, declare the index in a `__table_args__` built from
> `sqlalchemy.text("resolved_at IS NULL")` instead, and say so in your report.

Add to `reim/database/models/__init__.py`: import `AlertState` and add it to `__all__`, keeping both alphabetical. **Autogeneration produces an empty migration if you skip this.**

- [ ] **Step 4: Generate and inspect the migration**

```bash
REIM_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim make revision MESSAGE="add alert_states"
```

Open the generated file. Confirm: `down_revision` is `"9b55f6392677"`; `upgrade()` creates the table, both indexes, and the partial index with its `postgresql_where`; `downgrade()` drops the table (a plain `op.drop_table` — `enum_column` is not used here and there is no PostgreSQL `TYPE` to drop). Replace any `### commands auto generated ###` comment blocks with nothing, and give the module a one-line docstring matching the initial migration's style.

- [ ] **Step 5: Verify the migration round-trips**

```bash
export REIM_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim
.venv/bin/alembic upgrade head && .venv/bin/alembic check && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head
```

`alembic check` reporting no drift is the discriminating test that the migration matches the model rather than merely running. If it reports the partial index as drift, the model's `__table_args__` is not describing what the migration created — fix the model, regenerate, do not hand-edit the migration to match.

- [ ] **Step 6: Write the repository**

Create `reim/repositories/alerts.py`:

```python
"""Query helpers for alert state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reim.database.models import AlertState


@dataclass(frozen=True)
class OpenAlert:
    """An alert that has been notified and has not yet resolved."""

    condition: str
    pipeline_key: str
    first_notified_at: datetime
    last_notified_at: datetime


def list_open(session: Session) -> list[OpenAlert]:
    """Return every alert still considered firing, oldest first."""
    statement = (
        select(AlertState)
        .where(AlertState.resolved_at.is_(None))
        .order_by(AlertState.first_notified_at, AlertState.condition, AlertState.pipeline_key)
    )
    return [
        OpenAlert(
            condition=row.condition,
            pipeline_key=row.pipeline_key,
            first_notified_at=row.first_notified_at,
            last_notified_at=row.last_notified_at,
        )
        for row in session.scalars(statement)
    ]


def record_notified(
    session: Session,
    *,
    condition: str,
    pipeline_key: str,
    details: dict[str, Any],
    now: datetime,
) -> None:
    """Open a new alert, or advance an existing one's last-notified time.

    ``first_notified_at`` is never moved on an open row: it is what tells an
    operator how long this has been broken.
    """
    existing = session.scalar(
        select(AlertState).where(
            AlertState.condition == condition,
            AlertState.pipeline_key == pipeline_key,
            AlertState.resolved_at.is_(None),
        )
    )
    if existing is not None:
        existing.last_notified_at = now
        existing.details = details
        return

    session.add(
        AlertState(
            condition=condition,
            pipeline_key=pipeline_key,
            first_notified_at=now,
            last_notified_at=now,
            details=details,
        )
    )
    session.flush()


def mark_resolved(session: Session, *, condition: str, pipeline_key: str, now: datetime) -> None:
    """Close the open alert for this condition and pipeline, if there is one."""
    existing = session.scalar(
        select(AlertState).where(
            AlertState.condition == condition,
            AlertState.pipeline_key == pipeline_key,
            AlertState.resolved_at.is_(None),
        )
    )
    if existing is not None:
        existing.resolved_at = now
        session.flush()
```

- [ ] **Step 7: Run the tests, then the whole gate and commit**

```bash
REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest tests/integration/test_alert_repository.py -q
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
git add reim/database/models/ reim/repositories/alerts.py alembic/versions/ tests/integration/test_alert_repository.py
git commit -m "feat(alerts): remember what has been said, and what has recovered"
```

---

### Task 3: The settings and the four conditions

**Files:**
- Create: `reim/services/alert_rules.py`
- Modify: `reim/core/config.py`
- Test: `tests/unit/test_alert_rules.py`

**Interfaces:**
- Consumes: `MetricsSnapshot`, `PipelineMetrics` (with `last_run_status` from Task 1), `LatestFailedCheck` (Task 1), `CheckSeverity`, `PipelineStatus`, `SEVERITY_ORDER` (`reim/core/constants.py`).
- Produces, relied on by Tasks 4 and 5:
  ```text
  AlertCondition: StrEnum with STALE/FAILED_RUN/STUCK_RUN/QUALITY
  Alert(condition: AlertCondition, pipeline_key: str, severity: CheckSeverity,
        summary: str, details: dict[str, Any])
  evaluate(snapshot, failed_checks, *, severity_floor, stuck_run_after, now) -> list[Alert]
  ```
  `failed_checks` is a `Sequence[LatestFailedCheck]`; `stuck_run_after` is a `timedelta`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_alert_rules.py`:

```python
"""``evaluate``: the four conditions, and every boundary they turn on.

Pure — a snapshot and a list of checks in, alerts out — so all of it runs
without a database, a clock or a webhook. The boundaries are where alerting
bugs live: an age exactly equal to its threshold, a run stuck for exactly the
grace period, a check one severity below the floor.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from reim.core.constants import CheckSeverity, PipelineStatus
from reim.services.alert_rules import AlertCondition, evaluate
from reim.repositories.pipeline_runs import LatestFailedCheck
from reim.services.metrics import MetricsSnapshot, PipelineMetrics

NOW = datetime(2026, 9, 12, 18, 0, tzinfo=UTC)


def _metrics(**overrides: Any) -> PipelineMetrics:
    """A healthy pipeline, so each test overrides only its own concern."""
    defaults: dict[str, Any] = {
        "pipeline_key": "bcn_fx",
        "enabled": True,
        "observations": 100,
        "data_age_days": 2,
        "freshness_max_age_days": 7,
        "last_run_at": NOW - timedelta(hours=1),
        "last_success_at": NOW - timedelta(hours=1),
        "last_run_duration_ms": 2_500,
        "last_run_status": PipelineStatus.SUCCESS,
        "last_run_records": dict.fromkeys(
            ("extracted", "inserted", "updated", "unchanged", "rejected"), 1
        ),
        "runs_by_status": {"success": 1},
        "records_total": dict.fromkeys(
            ("extracted", "inserted", "updated", "unchanged", "rejected"), 1
        ),
        "duration_ms_total": 2_500,
    }
    defaults.update(overrides)
    return PipelineMetrics(**defaults)  # type: ignore[arg-type]


def _evaluate(
    checks: list[LatestFailedCheck] | None = None,
    *,
    floor: CheckSeverity = CheckSeverity.ERROR,
    stuck_after: timedelta = timedelta(hours=6),
    **overrides: Any,
) -> list[Any]:
    snapshot = MetricsSnapshot(database_up=True, pipelines=(_metrics(**overrides),))
    return evaluate(
        snapshot,
        checks or [],
        severity_floor=floor,
        stuck_run_after=stuck_after,
        now=NOW,
    )


def test_a_healthy_pipeline_produces_nothing() -> None:
    assert _evaluate() == []


def test_data_older_than_its_threshold_is_stale() -> None:
    alerts = _evaluate(data_age_days=9, freshness_max_age_days=7)

    assert [alert.condition for alert in alerts] == [AlertCondition.STALE]
    assert alerts[0].details == {"data_age_days": 9, "freshness_max_age_days": 7}


def test_an_age_exactly_at_the_threshold_is_not_stale() -> None:
    """The threshold is a maximum tolerated age, so equal is still tolerated."""
    assert _evaluate(data_age_days=7, freshness_max_age_days=7) == []


def test_no_configured_threshold_never_goes_stale() -> None:
    """No policy means no verdict — the metrics design's absent-series rule."""
    assert _evaluate(data_age_days=9_000, freshness_max_age_days=None) == []


def test_a_source_holding_no_data_is_not_reported_as_stale() -> None:
    assert _evaluate(data_age_days=None) == []


def test_a_failed_last_run_alerts() -> None:
    alerts = _evaluate(last_run_status=PipelineStatus.FAILED)

    assert [alert.condition for alert in alerts] == [AlertCondition.FAILED_RUN]
    assert alerts[0].severity is CheckSeverity.ERROR


def test_a_partial_run_is_not_a_failure() -> None:
    """``partial`` wrote data; the metrics increment already counts it a success."""
    assert _evaluate(last_run_status=PipelineStatus.PARTIAL) == []


def test_a_run_still_running_past_the_grace_period_is_stuck() -> None:
    """A killed process leaves ``running`` forever and never becomes ``failed``."""
    alerts = _evaluate(
        last_run_status=PipelineStatus.RUNNING,
        last_run_at=NOW - timedelta(hours=7),
        stuck_after=timedelta(hours=6),
    )

    assert [alert.condition for alert in alerts] == [AlertCondition.STUCK_RUN]


def test_a_run_running_within_the_grace_period_is_not_stuck() -> None:
    assert (
        _evaluate(
            last_run_status=PipelineStatus.RUNNING,
            last_run_at=NOW - timedelta(hours=5),
            stuck_after=timedelta(hours=6),
        )
        == []
    )


def test_a_run_running_exactly_the_grace_period_is_not_stuck() -> None:
    """Equal is still tolerated — the same rule the staleness threshold follows.

    Without this, flipping ``<=`` to ``<`` in ``_stuck_run`` passes every other
    test, because the neighbouring cases sit a clear hour either side of the
    boundary rather than on it.
    """
    assert (
        _evaluate(
            last_run_status=PipelineStatus.RUNNING,
            last_run_at=NOW - timedelta(hours=6),
            stuck_after=timedelta(hours=6),
        )
        == []
    )


def test_a_pipeline_that_never_ran_stays_silent() -> None:
    """Adding a catalog entry must not page anyone about unstarted work."""
    assert (
        _evaluate(
            last_run_status=None,
            last_run_at=None,
            last_success_at=None,
            data_age_days=None,
        )
        == []
    )


def test_a_disabled_pipeline_is_skipped_entirely() -> None:
    assert _evaluate(enabled=False, last_run_status=PipelineStatus.FAILED) == []


def test_a_failed_check_at_the_floor_alerts() -> None:
    checks = [
        LatestFailedCheck(
            pipeline_key="bcn_fx", check_name="range", severity=CheckSeverity.ERROR, failures=3
        )
    ]

    alerts = _evaluate(checks, floor=CheckSeverity.ERROR)

    assert [alert.condition for alert in alerts] == [AlertCondition.QUALITY]
    assert alerts[0].details["checks"] == [
        {"check_name": "range", "severity": "error", "failures": 3}
    ]


def test_a_failed_check_below_the_floor_does_not_alert() -> None:
    checks = [
        LatestFailedCheck(
            pipeline_key="bcn_fx", check_name="range", severity=CheckSeverity.WARNING, failures=1
        )
    ]

    assert _evaluate(checks, floor=CheckSeverity.ERROR) == []


def test_the_quality_alert_takes_the_worst_severity_present() -> None:
    checks = [
        LatestFailedCheck(
            pipeline_key="bcn_fx", check_name="range", severity=CheckSeverity.ERROR, failures=1
        ),
        LatestFailedCheck(
            pipeline_key="bcn_fx",
            check_name="freshness",
            severity=CheckSeverity.CRITICAL,
            failures=1,
        ),
    ]

    alerts = _evaluate(checks, floor=CheckSeverity.ERROR)

    assert alerts[0].severity is CheckSeverity.CRITICAL


def test_checks_belonging_to_another_pipeline_are_ignored() -> None:
    checks = [
        LatestFailedCheck(
            pipeline_key="somewhere_else",
            check_name="range",
            severity=CheckSeverity.ERROR,
            failures=1,
        )
    ]

    assert _evaluate(checks, floor=CheckSeverity.ERROR) == []


def test_a_down_database_produces_no_alerts() -> None:
    """A snapshot that could not be built says nothing about any pipeline."""
    assert (
        evaluate(
            MetricsSnapshot(database_up=False),
            [],
            severity_floor=CheckSeverity.ERROR,
            stuck_run_after=timedelta(hours=6),
            now=NOW,
        )
        == []
    )


def test_one_pipeline_can_raise_several_conditions() -> None:
    checks = [
        LatestFailedCheck(
            pipeline_key="bcn_fx", check_name="range", severity=CheckSeverity.ERROR, failures=1
        )
    ]

    alerts = _evaluate(checks, data_age_days=9, last_run_status=PipelineStatus.FAILED)

    assert {alert.condition for alert in alerts} == {
        AlertCondition.STALE,
        AlertCondition.FAILED_RUN,
        AlertCondition.QUALITY,
    }


def test_every_alert_carries_a_summary_sentence() -> None:
    """The webhook payload is read by a human, not only by a rule."""
    alerts = _evaluate(data_age_days=9, last_run_status=PipelineStatus.FAILED)

    for alert in alerts:
        assert alert.summary
        assert alert.pipeline_key in alert.summary
    assert len({alert.summary for alert in alerts}) == len(alerts)
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_alert_rules.py -q
```

Expected: `ModuleNotFoundError: No module named 'reim.services.alert_rules'`.

- [ ] **Step 3: Add the settings**

In `reim/core/config.py`, after the metrics field, add a section following the file's existing comment style:

```text
# -- Alerting ---------------------------------------------------------
alert_webhook_url: str | None = None
alert_severity_floor: CheckSeverity = CheckSeverity.ERROR
alert_repeat_hours: int = Field(default=24, ge=1, le=720)
alert_stuck_run_hours: int = Field(default=6, ge=1, le=168)
```

Import `CheckSeverity` from `reim.core.constants`. There is no circular-import risk: `constants.py` imports only `__future__` and `enum`, verified before this plan was written.

- [ ] **Step 4: Write the rules module**

Create `reim/services/alert_rules.py`:

```python
"""The four conditions REIM alerts on, evaluated without touching anything.

Pure by construction: a :class:`~reim.services.metrics.MetricsSnapshot`, the
latest run's failed checks, and an injected ``now`` in; alerts out. No session,
no clock, no settings, which is why every boundary is asserted directly against
this function rather than inferred from a delivered notification.

Staleness is read from the snapshot rather than recomputed. The threshold
comparison is policy, and that policy lives in ``sources/quality_rules.yml``
alone — deriving it a second time here would put it in two places that could
disagree.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from reim.core.constants import SEVERITY_ORDER, CheckSeverity, PipelineStatus
from reim.repositories.pipeline_runs import LatestFailedCheck
from reim.services.metrics import MetricsSnapshot, PipelineMetrics


class AlertCondition(StrEnum):
    """What REIM will speak up about."""

    STALE = "stale"
    FAILED_RUN = "failed_run"
    STUCK_RUN = "stuck_run"
    QUALITY = "quality"


@dataclass(frozen=True)
class Alert:
    """One condition holding on one pipeline, ready to be notified."""

    condition: AlertCondition
    pipeline_key: str
    severity: CheckSeverity
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


def _stale(metrics: PipelineMetrics) -> Alert | None:
    """Data older than the maximum age configured for its indicators.

    Both figures must be present: no configured threshold means no policy, and
    no stored data means no age. Equality is not stale — the threshold is a
    maximum tolerated age, so being exactly at it is still tolerated.
    """
    age = metrics.data_age_days
    threshold = metrics.freshness_max_age_days
    if age is None or threshold is None or age <= threshold:
        return None
    return Alert(
        condition=AlertCondition.STALE,
        pipeline_key=metrics.pipeline_key,
        severity=CheckSeverity.WARNING,
        summary=(
            f"{metrics.pipeline_key} has no data newer than {age} days, "
            f"past its {threshold}-day threshold."
        ),
        details={"data_age_days": age, "freshness_max_age_days": threshold},
    )


def _failed_run(metrics: PipelineMetrics) -> Alert | None:
    """The most recent run failed outright.

    ``partial`` is not a failure: it wrote data, which is why freshness already
    counts it as a success.
    """
    if metrics.last_run_status is not PipelineStatus.FAILED:
        return None
    return Alert(
        condition=AlertCondition.FAILED_RUN,
        pipeline_key=metrics.pipeline_key,
        severity=CheckSeverity.ERROR,
        summary=f"{metrics.pipeline_key}'s most recent run failed.",
        details={"last_run_at": _iso(metrics.last_run_at)},
    )


def _stuck_run(
    metrics: PipelineMetrics, *, stuck_run_after: timedelta, now: datetime
) -> Alert | None:
    """A run still marked ``running`` long after it started.

    The runner writes its row before extraction and finalises it in a
    ``finally`` block, so a process killed outright leaves ``running`` forever.
    It never becomes ``failed``, so nothing else notices it.
    """
    if metrics.last_run_status is not PipelineStatus.RUNNING or metrics.last_run_at is None:
        return None
    stuck_for = now - metrics.last_run_at
    if stuck_for <= stuck_run_after:
        return None
    hours = int(stuck_for.total_seconds() // 3600)
    return Alert(
        condition=AlertCondition.STUCK_RUN,
        pipeline_key=metrics.pipeline_key,
        severity=CheckSeverity.ERROR,
        summary=(
            f"{metrics.pipeline_key} has a run still marked running after {hours} hours, "
            "which usually means the process was killed."
        ),
        details={"last_run_at": _iso(metrics.last_run_at), "stuck_hours": hours},
    )


def _quality(
    metrics: PipelineMetrics,
    checks: Sequence[LatestFailedCheck],
    *,
    severity_floor: CheckSeverity,
) -> Alert | None:
    """The latest run recorded a failed check at or above the floor."""
    floor = SEVERITY_ORDER[severity_floor]
    relevant = [
        check
        for check in checks
        if check.pipeline_key == metrics.pipeline_key and SEVERITY_ORDER[check.severity] >= floor
    ]
    if not relevant:
        return None
    worst = max(relevant, key=lambda check: SEVERITY_ORDER[check.severity])
    names = ", ".join(sorted(check.check_name for check in relevant))
    return Alert(
        condition=AlertCondition.QUALITY,
        pipeline_key=metrics.pipeline_key,
        severity=worst.severity,
        summary=(
            f"{metrics.pipeline_key}'s most recent run failed {len(relevant)} quality "
            f"check(s) at {worst.severity.value} or worse: {names}."
        ),
        details={
            "checks": [
                {
                    "check_name": check.check_name,
                    "severity": check.severity.value,
                    "failures": check.failures,
                }
                for check in relevant
            ]
        },
    )


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat()


def evaluate(
    snapshot: MetricsSnapshot,
    failed_checks: Sequence[LatestFailedCheck],
    *,
    severity_floor: CheckSeverity,
    stuck_run_after: timedelta,
    now: datetime,
) -> list[Alert]:
    """Return every condition currently holding, across every enabled pipeline.

    A snapshot whose database was unreachable says nothing about any pipeline,
    so it produces nothing: reporting 23 pipelines as broken because one query
    failed would be worse than silence, and the outage is already visible as
    ``reim_database_up 0``.

    Disabled pipelines are skipped entirely — the catalog records the intent
    that nobody should be paged about them.
    """
    if not snapshot.database_up:
        return []

    alerts: list[Alert] = []
    for metrics in snapshot.pipelines:
        if not metrics.enabled:
            continue
        candidates = (
            _stale(metrics),
            _failed_run(metrics),
            _stuck_run(metrics, stuck_run_after=stuck_run_after, now=now),
            _quality(metrics, failed_checks, severity_floor=severity_floor),
        )
        alerts.extend(alert for alert in candidates if alert is not None)
    return alerts
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_alert_rules.py -q
```

Expected: 19 passed.

- [ ] **Step 6: Prove the threshold boundary has teeth**

This task has **two** equality boundaries and both get the drill, because a boundary tested from only one side is not pinned at all.

1. Change `age <= threshold` to `age < threshold` in `_stale`, confirm `test_an_age_exactly_at_the_threshold_is_not_stale` fails, and restore it. An off-by-one here would page an operator every single day about a source behaving exactly as configured.
2. Change `stuck_for <= stuck_run_after` to `stuck_for < stuck_run_after` in `_stuck_run`, confirm `test_a_run_running_exactly_the_grace_period_is_not_stuck` fails — and that the 5-hour and 7-hour tests still pass, which is why the equality case had to be added. Restore it.

If either mutation does not fail, stop and report it rather than working around it.

- [ ] **Step 7: Run the whole gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
git add reim/core/config.py reim/services/alert_rules.py tests/unit/test_alert_rules.py
git commit -m "feat(alerts): the four conditions, and the boundaries they turn on"
```

---

### Task 4: Reconciliation — what to say, and what to leave unsaid

**Files:**
- Create: `reim/services/alert_reconcile.py`
- Test: `tests/unit/test_alert_reconcile.py`

**Interfaces:**
- Consumes: `Alert`, `AlertCondition` (Task 3), `OpenAlert` (Task 2).
- Produces, relied on by Task 5:
  ```text
  Reconciliation(new: tuple[Alert, ...], repeat: tuple[Alert, ...],
                 resolved: tuple[OpenAlert, ...], suppressed: tuple[Alert, ...])
  Reconciliation.has_changes -> bool      # new or repeat or resolved
  Reconciliation.firing -> tuple[Alert, ...]   # new + repeat + suppressed
  reconcile(alerts, open_alerts, *, repeat_after, now) -> Reconciliation
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_alert_reconcile.py`:

```python
"""``reconcile``: the difference between what is true and what has been said.

This is the whole reason for the state table, and it is pure, so the full
lifecycle — fire, suppress, re-notify, resolve — is asserted here without a
database or a webhook.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from reim.core.constants import CheckSeverity
from reim.services.alert_reconcile import reconcile
from reim.services.alert_rules import Alert, AlertCondition
from reim.repositories.alerts import OpenAlert

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
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_alert_reconcile.py -q
```

Expected: `ModuleNotFoundError: No module named 'reim.services.alert_reconcile'`.

- [ ] **Step 3: Write the reconciler**

Create `reim/services/alert_reconcile.py`:

```python
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

from reim.services.alert_rules import Alert
from reim.repositories.alerts import OpenAlert


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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_alert_reconcile.py -q
```

Expected: 10 passed.

- [ ] **Step 5: Prove the suppression test has teeth**

Remove the `suppressed` branch so every firing alert is treated as `repeat`, and confirm `test_a_condition_just_notified_is_suppressed` fails. Restore it. Without that branch the feature is exactly the notification storm it exists to prevent.

- [ ] **Step 6: Run the whole gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
git add reim/services/alert_reconcile.py tests/unit/test_alert_reconcile.py
git commit -m "feat(alerts): say it once, say it again tomorrow, say when it recovers"
```

---

### Task 5: The service — payload, delivery, and the order that matters

**Files:**
- Create: `reim/services/alerting.py`
- Test: `tests/integration/test_alerting_service.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4, plus `http_client` and `post` (`reim/ingestion/http.py:72,188`) and `ExtractionError` (`reim/core/exceptions.py:71`).
- Produces, relied on by Task 6:
  ```text
  AlertDeliveryError(REIMError)          # code = "alert_delivery_error"
  Sender = Callable[[bytes], Awaitable[None]]
  build_payload(reconciliation, *, environment, now) -> bytes
  async run_alert_check(session, *, settings=None, send=None, now=None,
                        dry_run=False) -> Reconciliation
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_alerting_service.py`:

```python
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
```

> **On async tests:** `pyproject.toml:148` sets `asyncio_mode = "auto"`, so
> these need no `@pytest.mark.asyncio` marker — an `async def test_…` is
> collected and awaited as it stands. Do not add one.
>
> **On constructing `Settings` directly:** no existing test does, so this is a
> first. It is safe because init keyword arguments outrank environment variables
> and `.env` in pydantic-settings' default precedence, so `alert_webhook_url=None`
> stays `None` even on a machine that exports `REIM_ALERT_WEBHOOK_URL`. If you
> find otherwise, report it rather than working around it.

- [ ] **Step 2: Run them to verify they fail**

```bash
REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest tests/integration/test_alerting_service.py -q
```

Expected: `ModuleNotFoundError: No module named 'reim.services.alerting'`.

- [ ] **Step 3: Write the service**

Create `reim/services/alerting.py`:

```python
"""Evaluating, delivering and remembering alerts.

The interesting logic is not here: evaluation lives in
``reim.services.alert_rules`` and reconciliation in
``reim.services.alert_reconcile``, both pure. This module does the I/O around
them, and owns one ordering decision that matters more than the rest of it —
state is recorded only after a delivery succeeds.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from reim.core.config import Settings, get_settings
from reim.core.exceptions import ExtractionError, REIMError
from reim.services.alert_reconcile import Reconciliation, reconcile
from reim.services.alert_rules import evaluate
from reim.ingestion.http import http_client, post
from reim.repositories import alerts as alert_repo
from reim.repositories import pipeline_runs as run_repo
from reim.services.metrics import build_metrics_snapshot

#: Version of the webhook payload shape. Bump only for a breaking change.
PAYLOAD_VERSION = 1

#: A delivery mechanism: hand it an encoded body, it gets there or raises.
Sender = Callable[[bytes], Awaitable[None]]


class AlertDeliveryError(REIMError):
    """An alert could not be delivered."""

    code = "alert_delivery_error"


def build_payload(reconciliation: Reconciliation, *, environment: str, now: datetime) -> bytes:
    """Render one run's changes as the webhook body.

    One digest per run rather than one request per alert: a database that was
    down during the nightly sweep is one message, not twenty-three.
    """
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
            }
            for alert in reconciliation.new + reconciliation.repeat
        ],
        "resolved": [
            {
                "condition": row.condition,
                "pipeline_key": row.pipeline_key,
                "summary": f"{row.pipeline_key} no longer reports {row.condition}.",
                "first_notified_at": row.first_notified_at.isoformat(),
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
        raise AlertDeliveryError(f"Could not deliver alerts to {url}: {exc.message}") from exc

    if response.status_code >= 300:
        msg = f"Webhook at {url} answered HTTP {response.status_code}"
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

    **State is written only after the delivery succeeds.** A webhook that is
    down must cost noise, never an alert: nothing is marked notified, so the
    next run says it again. Recording first and delivering after would lose an
    alert permanently on a transient failure.
    """
    resolved_settings = settings or get_settings()
    moment = now or datetime.now(UTC)

    snapshot = build_metrics_snapshot(session, today=moment.date())
    failed_checks = run_repo.latest_run_failed_checks(session)

    alerts = evaluate(
        snapshot,
        failed_checks,
        severity_floor=resolved_settings.alert_severity_floor,
        stuck_run_after=timedelta(hours=resolved_settings.alert_stuck_run_hours),
        now=moment,
    )
    result = reconcile(
        alerts,
        alert_repo.list_open(session),
        repeat_after=timedelta(hours=resolved_settings.alert_repeat_hours),
        now=moment,
    )

    if not result.has_changes or dry_run:
        return result

    url = resolved_settings.alert_webhook_url
    if send is None and not url:
        return result

    body = build_payload(result, environment=resolved_settings.environment.value, now=moment)
    if send is not None:
        await send(body)
    else:
        assert url  # narrowed by the guard above
        await _post_to_webhook(url, body, resolved_settings)

    for alert in result.new + result.repeat:
        alert_repo.record_notified(
            session,
            condition=alert.condition.value,
            pipeline_key=alert.pipeline_key,
            details=alert.details,
            now=moment,
        )
    for row in result.resolved:
        alert_repo.mark_resolved(
            session, condition=row.condition, pipeline_key=row.pipeline_key, now=moment
        )
    session.flush()
    return result
```

> **If `assert url` trips a lint rule** (`S101` is not in the selected set, but
> check), replace it with an explicit `if url is None: raise AlertDeliveryError(...)`
> and note the change.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest tests/integration/test_alerting_service.py -q
```

Expected: 9 passed.

- [ ] **Step 5: Prove the ordering has teeth**

Move the two `alert_repo` loops to **before** the `await send(body)` call and confirm `test_a_failed_delivery_records_nothing_so_the_next_run_retries` fails — the second run should find nothing new because the first run recorded an alert it never delivered. Restore the original order. This is the single most important assertion in the increment: the reordered version loses alerts silently.

- [ ] **Step 6: Run the whole gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
git add reim/services/alerting.py tests/integration/test_alerting_service.py
git commit -m "feat(alerts): deliver first, remember second"
```

---

### Task 6: The command, and the documentation

**Files:**
- Modify: `reim/cli/main.py`, `ROADMAP.md`, `README.md`, `.env.example`
- Test: `tests/integration/test_alerting_service.py` (extend, or a small CLI test if the suite has a pattern for one)

**Interfaces:**
- Consumes: `run_alert_check`, `AlertDeliveryError` (Task 5).

- [ ] **Step 1: Add the CLI group**

In `reim/cli/main.py`, beside the other groups:

```text
alert_app = typer.Typer(help="Evaluate and deliver operational alerts.", no_args_is_help=True)
app.add_typer(alert_app, name="alert")
```

Then the command, following `quality_report`'s shape — `session_scope()`, `err()` for stderr, and `typer.Exit` with the module's exit constants:

```python
@alert_app.command("check")
def alert_check(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Evaluate and print without delivering or recording."),
    ] = False,
) -> None:
    """Evaluate alert conditions and deliver what changed. Exits 1 if anything is firing.

    Intended for cron, beside the ingestion jobs. The exit code reflects whether
    anything is wrong, not whether a notification was sent, so a cron job
    watching the status keeps seeing a failure while an alert is merely being
    suppressed.
    """
    with session_scope() as session:
        try:
            result = asyncio.run(run_alert_check(session, dry_run=dry_run))
        except AlertDeliveryError as exc:
            err(f"✗ {exc.message}", err=True)
            raise typer.Exit(EXIT_FAILURE) from exc

    for alert in result.firing:
        typer.echo(f"{alert.severity.value:8} {alert.condition.value:12} {alert.summary}")
    for row in result.resolved:
        typer.echo(f"{'resolved':8} {row.condition:12} {row.pipeline_key}")

    if not result.firing and not result.resolved:
        typer.echo("No alert conditions are firing.")
        raise typer.Exit(EXIT_OK)
    if result.firing:
        raise typer.Exit(EXIT_FAILURE)
    raise typer.Exit(EXIT_OK)
```

Check how `err` is defined in that module and match it; if the existing commands use `typer.echo(..., err=True)` directly, do that instead.

- [ ] **Step 2: Verify it runs against the real database**

```bash
export REIM_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim
.venv/bin/python -m reim.cli alert check --dry-run
.venv/bin/python -m reim.cli alert check --help
```

The local database holds seeded data, so expect either "No alert conditions are firing." or a list of stale pipelines with exit 1 — both are correct. Record what you saw. No webhook is configured, so nothing is delivered and nothing is recorded.

- [ ] **Step 3: Update `.env.example`**

Add the four settings with the commented explanations the file's existing entries use: that an unset `REIM_ALERT_WEBHOOK_URL` means alerting is off rather than broken; that the floor is one of `info`/`warning`/`error`/`critical`; that the repeat interval is how long REIM stays quiet about a problem it has already reported; and that the stuck-run threshold is how long a run may sit in `running` before it is assumed to have been killed.

- [ ] **Step 4: Update the ROADMAP**

In `ROADMAP.md`, replace the **Alerting** bullet under `## v0.5.0 — Operations` with a struck-through `✅ **done**` entry in the same style as the items above it. Convey: the four conditions, including `stuck_run` which the bullet did not name and why it exists; that evaluation is a cron'd CLI command because staleness is invisible from inside a run; that staleness is read from the metrics snapshot rather than re-derived, so the policy stays in `quality_rules.yml`; that a state table gives both suppression and recovery notices; and that state is recorded only after a successful delivery, so a webhook outage costs repetition rather than a lost alert.

- [ ] **Step 5: Update the README**

Add a short section documenting `reim alert check`: the four conditions, the four settings, the payload shape (fenced as ` ```text `), and the fact that an unset webhook URL degrades it to a print-and-exit-non-zero check. Mention the suggested cron line. Match the surrounding voice — plain declarative sentences, reasoning stated.

- [ ] **Step 6: Check the formatter and commit**

`ruff format` rewrites ` ```python ` blocks in Markdown, so both documents must use ` ```text ` for any sample:

```bash
.venv/bin/ruff format . && git diff --stat
```

Expect no formatter change to `ROADMAP.md`, `README.md` or `.env.example`. Then:

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
git add reim/cli/main.py ROADMAP.md README.md .env.example
git commit -m "feat(alerts): a command for cron, and what it promises"
```

---

## Done when

* `reim alert check` evaluates four conditions across enabled pipelines, delivers one digest per run, and exits 1 whenever anything is firing.
* A condition fires once, stays quiet for `REIM_ALERT_REPEAT_HOURS`, and sends exactly one resolution notice when it clears — pinned by an integration test that walks the whole sequence.
* A failed delivery records nothing, so the next run retries — pinned by a test whose mutation (recording before delivering) makes it fail.
* An unset webhook URL still evaluates, prints and exits non-zero.
* `make migrate-check` passes: the migration matches the model, and `downgrade -1` works.
* The full gate passes: `ruff check`, `ruff format --check`, `mypy reim apps`, `pytest -q`.
* `ROADMAP.md` marks the alerting item done; `README.md` and `.env.example` document the command and its settings.
