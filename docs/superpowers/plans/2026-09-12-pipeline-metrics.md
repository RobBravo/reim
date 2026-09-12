# Per-Pipeline Prometheus Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/metrics` reports per-pipeline volumes, durations and freshness — derived from the `pipeline_runs` table at scrape time — in a constant six queries, so a Prometheus alert rule can decide what is stale.

**Architecture:** Six grouped-aggregate repository queries replace the 115 round trips `build_pipeline_summaries` costs. A new `reim/services/metrics.py` holds two halves: `build_metrics_snapshot(session)` needs a session and returns frozen dataclasses; `render_snapshot(snapshot)` is pure and turns them into Prometheus text exposition. The endpoint concatenates the process-level defaults with the snapshot's families.

**Tech Stack:** FastAPI, SQLAlchemy 2 (PostgreSQL), `prometheus-client` 0.26.0, pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-12-pipeline-metrics-design.md`

## Global Constraints

* **Every metric is derived from `pipeline_runs` at scrape time.** Ingestion runs in a CLI process (`reim/cli/main.py:216`) that has exited before any scrape arrives, so in-process counters would never be visible, and a Pushgateway is the new infrastructure v0.5.0 rules out (spec D1).
* **No cache, no TTL.** The queries are cheap once aggregated in SQL (spec D3).
* **Six queries per scrape, flat in the number of catalog sources.** A per-source loop is the regression this whole increment exists to avoid (spec §3.1).
* **No `is_stale`, and no verdict of any kind.** Age and threshold ship as separate gauges; Prometheus does the comparison (spec D4).
* **An absent series, never a zero, when there is no threshold and when there is no data.** `0` reads as "permanently overdue" or "perfectly fresh" (spec D7). Counters are the exception and start at zero — see Task 5, Step 1.
* **`CounterMetricFamily`/`GaugeMetricFamily`, never `Counter`/`Gauge`.** The metric classes append a `_created` series holding the process start time, meaningless for a counter rebuilt from the database on every scrape (spec D9).
* **A counter family is constructed with its BASE name.** `CounterMetricFamily("reim_pipeline_runs", …)` renders as `reim_pipeline_runs_total`; passing `"reim_pipeline_runs_total"` renders `reim_pipeline_runs_total_total`. Verified against 0.26.0.
* **Base units.** Seconds, never milliseconds. Timestamps in Unix seconds.
* **Database availability is discovered by querying and catching `SQLAlchemyError`, never by a pre-check.** `check_database_connection()` must not appear in the new code (spec D11).
* **A database outage renders `reim_database_up 0` at status 200**, never a 500 (spec D10).
* **The verification gate, which must pass before every commit:**
  ```bash
  .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q
  ```
* **No `pip` in the venv** — use `.venv/bin/<tool>`. Integration tests need the test database: `make db-up CONTAINER_ENGINE=podman` prints the `export REIM_TEST_DATABASE_URL=…` line. Without it, `@requires_db` tests skip rather than fail.
* **mypy strict** over `reim` and `apps`. Test functions need `-> None`.
* `ruff format` rewrites ` ```python ` blocks in Markdown that are not valid standalone modules; fence such fragments as ` ```text `.

---

## File Structure

| File | Responsibility |
|---|---|
| `reim/repositories/pipeline_runs.py` *(modify)* | Four additions: the two `DISTINCT ON` latest-run helpers, the per-status totals, the failed-check join |
| `reim/repositories/observations.py` *(modify)* | `summarize_sources` — one `GROUP BY source_id` giving row count and newest period |
| `reim/repositories/reference.py` *(modify)* | `source_ids_by_key` — catalog key → `source_id` in one query |
| `reim/services/metrics.py` *(create)* | The frozen dataclasses, `build_metrics_snapshot` (needs a session), `render_snapshot` (pure) |
| `apps/api/routers/system.py` *(modify)* | `/metrics` gains `SessionDep` and the snapshot |
| `tests/integration/test_metrics_repository.py` *(create)* | The six queries against real PostgreSQL |
| `tests/integration/test_metrics_service.py` *(create)* | The snapshot, the outage path, the query-count pin |
| `tests/unit/test_metrics_render.py` *(create)* | Every rendering rule, no database |
| `tests/integration/test_metrics_endpoint.py` *(create)* | The endpoint, degradation, the 404 |
| `ROADMAP.md`, `README.md` *(modify)* | Mark v0.5.0's metrics item done; document the surface |

---

### Task 1: The run aggregates

**Files:**
- Modify: `reim/repositories/pipeline_runs.py`
- Test: `tests/integration/test_metrics_repository.py` (create)

**Interfaces:**
- Consumes: `PipelineRun`, `PipelineStatus` — already imported in that module.
- Produces, relied on by Task 4:
  ```text
  RunStatusAggregate(pipeline_key: str, status: PipelineStatus, runs: int,
                     records_extracted: int, records_inserted: int,
                     records_updated: int, records_unchanged: int,
                     records_rejected: int, duration_ms: int)
  latest_runs_by_pipeline(session) -> dict[str, PipelineRun]
  latest_successful_runs_by_pipeline(session) -> dict[str, PipelineRun]
  aggregate_runs_by_pipeline(session) -> list[RunStatusAggregate]
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_metrics_repository.py`:

```python
"""The grouped aggregates behind ``/metrics``, against real PostgreSQL.

``DISTINCT ON`` is PostgreSQL syntax and the nullable-``duration_ms`` sum is
PostgreSQL semantics, so these run against the database rather than being
mocked into agreement with themselves. Each one replaces a per-source loop, so
the assertions are about the grouping being right, not about speed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from reim.core.constants import PipelineStatus
from reim.database.models import PipelineRun
from reim.repositories import pipeline_runs as run_repo
from tests.conftest import requires_db


def _make_run(
    session: Session,
    *,
    pipeline_key: str,
    started_at: datetime,
    status: PipelineStatus = PipelineStatus.SUCCESS,
    duration_ms: int | None = 100,
    inserted: int = 0,
    unchanged: int = 0,
) -> PipelineRun:
    run = PipelineRun(
        id=uuid.uuid4(),
        pipeline_key=pipeline_key,
        started_at=started_at,
        status=status,
        duration_ms=duration_ms,
        records_inserted=inserted,
        records_unchanged=unchanged,
        created_at=started_at,
    )
    session.add(run)
    session.flush()
    return run


@requires_db
def test_the_latest_run_per_pipeline_is_the_newest_one(session: Session) -> None:
    now = datetime.now(UTC)
    _make_run(session, pipeline_key="a", started_at=now - timedelta(days=2))
    newest = _make_run(session, pipeline_key="a", started_at=now)
    _make_run(session, pipeline_key="b", started_at=now - timedelta(days=1))

    latest = run_repo.latest_runs_by_pipeline(session)

    assert set(latest) == {"a", "b"}
    assert latest["a"].id == newest.id


@requires_db
def test_the_latest_successful_run_accepts_partial_and_skips_failures(session: Session) -> None:
    """``partial`` wrote data, so it counts as a success for freshness."""
    now = datetime.now(UTC)
    partial = _make_run(
        session,
        pipeline_key="a",
        started_at=now - timedelta(hours=1),
        status=PipelineStatus.PARTIAL,
    )
    _make_run(session, pipeline_key="a", started_at=now, status=PipelineStatus.FAILED)

    latest = run_repo.latest_successful_runs_by_pipeline(session)

    assert latest["a"].id == partial.id


@requires_db
def test_a_pipeline_with_no_successful_run_is_absent_not_null(session: Session) -> None:
    """Absence is what the caller turns into a missing series, not a zero."""
    _make_run(
        session,
        pipeline_key="a",
        started_at=datetime.now(UTC),
        status=PipelineStatus.FAILED,
    )

    assert run_repo.latest_successful_runs_by_pipeline(session) == {}
    assert set(run_repo.latest_runs_by_pipeline(session)) == {"a"}


@requires_db
def test_the_totals_cover_every_run_not_only_the_last(session: Session) -> None:
    now = datetime.now(UTC)
    for index in range(3):
        _make_run(
            session,
            pipeline_key="a",
            started_at=now - timedelta(hours=index),
            duration_ms=200,
            inserted=10,
        )

    rows = run_repo.aggregate_runs_by_pipeline(session)

    assert len(rows) == 1
    assert rows[0].runs == 3
    assert rows[0].records_inserted == 30
    assert rows[0].duration_ms == 600


@requires_db
def test_the_totals_are_separated_by_status(session: Session) -> None:
    now = datetime.now(UTC)
    _make_run(session, pipeline_key="a", started_at=now, inserted=5)
    _make_run(
        session,
        pipeline_key="a",
        started_at=now - timedelta(hours=1),
        status=PipelineStatus.FAILED,
        inserted=0,
    )

    by_status = {row.status: row for row in run_repo.aggregate_runs_by_pipeline(session)}

    assert by_status[PipelineStatus.SUCCESS].runs == 1
    assert by_status[PipelineStatus.FAILED].runs == 1
    assert by_status[PipelineStatus.SUCCESS].records_inserted == 5


@requires_db
def test_a_crashed_run_with_no_duration_does_not_null_the_sum(session: Session) -> None:
    """``duration_ms`` is nullable: a run that crashed never got one.

    Without the coalesce, one crashed run makes the whole pipeline's duration
    total null, and the counter silently stops being exported.
    """
    now = datetime.now(UTC)
    _make_run(session, pipeline_key="a", started_at=now, duration_ms=None)
    _make_run(session, pipeline_key="a", started_at=now - timedelta(hours=1), duration_ms=500)

    rows = run_repo.aggregate_runs_by_pipeline(session)

    assert rows[0].duration_ms == 500
```

- [ ] **Step 2: Run them to verify they fail**

```bash
export REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim
.venv/bin/pytest tests/integration/test_metrics_repository.py -q
```

Expected: every test fails with `AttributeError: module 'reim.repositories.pipeline_runs' has no attribute 'latest_runs_by_pipeline'`. If they **skip** instead, `REIM_TEST_DATABASE_URL` is not exported — fix that before continuing, because a skipped test proves nothing.

- [ ] **Step 3: Add the aggregates**

In `reim/repositories/pipeline_runs.py`, extend the imports:

```text
from collections.abc import Sequence
from dataclasses import dataclass
```

Append to the module:

```python
@dataclass(frozen=True)
class RunStatusAggregate:
    """Cumulative totals for one pipeline in one status."""

    pipeline_key: str
    status: PipelineStatus
    runs: int
    records_extracted: int
    records_inserted: int
    records_updated: int
    records_unchanged: int
    records_rejected: int
    duration_ms: int


def _latest_by_pipeline(
    session: Session, *, statuses: Sequence[PipelineStatus] | None = None
) -> dict[str, PipelineRun]:
    """Return the newest run per pipeline in one query.

    Twenty-three ``latest_run`` calls is the right shape for one page load and
    the wrong one for a scrape every fifteen seconds. ``DISTINCT ON`` requires
    its ``ORDER BY`` to lead with the distinct column, which is why
    ``pipeline_key`` comes first and ``started_at`` descending still decides
    which row survives.
    """
    statement = (
        select(PipelineRun)
        .distinct(PipelineRun.pipeline_key)
        .order_by(PipelineRun.pipeline_key, PipelineRun.started_at.desc())
    )
    if statuses is not None:
        statement = statement.where(PipelineRun.status.in_(statuses))
    return {run.pipeline_key: run for run in session.scalars(statement)}


def latest_runs_by_pipeline(session: Session) -> dict[str, PipelineRun]:
    """Return every pipeline's most recent run, keyed by pipeline key."""
    return _latest_by_pipeline(session)


def latest_successful_runs_by_pipeline(session: Session) -> dict[str, PipelineRun]:
    """Return every pipeline's most recent run that did not fail.

    ``partial`` counts: it means some data was written, which is what a
    freshness gauge cares about.
    """
    return _latest_by_pipeline(session, statuses=[PipelineStatus.SUCCESS, PipelineStatus.PARTIAL])


def aggregate_runs_by_pipeline(session: Session) -> list[RunStatusAggregate]:
    """Return cumulative run, record and duration totals per pipeline and status.

    ``duration_ms`` is nullable — a run that crashed before finishing never got
    one — so its sum is coalesced, or a single crashed run would null the whole
    pipeline's total. The record counters are ``NOT NULL`` with a default of 0
    and every group holds at least one row, so their sums cannot be null;
    coalescing them too would imply a null is possible there.
    """
    statement = select(
        PipelineRun.pipeline_key,
        PipelineRun.status,
        func.count(PipelineRun.id).label("runs"),
        func.sum(PipelineRun.records_extracted).label("extracted"),
        func.sum(PipelineRun.records_inserted).label("inserted"),
        func.sum(PipelineRun.records_updated).label("updated"),
        func.sum(PipelineRun.records_unchanged).label("unchanged"),
        func.sum(PipelineRun.records_rejected).label("rejected"),
        func.coalesce(func.sum(PipelineRun.duration_ms), 0).label("duration_ms"),
    ).group_by(PipelineRun.pipeline_key, PipelineRun.status)

    return [
        RunStatusAggregate(
            pipeline_key=row.pipeline_key,
            status=row.status,
            runs=int(row.runs),
            records_extracted=int(row.extracted),
            records_inserted=int(row.inserted),
            records_updated=int(row.updated),
            records_unchanged=int(row.unchanged),
            records_rejected=int(row.rejected),
            duration_ms=int(row.duration_ms),
        )
        for row in session.execute(statement)
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/integration/test_metrics_repository.py -q
```

Expected: 6 passed.

- [ ] **Step 5: Prove the coalesce test has teeth**

Temporarily change `func.coalesce(func.sum(PipelineRun.duration_ms), 0)` to `func.sum(PipelineRun.duration_ms)`, run the tests, and confirm `test_a_crashed_run_with_no_duration_does_not_null_the_sum` fails with a `TypeError` on `int(None)`. Restore the coalesce. A test that passes either way is not protecting anything.

- [ ] **Step 6: Run the whole gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q
git add reim/repositories/pipeline_runs.py tests/integration/test_metrics_repository.py
git commit -m "feat(metrics): the newest run and the running totals, per pipeline, in two queries"
```

---

### Task 2: The source aggregates

**Files:**
- Modify: `reim/repositories/observations.py`, `reim/repositories/reference.py`
- Test: `tests/integration/test_metrics_repository.py` (extend)

**Interfaces:**
- Produces, relied on by Task 4:
  ```text
  SourceVolume(observations: int, latest_period_end: date | None)
  summarize_sources(session) -> dict[uuid.UUID, SourceVolume]
  source_ids_by_key(session) -> dict[str, uuid.UUID]
  ```

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_metrics_repository.py`, and add these imports at the top of the file:

```text
from reim.repositories import observations as observation_repo
from reim.repositories import reference as reference_repo
```

```python
@requires_db
def test_sources_are_summarized_in_one_pass(seeded_session: Session, make_observation) -> None:  # type: ignore[no-untyped-def]
    """Count and newest period for every source, without a query per source."""
    from reim.services.observation_writer import write_observations

    write_observations(
        seeded_session,
        [make_observation(str(year)) for year in (2020, 2021, 2022)],
        connector_version="1.0.0",
    )
    seeded_session.commit()

    source_ids = reference_repo.source_ids_by_key(seeded_session)
    volumes = observation_repo.summarize_sources(seeded_session)
    volume = volumes[source_ids["worldbank_ni_cpi_inflation"]]

    assert volume.observations == 3
    assert volume.latest_period_end is not None
    assert volume.latest_period_end.year == 2022


@requires_db
def test_a_source_holding_nothing_is_absent_rather_than_zero(seeded_session: Session) -> None:
    """Storing nothing and storing rows that cover nothing are different facts.

    The caller turns absence into a missing age series and a zero observation
    count; it cannot make that distinction if the repository flattens it here.
    """
    source_ids = reference_repo.source_ids_by_key(seeded_session)

    volumes = observation_repo.summarize_sources(seeded_session)

    assert volumes == {}
    assert "worldbank_ni_cpi_inflation" in source_ids


@requires_db
def test_every_registered_source_is_keyed_by_its_catalog_key(seeded_session: Session) -> None:
    source_ids = reference_repo.source_ids_by_key(seeded_session)

    assert len(source_ids) >= 23
    assert all(isinstance(value, uuid.UUID) for value in source_ids.values())
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/pytest tests/integration/test_metrics_repository.py -q -k "one_pass or absent_rather or catalog_key"
```

Expected: `AttributeError` on `summarize_sources` / `source_ids_by_key`.

- [ ] **Step 3: Add `summarize_sources`**

Append to `reim/repositories/observations.py` (`dataclass`, `uuid`, `date`, `func`, `select` and `Observation` are already imported):

```python
@dataclass(frozen=True)
class SourceVolume:
    """How much one source holds, and how recent it is."""

    observations: int
    latest_period_end: date | None


def summarize_sources(session: Session) -> dict[uuid.UUID, SourceVolume]:
    """Return row count and newest period per source, in one grouped pass.

    A source with no observations is absent from the mapping rather than
    present with a zero: "nothing stored" and "stored, covering nothing" read
    differently on a freshness dashboard, and the caller needs to keep them
    apart.
    """
    statement = select(
        Observation.source_id,
        func.count(Observation.id).label("observations"),
        func.max(Observation.period_end).label("latest_period_end"),
    ).group_by(Observation.source_id)

    return {
        row.source_id: SourceVolume(
            observations=int(row.observations),
            latest_period_end=row.latest_period_end,
        )
        for row in session.execute(statement)
    }
```

- [ ] **Step 4: Add `source_ids_by_key`**

Add `import uuid` to `reim/repositories/reference.py` and append:

```python
def source_ids_by_key(session: Session) -> dict[str, uuid.UUID]:
    """Return every registered source's id, keyed by its catalog key.

    One query in place of a ``get_source_by_key`` per catalog entry; the caller
    joins the catalog to what is stored in memory.
    """
    statement = select(DataSource.source_key, DataSource.id)
    return {row.source_key: row.id for row in session.execute(statement)}
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/integration/test_metrics_repository.py -q
```

Expected: 9 passed.

- [ ] **Step 6: Run the whole gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q
git add reim/repositories/observations.py reim/repositories/reference.py tests/integration/test_metrics_repository.py
git commit -m "feat(metrics): volume and newest period for every source, in one grouped query"
```

---

### Task 3: The failed-check join

**Files:**
- Modify: `reim/repositories/pipeline_runs.py`
- Test: `tests/integration/test_metrics_repository.py` (extend)

**Interfaces:**
- Produces, relied on by Tasks 4 and 5:
  ```text
  FailedCheckCount(pipeline_key: str, check_name: str, failures: int)
  summarize_failed_checks_by_pipeline(session) -> list[FailedCheckCount]
  ```

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_metrics_repository.py`, adding these imports at the top:

```text
from reim.core.constants import CheckSeverity, CheckStatus, CheckType
from reim.database.models import DataQualityCheck
```

```python
def _make_check(
    session: Session,
    *,
    run: PipelineRun,
    check_name: str,
    status: CheckStatus = CheckStatus.FAILED,
) -> None:
    session.add(
        DataQualityCheck(
            id=uuid.uuid4(),
            pipeline_run_id=run.id,
            check_name=check_name,
            check_type=CheckType.COMPLETENESS,
            status=status,
            severity=CheckSeverity.ERROR,
            created_at=run.started_at,
        )
    )
    session.flush()


@requires_db
def test_the_same_check_failing_in_two_pipelines_is_two_rows(session: Session) -> None:
    """The whole reason this is not ``summarize_failed_checks_by_name``.

    Grouped by name alone, an alert could say a freshness check is failing but
    not which pipeline to look at.
    """
    now = datetime.now(UTC)
    for key in ("a", "b", "a"):
        run = _make_run(session, pipeline_key=key, started_at=now)
        _make_check(session, run=run, check_name="freshness")

    counts = run_repo.summarize_failed_checks_by_pipeline(session)

    assert [(row.pipeline_key, row.failures) for row in counts] == [("a", 2), ("b", 1)]


@requires_db
def test_passing_checks_are_not_counted_as_failures(session: Session) -> None:
    run = _make_run(session, pipeline_key="a", started_at=datetime.now(UTC))
    _make_check(session, run=run, check_name="freshness", status=CheckStatus.PASSED)

    assert run_repo.summarize_failed_checks_by_pipeline(session) == []


@requires_db
def test_failed_check_counts_come_back_in_a_stable_order(session: Session) -> None:
    """Two renders of identical data must produce identical exposition text."""
    now = datetime.now(UTC)
    run = _make_run(session, pipeline_key="a", started_at=now)
    for name in ("range", "freshness", "completeness"):
        _make_check(session, run=run, check_name=name)

    counts = run_repo.summarize_failed_checks_by_pipeline(session)

    assert [row.check_name for row in counts] == ["completeness", "freshness", "range"]
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/pytest tests/integration/test_metrics_repository.py -q -k "two_rows or not_counted or stable_order"
```

Expected: `AttributeError: … has no attribute 'summarize_failed_checks_by_pipeline'`.

- [ ] **Step 3: Add the join**

Append to `reim/repositories/pipeline_runs.py`:

```python
@dataclass(frozen=True)
class FailedCheckCount:
    """How many times one check has failed in one pipeline."""

    pipeline_key: str
    check_name: str
    failures: int


def summarize_failed_checks_by_pipeline(session: Session) -> list[FailedCheckCount]:
    """Return failed-check counts grouped by pipeline and check name.

    ``summarize_failed_checks_by_name`` groups by name alone, which is what the
    observability page shows and is not enough for a metric: the same check
    failing on two pipelines has to be two series, or an alert can say a
    freshness check is failing without saying where to look.

    ``DataQualityCheck`` carries no ``pipeline_key``, so the pipeline comes from
    joining the run on the indexed ``pipeline_run_id``. This is a new function
    rather than a parameter on the existing one, whose caller's grouping must
    not change.

    Ordered in SQL so two renders of identical data produce identical
    exposition text, rather than whatever order the database happened to
    return.
    """
    statement = (
        select(
            PipelineRun.pipeline_key,
            DataQualityCheck.check_name,
            func.count(DataQualityCheck.id).label("failures"),
        )
        .join(PipelineRun, DataQualityCheck.pipeline_run_id == PipelineRun.id)
        .where(DataQualityCheck.status == CheckStatus.FAILED)
        .group_by(PipelineRun.pipeline_key, DataQualityCheck.check_name)
        .order_by(PipelineRun.pipeline_key, DataQualityCheck.check_name)
    )
    return [
        FailedCheckCount(
            pipeline_key=row.pipeline_key,
            check_name=row.check_name,
            failures=int(row.failures),
        )
        for row in session.execute(statement)
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/integration/test_metrics_repository.py -q
```

Expected: 12 passed.

- [ ] **Step 5: Run the whole gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q
git add reim/repositories/pipeline_runs.py tests/integration/test_metrics_repository.py
git commit -m "feat(metrics): count failed checks per pipeline, not only per check name"
```

---

### Task 4: The snapshot

**Files:**
- Create: `reim/services/metrics.py`
- Test: `tests/integration/test_metrics_service.py` (create)

**Interfaces:**
- Consumes: everything Tasks 1–3 produced, plus `SourceEntry` (`reim/domain/sources/catalog.py:50`, fields `key`, `enabled`, `frequency`, `indicators`), `QualityRuleSet.for_indicator(code).freshness_max_age_days` (`reim/domain/quality/rules.py:85`).
- Produces, relied on by Task 5 and Task 6:
  ```text
  RECORD_OUTCOMES = ("extracted", "inserted", "updated", "unchanged", "rejected")
  PipelineMetrics(pipeline_key: str, enabled: bool, observations: int,
                  data_age_days: int | None, freshness_max_age_days: int | None,
                  last_run_at: datetime | None, last_success_at: datetime | None,
                  last_run_duration_ms: int | None,
                  last_run_records: dict[str, int] | None,
                  runs_by_status: dict[str, int], records_total: dict[str, int],
                  duration_ms_total: int)
  MetricsSnapshot(database_up: bool, pipelines: tuple[PipelineMetrics, ...],
                  failed_checks: tuple[FailedCheckCount, ...])
  build_metrics_snapshot(session, *, catalog=None, rules=None, today=None) -> MetricsSnapshot
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_metrics_service.py`:

```python
"""``build_metrics_snapshot``: the figures, the outage, and the query budget.

The snapshot needs a session, so it is tested here; every rendering rule is
tested without one in ``tests/unit/test_metrics_render.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from reim.core.constants import PipelineStatus
from reim.database.models import PipelineRun
from reim.domain.quality.rules import QualityRuleSet
from reim.services.metrics import RECORD_OUTCOMES, build_metrics_snapshot
from tests.conftest import requires_db


def _make_run(
    session: Session,
    *,
    pipeline_key: str,
    started_at: datetime,
    status: PipelineStatus = PipelineStatus.SUCCESS,
    duration_ms: int | None = 2_500,
    inserted: int = 0,
) -> PipelineRun:
    run = PipelineRun(
        id=uuid.uuid4(),
        pipeline_key=pipeline_key,
        started_at=started_at,
        status=status,
        duration_ms=duration_ms,
        records_inserted=inserted,
        created_at=started_at,
    )
    session.add(run)
    session.flush()
    return run


def _for(snapshot, pipeline_key: str):  # type: ignore[no-untyped-def]
    return next(item for item in snapshot.pipelines if item.pipeline_key == pipeline_key)


@requires_db
def test_every_catalog_entry_gets_a_row_even_with_no_runs(seeded_session: Session) -> None:
    """A pipeline that never ran is reported as never having run, not omitted.

    Omitting it would make a pipeline that stopped being scheduled invisible,
    which is the failure an operator most needs to see.
    """
    snapshot = build_metrics_snapshot(seeded_session)

    assert snapshot.database_up is True
    assert len(snapshot.pipelines) == 23
    never_ran = _for(snapshot, "worldbank_ni_cpi_inflation")
    assert never_ran.last_run_at is None
    assert never_ran.last_run_records is None
    assert never_ran.runs_by_status == {}
    assert never_ran.records_total == dict.fromkeys(RECORD_OUTCOMES, 0)


@requires_db
def test_the_last_run_and_the_totals_are_both_reported(seeded_session: Session) -> None:
    now = datetime.now(UTC)
    _make_run(
        seeded_session,
        pipeline_key="worldbank_ni_cpi_inflation",
        started_at=now - timedelta(days=1),
        inserted=7,
    )
    latest = _make_run(
        seeded_session, pipeline_key="worldbank_ni_cpi_inflation", started_at=now, inserted=3
    )
    seeded_session.flush()

    metrics = _for(build_metrics_snapshot(seeded_session), "worldbank_ni_cpi_inflation")

    assert metrics.last_run_at == latest.started_at
    assert metrics.last_run_records is not None
    assert metrics.last_run_records["inserted"] == 3
    assert metrics.records_total["inserted"] == 10
    assert metrics.runs_by_status == {"success": 2}
    assert metrics.duration_ms_total == 5_000


@requires_db
def test_a_failed_last_run_still_reports_the_older_success(seeded_session: Session) -> None:
    now = datetime.now(UTC)
    success = _make_run(
        seeded_session,
        pipeline_key="worldbank_ni_cpi_inflation",
        started_at=now - timedelta(days=3),
    )
    _make_run(
        seeded_session,
        pipeline_key="worldbank_ni_cpi_inflation",
        started_at=now,
        status=PipelineStatus.FAILED,
    )
    seeded_session.flush()

    metrics = _for(build_metrics_snapshot(seeded_session), "worldbank_ni_cpi_inflation")

    assert metrics.last_success_at == success.started_at
    assert metrics.last_run_at != success.started_at


@requires_db
def test_age_is_measured_from_the_newest_period_not_the_run(
    seeded_session: Session,
    make_observation,  # type: ignore[no-untyped-def]
) -> None:
    """A pipeline that runs nightly over a source stuck in 2020 is stale."""
    from reim.services.observation_writer import write_observations

    write_observations(seeded_session, [make_observation("2020")], connector_version="1.0.0")
    seeded_session.commit()

    snapshot = build_metrics_snapshot(seeded_session, today=date(2026, 1, 1))
    metrics = _for(snapshot, "worldbank_ni_cpi_inflation")

    assert metrics.observations == 1
    assert metrics.data_age_days == (date(2026, 1, 1) - date(2020, 12, 31)).days


@requires_db
def test_a_source_with_no_data_has_no_age_but_zero_observations(seeded_session: Session) -> None:
    metrics = _for(build_metrics_snapshot(seeded_session), "worldbank_ni_cpi_inflation")

    assert metrics.data_age_days is None
    assert metrics.observations == 0


@requires_db
def test_the_strictest_threshold_wins_across_a_pipelines_indicators(
    seeded_session: Session,
) -> None:
    """No catalog entry's indicators disagree today, so the case is constructed.

    ``reim/services/status.py:53`` takes ``indicators[0]``; this takes the
    minimum across the pipeline's indicators, so a freshness gauge fires early
    rather than never when two indicators in one source are given different
    thresholds.

    The real catalog is used rather than a synthetic one, because both
    ``SourceEntry`` and ``QualityRuleSet`` reject indicator codes that are not
    in ``INDICATORS_BY_CODE`` — an invented code cannot be validated into
    existence. ``inide_cpi_monthly`` declares nine indicators; two are given
    thresholds here and the remaining seven fall back to the rule file's
    defaults, which set none. So this pins both halves of the rule: the
    strictest configured threshold wins, and an indicator with no threshold is
    skipped rather than counted as zero.
    """
    rules = QualityRuleSet.model_validate(
        {
            "version": 1,
            "indicators": {
                "ni_cpi_index_monthly": {"freshness_max_age_days": 800},
                "ni_cpi_inflation_monthly": {"freshness_max_age_days": 30},
            },
        }
    )

    snapshot = build_metrics_snapshot(seeded_session, rules=rules)

    assert _for(snapshot, "inide_cpi_monthly").freshness_max_age_days == 30


@requires_db
def test_a_pipeline_whose_indicators_have_no_threshold_reports_none(
    seeded_session: Session,
) -> None:
    """Absence here becomes an absent series, which is how "no policy" reads."""
    rules = QualityRuleSet.model_validate({"version": 1, "indicators": {}})

    snapshot = build_metrics_snapshot(seeded_session, rules=rules)

    assert _for(snapshot, "inide_cpi_monthly").freshness_max_age_days is None
```

Add these two tests as well:

```python
@requires_db
def test_a_database_failure_yields_a_down_snapshot_not_an_exception(
    seeded_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Discovered by querying and catching, never by a pre-check."""

    def _raise(*args: object, **kwargs: object) -> None:
        raise SQLAlchemyError("database is down")

    monkeypatch.setattr("reim.services.metrics.run_repo.latest_runs_by_pipeline", _raise)

    snapshot = build_metrics_snapshot(seeded_session)

    assert snapshot.database_up is False
    assert snapshot.pipelines == ()
    assert snapshot.failed_checks == ()


@requires_db
def test_a_snapshot_costs_six_queries_whatever_the_catalog_holds(
    seeded_session: Session,
) -> None:
    """The regression this increment exists to prevent.

    A change that reintroduces a query per source makes the endpoint slow
    rather than broken; without this assertion nothing fails.
    """
    seeded_session.commit()
    statements: list[str] = []
    bind = seeded_session.get_bind()

    def _record(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(bind, "before_cursor_execute", _record)
    try:
        build_metrics_snapshot(seeded_session)
    finally:
        event.remove(bind, "before_cursor_execute", _record)

    assert len(statements) == 6, "\n\n".join(statements)
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/pytest tests/integration/test_metrics_service.py -q
```

Expected: `ModuleNotFoundError: No module named 'reim.services.metrics'`.

- [ ] **Step 3: Write the module**

Create `reim/services/metrics.py`:

```python
"""The figures behind ``/metrics``, and their Prometheus rendering.

Two halves on purpose. ``build_metrics_snapshot`` needs a session and is tested
against the database; ``render_snapshot`` needs nothing at all and is where the
exhaustive naming and absent-series tests live.

Every figure is derived from ``pipeline_runs`` at scrape time, because ingestion
runs in a CLI process that has exited long before a scrape arrives — an
in-process counter would never be visible to the process answering Prometheus,
and a Pushgateway is infrastructure this project does not take on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from reim.database.models import PipelineRun
from reim.domain.quality.rules import QualityRuleSet, get_quality_rules
from reim.domain.sources.catalog import SourceCatalog, SourceEntry, get_catalog
from reim.repositories import observations as observation_repo
from reim.repositories import pipeline_runs as run_repo
from reim.repositories import reference as reference_repo
from reim.repositories.observations import SourceVolume
from reim.repositories.pipeline_runs import FailedCheckCount, RunStatusAggregate

#: The five record counters a run reports, in the order they happen.
RECORD_OUTCOMES = ("extracted", "inserted", "updated", "unchanged", "rejected")


@dataclass(frozen=True)
class PipelineMetrics:
    """Everything ``/metrics`` reports about one pipeline.

    ``None`` means "no series": no threshold configured, no data stored, no run
    yet. A zero would assert something the data does not support — that a
    pipeline is perfectly fresh, or that its last run inserted nothing.
    """

    pipeline_key: str
    enabled: bool
    observations: int
    data_age_days: int | None
    freshness_max_age_days: int | None
    last_run_at: datetime | None
    last_success_at: datetime | None
    last_run_duration_ms: int | None
    last_run_records: dict[str, int] | None
    runs_by_status: dict[str, int]
    records_total: dict[str, int]
    duration_ms_total: int


@dataclass(frozen=True)
class MetricsSnapshot:
    """One scrape's worth of figures, or the fact that the database is down."""

    database_up: bool
    pipelines: tuple[PipelineMetrics, ...] = ()
    failed_checks: tuple[FailedCheckCount, ...] = ()


@dataclass(frozen=True)
class _PipelineTotals:
    """One pipeline's cumulative totals, folded across statuses."""

    runs_by_status: dict[str, int]
    records_total: dict[str, int]
    duration_ms_total: int


def _fold_aggregates(rows: list[RunStatusAggregate]) -> dict[str, _PipelineTotals]:
    """Collapse the per-status rows into one set of totals per pipeline.

    The query groups by pipeline *and* status because the run counter needs the
    status label; the record and duration counters do not, so they are summed
    back across statuses here rather than in a second query.
    """
    runs: dict[str, dict[str, int]] = {}
    records: dict[str, dict[str, int]] = {}
    durations: dict[str, int] = {}

    for row in rows:
        key = row.pipeline_key
        # (pipeline, status) is unique per group, so this assigns rather than adds.
        runs.setdefault(key, {})[row.status.value] = row.runs
        outcomes = records.setdefault(key, dict.fromkeys(RECORD_OUTCOMES, 0))
        outcomes["extracted"] += row.records_extracted
        outcomes["inserted"] += row.records_inserted
        outcomes["updated"] += row.records_updated
        outcomes["unchanged"] += row.records_unchanged
        outcomes["rejected"] += row.records_rejected
        durations[key] = durations.get(key, 0) + row.duration_ms

    return {
        key: _PipelineTotals(
            runs_by_status=runs[key],
            records_total=records[key],
            duration_ms_total=durations[key],
        )
        for key in runs
    }


def _freshness_threshold(entry: SourceEntry, rules: QualityRuleSet) -> int | None:
    """Return the strictest freshness threshold across a pipeline's indicators.

    Freshness is per source — ``latest_period_end`` is keyed on ``source_id`` —
    but thresholds are per indicator, and 14 of the 23 catalog entries declare
    more than one. None of them disagree today, so this is the same number
    ``build_pipeline_summaries`` derives from ``indicators[0]``
    (``reim/services/status.py:53``). When they do disagree the strictest wins:
    a freshness gauge that fires early beats one that never fires.

    An indicator with no threshold is skipped rather than read as zero, so "no
    policy here" cannot silence a sibling indicator that does have one.
    """
    configured = [
        threshold
        for threshold in (
            rules.for_indicator(code).freshness_max_age_days for code in entry.indicators
        )
        if threshold is not None
    ]
    return min(configured) if configured else None


def _pipeline_metrics(
    *,
    entry: SourceEntry,
    rules: QualityRuleSet,
    today: date,
    last_run: PipelineRun | None,
    last_success: PipelineRun | None,
    totals: _PipelineTotals | None,
    volume: SourceVolume | None,
) -> PipelineMetrics:
    """Assemble one pipeline's figures from the aggregates already fetched."""
    age: int | None = None
    if volume is not None and volume.latest_period_end is not None:
        age = (today - volume.latest_period_end).days

    last_records: dict[str, int] | None = None
    if last_run is not None:
        last_records = {
            "extracted": last_run.records_extracted,
            "inserted": last_run.records_inserted,
            "updated": last_run.records_updated,
            "unchanged": last_run.records_unchanged,
            "rejected": last_run.records_rejected,
        }

    return PipelineMetrics(
        pipeline_key=entry.key,
        enabled=entry.enabled,
        observations=volume.observations if volume is not None else 0,
        data_age_days=age,
        freshness_max_age_days=_freshness_threshold(entry, rules),
        last_run_at=last_run.started_at if last_run is not None else None,
        last_success_at=last_success.started_at if last_success is not None else None,
        last_run_duration_ms=last_run.duration_ms if last_run is not None else None,
        last_run_records=last_records,
        runs_by_status=totals.runs_by_status if totals is not None else {},
        records_total=(
            totals.records_total if totals is not None else dict.fromkeys(RECORD_OUTCOMES, 0)
        ),
        duration_ms_total=totals.duration_ms_total if totals is not None else 0,
    )


def build_metrics_snapshot(
    session: Session,
    *,
    catalog: SourceCatalog | None = None,
    rules: QualityRuleSet | None = None,
    today: date | None = None,
) -> MetricsSnapshot:
    """Return every figure ``/metrics`` exports, in six queries.

    Availability is discovered by running the queries and catching the failure,
    never by pre-checking the connection: a pre-check cannot speak for the query
    that follows it. A failure yields ``database_up=False`` and no pipeline
    series, so the scrape still answers — the scrape during an outage being the
    one that matters most.

    Every catalog entry gets a row, including one that has never run. Dropping
    it would hide a pipeline that stopped being scheduled, which is exactly the
    failure worth paging about.
    """
    resolved_catalog = catalog or get_catalog()
    resolved_rules = rules or get_quality_rules()
    reference_day = today or datetime.now(UTC).date()

    try:
        latest_runs = run_repo.latest_runs_by_pipeline(session)
        latest_successes = run_repo.latest_successful_runs_by_pipeline(session)
        aggregates = run_repo.aggregate_runs_by_pipeline(session)
        failed_checks = run_repo.summarize_failed_checks_by_pipeline(session)
        volumes = observation_repo.summarize_sources(session)
        source_ids = reference_repo.source_ids_by_key(session)
    except SQLAlchemyError:
        return MetricsSnapshot(database_up=False)

    totals = _fold_aggregates(aggregates)

    pipelines: list[PipelineMetrics] = []
    for entry in resolved_catalog.sources:
        source_id = source_ids.get(entry.key)
        pipelines.append(
            _pipeline_metrics(
                entry=entry,
                rules=resolved_rules,
                today=reference_day,
                last_run=latest_runs.get(entry.key),
                last_success=latest_successes.get(entry.key),
                totals=totals.get(entry.key),
                volume=volumes.get(source_id) if source_id is not None else None,
            )
        )

    return MetricsSnapshot(
        database_up=True,
        pipelines=tuple(pipelines),
        failed_checks=tuple(failed_checks),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/integration/test_metrics_service.py -q
```

Expected: 9 passed. If the query-count test reports 7, something flushed — confirm `seeded_session.commit()` runs before the listener is attached.

- [ ] **Step 5: Prove the query-count test has teeth**

Temporarily replace `volumes = observation_repo.summarize_sources(session)` with a loop calling `observation_repo.latest_period_end(session, source_id)` per source, and confirm the count assertion fails reporting 20-plus statements. Restore it. This is the test the whole increment rests on.

- [ ] **Step 6: Run the whole gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q
git add reim/services/metrics.py tests/integration/test_metrics_service.py
git commit -m "feat(metrics): one scrape's figures in six queries, and a test that pins the six"
```

---

### Task 5: The renderer

**Files:**
- Modify: `reim/services/metrics.py`
- Test: `tests/unit/test_metrics_render.py` (create)

**Interfaces:**
- Consumes: `MetricsSnapshot`, `PipelineMetrics`, `FailedCheckCount`, `RECORD_OUTCOMES` from Task 4.
- Produces, relied on by Task 6: `render_snapshot(snapshot: MetricsSnapshot) -> bytes`.

**The rule that decides absence, stated once:** a **gauge about a specific
event** is absent until the event happens (no threshold configured, no data
stored, no run yet). A **counter** starts at zero, because a counter's zero is
a real reading and `rate()` needs the series to exist. `records_total` therefore
reports five zeros for a pipeline that never ran, while `runs_by_status` reports
nothing — the outcome set is fixed and known, the status set is only known once
a run has happened.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_metrics_render.py`:

```python
"""``render_snapshot``: every naming and absent-series rule, with no database.

Rendering is where Prometheus conventions get quietly broken — a counter named
``_total`` that renders ``_total_total``, milliseconds exported as seconds, a
zero standing in for a fact nobody measured. None of it needs a session, so all
of it is asserted directly here.

Assertions look for the series they name rather than comparing whole payloads,
which would break every time ``prometheus_client`` adds a default collector.
"""

from __future__ import annotations

from datetime import UTC, datetime

from reim.repositories.pipeline_runs import FailedCheckCount
from reim.services.metrics import (
    RECORD_OUTCOMES,
    MetricsSnapshot,
    PipelineMetrics,
    render_snapshot,
)


def _metrics(**overrides: object) -> PipelineMetrics:
    """A fully-populated pipeline, so each test overrides only its own concern."""
    defaults: dict[str, object] = {
        "pipeline_key": "bcn_fx",
        "enabled": True,
        "observations": 1_200,
        "data_age_days": 3,
        "freshness_max_age_days": 7,
        "last_run_at": datetime(2026, 9, 12, 6, 0, tzinfo=UTC),
        "last_success_at": datetime(2026, 9, 12, 6, 0, tzinfo=UTC),
        "last_run_duration_ms": 2_500,
        "last_run_records": dict.fromkeys(RECORD_OUTCOMES, 4),
        "runs_by_status": {"success": 40, "failed": 2},
        "records_total": dict.fromkeys(RECORD_OUTCOMES, 100),
        "duration_ms_total": 90_000,
    }
    defaults.update(overrides)
    return PipelineMetrics(**defaults)  # type: ignore[arg-type]


def _render(**overrides: object) -> str:
    snapshot = MetricsSnapshot(
        database_up=True,
        pipelines=(_metrics(**overrides),),
        failed_checks=(),
    )
    return render_snapshot(snapshot).decode()


def test_the_counter_name_is_not_doubled() -> None:
    """``CounterMetricFamily`` appends ``_total`` itself.

    Constructing it with ``reim_pipeline_runs_total`` renders
    ``reim_pipeline_runs_total_total``, which no alert rule would ever match.
    """
    text = _render()

    assert "reim_pipeline_runs_total{" in text
    assert "_total_total" not in text


def test_no_created_series_is_emitted() -> None:
    """``Counter`` would add one holding the process start time.

    For a counter rebuilt from the database on every scrape it would report
    "created just now" each time, which is noise at best.
    """
    assert "_created" not in _render()


def test_durations_are_exported_in_seconds() -> None:
    text = _render(last_run_duration_ms=2_500, duration_ms_total=90_000)

    assert 'reim_pipeline_last_run_duration_seconds{pipeline_key="bcn_fx"} 2.5' in text
    assert 'reim_pipeline_run_duration_seconds_total{pipeline_key="bcn_fx"} 90.0' in text


def test_the_types_are_declared_as_gauges_and_counters() -> None:
    text = _render()

    assert "# TYPE reim_pipeline_data_age_days gauge" in text
    assert "# TYPE reim_pipeline_runs_total counter" in text
    assert "# TYPE reim_quality_checks_failed_total counter" in text


def test_a_pipeline_with_no_threshold_has_no_threshold_series() -> None:
    """No policy configured must not read as "never overdue" or "always overdue"."""
    text = _render(freshness_max_age_days=None)

    assert "reim_pipeline_freshness_max_age_days{" not in text
    assert "reim_pipeline_data_age_days{" in text


def test_a_pipeline_with_no_data_has_no_age_series_but_reports_zero_observations() -> None:
    text = _render(data_age_days=None, observations=0)

    assert "reim_pipeline_data_age_days{" not in text
    assert 'reim_pipeline_observations{pipeline_key="bcn_fx"} 0.0' in text


def test_a_pipeline_that_never_ran_omits_last_run_series_but_keeps_counters_at_zero() -> None:
    """A counter's zero is a reading; a last-run gauge's zero is an invention."""
    text = _render(
        last_run_at=None,
        last_success_at=None,
        last_run_duration_ms=None,
        last_run_records=None,
        runs_by_status={},
        records_total=dict.fromkeys(RECORD_OUTCOMES, 0),
        duration_ms_total=0,
    )

    assert "reim_pipeline_last_run_timestamp_seconds{" not in text
    assert "reim_pipeline_last_success_timestamp_seconds{" not in text
    assert "reim_pipeline_last_run_duration_seconds{" not in text
    assert "reim_pipeline_last_run_records{" not in text
    assert "reim_pipeline_runs_total{" not in text
    assert 'reim_pipeline_records_total{pipeline_key="bcn_fx",outcome="inserted"} 0.0' in text


def test_every_record_outcome_is_labelled_separately() -> None:
    text = _render()

    for outcome in RECORD_OUTCOMES:
        assert f'outcome="{outcome}"' in text


def test_each_run_status_gets_its_own_series() -> None:
    text = _render(runs_by_status={"success": 40, "failed": 2})

    assert 'reim_pipeline_runs_total{pipeline_key="bcn_fx",status="success"} 40.0' in text
    assert 'reim_pipeline_runs_total{pipeline_key="bcn_fx",status="failed"} 2.0' in text


def test_a_disabled_pipeline_reports_zero_rather_than_disappearing() -> None:
    """An alert rule excludes it by reading the gauge; it cannot read an absence."""
    text = _render(enabled=False)

    assert 'reim_pipeline_enabled{pipeline_key="bcn_fx"} 0.0' in text


def test_failed_checks_are_labelled_by_pipeline_and_name() -> None:
    snapshot = MetricsSnapshot(
        database_up=True,
        pipelines=(),
        failed_checks=(
            FailedCheckCount(pipeline_key="a", check_name="freshness", failures=3),
            FailedCheckCount(pipeline_key="b", check_name="freshness", failures=1),
        ),
    )

    text = render_snapshot(snapshot).decode()

    assert 'reim_quality_checks_failed_total{pipeline_key="a",check_name="freshness"} 3.0' in text
    assert 'reim_quality_checks_failed_total{pipeline_key="b",check_name="freshness"} 1.0' in text


def test_a_down_snapshot_reports_the_outage_and_no_pipeline_series() -> None:
    text = render_snapshot(MetricsSnapshot(database_up=False)).decode()

    assert "reim_database_up 0.0" in text
    assert "reim_pipeline_" not in text


def test_a_healthy_snapshot_reports_the_database_as_up() -> None:
    assert "reim_database_up 1.0" in _render()
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_metrics_render.py -q
```

Expected: `ImportError: cannot import name 'render_snapshot'`.

- [ ] **Step 3: Add the renderer**

Extend the imports of `reim/services/metrics.py`:

```text
from collections.abc import Iterator

from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric
```

Append to the module:

```python
class _SnapshotCollector:
    """Yields one snapshot's metric families. Registered, scraped, discarded."""

    def __init__(self, snapshot: MetricsSnapshot) -> None:
        self._snapshot = snapshot

    def collect(self) -> Iterator[Metric]:
        yield GaugeMetricFamily(
            "reim_database_up",
            "1 when the metrics queries reached the database, 0 when they failed.",
            value=1.0 if self._snapshot.database_up else 0.0,
        )
        yield from _pipeline_families(self._snapshot.pipelines)
        yield _failed_check_family(self._snapshot.failed_checks)


def _pipeline_families(pipelines: tuple[PipelineMetrics, ...]) -> Iterator[Metric]:
    """Build one family per metric, adding a series per pipeline.

    Counter families are constructed with their base name: the client appends
    ``_total``, so ``reim_pipeline_runs`` renders ``reim_pipeline_runs_total``
    and passing the suffix here would render it twice.
    """
    enabled = GaugeMetricFamily(
        "reim_pipeline_enabled",
        "1 when the pipeline is enabled in the source catalog, 0 when disabled.",
        labels=["pipeline_key"],
    )
    observations = GaugeMetricFamily(
        "reim_pipeline_observations",
        "Observations currently stored for this pipeline's source.",
        labels=["pipeline_key"],
    )
    age = GaugeMetricFamily(
        "reim_pipeline_data_age_days",
        "Days between today and the newest period this pipeline holds data for.",
        labels=["pipeline_key"],
    )
    threshold = GaugeMetricFamily(
        "reim_pipeline_freshness_max_age_days",
        "Configured maximum tolerated data age, from sources/quality_rules.yml.",
        labels=["pipeline_key"],
    )
    last_run = GaugeMetricFamily(
        "reim_pipeline_last_run_timestamp_seconds",
        "Start of the most recent run, in Unix seconds.",
        labels=["pipeline_key"],
    )
    last_success = GaugeMetricFamily(
        "reim_pipeline_last_success_timestamp_seconds",
        "Start of the most recent run that did not fail, in Unix seconds.",
        labels=["pipeline_key"],
    )
    last_duration = GaugeMetricFamily(
        "reim_pipeline_last_run_duration_seconds",
        "How long the most recent run took.",
        labels=["pipeline_key"],
    )
    last_records = GaugeMetricFamily(
        "reim_pipeline_last_run_records",
        "Records the most recent run reported, by outcome.",
        labels=["pipeline_key", "outcome"],
    )
    runs = CounterMetricFamily(
        "reim_pipeline_runs",
        "Runs recorded, by terminal status.",
        labels=["pipeline_key", "status"],
    )
    records = CounterMetricFamily(
        "reim_pipeline_records",
        "Records reported across every run, by outcome.",
        labels=["pipeline_key", "outcome"],
    )
    duration = CounterMetricFamily(
        "reim_pipeline_run_duration_seconds",
        "Time spent running this pipeline across every run.",
        labels=["pipeline_key"],
    )

    for metrics in pipelines:
        key = [metrics.pipeline_key]
        enabled.add_metric(key, 1.0 if metrics.enabled else 0.0)
        observations.add_metric(key, metrics.observations)
        if metrics.data_age_days is not None:
            age.add_metric(key, metrics.data_age_days)
        if metrics.freshness_max_age_days is not None:
            threshold.add_metric(key, metrics.freshness_max_age_days)
        if metrics.last_run_at is not None:
            last_run.add_metric(key, metrics.last_run_at.timestamp())
        if metrics.last_success_at is not None:
            last_success.add_metric(key, metrics.last_success_at.timestamp())
        if metrics.last_run_duration_ms is not None:
            last_duration.add_metric(key, metrics.last_run_duration_ms / 1000)
        if metrics.last_run_records is not None:
            for outcome, count in metrics.last_run_records.items():
                last_records.add_metric([metrics.pipeline_key, outcome], count)
        for status, count in metrics.runs_by_status.items():
            runs.add_metric([metrics.pipeline_key, status], count)
        for outcome, count in metrics.records_total.items():
            records.add_metric([metrics.pipeline_key, outcome], count)
        duration.add_metric(key, metrics.duration_ms_total / 1000)

    yield enabled
    yield observations
    yield age
    yield threshold
    yield last_run
    yield last_success
    yield last_duration
    yield last_records
    yield runs
    yield records
    yield duration


def _failed_check_family(counts: tuple[FailedCheckCount, ...]) -> Metric:
    """Build the failed-check counter, one series per pipeline and check name."""
    family = CounterMetricFamily(
        "reim_quality_checks_failed",
        "Quality checks recorded as failed, by pipeline and check name.",
        labels=["pipeline_key", "check_name"],
    )
    for count in counts:
        family.add_metric([count.pipeline_key, count.check_name], count.failures)
    return family


def render_snapshot(snapshot: MetricsSnapshot) -> bytes:
    """Render a snapshot as Prometheus text exposition.

    Pure: snapshot in, bytes out, no session, no clock, no settings — which is
    why every naming and absent-series rule is tested against this function
    rather than inferred from a scraped endpoint.

    A fresh registry per call, rather than module-level metric objects, so a
    label set that stops existing — a source dropped from the catalog — stops
    being exported instead of lingering at its last value forever.
    """
    registry = CollectorRegistry()
    registry.register(_SnapshotCollector(snapshot))
    return generate_latest(registry)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_metrics_render.py -q
```

Expected: 13 passed. If `mypy` objects to `registry.register(_SnapshotCollector(...))`, the collector needs to satisfy `prometheus_client.registry.Collector` — it does structurally, via `collect()`; add an explicit base class only if mypy demands it.

- [ ] **Step 5: Prove the doubled-name test has teeth**

Temporarily rename the `runs` family to `"reim_pipeline_runs_total"`, run the tests, and confirm `test_the_counter_name_is_not_doubled` fails. Restore it.

- [ ] **Step 6: Run the whole gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q
git add reim/services/metrics.py tests/unit/test_metrics_render.py
git commit -m "feat(metrics): render the snapshot, and let an absent series mean absent"
```

---

### Task 6: The endpoint, and the documentation

**Files:**
- Modify: `apps/api/routers/system.py`, `ROADMAP.md`, `README.md`
- Test: `tests/integration/test_metrics_endpoint.py` (create)

**Interfaces:**
- Consumes: `build_metrics_snapshot`, `render_snapshot` from Tasks 4 and 5; `SessionDep` (`apps/api/dependencies.py:33`).

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_metrics_endpoint.py`:

```python
"""``/metrics``: the process defaults, the pipeline series, and the outage.

The endpoint is thin — the figures are tested in
``tests/integration/test_metrics_service.py`` and the rendering in
``tests/unit/test_metrics_render.py``. What is asserted here is the wiring: both
payloads present, a 200 during an outage, and the 404 when metrics are off.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.dependencies import get_db
from apps.api.main import create_app
from tests.conftest import requires_db


@pytest.fixture
def client(seeded_session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: seeded_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@requires_db
def test_the_scrape_carries_both_the_process_and_the_pipeline_metrics(
    client: TestClient,
) -> None:
    """Concatenating two registries is only valid if neither name collides."""
    response = client.get("/metrics")

    assert response.status_code == 200
    body = response.text
    assert "python_info" in body
    assert "reim_database_up 1.0" in body
    assert "reim_pipeline_enabled{" in body


@requires_db
def test_every_catalog_pipeline_appears_in_the_scrape(client: TestClient) -> None:
    body = client.get("/metrics").text

    assert body.count("reim_pipeline_enabled{") == 23


@requires_db
def test_an_outage_answers_two_hundred_with_the_database_marked_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scrape target that vanishes during an outage is useless during one."""

    def _raise(*args: object, **kwargs: object) -> None:
        raise SQLAlchemyError("database is down")

    monkeypatch.setattr("reim.services.metrics.run_repo.latest_runs_by_pipeline", _raise)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "reim_database_up 0.0" in response.text
    assert "python_info" in response.text
    assert "reim_pipeline_enabled{" not in response.text


@requires_db
def test_metrics_can_still_be_switched_off(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REIM_METRICS_ENABLED", "false")
    from reim.core.config import get_settings

    get_settings.cache_clear()
    try:
        assert client.get("/metrics").status_code == 404
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/pytest tests/integration/test_metrics_endpoint.py -q
```

Expected: the first three fail — `reim_database_up` is absent, because the endpoint still exports only process metrics. The 404 test passes already; that is correct, it is a regression guard.

- [ ] **Step 3: Wire the endpoint**

In `apps/api/routers/system.py`, replace the `metrics` function with:

```python
@router.get("/metrics", include_in_schema=False, summary="Prometheus metrics")
def metrics(session: SessionDep) -> Response:
    """Expose process and per-pipeline metrics in Prometheus text format.

    Disabled by setting ``REIM_METRICS_ENABLED=false``.

    The session is safe to depend on even when the database is down: ``get_db``
    builds it without connecting, so the failure surfaces inside
    ``build_metrics_snapshot`` as a caught ``SQLAlchemyError`` and the scrape
    still answers, with ``reim_database_up 0``.
    """
    if not get_settings().metrics_enabled:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    body = generate_latest() + render_snapshot(build_metrics_snapshot(session))
    return Response(content=body, media_type=CONTENT_TYPE_LATEST)
```

Add to that file's imports:

```text
from reim.services.metrics import build_metrics_snapshot, render_snapshot
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/integration/test_metrics_endpoint.py tests/integration/test_web.py -q
```

Expected: all pass, including `test_the_api_is_unchanged_by_the_web_surface`, which asserts `/metrics` still answers 200 (`tests/integration/test_web.py:75`).

- [ ] **Step 5: See it against real data**

```bash
.venv/bin/uvicorn apps.api.main:app --port 8001 &
sleep 2
curl -s http://localhost:8001/metrics | grep -E "^reim_" | head -40
kill %1
```

Expect `reim_database_up`, `reim_pipeline_enabled` for each catalog key, and — against an empty database — no `reim_pipeline_data_age_days` at all. Check the exposition parses: `curl -s … | .venv/bin/python -c "import sys; from prometheus_client.parser import text_string_to_metric_families as p; print(len(list(p(sys.stdin.read()))))"`.

- [ ] **Step 6: Update the ROADMAP**

In `ROADMAP.md`, under `## v0.5.0 — Operations`, replace the Prometheus bullet with a struck-through, `✅ **done**` entry matching the style of the v0.4.0 items above it. Say: what it exports (per-pipeline volumes, durations, freshness), that it is derived from `pipeline_runs` at scrape time because ingestion runs in a CLI process that has exited before the scrape, that age and threshold ship as separate gauges so the staleness policy stays in `quality_rules.yml` rather than being re-encoded as a boolean, that six grouped queries replaced 115 round trips, and that an outage renders `reim_database_up 0` at status 200.

- [ ] **Step 7: Update the README**

Two edits:

1. In the endpoint table (`README.md:370`), change the `/metrics` line to read `Prometheus text format (process + per-pipeline)`.
2. Add a short subsection after that table listing the exported families and the one alert rule they are designed for:
   ```text
   reim_pipeline_data_age_days > reim_pipeline_freshness_max_age_days
   ```
   Fence it as ` ```text `, not ` ```python `, and say explicitly that REIM exports no `is_stale` — the threshold lives in `sources/quality_rules.yml` and the comparison belongs to the alert rule.

- [ ] **Step 8: Check the formatter and commit**

`ruff format` rewrites ` ```python ` blocks in Markdown. Both documents should contain only ` ```text ` fences for these additions:

```bash
.venv/bin/ruff format . && git diff --stat
```

Expect no change to `ROADMAP.md` or `README.md` from the formatter. Then:

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q
git add apps/api/routers/system.py tests/integration/test_metrics_endpoint.py ROADMAP.md README.md
git commit -m "feat(metrics): scrape the pipelines, and keep answering when the database does not"
```

---

## Done when

* `/metrics` exports the eleven pipeline families and `reim_database_up`, per catalog entry.
* A scrape costs six queries, pinned by a test that fails if a seventh appears.
* No threshold and no data each produce an absent series, not a zero.
* An outage answers 200 with `reim_database_up 0`; `REIM_METRICS_ENABLED=false` still answers 404.
* The full gate passes: `ruff check`, `ruff format --check`, `mypy reim apps`, `pytest -q`.
* `ROADMAP.md` marks v0.5.0's metrics item done and `README.md` documents the surface and the alert rule.
