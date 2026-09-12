# The pipeline observability page — design

REIM's second web page: what the ingestion pipelines actually did, run by run,
and which quality checks are failing. It reuses the skeleton the catalog
browser introduced and answers the question that page cannot — *what happened
before now*.

This is v0.4.0's second increment. Everything measured below was checked
against the repository on 2026-09-12.

## 1. What exists, and what this adds

The backend is already here. Measured, not assumed:

| Piece | State |
|---|---|
| `PipelineRun` (`reim/database/models/pipeline.py:21`) | Status, timings, `duration_ms`, five record counters, `error_type`/`error_message`, `run_metadata` JSONB, indexed on `(pipeline_key, started_at)` |
| `DataQualityCheck` (`…/pipeline.py:71`) | Written by the runner on every run (`reim/ingestion/runner.py:409`) — not an empty table |
| Repository (`reim/repositories/pipeline_runs.py`) | `list_runs:28`, `count_runs:45`, `get_run:60` (checks eager-loaded), `list_checks:92`, `summarize_failed_checks:114` |
| Schemas | `PipelineRunRead`, `PipelineRunDetail`, `QualityCheckRead` (`reim/schemas/pipelines.py:37,62,19`) |
| API | `/api/v1/pipelines/runs` and `/runs/{run_id}` already serve this |
| Web skeleton | `apps/web/routes.py`, `base.html` with its nav, `reim.css`, `load_pipeline_summaries:72`, the `TestClient` approach |

So this increment is front end over functions that exist, exactly as the
catalog browser was. It adds **one repository query and one schema**; no model,
no migration.

### 1.1 Why this is not the catalog page again

Freshness already has a home. The catalog shows `last_success_at`, the age in
days and the last run's status, per source. A second page repeating that would
be two pages telling the same story.

What the catalog structurally cannot show is **history**: what the previous
runs did, which checks failed, and whether a failure is new or has been
recurring for weeks. `PipelineSummary` collapses all of it into the last run.
This page is built around that difference, not around freshness.

### 1.2 The one measured fact that removes a join

**`pipeline_key == source_key == the catalog entry's key`, and that is an
enforced invariant, not a convention.** The run row takes
`connector.connector_key` (`reim/ingestion/runner.py:220` and `:249`), and
`BaseConnector.__init__` refuses to construct a connector whose key differs
from its catalog entry's:

```text
if source.key != self.connector_key:
    raise ValueError(...)          # reim/ingestion/base.py:44-46
```

`build_pipeline_summaries` sets both schema fields from the same `entry.key`
(`reim/services/status.py:58-59`).

A run therefore maps to a catalog entry by string key, in memory, with no
database lookup — the same join the catalog page already performs. The page
never resolves `PipelineRun.source_id`, which is nullable (`ondelete="SET
NULL"`) and would need a query per row.

## 2. The backend addition

### 2.1 Grouping failed checks by name

`summarize_failed_checks` groups by **severity only** — it returns
`{severity: count}`, which is what `SystemStatus.failed_checks_last_7_days`
needs and nothing more. "Which check is failing, and since when" needs
grouping by `(check_name, severity)` with a count, the latest occurrence and
the pipelines involved.

That is a new aggregate in SQL, joining `DataQualityCheck` to `PipelineRun`
for `pipeline_key`. The alternative — pulling rows through `list_checks` and
aggregating in Python — would silently truncate at its `limit` and report a
recurring failure as a rarer one than it is. A wrong number presented
confidently is worse than no number.

```text
summarize_failed_checks_by_name(session, *, since) -> list[FailedCheckGroup]
```

`FailedCheckGroup` is a new Pydantic model in `reim/schemas/pipelines.py`
carrying `check_name`, `check_type`, `severity`, `failures`, `last_failed_at`
and `pipeline_keys`. Ordered by severity (most severe first), then by
`failures` descending: the reader's first question is what is most broken.

### 2.2 A time window on the run queries

`_apply` (`pipeline_runs.py:15`) gains `since: datetime | None = None`, which
`list_runs` and `count_runs` inherit together since both build on it. Existing
callers are unaffected — the parameter is keyword-only with a `None` default,
and `None` adds no clause.

This is not gold-plating: §4 shows that without a run count over the same
window, "nothing failed" and "nothing ran" are indistinguishable, and that is
the single most misleading thing an observability page can do.

## 3. The two pages

### 3.1 `/runs` — the history

The **most recent 100 runs** across all pipelines, newest first: start time
with its age, the source, status, duration, records inserted / updated /
rejected, and a link to the detail page.

One hundred is roughly four complete sweeps of the 23 pipelines; fifty would be
barely two. Deeper history is the API's job — `/api/v1/pipelines/runs?offset=`
is paginated and stays so. The page **says** it is showing the most recent 100
rather than implying that is all there is.

Below it, the trends block: **failed quality checks over the last 30 days**,
grouped as §2.1 describes. Thirty days and not seven because these are
economic series ingested infrequently — a seven-day window would show an empty
block almost always, and an always-empty block teaches the reader to stop
looking at it.

### 3.2 `/runs/{run_id}` — one run

Everything the overview compresses away:

* Pipeline, status, started and finished, duration, `connector_version` and
  `pipeline_version`.
* **All five counters** — extracted, inserted, updated, unchanged, rejected.
  `PipelineSummary` carries only three; extracted and unchanged appear nowhere
  else in the web surface, and `extracted` against `inserted + updated +
  unchanged + rejected` is how a reader sees that rows went missing.
* The error block — `error_type` and `error_message` — when the run recorded
  one.
* `run_metadata` as key/value rows **when it is non-empty**, which is where
  connectors leave run-specific context.
* The full quality-check table: name, type, status, severity, indicator,
  period, expected against actual.

## 4. The empty states

The catalog page renders without a database; **this page does not**. Every
block on it comes from the database, so a dead database leaves nothing to
show. That makes the state-conflation failure more dangerous here, and the last
branch's review already caught one instance of it (three distinct states
rendering the same sentence).

The run table distinguishes three states:

| Condition | What it says |
|---|---|
| Database unreachable | *The run history cannot be read: the database is not responding.* |
| Database fine, zero runs | *No pipeline has run yet.* |
| Database fine, runs exist | The table |

The trends block distinguishes three more, and the middle one is the reason
§2.2 exists:

| Condition | What it says |
|---|---|
| Zero runs in the window | *No pipeline ran in the last 30 days.* |
| Runs happened, no failures | *N runs in the last 30 days, no failed checks.* |
| Failures | The grouped table |

"Nothing failed" and "nothing ran" look identical to an operator who is told
only that the list is empty, and they mean opposite things: one is healthy, the
other means ingestion has stopped. Separating them is the point of the block.

Database availability is discovered the way `load_pipeline_summaries`
(`apps/web/routes.py:72`) already discovers it — by issuing the query and
catching `SQLAlchemyError`, not by a connectivity check beforehand that a
query one millisecond later can outlive. That helper's docstring makes the
argument; this page follows it rather than restating it.

## 5. The 404, without touching the API's error contract

Every exception handler in `apps/api/errors.py` returns `JSONResponse`,
unconditionally. A web view that raised `ResourceNotFoundError` the way
`apps/api/routers/pipelines.py:71` does would hand a browser an error envelope
instead of a page.

So the view **does not raise**. It takes `run_id` as `str`, parses it itself,
and returns an HTML page with status 404 for both a malformed identifier and a
well-formed one that matches no run. Today `/runs/not-a-uuid` would produce a
422 JSON validation error, which is exactly as useless to a browser as the 404
would be.

The API's uniform error envelope is left untouched. Content negotiation inside
the shared handlers was rejected: it would make every API error path depend on
a request attribute, to fix a problem that belongs to two view functions.

## 6. Testing

The same `TestClient` with a seeded session (`tests/integration/test_web.py`).
**Tests assert content, not markup** — decision D7 of the catalog design, which
the last branch violated once and paid for in review.

* Each of the six empty states in §4 is tested on its own, building the runs
  and checks that state requires. Six states that differ only in wording is
  precisely where a copy/paste error hides.
* The failed-check aggregation and the duration formatting are unit-tested
  without a database, the way the freshness filter is in
  `tests/unit/test_web_routes.py`.
* A run detail page renders its error block, its `run_metadata` and its checks;
  a successful run renders no error block.
* Both 404 paths — malformed identifier and unknown run — return status 404
  and HTML, not JSON.

The existing guard test that the web views issue no outbound HTTP covers the
new routes with no change.

## 7. Decisions

| | Decision | Rationale |
|---|---|---|
| **D1** | The page is built around run history, not freshness | The catalog already shows freshness per source; repeating it would make two pages tell one story (§1.1) |
| **D2** | Runs join the catalog by string key, never through `source_id` | `pipeline_key` *is* the catalog key, enforced at `base.py:44-46`, written at `runner.py:220`; `source_id` is nullable and would cost a query per row (§1.2) |
| **D3** | Failed checks are grouped in SQL, not in Python over `list_checks` | Python-side aggregation truncates at the query limit and understates a recurring failure (§2.1) |
| **D4** | `_apply` gains `since`, giving both run queries a window | Without a run count over the same window, "nothing failed" and "nothing ran" cannot be told apart (§2.2, §4) |
| **D5** | 100 runs, and the page says so | Four sweeps of 23 pipelines; deeper history stays the paginated API's job (§3.1) |
| **D6** | A 30-day window for trends, not the 7 days `SystemStatus` uses | These series are ingested infrequently; a block that is always empty stops being read (§3.1) |
| **D7** | Six empty states, each with its own sentence | An operator told only "the list is empty" cannot distinguish healthy from stopped (§4) |
| **D8** | The view returns an HTML 404 itself; the shared handlers are untouched | Content negotiation in `errors.py` would make every API error path pay for two view functions (§5) |
| **D9** | Database availability is discovered by querying, not by pre-checking | Inherited from `load_pipeline_summaries`; a pre-check cannot speak for the query that follows it (§4) |

Decisions D3 (views call repositories, not the application's own HTTP API), D4
(Pydantic schemas are the shape handed to templates) and D7 (tests assert
content, not markup) of the catalog-browser design carry over unchanged and are
not restated here.

## 8. Out of scope

* **Charts and sparklines.** The charting decision belongs to the time-series
  dashboard and is still open.
* **Filtering the history by pipeline.** `list_runs` accepts the filter and the
  route could grow it later; it is not in this increment.
* **Pagination on the web surface.** The API paginates; the page shows a
  bounded window and says so.
* **Any run trigger.** Ingestion stays a CLI and scheduler concern —
  decision D13 of the original implementation plan.
* **Authentication.** v0.5.0, with rate limiting.
