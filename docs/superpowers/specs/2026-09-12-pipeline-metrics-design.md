# Per-pipeline Prometheus metrics — design

REIM already exposes `/metrics`, but only the process-level defaults
`prometheus_client` registers for free: heap, file descriptors, GC counts. None
of it says whether the data is arriving. This increment adds the per-pipeline
volumes, durations and freshness gauges that make the endpoint worth scraping,
derived entirely from the `pipeline_runs` table.

This is v0.5.0's first increment. Everything measured below was checked against
the repository on 2026-09-12.

## 1. What exists, and what this adds

Measured, not assumed:

| Piece | State |
|---|---|
| `/metrics` (`apps/api/routers/system.py:56`) | Returns `generate_latest()` over the default registry. No session, no database access. 404 when `REIM_METRICS_ENABLED=false` (`reim/core/config.py:71`) |
| `PipelineRun` (`reim/database/models/pipeline.py:21`) | `started_at`, `duration_ms`, **five** record counters (`records_extracted`, `_inserted`, `_updated`, `_unchanged`, `_rejected`), `status`, indexed on `(pipeline_key, started_at)` and on `status` |
| `PipelineStatus` (`reim/core/constants.py:133`) | `running`, `success`, `partial`, `failed`, `skipped` |
| `DataQualityCheck` (`…/pipeline.py:71`) | `check_name` and a `CheckStatus` (`constants.py:155`: `passed`/`failed`/`skipped`). **No `pipeline_key` column** — see §3.2 |
| `build_pipeline_summaries` (`reim/services/status.py:22`) | Already computes every figure this increment needs, at a cost this increment cannot pay — see §1.2 |
| `prometheus-client` | 0.26.0 installed, `>=0.21` pinned in `pyproject.toml:36`. No new dependency |

The addition is **six repository functions, one service module and one changed
endpoint**. No model, no migration, no dependency.

### 1.1 The constraint that shapes everything: ingestion runs in another process

`PipelineRunner` is constructed only in `reim/cli/main.py:216` and `:234`.
Nothing under `apps/` runs a pipeline — the API process never executes an
ingestion.

So the usual instrumentation is unavailable. A `Histogram` observed inside the
runner, or a `Counter` incremented as records land, lives in a short-lived CLI
process that exits; the process answering the scrape never saw it. The bridge
for that shape is a Pushgateway, which is new infrastructure — the thing
v0.5.0 explicitly rules out.

**Every metric is therefore derived from `pipeline_runs` at scrape time.** That
is not a compromise: the database is the durable record, so the figures survive
restarts and redeployments, which in-process counters would not. It does mean
no histogram or quantile is possible, which §2.2 works around.

### 1.2 The data already exists, at the wrong cost

`build_pipeline_summaries` returns `last_run_duration_ms`, the record counters,
`observation_count`, `latest_period_end`, `data_age_days` and `is_stale` per
pipeline — the whole shopping list. It is the right function for
`/api/v1/pipelines`, a request a human makes occasionally, and the wrong one
for a surface Prometheus scrapes every 15 seconds, because it loops over the
catalog issuing **five queries per source**:

```text
latest_run              reim/repositories/pipeline_runs.py:77
latest_successful_run   …:87
get_source_by_key       reim/repositories/reference.py:45
count(Observation)      inline in status.py
latest_period_end       reim/repositories/observations.py:196
```

At 23 catalog sources that is **115 round trips per call**, two of them
aggregates over `observations`, the largest table. A 15-second scrape interval
would make it roughly 8 queries a second, forever, to re-derive numbers that
change when a pipeline runs — monthly or quarterly for most of these sources.

This increment does not reuse that function and does not add a cache. It pushes
the aggregation into SQL, exactly as the observability page did when it added
`summarize_failed_checks_by_name` (`pipeline_runs.py:134`) rather than counting
in Python over `list_checks`. Six queries, flat in the number of sources
(§3.1).

## 2. The metric surface

These names are an interface: alert rules and dashboards bind to them, and
renaming one later silently breaks somebody's pager. They follow Prometheus
convention — base units (seconds, never milliseconds), `_total` on counters
only, no unit suffix on a dimensionless count.

### 2.1 Gauges — what is true now

All labelled `{pipeline_key}`.

| Metric | Meaning |
|---|---|
| `reim_pipeline_enabled` | 1 or 0, from the catalog. Lets a rule exclude a deliberately disabled pipeline instead of paging about it |
| `reim_pipeline_observations` | Rows currently stored for that source |
| `reim_pipeline_data_age_days` | `today − latest_period_end`. **Absent** when the source holds no data |
| `reim_pipeline_freshness_max_age_days` | The configured threshold. **Absent** when none is configured |
| `reim_pipeline_last_run_timestamp_seconds` | `started_at` of the most recent run, Unix seconds |
| `reim_pipeline_last_success_timestamp_seconds` | `started_at` of the most recent `success` or `partial` run |
| `reim_pipeline_last_run_duration_seconds` | `duration_ms / 1000` |
| `reim_pipeline_last_run_records{outcome}` | The last run's counters. `outcome` ∈ `extracted`, `inserted`, `updated`, `unchanged`, `rejected` |

One metric with an `outcome` label, rather than five metric names, because the
five are the same measurement partitioned — and because `sum by (outcome)` over
all pipelines is then a query rather than an addition.

The staleness rule is the operator's to write:

```text
reim_pipeline_data_age_days > reim_pipeline_freshness_max_age_days
```

Both are in days, so the rule needs no unit conversion, and the threshold stays
visible to whoever tunes it.

### 2.2 Counters — what has happened

`pipeline_runs` is append-only: the runner inserts a row before extraction
starts and finalises it in a `finally` block, and nothing deletes runs. Sums
over that table are therefore genuinely monotonic, which makes them legitimate
counters rather than gauges wearing a `_total` suffix.

| Metric | Built from |
|---|---|
| `reim_pipeline_runs_total{pipeline_key, status}` | `count(*) group by pipeline_key, status` |
| `reim_pipeline_records_total{pipeline_key, outcome}` | `sum(records_*) group by pipeline_key` |
| `reim_pipeline_run_duration_seconds_total{pipeline_key}` | `sum(duration_ms) / 1000 group by pipeline_key` |
| `reim_quality_checks_failed_total{pipeline_key, check_name}` | §3.2 |

`rate()` and `increase()` work on all four, which is what makes a failing
pipeline distinguishable from a pipeline that failed once in March.

One series carries no `pipeline_key` at all: **`reim_database_up`**, 1 or 0,
set from whether the queries above actually succeeded (§5).

The duration counter is the histogram substitute forced by §1.1. It is the
standard `_sum`/`_count` pair in disguise: average run duration over any window
is

```text
rate(reim_pipeline_run_duration_seconds_total[1d])
  / rate(reim_pipeline_runs_total[1d])
```

That yields a mean, not a p99. A quantile would require per-run observations in
the scraping process, which §1.1 rules out; the honest options were a mean or
nothing.

Cardinality at 23 sources: **276 gauge series** (seven single-series gauges at
23 each, plus `last_run_records` at 23 × 5 outcomes), and at most **253 counter
series** (`runs_total` at 23 × 5 statuses, though only statuses that actually
occurred are emitted; `records_total` at 23 × 5; the duration counter at 23),
plus one series per (pipeline, failing check name) pair. Order 600 in total —
small enough that no label needs dropping, and both `pipeline_key` and
`check_name` come from configuration rather than from user input, so the series
count cannot be driven up by traffic.

### 2.3 What is deliberately not exported

**`is_stale`.** `PipelineSummary` carries it and this endpoint does not. A
boolean verdict on the metrics surface would re-encode a policy that
`sources/quality_rules.yml` already owns, in a second place, where an operator
tuning the threshold would not think to look. Exporting the age and the
threshold as separate gauges gives strictly more information — the alert rule
in §2.1 reconstructs the verdict, and a dashboard can show how close to the
line a pipeline is sitting, which a boolean cannot.

**Anything about HTTP requests.** Request rates and latencies are the business
of an ASGI middleware, and they arrive with the API-keys increment or not at
all. This increment is about the data, not the traffic.

### 2.4 Two rules about absent series

An absent series and a zero say different things, and conflating them is how a
freshness dashboard comes to report that everything is fine.

1. **No threshold configured → no `reim_pipeline_freshness_max_age_days`
   series.** `defaults:` in `sources/quality_rules.yml` sets no
   `freshness_max_age_days`, so `IndicatorRule.freshness_max_age_days` falls
   back to `None` for any indicator the file does not list. Exporting `0` would
   make every such pipeline permanently overdue; exporting `+Inf` would make it
   permanently fine. Omitting the series makes the alert rule in §2.1 not fire
   at all, which is the truthful reading of "no policy exists".
2. **No data stored → no `reim_pipeline_data_age_days` series.** A source that
   has never ingested has no `latest_period_end`. Age `0` would read as
   perfectly fresh.

Neither case occurs in the catalog as it stands: all 23 sources resolve a
threshold today. Both are still correctness rules, because the fallback in
`rules.py:85` is reachable by adding one indicator to the registry without
adding a rule for it — so their tests must construct the case rather than hunt
for a real catalog entry that exhibits it.

### 2.5 The threshold for a pipeline with several indicators

Freshness is per source — `latest_period_end` is keyed on `source_id` — but the
threshold is per indicator, and **14 of the 23 sources declare more than one
indicator**. `build_pipeline_summaries` resolves this by using
`entry.indicators[0]` and ignoring the rest (`reim/services/status.py:53`).

Measured: **no source currently has indicators whose thresholds differ**, so
`indicators[0]` and `min(...)` are the same number for all 23 today. This
increment takes the **minimum across the pipeline's indicators**, because when
they do diverge, the strictest threshold is the one that makes the gauge fire
early rather than never — a freshness alert that under-reports is worse than
one that nags. It is called out here rather than buried because it is a
deliberate, currently-invisible divergence from `/api/v1/pipelines`.

## 3. The queries

### 3.1 Six queries, flat in the number of sources

Added to the existing repositories, where the rest of this aggregation already
lives. Six functions, six queries, regardless of how many sources the catalog
grows to:

| Function | File | Query |
|---|---|---|
| `latest_runs_by_pipeline(session)` | `pipeline_runs.py` | One `DISTINCT ON (pipeline_key) … ORDER BY pipeline_key, started_at DESC`, replacing 23 `latest_run` calls |
| `latest_successful_runs_by_pipeline(session)` | `pipeline_runs.py` | The same, filtered to `success`/`partial` |
| `aggregate_runs_by_pipeline(session)` | `pipeline_runs.py` | One `GROUP BY pipeline_key, status` returning run counts, record sums and the duration sum |
| `summarize_failed_checks_by_pipeline(session)` | `pipeline_runs.py` | §3.2 — one join, `GROUP BY pipeline_key, check_name` |
| `summarize_sources(session)` | `observations.py` | One `GROUP BY source_id` returning `count(*)` and `max(period_end)`, replacing 23 count + 23 `max` queries |
| `source_ids_by_key(session)` | `reference.py` | One `select(DataSource.id, DataSource.source_key)`, replacing 23 `get_source_by_key` calls |

`summarize_sources` returns a mapping keyed by `source_id`, while the catalog
speaks in keys — hence `source_ids_by_key`, which is new: `reference.py` has
`list_countries` and `list_organizations` but no list-all-sources function.

`DISTINCT ON` is PostgreSQL-specific. That is already the only supported
database — `postgresql+psycopg` throughout, JSONB columns in the models, and no
SQLite anywhere in the test suite — so this introduces no new portability
constraint.

### 3.2 The quality-check counter needs a join

`DataQualityCheck` has no `pipeline_key`; it reaches its pipeline only through
`pipeline_run_id`. The existing `summarize_failed_checks_by_name`
(`pipeline_runs.py:134`) groups by `check_name` alone, which is what the
observability page displays and is not enough here — a check failing on one
pipeline must not be indistinguishable from the same check failing on another.

So one more query: `GROUP BY pipeline_runs.pipeline_key,
data_quality_checks.check_name WHERE status = 'failed'`, joining on
`pipeline_run_id`, which is indexed
(`ix_data_quality_checks_pipeline_run_id`). This is a new function rather than a
parameter on the existing one; `summarize_failed_checks_by_name` has a caller
whose grouping must not change.

This is the one metric beyond the ROADMAP's literal "volumes, durations,
freshness gauges". It is here because v0.5.0's alerting item names quality
regressions specifically, and under the decision that Prometheus does the
judging (§2.3), the counter has to exist before a rule can read it.

## 4. Rendering

A new `reim/services/metrics.py`, in two halves so the half worth testing
exhaustively needs no database:

```text
build_metrics_snapshot(session, catalog=None, rules=None) -> MetricsSnapshot
render_snapshot(snapshot) -> bytes
```

`MetricsSnapshot` is frozen dataclasses — a `database_up` flag, a
`PipelineMetrics` per catalog entry, and the failed-check counts.
`render_snapshot` is **pure**: snapshot in, exposition text out, no session, no
clock, no settings.

It builds `GaugeMetricFamily` and `CounterMetricFamily` from
`prometheus_client.core` into a fresh `CollectorRegistry` per scrape. Verified
empirically against 0.26.0, because three details bite here:

* A `Counter` constructed with the name `reim_pipeline_runs_total` renders as
  `reim_pipeline_runs_total_total` — the client appends the suffix. Metric
  families are built with the **base** name; §2.2's table shows the rendered
  name.
* `Counter` also emits a `_created` gauge holding the process start time, which
  is meaningless for a counter rebuilt from the database on every scrape and
  would report "created just now" each time. `CounterMetricFamily` emits no
  `_created` series at all, which is why the family API is used rather than the
  metric classes plus `PROMETHEUS_DISABLE_CREATED_SERIES`
  (`prometheus_client/metrics.py:45`) — the behaviour belongs in our code, not
  in the deployment's environment.
* A fresh registry per scrape, rather than module-level metric objects, means a
  label set that stops existing — a source removed from the catalog — stops
  being exported, instead of lingering at its last value forever.

The endpoint returns the default registry's process metrics concatenated with
the snapshot's. The text exposition format is a concatenation of metric
families, so this is valid as long as no name appears in both payloads; the
default registry exports only `process_*`, `python_*` and `gc_*`, and ours only
`reim_*`.

## 5. Degradation

`/metrics` gains `SessionDep`. That is safe: `get_db`
(`apps/api/dependencies.py:15`) constructs the session without connecting —
SQLAlchemy connects lazily on first use — so an unreachable database surfaces
as a catchable `SQLAlchemyError` inside the endpoint rather than a
dependency-time 500, and the `finally: session.rollback()` is a no-op on a
session that never opened a connection.

`build_metrics_snapshot` wraps its queries in `except SQLAlchemyError` and
returns a snapshot with `database_up=False` and no pipeline series.
`/metrics` then answers **200** with the process metrics and
`reim_database_up 0`. A scrape target that starts failing during a database
outage is exactly the target you needed during the outage; a gauge that says
`0` is a signal, and a 500 is a gap in the graph.

Availability is discovered by running the queries and catching the failure,
never by calling `check_database_connection()` (`reim/database/session.py:61`)
first — the same rule `load_pipeline_summaries` follows
(`apps/web/routes.py:135`, `:155`), for the same reason: a pre-check cannot
speak for the query that follows it.

`REIM_METRICS_ENABLED=false` keeps returning 404, unchanged.

## 6. Testing

* **`tests/unit/test_metrics_render.py`** — `render_snapshot` is pure, so all of
  it runs without a database: the rendered names and `TYPE` lines, `duration_ms`
  → seconds, the two absent-series rules of §2.4 (constructed, per §2.4), the
  `outcome` and `status` label sets, no `_created` series, and
  `reim_database_up 0` with no pipeline series on a down snapshot.
* **`tests/integration/test_metrics.py`** — against seeded runs: a pipeline's
  gauges and counters carry the values those runs imply; a second run moves the
  last-run gauges and adds to the counters; the quality counter separates the
  same `check_name` across two pipelines (§3.2 exists for that case, so a test
  must pin it).
* **The outage path** follows the established pattern —
  `monkeypatch.setattr` on the repository function to raise `SQLAlchemyError`,
  as `tests/integration/test_web_runs.py:74` does — asserting 200,
  `reim_database_up 0`, and that process metrics still appear.
* **A query-count assertion** pinning the scrape to a constant number of
  queries, using an event listener on the engine. Without it, a later change
  that reintroduces a per-source loop makes the endpoint slow rather than
  broken, and nothing fails.
* **Metrics disabled** still returns 404, and
  `test_the_api_is_unchanged_by_the_web_surface`
  (`tests/integration/test_web.py:75`) keeps asserting `/metrics` → 200
  unchanged.

Assertions parse the exposition text for the series they name; none assert the
whole payload, which would break every time `prometheus_client` adds a default
collector.

## 7. Decisions

| | Decision | Rationale |
|---|---|---|
| **D1** | Every metric is derived from `pipeline_runs` at scrape time | Ingestion runs in a CLI process that exits (`cli/main.py:216`); in-process counters would never reach the scraped process, and a Pushgateway is new infrastructure (§1.1) |
| **D2** | New grouped-aggregate queries, not `build_pipeline_summaries` | That function costs 115 round trips per call — right for an occasional JSON request, wrong at a 15-second scrape interval (§1.2) |
| **D3** | No cache, no TTL | The queries are cheap once aggregated in SQL, and a cached gauge makes "why does this number disagree with the database" a question the operator has to ask (§1.2) |
| **D4** | Raw facts exported; Prometheus judges staleness | A boolean verdict would re-encode `quality_rules.yml`'s policy where nobody tuning it would look, and carries less information than the age and threshold do (§2.3) |
| **D5** | Gauges for current state, counters for append-only history | `pipeline_runs` is never deleted from, so sums over it are genuinely monotonic; `rate()` then distinguishes a pipeline failing nightly from one that failed once (§2.2) |
| **D6** | Mean run duration via a `_seconds_total` counter, no quantiles | A histogram needs per-run observations in the scraped process, which D1 forbids; the choice was a mean or nothing (§2.2) |
| **D7** | An absent series, never a zero, when there is no threshold or no data | `0` reads as "permanently overdue" or "perfectly fresh"; both are assertions the data does not support (§2.4) |
| **D8** | The strictest threshold across a pipeline's indicators | 14 sources declare several; none diverge today, so nothing changes now, and when they do diverge an early alert beats a silent one (§2.5) |
| **D9** | `CounterMetricFamily` over `Counter`, and a fresh registry per scrape | The family API emits no meaningless `_created` series without depending on a deployment environment variable, and a fresh registry drops label sets that stopped existing (§4) |
| **D10** | A database outage renders `reim_database_up 0` at status 200 | The scrape you most need is the one during the outage; a 500 is a hole in the graph (§5) |
| **D11** | Availability is discovered by querying and catching, never pre-checked | Inherited from `load_pipeline_summaries`; a pre-check cannot speak for the query after it (§5) |
| **D12** | `reim_quality_checks_failed_total` ships here, ahead of its consumer | v0.5.0's alerting item names quality regressions, and under D4 the counter must exist before a rule can read it (§3.2) |

## 8. Out of scope

* **Alerting rules themselves.** This increment makes them writable; shipping
  them is v0.5.0's alerting item, along with whatever delivers the notification.
* **HTTP request metrics.** Middleware territory, and it belongs with the
  API-keys increment that adds middleware anyway (§2.3).
* **Authentication on `/metrics`.** Today the endpoint is open, as `/health`
  and `/ready` are. Whether it moves behind a key is the API-keys increment's
  decision, not this one's — and network-level restriction is the usual answer
  for a scrape endpoint.
* **A Grafana dashboard.** The deployment guide's job, once the names below are
  stable.
* **Per-indicator freshness series.** `latest_period_end` is per source, so an
  indicator-labelled age would need a different query and a different index;
  D8 records how the ambiguity is resolved instead.
* **Backfilling `duration_ms` on historical rows.** Runs recorded before this
  column was populated contribute nothing to the duration counter, and nothing
  in this increment rewrites them.
