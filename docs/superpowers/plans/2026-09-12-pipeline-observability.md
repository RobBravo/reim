# Pipeline Observability Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two server-rendered pages — `/runs` (the last 100 pipeline runs plus failed-check trends) and `/runs/{run_id}` (one run in full) — so REIM's ingestion history is readable without constructing an HTTP request.

**Architecture:** Front end over functions that already exist. The view functions call `reim.repositories.pipeline_runs` directly, never the application's own HTTP API, and hand Pydantic schemas to Jinja2 templates — the skeleton `apps/web/` already established. One new aggregate query and one new schema are the entire backend change; there is no model and no migration.

**Tech Stack:** FastAPI, Jinja2, SQLAlchemy 2 (PostgreSQL), Pydantic v2, pytest.

**Spec:** `docs/superpowers/specs/2026-09-12-pipeline-observability-design.md`

## Global Constraints

* **Views call repositories and services, never the app's own HTTP API.** Decision D3 of the catalog design, pinned by `test_the_pages_make_no_outbound_http_requests` in `tests/integration/test_web.py`.
* **Tests assert content, not markup.** Decision D7 of the catalog design. Never assert on an `id` attribute, a tag name or a CSS class as a stand-in for content — the last branch shipped exactly that mistake and a reviewer caught it. A test must fail if a cell renders empty.
* **No new dependency.** `jinja2` is the only package the web surface added and stays so. No CDN, no bundler, no JavaScript library.
* **Every empty state gets its own sentence.** Six of them, listed in §4 of the spec. Never let two distinct conditions render the same words.
* **Database availability is discovered by querying, not by pre-checking** — `check_database_connection()` must not appear in `apps/web/routes.py`. See `load_pipeline_summaries`'s docstring at `apps/web/routes.py:72`.
* **The verification gate, which must pass before every commit:**
  ```bash
  .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q
  ```
* **There is no `pip` in the venv.** Use `.venv/bin/<tool>` directly. The test database comes up with `make db-up CONTAINER_ENGINE=podman`, which prints the `export REIM_TEST_DATABASE_URL=...` line to use.
* **`asyncio_mode = "auto"`** — do not decorate async tests with `@pytest.mark.asyncio`.
* **Type annotations are mandatory**; `mypy` runs in strict mode over `reim` and `apps`. Test functions need `-> None`.

---

## File Structure

| File | Responsibility |
|---|---|
| `reim/repositories/pipeline_runs.py` (modify) | `since` filtering on the run queries; the new failed-check aggregate |
| `reim/schemas/pipelines.py` (modify) | `FailedCheckGroup`, the shape the aggregate returns |
| `apps/web/routes.py` (modify) | `_format_duration`, `load_runs_page`, the two view functions |
| `apps/web/templates/runs.html` (create) | The history table and the trends block, with their six empty states |
| `apps/web/templates/run_detail.html` (create) | One run: counters, error, metadata, checks |
| `apps/web/templates/run_not_found.html` (create) | The HTML 404 |
| `apps/web/templates/base.html` (modify) | A second nav link |
| `apps/web/static/reim.css` (modify) | Styles for the new blocks; `.catalog-table-wrapper` generalised to `.table-wrapper` |
| `tests/unit/test_web_routes.py` (modify) | `_format_duration`'s branches, no database |
| `tests/unit/test_failed_check_groups.py` (create) | Ordering of the aggregate's result, no database |
| `tests/integration/test_web_runs.py` (create) | Both pages, all six empty states, both 404 paths |
| `tests/integration/test_pipeline_run_repository.py` (create) | The `since` window and the aggregate, against PostgreSQL |
| `ROADMAP.md`, `README.md` (modify) | Mark the increment done; describe the pages |

---

### Task 1: The repository window and the failed-check aggregate

**Files:**
- Modify: `reim/repositories/pipeline_runs.py:15-58` (`_apply`, `list_runs`, `count_runs`), and append the new function
- Modify: `reim/schemas/pipelines.py` (append `FailedCheckGroup` after `QualityCheckRead`, which ends at line 34)
- Test: `tests/integration/test_pipeline_run_repository.py` (create), `tests/unit/test_failed_check_groups.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces, relied on by Tasks 2 and 3:
  ```text
  list_runs(session, *, pipeline_key=None, status=None, since=None, limit=50, offset=0) -> list[PipelineRun]
  count_runs(session, *, pipeline_key=None, status=None, since=None) -> int
  summarize_failed_checks_by_name(session, *, since=None) -> list[FailedCheckGroup]

  FailedCheckGroup(check_name: str, check_type: CheckType, severity: CheckSeverity,
                   failures: int, last_failed_at: datetime, pipeline_keys: list[str])
  ```

**Context you need:** `SEVERITY_ORDER` **already exists** in `reim/core/constants.py:177` as `dict[CheckSeverity, int]` mapping INFO→0, WARNING→1, ERROR→2, CRITICAL→3. Import it; do not define a second one.

- [ ] **Step 1: Write the failing unit test for ordering**

Create `tests/unit/test_failed_check_groups.py`:

```python
"""Ordering of the failed-check aggregate, without a database.

The SQL groups; Python orders. The reader's first question is what is most
broken, so severity leads, then how often it failed, then the name as a
tie-break so the page is stable between renders of identical data.
"""

from __future__ import annotations

from datetime import UTC, datetime

from reim.core.constants import CheckSeverity, CheckType
from reim.repositories.pipeline_runs import order_failed_check_groups
from reim.schemas.pipelines import FailedCheckGroup


def _group(name: str, severity: CheckSeverity, failures: int) -> FailedCheckGroup:
    return FailedCheckGroup(
        check_name=name,
        check_type=CheckType.COMPLETENESS,
        severity=severity,
        failures=failures,
        last_failed_at=datetime(2026, 9, 12, tzinfo=UTC),
        pipeline_keys=["worldbank_ni_cpi_inflation"],
    )


def test_the_most_severe_group_comes_first() -> None:
    groups = [
        _group("a", CheckSeverity.INFO, 99),
        _group("b", CheckSeverity.CRITICAL, 1),
        _group("c", CheckSeverity.WARNING, 50),
    ]

    ordered = order_failed_check_groups(groups)

    assert [group.check_name for group in ordered] == ["b", "c", "a"]


def test_within_a_severity_the_most_frequent_comes_first() -> None:
    groups = [
        _group("rare", CheckSeverity.ERROR, 2),
        _group("common", CheckSeverity.ERROR, 40),
    ]

    ordered = order_failed_check_groups(groups)

    assert [group.check_name for group in ordered] == ["common", "rare"]


def test_ties_break_on_name_so_the_page_is_stable() -> None:
    groups = [
        _group("zeta", CheckSeverity.ERROR, 3),
        _group("alpha", CheckSeverity.ERROR, 3),
    ]

    ordered = order_failed_check_groups(groups)

    assert [group.check_name for group in ordered] == ["alpha", "zeta"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_failed_check_groups.py -q`
Expected: FAIL — `ImportError: cannot import name 'order_failed_check_groups'`

- [ ] **Step 3: Add the `FailedCheckGroup` schema**

In `reim/schemas/pipelines.py`, immediately after the `QualityCheckRead` class (it ends with `created_at: datetime` at line 34) and before `class PipelineRunRead`:

```python
class FailedCheckGroup(BaseModel):
    """Failed checks of one name and severity, aggregated over a time window.

    ``summarize_failed_checks`` answers "how bad is it" by severity alone.
    This answers "what is failing, how often, since when, and where" — the
    question an operator actually has, and the one that distinguishes a new
    failure from one that has been recurring for weeks.
    """

    check_name: str
    check_type: CheckType
    severity: CheckSeverity
    failures: int
    last_failed_at: datetime
    pipeline_keys: list[str]
```

`CheckType`, `CheckSeverity` and `datetime` are already imported at the top of that file.

- [ ] **Step 4: Add the ordering helper**

In `reim/repositories/pipeline_runs.py`, add to the imports:

```python
from reim.core.constants import SEVERITY_ORDER
from reim.schemas.pipelines import FailedCheckGroup
```

(The existing import line `from reim.core.constants import CheckSeverity, CheckStatus, PipelineStatus` gains `SEVERITY_ORDER` rather than becoming a second statement.)

Then append:

```python
def order_failed_check_groups(groups: list[FailedCheckGroup]) -> list[FailedCheckGroup]:
    """Order grouped failures worst-first, then most frequent, then by name.

    Ordered in Python rather than in SQL because ``CheckSeverity`` has no
    natural sort in the database — ordering it there means a ``CASE``
    expression restating ``SEVERITY_ORDER``, which would then be two
    definitions of one fact. The grouped result is at most a few dozen rows,
    so sorting it here costs nothing.

    The name is the final tie-break so that two renders of identical data
    produce identical pages; without it the order would depend on whatever
    the database happened to return.
    """
    return sorted(
        groups,
        key=lambda group: (-SEVERITY_ORDER[group.severity], -group.failures, group.check_name),
    )
```

- [ ] **Step 5: Run the unit test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_failed_check_groups.py -q`
Expected: PASS (3 tests)

- [ ] **Step 6: Write the failing integration test for the window and the aggregate**

Create `tests/integration/test_pipeline_run_repository.py`:

```python
"""The run window and the failed-check aggregate, against real PostgreSQL.

``array_agg`` and ``DISTINCT`` inside an aggregate are PostgreSQL behaviour,
not SQLAlchemy behaviour, so these run against the real database rather than
being mocked into agreement with themselves.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from reim.core.constants import CheckSeverity, CheckStatus, CheckType, PipelineStatus
from reim.database.models import DataQualityCheck, PipelineRun
from reim.repositories import pipeline_runs as run_repo
from tests.conftest import requires_db


def _make_run(session: Session, *, pipeline_key: str, started_at: datetime) -> PipelineRun:
    run = PipelineRun(
        id=uuid.uuid4(),
        pipeline_key=pipeline_key,
        started_at=started_at,
        status=PipelineStatus.SUCCESS,
        created_at=started_at,
    )
    session.add(run)
    session.flush()
    return run


def _make_check(
    session: Session,
    *,
    run: PipelineRun,
    check_name: str,
    severity: CheckSeverity,
    created_at: datetime,
    status: CheckStatus = CheckStatus.FAILED,
) -> None:
    session.add(
        DataQualityCheck(
            id=uuid.uuid4(),
            pipeline_run_id=run.id,
            check_name=check_name,
            check_type=CheckType.COMPLETENESS,
            status=status,
            severity=severity,
            created_at=created_at,
        )
    )
    session.flush()


@requires_db
def test_since_excludes_runs_older_than_the_window(session: Session) -> None:
    now = datetime.now(UTC)
    _make_run(session, pipeline_key="a", started_at=now - timedelta(days=1))
    _make_run(session, pipeline_key="b", started_at=now - timedelta(days=90))

    since = now - timedelta(days=30)

    assert run_repo.count_runs(session, since=since) == 1
    assert run_repo.count_runs(session) == 2
    assert [run.pipeline_key for run in run_repo.list_runs(session, since=since)] == ["a"]


@requires_db
def test_the_aggregate_counts_every_failure_not_a_truncated_page(session: Session) -> None:
    """The reason this is SQL and not a Python fold over ``list_checks``."""
    now = datetime.now(UTC)
    for index in range(250):
        run = _make_run(session, pipeline_key="a", started_at=now - timedelta(minutes=index))
        _make_check(
            session,
            run=run,
            check_name="freshness",
            severity=CheckSeverity.ERROR,
            created_at=now - timedelta(minutes=index),
        )

    groups = run_repo.summarize_failed_checks_by_name(session)

    assert len(groups) == 1
    assert groups[0].failures == 250


@requires_db
def test_the_aggregate_reports_every_pipeline_a_check_failed_in(session: Session) -> None:
    now = datetime.now(UTC)
    for key in ("banguat_exchange_rate", "inide_cpi_monthly", "banguat_exchange_rate"):
        run = _make_run(session, pipeline_key=key, started_at=now)
        _make_check(
            session, run=run, check_name="freshness", severity=CheckSeverity.WARNING, created_at=now
        )

    groups = run_repo.summarize_failed_checks_by_name(session)

    assert groups[0].pipeline_keys == ["banguat_exchange_rate", "inide_cpi_monthly"]


@requires_db
def test_passing_checks_are_not_reported_as_failures(session: Session) -> None:
    now = datetime.now(UTC)
    run = _make_run(session, pipeline_key="a", started_at=now)
    _make_check(
        session,
        run=run,
        check_name="freshness",
        severity=CheckSeverity.ERROR,
        created_at=now,
        status=CheckStatus.PASSED,
    )

    assert run_repo.summarize_failed_checks_by_name(session) == []


@requires_db
def test_the_aggregate_honours_the_window_and_reports_the_latest_failure(
    session: Session,
) -> None:
    now = datetime.now(UTC)
    recent = now - timedelta(days=2)
    old = now - timedelta(days=90)
    for moment in (recent, old):
        run = _make_run(session, pipeline_key="a", started_at=moment)
        _make_check(
            session,
            run=run,
            check_name="freshness",
            severity=CheckSeverity.ERROR,
            created_at=moment,
        )

    groups = run_repo.summarize_failed_checks_by_name(session, since=now - timedelta(days=30))

    assert len(groups) == 1
    assert groups[0].failures == 1
    assert groups[0].last_failed_at.replace(microsecond=0) == recent.replace(microsecond=0)
```

- [ ] **Step 7: Run it to verify it fails**

Bring the database up first if it is not running:

```bash
make db-up CONTAINER_ENGINE=podman
export REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim
.venv/bin/alembic upgrade head
```

Run: `.venv/bin/pytest tests/integration/test_pipeline_run_repository.py -q`
Expected: FAIL — `AttributeError: module 'reim.repositories.pipeline_runs' has no attribute 'summarize_failed_checks_by_name'`, and `count_runs() got an unexpected keyword argument 'since'`

- [ ] **Step 8: Add `since` to the three run queries**

Replace `_apply` (`reim/repositories/pipeline_runs.py:15-26`) with:

```python
def _apply(
    statement: Select[tuple[PipelineRun]],
    *,
    pipeline_key: str | None,
    status: PipelineStatus | None,
    since: datetime | None = None,
) -> Select[tuple[PipelineRun]]:
    if pipeline_key:
        statement = statement.where(PipelineRun.pipeline_key == pipeline_key)
    if status:
        statement = statement.where(PipelineRun.status == status)
    if since:
        statement = statement.where(PipelineRun.started_at >= since)
    return statement
```

In `list_runs`, add `since: datetime | None = None,` to the keyword-only parameters (after `status`) and pass `since=since` into the `_apply` call. In `count_runs`, do the same. Both filters ride the existing `ix_pipeline_runs_pipeline_key_started_at` index.

- [ ] **Step 9: Add the aggregate**

Append to `reim/repositories/pipeline_runs.py`, after `summarize_failed_checks`:

```python
def summarize_failed_checks_by_name(
    session: Session, *, since: datetime | None = None
) -> list[FailedCheckGroup]:
    """Return failed checks grouped by name and severity, worst first.

    Grouped in SQL rather than by folding ``list_checks`` in Python: that
    function caps its result at ``limit``, so a check failing more often than
    the cap would be reported as rarer than it is. A wrong number presented
    confidently is worse than no number.

    ``pipeline_keys`` comes from joining the run, whose ``pipeline_key`` is
    the catalog key — an invariant enforced by ``BaseConnector.__init__``,
    which refuses to construct a connector whose key differs from its
    catalog entry's.
    """
    statement = (
        select(
            DataQualityCheck.check_name,
            DataQualityCheck.check_type,
            DataQualityCheck.severity,
            func.count(DataQualityCheck.id).label("failures"),
            func.max(DataQualityCheck.created_at).label("last_failed_at"),
            func.array_agg(PipelineRun.pipeline_key.distinct()).label("pipeline_keys"),
        )
        .join(PipelineRun, DataQualityCheck.pipeline_run_id == PipelineRun.id)
        .where(DataQualityCheck.status == CheckStatus.FAILED)
        .group_by(
            DataQualityCheck.check_name,
            DataQualityCheck.check_type,
            DataQualityCheck.severity,
        )
    )
    if since:
        statement = statement.where(DataQualityCheck.created_at >= since)

    groups = [
        FailedCheckGroup(
            check_name=row.check_name,
            check_type=row.check_type,
            severity=row.severity,
            failures=int(row.failures),
            last_failed_at=row.last_failed_at,
            pipeline_keys=sorted(row.pipeline_keys),
        )
        for row in session.execute(statement)
    ]
    return order_failed_check_groups(groups)
```

- [ ] **Step 10: Run the integration tests to verify they pass**

Run: `.venv/bin/pytest tests/integration/test_pipeline_run_repository.py -q`
Expected: PASS (5 tests)

- [ ] **Step 11: Run the whole gate**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q
```

If `mypy` objects to `row.pipeline_keys` being untyped, that is expected for a SQLAlchemy `Row`: `sorted()` already narrows it to `list[str]` for the Pydantic field, which validates it. Do not add a `type: ignore` unless mypy actually demands one — and if it does, put the narrowest code on it.

- [ ] **Step 12: Commit**

```bash
git add reim/repositories/pipeline_runs.py reim/schemas/pipelines.py \
        tests/unit/test_failed_check_groups.py tests/integration/test_pipeline_run_repository.py
git commit -m "feat(pipelines): group failed checks by name, and window the run queries"
```

---

### Task 2: The `/runs` history table

**Files:**
- Modify: `apps/web/routes.py` (add `_format_duration`, register it as a filter beside `freshness`, add `RunsPageData`, `load_runs_page`, and the `runs` view)
- Create: `apps/web/templates/runs.html`
- Modify: `apps/web/templates/catalog.html:17` and `apps/web/static/reim.css:121` (rename `.catalog-table-wrapper` to `.table-wrapper` — the second table needs it, and a class named for one page is the wrong name for a shared one)
- Test: `tests/unit/test_web_routes.py` (append), `tests/integration/test_web_runs.py` (create)

**Interfaces:**
- Consumes from Task 1: `list_runs(session, *, since=None, limit=...)`, `count_runs(session, *, since=None)`, `summarize_failed_checks_by_name(session, *, since=None)`, `FailedCheckGroup`.
- Produces, relied on by Tasks 3 and 4:
  ```text
  RUN_HISTORY_LIMIT: int = 100
  TRENDS_WINDOW_DAYS: int = 30
  _format_duration(milliseconds: int | None) -> str      # jinja filter "duration"
  load_runs_page(session: Session) -> RunsPageData | None  # None == database did not answer
  RunsPageData(runs: list[PipelineRunRead], runs_in_window: int, failed_checks: list[FailedCheckGroup])
  source_name_for(pipeline_key: str) -> str
  ```

**This task renders the history table and its three empty states. The trends block is Task 3** — leave a `{% block %}`-free placeholder comment where it will go, not a half-built block.

- [ ] **Step 1: Write the failing unit tests for the duration formatter**

Append to `tests/unit/test_web_routes.py` (and extend the module docstring's first line to say it covers the freshness formatter *and the duration formatter*):

```python
def test_a_run_with_no_duration_reads_as_a_dash() -> None:
    """A run still in flight has no duration — a dash, never "0 ms"."""
    assert _format_duration(None) == "—"


@pytest.mark.parametrize(
    ("milliseconds", "expected"),
    [
        (0, "0 ms"),
        (999, "999 ms"),
        (1000, "1.0 s"),
        (59_999, "60.0 s"),
        (60_000, "1m 0s"),
        (3_723_000, "62m 3s"),
    ],
)
def test_every_duration_branch_and_its_boundary(milliseconds: int, expected: str) -> None:
    assert _format_duration(milliseconds) == expected
```

Add `_format_duration` to the existing `from apps.web.routes import _format_freshness` line.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_web_routes.py -q`
Expected: FAIL — `ImportError: cannot import name '_format_duration'`

- [ ] **Step 3: Add the duration formatter and register it**

In `apps/web/routes.py`, after `_format_freshness` (which ends at line 70) and before the `templates = Jinja2Templates(...)` line:

```python
def _format_duration(milliseconds: int | None) -> str:
    """Render a run's duration at the precision a reader can act on.

    ``None`` means the run has not finished — a dash, not "0 ms", which would
    claim it finished instantly.

    The units step up so the number stays two or three significant figures:
    a 90-minute backfill reported as "5400000 ms" is a number nobody reads.
    """
    if milliseconds is None:
        return "—"
    if milliseconds < 1000:
        return f"{milliseconds} ms"
    seconds = milliseconds / 1000
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, remaining_seconds = divmod(int(seconds), 60)
    return f"{minutes}m {remaining_seconds}s"
```

Then register it beside the existing filter:

```text
templates.env.filters["duration"] = _format_duration
```

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_web_routes.py -q`
Expected: PASS (all previous tests plus 7 new)

- [ ] **Step 5: Write the failing page tests**

Create `tests/integration/test_web_runs.py`:

```python
"""The run-history page: routing, the table, and its three empty states.

These need no database except where marked: the page's "database is
unreachable" branch is reached by making the query raise, which is how a real
outage reaches it, and the "no runs yet" branch needs a live but empty schema.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.dependencies import get_db
from apps.api.main import create_app
from reim.core.constants import PipelineStatus
from reim.database.models import PipelineRun
from tests.conftest import requires_db


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    """A test client backed by a live, empty test schema."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _add_run(
    session: Session,
    *,
    pipeline_key: str = "banguat_exchange_rate",
    status: PipelineStatus = PipelineStatus.SUCCESS,
    started_at: datetime | None = None,
    **fields: object,
) -> PipelineRun:
    moment = started_at or datetime.now(UTC)
    run = PipelineRun(
        id=uuid.uuid4(),
        pipeline_key=pipeline_key,
        started_at=moment,
        status=status,
        created_at=moment,
        **fields,
    )
    session.add(run)
    session.flush()
    return run


def test_the_runs_page_is_served() -> None:
    client = TestClient(create_app())

    response = client.get("/runs")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_a_dead_database_is_said_out_loud_not_shown_as_an_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """State one of three: the query itself fails, as a real outage would."""

    def _raise(*args: object, **kwargs: object) -> None:
        raise SQLAlchemyError("database is down")

    monkeypatch.setattr("apps.web.routes.run_repo.list_runs", _raise)
    client = TestClient(create_app())

    body = client.get("/runs").text

    assert "database is not responding" in body.lower()
    assert "no pipeline has run yet" not in body.lower()


@requires_db
def test_an_empty_history_says_nothing_has_run_not_that_it_is_broken(
    client: TestClient,
) -> None:
    """State two of three, and the one a fresh install sees."""
    body = client.get("/runs").text

    assert "No pipeline has run yet" in body
    assert "database is not responding" not in body.lower()


@requires_db
def test_a_run_shows_its_source_status_and_record_counts(
    client: TestClient, session: Session
) -> None:
    """State three: the table, with the facts that make a row worth reading."""
    _add_run(
        session,
        pipeline_key="banguat_exchange_rate",
        status=PipelineStatus.PARTIAL,
        duration_ms=4200,
        records_inserted=17,
        records_updated=3,
        records_rejected=1,
    )

    body = client.get("/runs").text

    assert "Banco de Guatemala" in body or "banguat_exchange_rate" in body
    assert "partial" in body
    assert "4.2 s" in body
    assert "17" in body


@requires_db
def test_a_run_whose_pipeline_left_the_catalog_still_renders(
    client: TestClient, session: Session
) -> None:
    """History outlives the catalog: a removed source must not 500 the page."""
    _add_run(session, pipeline_key="a_source_that_was_removed")

    response = client.get("/runs")

    assert response.status_code == 200
    assert "a_source_that_was_removed" in response.text


@requires_db
def test_the_page_says_it_is_showing_a_bounded_window(client: TestClient) -> None:
    """100 runs is not "all runs", and a page that implies otherwise lies."""
    body = client.get("/runs").text

    assert "100" in body


@requires_db
def test_every_listed_run_links_to_its_detail_page(client: TestClient, session: Session) -> None:
    run = _add_run(session)

    body = client.get("/runs").text

    assert f"/runs/{run.id}" in body
```

- [ ] **Step 6: Run them to verify they fail**

Run: `.venv/bin/pytest tests/integration/test_web_runs.py -q`
Expected: FAIL — `/runs` returns 404 because the route does not exist.

- [ ] **Step 7: Add the page data loader and the view**

In `apps/web/routes.py`, extend the imports:

```python
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from reim.repositories import pipeline_runs as run_repo
from reim.schemas.pipelines import FailedCheckGroup, PipelineRunRead
```

(`datetime` and `UTC` are already imported; add `timedelta` to that line rather than writing a second import.)

Add the two constants below `STATIC_DIRECTORY`:

```python
#: How many runs the history page shows. Roughly four complete sweeps of the
#: 23 pipelines; deeper history is the paginated API's job, and the page says so.
RUN_HISTORY_LIMIT = 100

#: Window for the failed-check trends. Thirty days and not the seven
#: ``SystemStatus`` uses, because these series are ingested infrequently and a
#: block that is always empty stops being read.
TRENDS_WINDOW_DAYS = 30
```

Then, after `load_pipeline_summaries`:

```python
@dataclass(frozen=True)
class RunsPageData:
    """Everything ``/runs`` renders, loaded together or not at all."""

    runs: list[PipelineRunRead]
    runs_in_window: int
    failed_checks: list[FailedCheckGroup]


def load_runs_page(session: Session) -> RunsPageData | None:
    """Return the history page's data, or ``None`` when the database is out.

    Three queries share one ``try``: the page has nothing to show if any of
    them fails, so there is no partial state worth rendering, and one
    ``except`` means one place decides "unreachable" — the same argument
    ``load_pipeline_summaries`` makes, and the reason neither function pings
    the database first. ``None`` rather than a flag because there is no
    meaningful empty ``RunsPageData``: zero runs and no data at all are
    different answers, and the template must not be able to confuse them.
    """
    since = datetime.now(UTC) - timedelta(days=TRENDS_WINDOW_DAYS)
    try:
        runs = run_repo.list_runs(session, limit=RUN_HISTORY_LIMIT)
        runs_in_window = run_repo.count_runs(session, since=since)
        failed_checks = run_repo.summarize_failed_checks_by_name(session, since=since)
    except SQLAlchemyError:
        return None
    return RunsPageData(
        runs=[PipelineRunRead.model_validate(run) for run in runs],
        runs_in_window=runs_in_window,
        failed_checks=failed_checks,
    )


def source_name_for(pipeline_key: str) -> str:
    """The catalog's name for a run's pipeline, falling back to the key.

    History outlives the catalog: a source removed from ``sources/catalog.yml``
    keeps its runs in the database, and ``SourceCatalog.get`` raises
    ``CatalogError`` for a key it does not know
    (``reim/domain/sources/catalog.py:160-170``) rather than returning
    ``None``. Falling back to the raw key keeps that row readable instead of
    failing a page whose whole job is to show history.
    """
    try:
        return get_catalog().get(pipeline_key).name
    except CatalogError:
        return pipeline_key
```

`CatalogError` is defined at `reim/core/exceptions.py:37`; import it as
`from reim.core.exceptions import CatalogError`. The catalog import line is
already `from reim.domain.sources.catalog import SourceEntry, get_catalog` and
needs no change.

Then the view:

```python
@router.get("/runs", response_class=HTMLResponse)
def runs(request: Request, session: SessionDep) -> HTMLResponse:
    """Run history across every pipeline, newest first.

    Three states the table must never conflate, because they call for three
    different actions: the database is unreachable (investigate the database),
    nothing has run (start the scheduler), and runs exist (read them). The
    template gives each its own sentence.
    """
    data = load_runs_page(session)
    rows = (
        [(run, source_name_for(run.pipeline_key)) for run in data.runs] if data is not None else []
    )
    return templates.TemplateResponse(
        request,
        "runs.html",
        {
            "data": data,
            "rows": rows,
            "history_limit": RUN_HISTORY_LIMIT,
            "window_days": TRENDS_WINDOW_DAYS,
        },
    )
```

**`SourceCatalog.get` raises; it does not return `None`.** Measured at `reim/domain/sources/catalog.py:160-170`: an unknown key raises `CatalogError`, listing the available keys. `source_name_for` therefore catches rather than tests for `None`. Do not change `get`'s contract from the web layer — a catalog lookup that silently returns nothing would weaken every other caller to fix one.

- [ ] **Step 8: Create the template**

Create `apps/web/templates/runs.html`:

```html
{% extends "base.html" %}

{% block title %}Runs · REIM{% endblock %}

{% block content %}
<section class="runs">
  <h2>Pipeline runs</h2>

  {% if data is none %}
  {#
    The whole page is database-backed, unlike the catalog, which renders from
    sources/catalog.yml with or without one. So there is no table to degrade:
    the notice replaces it rather than sitting above it.
  #}
  <p class="notice" role="status">The run history cannot be read: the database is not responding.</p>
  {% elif not data.runs %}
  {#
    Distinct from the notice above and from "no failures" below. A fresh
    install lands here, and it means "start the scheduler", not "something
    broke" — the reader cannot act correctly on a sentence that covers both.
  #}
  <p class="muted">No pipeline has run yet.</p>
  {% else %}
  <div class="table-wrapper">
    <table class="runs-table">
      <caption>The {{ rows | length }} most recent runs (of at most {{ history_limit }})</caption>
      <thead>
        <tr>
          <th scope="col">Started</th>
          <th scope="col">Source</th>
          <th scope="col">Status</th>
          <th scope="col">Duration</th>
          <th scope="col">Records (inserted / updated / rejected)</th>
        </tr>
      </thead>
      <tbody>
        {% for run, source_name in rows %}
        <tr>
          <td><a href="/runs/{{ run.id }}">{{ run.started_at | freshness }}</a></td>
          <td>{{ source_name }}</td>
          <td class="status-{{ run.status.value }}">{{ run.status.value }}</td>
          <td>{{ run.duration_ms | duration }}</td>
          <td>{{ run.records_inserted }} / {{ run.records_updated }} / {{ run.records_rejected }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  <p class="muted">
    Showing the most recent {{ history_limit }} runs. Older runs are available from
    <code>/api/v1/pipelines/runs</code>, which is paginated.
  </p>
  {# The failed-check trends block is added in Task 3, below this paragraph. #}
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 9: Generalise the shared table wrapper**

In `apps/web/static/reim.css`, rename the selector `.catalog-table-wrapper` (line 121) to `.table-wrapper`. In `apps/web/templates/catalog.html` (line 17), change `<div class="catalog-table-wrapper">` to `<div class="table-wrapper">`. Add, beside it:

```css
.notice {
  margin: 0 0 1rem;
  padding: 0.75rem 1rem;
  border-left: 3px solid #b23c17;
  background: #fdf2ee;
}
```

`.catalog-notice` at line 125 keeps its own rule; do not merge the two in this task.

- [ ] **Step 10: Run the page tests to verify they pass**

Run: `.venv/bin/pytest tests/integration/test_web_runs.py tests/integration/test_web.py -q`
Expected: PASS — including the existing catalog tests, which must not regress from the class rename.

- [ ] **Step 11: Prove the table test has teeth**

Blank the source-name cell in `runs.html` (`<td></td>` in place of `<td>{{ source_name }}</td>`) and run `test_a_run_shows_its_source_status_and_record_counts`. It must FAIL. Restore the cell, re-run, confirm PASS, and confirm `git diff` shows only your intended changes.

A test that passes with the cell blanked is asserting on markup, not content — the mistake this branch's constraints exist to prevent.

- [ ] **Step 12: Run the whole gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q
git add apps/web/routes.py apps/web/templates/runs.html apps/web/templates/catalog.html \
        apps/web/static/reim.css tests/unit/test_web_routes.py tests/integration/test_web_runs.py
git commit -m "feat(web): show what the pipelines actually did, run by run"
```

---

### Task 3: The failed-check trends block

**Files:**
- Modify: `apps/web/templates/runs.html` (replace the Task 2 placeholder comment)
- Modify: `apps/web/static/reim.css` (severity styling)
- Test: `tests/integration/test_web_runs.py` (append)

**Interfaces:**
- Consumes from Task 2: `data.failed_checks: list[FailedCheckGroup]`, `data.runs_in_window: int`, `window_days: int` — all already in the template context; this task adds **no Python**.
- Produces: nothing later tasks consume.

**The three states this block must distinguish**, and why each needs its own sentence: zero runs in the window means ingestion has stopped; runs with no failures means healthy; failures means act. An operator told only that a list is empty cannot tell the first from the second, and they are opposite conditions.

- [ ] **Step 1: Write the failing tests for the three states**

Append to `tests/integration/test_web_runs.py`:

```python
@requires_db
def test_no_runs_in_the_window_is_not_reported_as_no_failures(
    client: TestClient, session: Session
) -> None:
    """The distinction the whole block exists for.

    A pipeline that stopped running 90 days ago produces no failed checks in
    a 30-day window — identical output to a pipeline that ran perfectly, and
    the opposite situation. One says "investigate", the other says "fine".
    """
    _add_run(session, started_at=datetime.now(UTC) - timedelta(days=90))

    body = client.get("/runs").text

    assert "No pipeline ran in the last 30 days" in body
    assert "no failed checks" not in body.lower()


@requires_db
def test_runs_without_failures_report_how_many_ran(client: TestClient, session: Session) -> None:
    """ "Healthy" is only meaningful with the evidence beside it."""
    _add_run(session, started_at=datetime.now(UTC) - timedelta(days=1))
    _add_run(session, started_at=datetime.now(UTC) - timedelta(days=2))

    body = client.get("/runs").text

    assert "2 runs in the last 30 days" in body
    assert "no failed checks" in body.lower()
    assert "No pipeline ran in the last 30 days" not in body


@requires_db
def test_a_failing_check_is_named_counted_and_dated(client: TestClient, session: Session) -> None:
    now = datetime.now(UTC)
    for offset in (1, 2, 3):
        run = _add_run(session, started_at=now - timedelta(days=offset))
        session.add(
            DataQualityCheck(
                id=uuid.uuid4(),
                pipeline_run_id=run.id,
                check_name="freshness_within_threshold",
                check_type=CheckType.TIMELINESS,
                status=CheckStatus.FAILED,
                severity=CheckSeverity.ERROR,
                created_at=now - timedelta(days=offset),
            )
        )
    session.flush()

    body = client.get("/runs").text

    assert "freshness_within_threshold" in body
    assert "3" in body
    assert "error" in body
    assert "banguat_exchange_rate" in body or "Banco de Guatemala" in body
    assert "no failed checks" not in body.lower()
```

Extend that file's imports with:

```python
from reim.core.constants import CheckSeverity, CheckStatus, CheckType, PipelineStatus
from reim.database.models import DataQualityCheck, PipelineRun
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/integration/test_web_runs.py -q -k "window or failures or failing"`
Expected: FAIL — none of those sentences is in the page yet.

- [ ] **Step 3: Add the block**

In `apps/web/templates/runs.html`, replace the line
`{# The failed-check trends block is added in Task 3, below this paragraph. #}`
with:

```html
  <section class="trends">
    <h3>Failed quality checks, last {{ window_days }} days</h3>
    {% if data.runs_in_window == 0 %}
    {#
      Not the same as "no failures": this says ingestion has stopped. The two
      look identical if the block only reports an empty list, and they call
      for opposite responses.
    #}
    <p class="muted">No pipeline ran in the last {{ window_days }} days.</p>
    {% elif not data.failed_checks %}
    {#
      The run count is the evidence that makes "healthy" mean anything. Without
      it the reader cannot tell this from the branch above.
    #}
    <p class="muted">{{ data.runs_in_window }} runs in the last {{ window_days }} days, no failed checks.</p>
    {% else %}
    <div class="table-wrapper">
      <table class="checks-table">
        <caption>{{ data.failed_checks | length }} check(s) failing, most severe first</caption>
        <thead>
          <tr>
            <th scope="col">Check</th>
            <th scope="col">Type</th>
            <th scope="col">Severity</th>
            <th scope="col">Failures</th>
            <th scope="col">Last failed</th>
            <th scope="col">Pipelines</th>
          </tr>
        </thead>
        <tbody>
          {% for group in data.failed_checks %}
          <tr>
            <td>{{ group.check_name }}</td>
            <td>{{ group.check_type.value }}</td>
            <td class="severity-{{ group.severity.value }}">{{ group.severity.value }}</td>
            <td>{{ group.failures }}</td>
            <td>{{ group.last_failed_at | freshness }}</td>
            <td>{{ group.pipeline_keys | join(", ") }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% endif %}
  </section>
```

- [ ] **Step 4: Style the severities**

Append to `apps/web/static/reim.css`:

```css
.severity-critical,
.severity-error {
  color: #b23c17;
  font-weight: 600;
}

.severity-warning {
  color: #8a6100;
}

.status-failed {
  color: #b23c17;
  font-weight: 600;
}

.status-partial {
  color: #8a6100;
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/integration/test_web_runs.py -q`
Expected: PASS (all tests from Tasks 2 and 3)

- [ ] **Step 6: Prove the three states are genuinely distinct**

Run the three new tests together and confirm each asserts the *absence* of the other states' wording, not only the presence of its own. Then change the `{% elif not data.failed_checks %}` branch to render the same words as the branch above it and confirm `test_runs_without_failures_report_how_many_ran` fails. Revert.

If the tests still pass with two branches sharing wording, they are not testing what this block is for — strengthen them before moving on.

- [ ] **Step 7: Run the whole gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q
git add apps/web/templates/runs.html apps/web/static/reim.css tests/integration/test_web_runs.py
git commit -m "feat(web): say what is failing, and tell a quiet pipeline from a healthy one"
```

---

### Task 4: The run detail page and its HTML 404

**Files:**
- Modify: `apps/web/routes.py` (the `run_detail` view)
- Create: `apps/web/templates/run_detail.html`, `apps/web/templates/run_not_found.html`
- Test: `tests/integration/test_web_runs.py` (append)

**Interfaces:**
- Consumes from Task 2: `templates`, `source_name_for`, the `duration` and `freshness` filters.
- Produces: nothing later tasks consume.

**Why the view does not raise.** Every handler in `apps/api/errors.py` returns `JSONResponse`, unconditionally — `apps/api/routers/pipelines.py:71` raises `ResourceNotFoundError` and the API client gets an error envelope, which is correct for the API and useless to a browser. So this view parses the identifier itself and returns an HTML page with status 404 for **both** a malformed identifier and an unknown run. Do not touch `apps/api/errors.py`; content negotiation there would make every API error path depend on a request attribute in order to serve two view functions.

**Route order matters.** `/runs/{run_id}` must be registered *after* `/runs`, and `run_id` is typed `str`, not `uuid.UUID` — a `UUID` annotation hands validation back to FastAPI, which produces the JSON 422 this task exists to avoid.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_web_runs.py`:

```python
def test_a_malformed_run_id_gets_a_page_not_a_json_envelope() -> None:
    """FastAPI would answer 422 JSON; a browser can do nothing with that."""
    client = TestClient(create_app())

    response = client.get("/runs/not-a-uuid")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "not-a-uuid" in response.text


@requires_db
def test_an_unknown_run_gets_the_same_page(client: TestClient) -> None:
    unknown = uuid.uuid4()

    response = client.get(f"/runs/{unknown}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")


@requires_db
def test_a_run_detail_shows_all_five_counters(client: TestClient, session: Session) -> None:
    """Extracted and unchanged appear nowhere else in the web surface.

    ``extracted`` against the other four is how a reader sees rows going
    missing, which is precisely what the overview's three counters hide.
    """
    run = _add_run(
        session,
        records_extracted=100,
        records_inserted=60,
        records_updated=20,
        records_unchanged=15,
        records_rejected=5,
    )

    body = client.get(f"/runs/{run.id}").text

    for count in ("100", "60", "20", "15", "5"):
        assert count in body


@requires_db
def test_a_failed_run_shows_its_error(client: TestClient, session: Session) -> None:
    run = _add_run(
        session,
        status=PipelineStatus.FAILED,
        error_type="ConnectorTimeout",
        error_message="Banguat did not answer within 30s",
    )

    body = client.get(f"/runs/{run.id}").text

    assert "ConnectorTimeout" in body
    assert "Banguat did not answer within 30s" in body


@requires_db
def test_a_successful_run_shows_no_error_block(client: TestClient, session: Session) -> None:
    run = _add_run(session, status=PipelineStatus.SUCCESS)

    body = client.get(f"/runs/{run.id}").text

    assert "Error" not in body


@requires_db
def test_run_metadata_is_shown_when_the_connector_recorded_any(
    client: TestClient, session: Session
) -> None:
    run = _add_run(session, run_metadata={"connector_key": "banguat_exchange_rate"})

    body = client.get(f"/runs/{run.id}").text

    assert "connector_key" in body
    assert "banguat_exchange_rate" in body


@requires_db
def test_the_checks_a_run_produced_are_listed(client: TestClient, session: Session) -> None:
    run = _add_run(session)
    session.add(
        DataQualityCheck(
            id=uuid.uuid4(),
            pipeline_run_id=run.id,
            check_name="value_within_range",
            check_type=CheckType.VALIDITY,
            status=CheckStatus.FAILED,
            severity=CheckSeverity.ERROR,
            indicator_code="gt_exchange_rate_official_daily",
            period_label="2026-09-01",
            expected_value="<= 8.0",
            actual_value="41.7",
            created_at=datetime.now(UTC),
        )
    )
    session.flush()

    body = client.get(f"/runs/{run.id}").text

    assert "value_within_range" in body
    assert "gt_exchange_rate_official_daily" in body
    assert "41.7" in body


@requires_db
def test_a_run_with_no_checks_says_so(client: TestClient, session: Session) -> None:
    """An empty table reads as a broken page; the words read as a fact."""
    run = _add_run(session)

    body = client.get(f"/runs/{run.id}").text

    assert "recorded no quality checks" in body.lower()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/integration/test_web_runs.py -q -k "run_detail or malformed or unknown_run or counters or error or metadata or checks"`
Expected: FAIL — `/runs/<uuid>` returns 404 from the router with a JSON body, not an HTML page.

- [ ] **Step 3: Add the view**

Append to `apps/web/routes.py`, after the `runs` view:

```python
@router.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(request: Request, session: SessionDep, run_id: str) -> HTMLResponse:
    """One run in full: every counter, its error, its metadata, its checks.

    ``run_id`` is a ``str`` and parsed here rather than annotated ``uuid.UUID``
    on purpose. A ``UUID`` annotation hands validation to FastAPI, whose
    ``RequestValidationError`` handler returns a JSON envelope — correct for
    the API, useless to a browser. Both a malformed identifier and an unknown
    run are the same thing to a reader ("that run is not here"), so both get
    the same HTML page with status 404.

    The view never raises ``ResourceNotFoundError`` the way
    ``apps/api/routers/pipelines.py`` does, because every handler in
    ``apps/api/errors.py`` answers in JSON unconditionally. Teaching those
    handlers to negotiate content would make every API error path carry a
    branch that exists for two view functions.
    """
    try:
        identifier = uuid.UUID(run_id)
    except ValueError:
        return _run_not_found(request, run_id)

    try:
        run = run_repo.get_run(session, identifier)
    except SQLAlchemyError:
        return templates.TemplateResponse(request, "run_detail.html", {"run": None})

    if run is None:
        return _run_not_found(request, run_id)

    detail = PipelineRunDetail.model_validate(run)
    detail.quality_checks = [QualityCheckRead.model_validate(check) for check in run.quality_checks]
    return templates.TemplateResponse(
        request,
        "run_detail.html",
        {"run": detail, "source_name": source_name_for(detail.pipeline_key)},
    )


def _run_not_found(request: Request, run_id: str) -> HTMLResponse:
    """The 404 page, for a malformed identifier and an unknown run alike."""
    return templates.TemplateResponse(
        request, "run_not_found.html", {"run_id": run_id}, status_code=404
    )
```

Extend the schema import to `from reim.schemas.pipelines import FailedCheckGroup, PipelineRunDetail, PipelineRunRead, QualityCheckRead`.

- [ ] **Step 4: Create the two templates**

Create `apps/web/templates/run_not_found.html`:

```html
{% extends "base.html" %}

{% block title %}Run not found · REIM{% endblock %}

{% block content %}
<section class="run-detail">
  <h2>Run not found</h2>
  {#
    The identifier is echoed back because the commonest way to land here is a
    truncated or mistyped link, and the reader cannot check that against what
    they meant unless they can see it.
  #}
  <p>No pipeline run is recorded with the identifier <code>{{ run_id }}</code>.</p>
  <p><a href="/runs">Back to the run history</a></p>
</section>
{% endblock %}
```

Create `apps/web/templates/run_detail.html`:

```html
{% extends "base.html" %}

{% block title %}Run · REIM{% endblock %}

{% block content %}
<section class="run-detail">
  {% if run is none %}
  <h2>Pipeline run</h2>
  <p class="notice" role="status">This run cannot be read: the database is not responding.</p>
  {% else %}
  <h2>{{ source_name }}</h2>
  <dl class="run-facts">
    <dt>Status</dt><dd class="status-{{ run.status.value }}">{{ run.status.value }}</dd>
    <dt>Started</dt><dd>{{ run.started_at | freshness }}</dd>
    <dt>Finished</dt><dd>{% if run.finished_at %}{{ run.finished_at | freshness }}{% else %}Still running{% endif %}</dd>
    <dt>Duration</dt><dd>{{ run.duration_ms | duration }}</dd>
    <dt>Connector version</dt><dd>{{ run.connector_version or "—" }}</dd>
    <dt>Pipeline version</dt><dd>{{ run.pipeline_version or "—" }}</dd>
    <dt>Pipeline key</dt><dd><code>{{ run.pipeline_key }}</code></dd>
  </dl>

  {#
    All five counters, unlike the overview's three. Extracted against the sum
    of the other four is how a reader sees that rows went missing between the
    source and the database — the one arithmetic this page exists to allow.
  #}
  <h3>Records</h3>
  <div class="table-wrapper">
    <table class="counters-table">
      <caption>What the run did with the rows it fetched</caption>
      <thead>
        <tr>
          <th scope="col">Extracted</th>
          <th scope="col">Inserted</th>
          <th scope="col">Updated</th>
          <th scope="col">Unchanged</th>
          <th scope="col">Rejected</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>{{ run.records_extracted }}</td>
          <td>{{ run.records_inserted }}</td>
          <td>{{ run.records_updated }}</td>
          <td>{{ run.records_unchanged }}</td>
          <td>{{ run.records_rejected }}</td>
        </tr>
      </tbody>
    </table>
  </div>

  {% if run.error_type or run.error_message %}
  <h3>Error</h3>
  <p class="notice"><strong>{{ run.error_type }}</strong> &mdash; {{ run.error_message }}</p>
  {% endif %}

  {% if run.run_metadata %}
  {# Where connectors leave run-specific context; absent for a run that recorded none. #}
  <h3>Run metadata</h3>
  <dl class="run-facts">
    {% for key, value in run.run_metadata.items() %}
    <dt>{{ key }}</dt><dd>{{ value }}</dd>
    {% endfor %}
  </dl>
  {% endif %}

  <h3>Quality checks</h3>
  {% if run.quality_checks %}
  <div class="table-wrapper">
    <table class="checks-table">
      <caption>{{ run.quality_checks | length }} check(s) recorded by this run</caption>
      <thead>
        <tr>
          <th scope="col">Check</th>
          <th scope="col">Type</th>
          <th scope="col">Result</th>
          <th scope="col">Severity</th>
          <th scope="col">Indicator</th>
          <th scope="col">Period</th>
          <th scope="col">Expected</th>
          <th scope="col">Actual</th>
        </tr>
      </thead>
      <tbody>
        {% for check in run.quality_checks %}
        <tr>
          <td>{{ check.check_name }}</td>
          <td>{{ check.check_type.value }}</td>
          <td class="status-{{ check.status.value }}">{{ check.status.value }}</td>
          <td class="severity-{{ check.severity.value }}">{{ check.severity.value }}</td>
          <td>{{ check.indicator_code or "—" }}</td>
          <td>{{ check.period_label or "—" }}</td>
          <td>{{ check.expected_value or "—" }}</td>
          <td>{{ check.actual_value or "—" }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  {# Stated, not left blank: an empty section reads as a failed render. #}
  <p class="muted">This run recorded no quality checks.</p>
  {% endif %}

  <p><a href="/runs">Back to the run history</a></p>
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 5: Style the definition lists**

Append to `apps/web/static/reim.css`:

```css
.run-facts {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 0.35rem 1.5rem;
  margin: 0 0 1.5rem;
}

.run-facts dt {
  font-weight: 600;
  color: #4a4a4a;
}

.run-facts dd {
  margin: 0;
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/integration/test_web_runs.py -q`
Expected: PASS

Note `test_a_successful_run_shows_no_error_block` asserts `"Error" not in body`. If the word appears elsewhere on the page (a nav item, a severity label in a check row), that assertion will fail for the wrong reason — tighten it to the `<h3>Error</h3>` heading's text content rather than deleting it, and say in the report that you did.

- [ ] **Step 7: Run the whole gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q
git add apps/web/routes.py apps/web/templates/run_detail.html \
        apps/web/templates/run_not_found.html apps/web/static/reim.css \
        tests/integration/test_web_runs.py
git commit -m "fix(web): answer a browser with a page, not an error envelope"
```

---

### Task 5: Navigation, a live run, and the documentation

**Files:**
- Modify: `apps/web/templates/base.html:13-15` (the nav)
- Modify: `ROADMAP.md:294`, `README.md`
- Test: `tests/integration/test_web_runs.py` (append one test)

**Interfaces:**
- Consumes from Tasks 2 and 4: the `/runs` and `/runs/{run_id}` routes.
- Produces: nothing.

- [ ] **Step 1: Write the failing navigation test**

Append to `tests/integration/test_web_runs.py`:

```python
def test_both_pages_are_reachable_from_the_navigation() -> None:
    """A page nobody can click is a page nobody reads."""
    client = TestClient(create_app())

    for path in ("/", "/runs"):
        body = client.get(path).text
        assert 'href="/runs"' in body
        assert 'href="/"' in body
```

This is the one place asserting on an attribute rather than on rendered text, because a navigation link *is* its `href` — there is no rendered content that proves reachability. Say so in the test, not only here.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/integration/test_web_runs.py -q -k navigation`
Expected: FAIL — `base.html` has only the catalog link.

- [ ] **Step 3: Add the link**

In `apps/web/templates/base.html`, replace the nav block:

```html
    <nav class="site-nav">
      <a href="/">Catalog</a>
      <a href="/runs">Runs</a>
    </nav>
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/pytest tests/integration/test_web_runs.py -q -k navigation`
Expected: PASS

- [ ] **Step 5: See the pages with real data in them**

Every test above builds its rows by hand. Run one real pipeline so the pages are seen with data a connector actually produced — including quality checks the runner wrote, which no test constructs the same way.

```bash
make db-up CONTAINER_ENGINE=podman
export REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim
export REIM_DATABASE_URL=$REIM_TEST_DATABASE_URL
.venv/bin/alembic upgrade head
.venv/bin/python -m reim.cli db seed
.venv/bin/python -m reim.cli pipeline run worldbank_ni_cpi_inflation
.venv/bin/uvicorn apps.api.main:app --port 8123 &
sleep 3
curl -s localhost:8123/runs | head -60
curl -s localhost:8123/runs | grep -o '/runs/[0-9a-f-]\{36\}' | head -1
```

Then fetch that detail URL and confirm by eye: the run appears with its source name, its status and its duration; the trends block reports the right run count; the detail page shows five counters and the checks the runner recorded. Kill the server (`kill %1`) when done.

Record in your report **what you actually saw** — the run count, whether any check failed, and the rendered duration. If the pipeline fails against the live API (it reaches `api.worldbank.org`), that is still a useful result: the page then shows a failed run with an error, which is the state hardest to see otherwise. Report which of the two happened.

- [ ] **Step 6: Update the roadmap**

In `ROADMAP.md`, replace line 294:

```text
- **Pipeline observability page** — run history, quality trends, staleness.
```

with an entry in the style of the catalog browser's above it: strike the title, mark it done, and say what shipped — the two pages, the 100-run window and the 30-day trends window with their reasons, the six empty states and why they are separate, the HTML 404 that leaves the API's error envelope untouched, and the one backend addition (`summarize_failed_checks_by_name`, grouped in SQL so a recurring failure is not undercounted). Do not claim staleness: it stayed on the catalog page deliberately, and the entry should say that this page is about history instead.

- [ ] **Step 7: Update the README**

`README.md` has a `## Web pages` section at line 318, written as prose (no route table) and opening "REIM's first web page is a server-rendered catalog browser". Rewrite that opening so it covers both pages rather than claiming there is one, and add a paragraph for `/runs` and `/runs/{run_id}`: what each shows, the 100-run window, and that the history page needs a database where the catalog does not. Keep the closing paragraph about the API being unchanged — it is still true and still worth saying.

- [ ] **Step 8: Check the documentation for the formatter's bite**

`ruff format` rewrites any ` ```python ` block in Markdown that is not a valid standalone module. Run:

```bash
.venv/bin/ruff format --check .
```

If it reports a Markdown file, the fix is to fence that fragment as ` ```text `, not to reformat the prose around it.

- [ ] **Step 9: Run the whole gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q
git add apps/web/templates/base.html ROADMAP.md README.md tests/integration/test_web_runs.py
git commit -m "docs(web): the observability page, and what it shows"
```

---

## Self-Review

**Spec coverage.** Every section maps to a task: §2.1 and §2.2 → Task 1; §3.1's table → Task 2; §3.1's trends block → Task 3; §3.2 and §5 → Task 4; the nav and docs → Task 5. §4's six empty states are split across Tasks 2 (three) and 3 (three), each with a test asserting the absence of its neighbours' wording. §6's testing requirements are distributed into the tasks that create the code they cover. §1.2's key invariant is used in Task 1's docstring and Task 2's `source_name_for`.

**Two spec gaps found while planning, decided here rather than left open:**

1. **The detail page's degraded state.** §4 specifies the three states of the *history* table but not what `/runs/{run_id}` does when the database is out. Task 4 renders the same notice with **status 200**, matching the catalog page's precedent — a page that explains itself is not a server error, and `/ready` already exists for health checking. Cost if wrong: a monitor watching page status codes would not see the outage, which is not what page status codes are for.

2. **A run whose pipeline has left the catalog.** Not in the spec at all, and it would have been a 500 on a page whose whole purpose is history — history outlives `sources/catalog.yml`. `source_name_for` falls back to the raw key, and Task 2 tests it.

**One instruction to verify rather than trust:** Task 2 Step 7 depends on `get_catalog().get(key)` returning `None` for an unknown key. The existing tests only assert `is not None` for keys that exist, which does not prove the negative case. The step says to check it and to adapt in `source_name_for` — not to change `get`'s contract from the web layer.

**Type consistency.** `FailedCheckGroup` is defined in Task 1 and consumed by name in Tasks 2 and 3 with the same six fields. `RunsPageData`, `load_runs_page`, `source_name_for`, `RUN_HISTORY_LIMIT` and `TRENDS_WINDOW_DAYS` are defined in Task 2 and used under those exact names in Tasks 3 and 4. The `duration` and `freshness` filters are registered in Task 2 and used in Tasks 2, 3 and 4.

**Deliberate ordering.** Task 3 adds no Python — it consumes context Task 2 already passes. That is why the trends block is its own task: a reviewer can reject the empty-state wording without touching the table, and the six states are exactly where a copy/paste error hides.
