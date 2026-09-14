# REIM — Regional Economic Intelligence Monitor

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)

**An open economic data platform for Central America.** REIM collects, normalizes,
stores and publishes economic indicators from official sources, keeping complete
provenance for every figure it holds.

REIM covers **seven countries**: Nicaragua, Guatemala, El Salvador, Honduras,
Costa Rica, Panama and Belize. Depth varies sharply — Nicaragua reads its
national central bank and statistics office directly, Guatemala its central
bank; four more have trade alongside CEPAL's annual GDP. Belize was registered
but inactive until CEPALSTAT gave it its first data of any kind: it reports
nothing to the dataflow the trade series come from, and it has only annual GDP
and CEPAL's monthly monetary aggregates — the latter its longest series of any
kind, 415 months of M1 and of M3 back to 1990-01.

Adding a country is a catalog entry plus a connector module, not a redesign.

---

## The problem

Central American economic data is published, but it is not *usable*. Figures live
in PDFs, HTML tables rendered by JavaScript, spreadsheets whose layout changes
between releases, and SOAP services from another decade. Series get revised
without notice. Comparing two countries means reconciling different units,
periods and vintages by hand, every time.

REIM turns that into a queryable database where every number carries its origin.

## What REIM guarantees

- **Official sources first.** Central banks, statistics offices, ministries,
  regional bodies and multilaterals — never aggregator scrapes.
- **Complete traceability.** Every observation stores its source, the exact URL
  requested, when it was retrieved, when it was published, the connector and
  pipeline versions that produced it, its validation status and a content hash.
- **Nothing invented.** Missing upstream values are skipped, never imputed,
  interpolated or carried forward. A source that cannot be automated reliably
  ships as a *disabled* connector with the blocker documented, not as a guess.
- **Idempotent ingestion.** Running a pipeline twice inserts zero duplicates.
- **Auditable revisions.** When a source republishes a figure, the previous
  values are snapshotted before the update. Nothing is ever silently deleted.
- **Exact arithmetic.** Economic values are `Decimal` end to end and stored in
  unconstrained PostgreSQL `NUMERIC`. No floats, no truncation.

---

## MVP scope

**In:** source catalog, ingestion connectors, normalized observations in
PostgreSQL, idempotent upserts with revision auditing, configurable data-quality
checks, a read-only REST API with filtering/pagination/CSV export, an operations
CLI, Docker Compose, migrations, tests and CI.

**Out (deliberately):** news ingestion, RAG, forecasting, alerting, LLM/MCP
integration, user authentication, web dashboard, distributed infrastructure.
See [ROADMAP.md](./ROADMAP.md).

### Data available

**23 live pipelines feeding 63 indicators**, every one verified against its
source. Nothing here is a scrape of an aggregator.

| Source | Countries | Frequency | Series | Coverage |
|--------|-----------|-----------|--------|----------|
| **BCN** — Banco Central de Nicaragua | Nicaragua | **daily** | official NIO/USD rate | 2012-01 onward |
| **Banguat** — Banco de Guatemala | Guatemala | **daily** | official GTQ/USD rate, buy and sell | 1990-01 onward |
| **INIDE** — national statistics office | Nicaragua | **monthly** | CPI index, month-on-month, year-on-year, each for the country, Managua and the rest of the country | 2007 onward |
| **IMF** — International Merchandise Trade Statistics | all six | **monthly** | exports FOB, imports CIF, trade balance | 1990-01 onward |
| **SIECA** — Secretaría de Integración Económica Centroamericana | six (not Belize) | **quarterly** | services exports, imports, balance | 2009-Q1 onward |
| **CEPAL** — CEPALSTAT | **all seven** | annual | GDP and GDP per inhabitant, each at current and at constant 2018 prices | 1990 onward |
| **CEPAL** — CEPALSTAT | **all seven** | **monthly** | monetary aggregates M1, M2 and M3, end of period, each in local currency | 1990-01 onward |
| **CEPAL** — CEPALSTAT | **all seven** | annual | central government public debt stock, in dollars and as a share of GDP | 1990 onward |
| **CEPAL** — CEPALSTAT | **all seven** | **monthly** | nominal exchange rate, local currency per USD, average of the daily rates within the month | 1990-01 onward |
| **CEPAL** — CEPALSTAT | **all seven** | **monthly** | consumer price index, each country on its own base period | 1980-01 onward |
| **CEPAL** — CEPALSTAT | **all seven**, six for the policy rate | **monthly** | nominal lending rate, nominal deposit rate and monetary policy rate | 1990-01 onward |
| **CEPAL** — CEPALSTAT | **all seven** | **quarterly** | balance of payments: the six headline balances, four sub-balances and fifteen components | 1993-Q1 onward |
| **World Bank** — Indicators API v2 | Nicaragua | annual | exchange rate, inflation, remittances, reserves, exports, imports | 1960 onward |

The BCN, Banguat and INIDE series are **national primary sources** — the
publisher itself, not a multilateral restatement. The World Bank, IMF, SIECA and
CEPAL series compile from national statistics and are one step removed from
them; CEPAL's are its own harmonised estimates and need not match a country's
official national accounts. **Three sources are not openly licensed** — the IMF,
SIECA and CEPAL — and each carries its terms and its attribution requirement;
see the limitations below.

No connector currently ships disabled. When one does, it ships with its blocker
documented rather than papered over — that has happened twice, and both times
the blocker turned out to be worth recording in
[docs/sources.md](./docs/sources.md).

---

## Architecture

A modular monolith. One deployable, clear internal seams.

```text
apps/api/           FastAPI HTTP layer (read-only): routers, deps, error envelope
reim/
  core/             settings, structured logging, typed exceptions, enums
  database/         SQLAlchemy models, session management
  domain/           the parts that would survive a rewrite of everything else
    countries/      country registry
    indicators/     canonical indicator definitions
    observations/   period normalization, content hashing
    sources/        catalog schema + loader, organization registry
    quality/        reusable checks and configurable rules
    pipelines/      dataclasses exchanged between layers, scheduler interface
  ingestion/        BaseConnector, registry, HTTP client, and the shared runner
  repositories/     SQL construction
  services/         seeding, idempotent writer, status, CSV export
  schemas/          Pydantic request/response models
  cli/              Typer commands
sources/            catalog.yml + quality_rules.yml (the declarative surface)
```

**Data flow**

```text
catalog.yml ─► registry ─► connector.extract()   ← official source over HTTP
                              │
                              ▼  RawDataset
                           connector.transform()
                              │
                              ▼  list[NormalizedObservation]
        standard quality battery + connector.validate()
                              │
              critical? ──────┴──► rollback, run marked failed
                              │
                              ▼  idempotent write in one transaction
                    observations + observation_revisions
                              │
                              ▼
                   pipeline_runs + data_quality_checks
```

The runner owns run bookkeeping, transactions, persistence, idempotency, error
handling and logging. A connector only implements `extract` / `transform` /
`validate`, so it cannot get the shared concerns subtly wrong.

### Design decisions worth knowing

| Decision | Why |
|----------|-----|
| Periods are stored as an explicit `[period_start, period_end]` interval plus the source's own label. | An annual figure is never collapsed into a single day. `2024` means `2024-01-01 .. 2024-12-31`. |
| Natural key `(country, indicator, source, period_start, period_end)` with a DB `UNIQUE` constraint. | Idempotency is enforced by PostgreSQL, not by trusting a hash. |
| `content_hash` covers only the *payload* — not `retrieved_at` or version stamps. | Re-running an unchanged pipeline must not look like a revision. |
| Two sources publishing the same concept stay separate series. | Competing vintages remain comparable instead of overwriting each other. |
| Synchronous SQLAlchemy; the API is `def`, not `async def`. | One DB stack. Ingestion never runs inside the request loop. |
| No HTTP endpoint triggers a pipeline. | Ingestion is a CLI/scheduler concern in this MVP. |
| All timestamps are `TIMESTAMPTZ` in UTC. | One unambiguous time base. |

Full rationale: [docs/implementation-plan.md](./docs/implementation-plan.md).

---

## Quick start

### With Docker Compose (recommended)

```bash
git clone https://github.com/RobBravo/reim.git
cd reim
cp .env.example .env

docker compose up --build
```

This starts PostgreSQL 16, applies migrations, seeds reference data and serves
the API on <http://localhost:8000>. Interactive docs: <http://localhost:8000/docs>.

Ingestion is **not** automatic — trigger it explicitly:

```bash
docker compose exec api python -m reim.cli pipeline run-all
```

Then:

```bash
curl -s "http://localhost:8000/api/v1/observations/latest?country=NI" | jq
```

### Local development

Requires Python 3.12+ and a reachable PostgreSQL 16.

```bash
make setup          # virtualenv + dependencies + .env
make db-up          # standalone PostgreSQL 16 on port 55432
export REIM_DATABASE_URL="postgresql+psycopg://reim:reim@localhost:55432/reim"

make migrate        # build the schema
make seed           # countries, organizations, indicators, catalog sources
make run-pipeline PIPELINE=worldbank_ni_cpi_inflation
make run-api        # http://localhost:8000/docs
```

`make help` lists every target.

---

## Configuration

All settings come from environment variables prefixed `REIM_`, with sane
defaults. See [`.env.example`](./.env.example) for the annotated list. **No
secret is ever read from the repository.**

Most commonly changed:

| Variable | Default | Purpose |
|----------|---------|---------|
| `REIM_DATABASE_URL` | `postgresql+psycopg://reim:reim@localhost:5432/reim` | PostgreSQL connection (psycopg 3 driver required) |
| `REIM_ENVIRONMENT` | `local` | `local` / `test` / `ci` / `staging` / `production` |
| `REIM_LOG_LEVEL` | `INFO` | Logging verbosity |
| `REIM_LOG_JSON` | `false` | JSON logs for containers and CI |
| `REIM_HTTP_TIMEOUT_SECONDS` | `30` | Per-request timeout for connectors |
| `REIM_HTTP_MAX_RETRIES` | `3` | Retries on transport errors and 5xx |
| `REIM_HTTP_USER_AGENT` | identifies REIM | Sent to every official source, except where a catalog entry declares its own `user_agent` (only `sieca_services_trade` does; see the limitations) |
| `REIM_CATALOG_PATH` | `sources/catalog.yml` | Source catalog location |
| `REIM_CORS_ALLOW_ORIGINS` | `*` | Narrow before exposing publicly |
| `REIM_MAX_PAGE_SIZE` | `1000` | Hard cap on page size |
| `REIM_MAX_EXPORT_ROWS` | `100000` | Hard cap on CSV export rows |

---

## Running pipelines

```bash
# What is registered, and how often it should run
python -m reim.cli pipeline list

# Validate the catalog, the quality rules and every connector import
python -m reim.cli catalog validate

# One pipeline, or all enabled ones
python -m reim.cli pipeline run worldbank_ni_cpi_inflation
python -m reim.cli pipeline run-all

# Recent executions and quality signal
python -m reim.cli pipeline status
python -m reim.cli quality report
```

Exit codes: `0` success, `1` a pipeline or quality gate failed, `2` invalid
configuration or arguments — so these compose cleanly into cron or CI.

### Rebuilding from an empty database

`pipeline run-all` fetches each source's **routine window**, which is not always
its whole history. Rebuilding from nothing therefore takes two steps, and the
second is easy to forget:

```bash
alembic upgrade head
python -m reim.cli db seed
python -m reim.cli pipeline run-all          # ~56,700 observations
```

That leaves **`bcn_exchange_rate` with about 40 rows**, not the 5,334 it holds
back to 2012-01: its routine window is the current month plus the previous one,
deliberately, so a scheduled run makes two requests instead of 176. To load the
history once, add `start_month: "2012-01"` to that entry's `options` in
`sources/catalog.yml`, run the pipeline, then **remove the line again** so
scheduled runs return to two requests:

```bash
python -m reim.cli pipeline run bcn_exchange_rate   # ~5,300 inserted, ~30 s
```

Everything else — INIDE, Banguat, SIECA, CEPAL and the six IMF trade series —
ships its full history in the routine run, because each of those sources
publishes the complete series on every request. Banguat's 36 years cost one
request of 1.3 MB; SIECA's 69 quarters for six countries cost four requests of
16.7 KB each; CEPAL's 36 years of GDP for seven countries cost four of about
170 KB, its monthly monetary aggregates six requests of 1.4–1.6 MB, its
central government public debt two requests of 617–635 KB, and its monthly
nominal exchange rate one request of 1.19 MB, its consumer price index one
of 2.02 MB, and its three interest rates four requests — three data responses
of 1.38–1.80 MB and one shared dimensions response of 28 KB.

A complete rebuild lands on the order of **61,700 observations**. No exact
figure is given on purpose: the BCN and Banguat each publish a rate every
calendar day, so the total grows daily and any number printed here would be
wrong tomorrow.
To see the real composition:

```bash
python -m reim.cli pipeline status
```

A `run-all` that reports fewer than 16 successes is usually an upstream problem
rather than a REIM fault: connectors retry and then fail loudly instead of
writing partial data. The error message carries the exact URL, so request it
yourself before assuming a bug — outages are often **per series**, not per host.
While this section was being written, five World Bank series returned `502`
while `FP.CPI.TOTL.ZG` on the same host returned `200`.

### Scheduling

REIM has no built-in scheduler by design. `pipeline schedule` reads the
catalog and prints a crontab fragment — one line per cadence the enabled
catalog uses, plus the alert check — to stdout. It writes nothing and installs
nothing; review the output, then pipe it into `crontab -` yourself:

```bash
python -m reim.cli pipeline schedule --working-dir /opt/reim
```

```text
# daily — 2 pipeline(s): banguat_exchange_rate, bcn_exchange_rate
0 13 * * * cd /opt/reim && .venv/bin/python -m reim.cli pipeline run-all --frequency daily

# monthly — 11 pipeline(s): cepalstat_cpi_monthly, cepalstat_exchange_rate_monthly, ... (names truncated)
15 13 5 * * cd /opt/reim && .venv/bin/python -m reim.cli pipeline run-all --frequency monthly

# Alerting — after the ingestion window, since staleness is only meaningful once the day's ingestion has finished.
0 15 * * * cd /opt/reim && .venv/bin/python -m reim.cli alert check
```

Today's catalog uses four cadences — daily, monthly, quarterly and annual —
so the full output has four ingestion blocks before the alert line; a fifth
cadence would add a fifth block automatically, with no template to edit. That
is true of the command's output, not of an installed crontab: the crontab is a
snapshot of the catalog at the moment `pipeline schedule` ran. A `weekly`
source added afterwards matches no line already installed and simply never
runs, so re-run `pipeline schedule` and reinstall whenever a source arrives at
a cadence not already listed, or nothing will schedule it.
Each block runs `pipeline run-all --frequency <cadence>`, which restricts that
sweep to the sources published at that cadence. `--frequency` also works on
its own, without going through `schedule`, when re-running just one cadence
by hand — after a network problem, for instance:
`pipeline run-all --frequency daily`.
`reim.domain.pipelines.scheduling.PipelineScheduler` is the interface a real
scheduler would implement later; it stays an unimplemented seam, since the
operator's cron remains the scheduler.

### Operational alerts

REIM evaluates four conditions — `stale` (data older than its indicators'
configured thresholds), `failed_run` (a pipeline that broke mid-load),
`stuck_run` (a run stuck in `running` state because its process was killed),
and `quality` (checks failed with error or worse severity) — and delivers one
digest per run to a webhook URL. Exit code is `0` if nothing is firing, `1` if
any condition holds whether suppressed or delivered. This allows a cron job
monitoring the exit status to detect a problem even while it is being
temporarily silenced.

```bash
.venv/bin/python -m reim.cli alert check --dry-run
```

The command respects four settings:

- `REIM_ALERT_WEBHOOK_URL` (required to deliver): an HTTPS endpoint to receive
  the digest. If unset, the command still evaluates all conditions, prints any
  firing alerts and resolves, and exits with the appropriate code, but sends
  nothing.
- `REIM_ALERT_SEVERITY_FLOOR=error` (default): one of `info`, `warning`,
  `error`, or `critical`. Only quality conditions with this severity or worse are
  reported.
- `REIM_ALERT_REPEAT_HOURS=24` (default): hours to wait after notifying about a
  condition before notifying again. A problem that stays silent for this interval
  still fires exit code 1, so cron knows to look.
- `REIM_ALERT_STUCK_RUN_HOURS=6` (default): hours a run is allowed to sit in
  `running` state before it is assumed to have been killed and flagged as stuck.
  Ingestion processes can die without cleaning up their row, and without this
  check nothing else would ever see them.

The payload is JSON:

```text
{
  "environment": "production",
  "firing": [
    {
      "condition": "stale",
      "details": {"data_age_days": 9, "freshness_max_age_days": 7},
      "first_notified_at": "2026-09-11T14:00:00+00:00",
      "pipeline_key": "worldbank_ni_cpi_inflation",
      "severity": "warning",
      "summary": "worldbank_ni_cpi_inflation has no data newer than 9 days, past its 7-day threshold."
    }
  ],
  "generated_at": "2026-09-13T10:30:45.123456+00:00",
  "resolved": [
    {
      "condition": "failed_run",
      "details": {"last_run_at": "2026-09-12T10:29:00+00:00"},
      "first_notified_at": "2026-09-12T10:30:00+00:00",
      "pipeline_key": "worldbank_ni_remittances",
      "summary": "worldbank_ni_remittances no longer reports failed_run."
    }
  ],
  "version": 1
}
```

The check must run **after** ingestion completes so staleness is visible.
`pipeline schedule` (see [Scheduling](#scheduling)) already emits the alert
line at the right time alongside the ingestion blocks, so there is one place
that knows the schedule rather than a second cron line to keep in sync by
hand.

---

## Web pages

REIM has three server-rendered web pages, served from the same application as
the API: `make run-api`, then open <http://localhost:8000/>.

The catalog browser at `/` answers what a new reader of the API docs cannot
easily see for themselves — what REIM holds (all 23 sources, their
organization, frequency and indicators), which licences forbid
redistribution, how fresh each source's data is, and what is disabled and
why. No database is required for the catalog itself; freshness renders as
"—" if PostgreSQL is unreachable, distinct from "Never run", which is
reserved for a source that has genuinely never completed a run.

The run history at `/runs` shows the most recent 100 pipeline runs — their
source, status, duration and record counts — plus a 30-day trend of failed
quality checks grouped by check name, so a recurring failure stands out
rather than being buried among one-off ones. Following a run to
`/runs/{run_id}` shows that run in full: every counter, its connector and
pipeline versions, the connector-specific metadata it recorded, and every
quality check it ran, passed or failed. Unlike the catalog, this page has
nothing to fall back to without a database — the history it shows only
exists there — so an unreachable database or an unknown run renders as an
explanatory page rather than the browser's fallback state.

`/series` plots one indicator over time across the countries chosen from an
ordinary `<form method="get">` — a `<select>` of all 63 indicators, a
multi-select of all 7 countries, and optional date bounds. The chart is
server-rendered SVG with no JavaScript at all: the same no-build-step
decision the catalog page made is not reopened for one page. Two countries'
lines share one axis only when the indicator's units and currencies agree
**and** the publisher defines it the same way in every country; otherwise the
page draws small multiples, one independently-scaled panel per country,
rather than implying a comparison the data cannot support. A period the
publisher did not report breaks the line instead of being bridged, and a
value table beside the chart carries every figure the chart draws, plus any
country the chart could not draw at all.

The API is unchanged and still lives at `/api/v1` — the pages are an addition
beside it, not a replacement, calling the same services and repositories the
API routers call rather than the API itself.

---

## Using the API

Base URL `/api/v1`. OpenAPI at `/docs` and `/openapi.json`. Read-only.

### Endpoints

```text
GET /health                              liveness (touches no dependency)
GET /ready                               readiness (checks PostgreSQL)
GET /metrics                             Prometheus text format (process + per-pipeline)
GET /api/v1/status                       platform counters and coverage

GET /api/v1/countries                    ?active_only
GET /api/v1/countries/{iso2}

GET /api/v1/organizations                ?country
GET /api/v1/sources                      ?country &category &frequency &active_only
GET /api/v1/sources/{source_key}

GET /api/v1/indicators                   ?category &frequency &country &source &active_only
GET /api/v1/indicators/{indicator_code}

GET /api/v1/observations                 filters + pagination + sorting
GET /api/v1/observations/latest          newest observation per series
GET /api/v1/observations/export.csv      streamed CSV

GET /api/v1/compare                      one indicator, 2-20 countries, aligned
                                         ?convert_to=USD adds a converted view

GET /api/v1/pipelines                    health, volumes and freshness
GET /api/v1/pipelines/runs               ?pipeline_key &status
GET /api/v1/pipelines/runs/{run_id}      run + its quality checks
```

### Metrics

`/metrics` carries the process-level defaults `prometheus_client` always
exports, plus these, one series per catalog entry:

```text
reim_database_up
reim_pipeline_enabled{pipeline_key}
reim_pipeline_observations{pipeline_key}
reim_pipeline_data_age_days{pipeline_key}
reim_pipeline_freshness_max_age_days{pipeline_key}
reim_pipeline_last_run_timestamp_seconds{pipeline_key}
reim_pipeline_last_success_timestamp_seconds{pipeline_key}
reim_pipeline_last_run_duration_seconds{pipeline_key}
reim_pipeline_last_run_records{pipeline_key,outcome}
reim_pipeline_runs_total{pipeline_key,status}
reim_pipeline_records_total{pipeline_key,outcome}
reim_pipeline_run_duration_seconds_total{pipeline_key}
reim_quality_checks_failed_total{pipeline_key,check_name}
```

They exist for one alert:

```text
reim_pipeline_data_age_days > reim_pipeline_freshness_max_age_days
```

REIM exports no `is_stale`. The threshold lives in `sources/quality_rules.yml`,
where it is tuned per indicator, and the comparison belongs to the alert rule,
not to the exporter — encoding it a second time here would give the two a
chance to disagree. No threshold configured and no data stored both produce an
absent series rather than a zero, so the alert should also require both sides
to exist. `reim_database_up` reports whether the metrics queries reached the
database; an outage still answers `200` with it at `0`, because the scrape
that matters most is the one taken during the outage.

Observation filters: `country` (ISO2 or ISO3), `indicator`, `source`,
`category`, `date_from`, `date_to`, `validation_status`, `status`, plus
`limit`, `offset`, `sort_by`, `order`.

`/compare` takes one `indicator` and a repeated `country`, and returns a
**rectangular** matrix: every row carries an entry for every country asked
for, `null` where that country publishes no figure, so a gap is stated rather
than inferred. It reports whether the series are comparable — the flag turns
on unit and currency — and names what differs. An indicator can also declare
that its publisher **defines it differently in each country**, as CEPAL's three
interest rates do; that adds a note saying levels are not comparable while
movements are, and leaves `comparable` alone, because the flag describes what
the publisher published.

`?convert_to=USD` adds a converted view **beside** the published figures and
never in place of them. Each row gains `values_converted`, `rates` and
`rate_basis`, keyed by country exactly like `values`, so every derived number
can be recomputed by hand from the response alone. Omit the parameter and the
response carries none of those keys at all.

El Salvador is the row that teaches the rule. CEPAL still quotes it at 8.8
colones per dollar, twenty-four years after dollarisation, and REIM stores that
rate — but El Salvador's monetary observations carry `currency_code = USD`, so
they pass through untouched:

```json
"values":           { "NIC": "36800",   "SLV": "9482" },
"values_converted": { "NIC": "1000.00", "SLV": "9482" },
"rates":            { "NIC": "36.8",    "SLV": null   }
```

Conversion keys on **the observation's own currency, never on its country**.
Keyed on the country, that `9482` would have been divided by 8.8.

Three things it will not do. It does not convert an indicator whose values are
rates, indices or ratios — `36.8 NIO per USD` divided by `36.8` is a confident,
meaningless `1.00`, so those are refused with `400`. It does not fall back to a
neighbouring month's rate: no rate for the period means `null`, and the
`conversion` block counts how many. And it does not change `comparable`, which
describes what the publisher published.

The converted figures are **indicative**, and the response says so. The rate is
an average of the daily rates across the month while the monetary series are
end-of-period stocks; CEPAL publishes no end-of-period rate, so the mismatch is
declared rather than hidden.

### Examples

```bash
# Is it up, and what does it hold?
curl -s http://localhost:8000/health
curl -s http://localhost:8000/api/v1/status | jq

# Inflation for Nicaragua, most recent first
curl -s "http://localhost:8000/api/v1/observations\
?country=NI&indicator=ni_cpi_inflation_annual&limit=5" | jq '.data[]
  | {period_label, value_numeric, unit, source_key}'

# The latest figure for every series we track
curl -s "http://localhost:8000/api/v1/observations/latest?country=NI" | jq '.[]
  | {indicator_code, period_label, value_numeric, unit}'

# A date range, oldest first
curl -s "http://localhost:8000/api/v1/observations\
?indicator=ni_remittances_received&date_from=2015-01-01&date_to=2024-12-31\
&sort_by=period_start&order=asc" | jq '.meta'

# Everything in the external-sector category, as CSV
curl -s "http://localhost:8000/api/v1/observations/export.csv?category=external_sector" \
  -o nicaragua_external_sector.csv

# Which sources are registered, and which are disabled and why
curl -s http://localhost:8000/api/v1/sources | jq '.data[]
  | {source_key, is_active, disabled_reason}'

# Pipeline health and data freshness
curl -s http://localhost:8000/api/v1/pipelines | jq '.[]
  | {pipeline_key, last_run_status, observation_count, data_age_days, is_stale}'
```

### Response shapes

Collections are paginated:

```json
{
  "meta": {"total": 26, "limit": 100, "offset": 0, "returned": 26, "has_more": false},
  "data": [ ... ]
}
```

Every error — domain, validation or unexpected — uses one envelope:

```json
{
  "error": {
    "code": "not_found",
    "message": "Indicator 'ni_gdp' is not registered",
    "details": {"indicator_code": "ni_gdp"}
  }
}
```

### CSV export columns

`country_iso3`, `country_name`, `indicator_code`, `indicator_name`,
`period_label`, `period_start`, `period_end`, `value_numeric`, `unit`,
`currency_code`, `source_key`, `source_url`, `published_at`, `retrieved_at`,
`validation_status`, `revision_count`, `connector_version`, `pipeline_version`,
`content_hash`.

Values are written at full stored precision — the export round-trips through
`Decimal` without loss.

---

## Data quality

Every run evaluates a standard battery plus connector-specific checks:
completeness, non-numeric values, duplicates, invalid periods, unjustified
future periods, configurable value ranges, anomalous period-over-period changes,
expected frequency, freshness, temporal monotonicity, and referential integrity
between indicator, source and country.

**Every check that walks a series walks one country at a time.** A regional
batch holds seven series, not one long one, so period-over-period change,
monotonicity and freshness are each measured per country: a jump is never
measured between two countries, and a country that stops publishing is reported
even while the other six stay current.

Severity determines what happens:

| Severity | Effect |
|----------|--------|
| `critical` | Transaction rolled back; run marked failed; **no data committed** |
| `error` | The offending observation is rejected; the rest of the batch is written |
| `warning` | Stored and marked `passed_with_warnings` |
| `info` | Recorded only |

Thresholds are per indicator in [`sources/quality_rules.yml`](./sources/quality_rules.yml)
so tuning them is a reviewable data change, not a code change. They are
deliberately wide: they are tripwires for a broken feed, not economic forecasts.
A legitimate value must never be rejected because a threshold was set too tightly.

## Testing

```bash
make test-unit      # no database, no network
make db-up          # PostgreSQL 16 for integration tests
make test           # everything
make test-cov       # with coverage
make check          # lint + typecheck + catalog + tests (what CI runs)
```

725 tests — 596 offline, 122 integration and 7 opt-in live. Integration tests
skip cleanly when `REIM_TEST_DATABASE_URL` is unset, so `pytest` works on a bare
checkout.

**No test calls a live official source.** Connector tests replay recorded
fixtures through `respx`. To check the real services on purpose:

```bash
make smoke          # opt-in; makes real network calls
python scripts/smoke_test_sources.py --source worldbank_ni_cpi_inflation
```

---

## Limitations

Stated plainly, because a data platform that hides its gaps is worse than none:

- **Three national primary sources, the rest multilateral.** INIDE's monthly
  CPI — national, Managua and rest-of-country — the BCN's daily exchange rate
  and Banguat's daily rate pair come straight from the publisher; the remaining
  connectors read the World Bank, the IMF, SIECA and CEPAL, which compile from
  national statistics and are one step removed from it. CEPAL's GDP figures are
  a further step: they are its **own harmonised estimates**, built so countries
  can be compared with each other, and need not match the national accounts each
  statistics office publishes.
- **Subnational coverage is two regions, not a geography model.** INIDE's
  Managua and rest-of-country breakdowns are separate indicator codes.
  `observations` has no region dimension, so this does not generalise to
  finer geography without a schema change.
- **Three sources are not openly licensed, and they are not alike.** The IMF
  merchandise-trade series carries "© International Monetary Fund. All Rights
  Reserved", but its terms **do permit redistribution with attribution**: cite
  the IMF — every observation carries the Fund's suggested citation in
  `raw_metadata.imf_citation` — keep the figures exact, and declare any
  transformation. **Commercial reuse requires permission from
  `copyright@imf.org`**, which this project has not sought. SIECA publishes **no
  licence grant at all**: both its hosts read "all rights reserved" and no
  terms-of-use page could be found to read. **CEPAL goes further and expressly
  forbids what REIM does**: its usage agreement grants download and copying "for
  Users' personal, non-commercial use without any right to resell, redistribute
  or create derivative works therefrom", and REIM redistributes those figures
  through its own API. That conflict is stated rather than hidden — REIM is a
  non-commercial research project and ships CEPAL's required citation with every
  observation — but a reader who needs certainty about reuse rights should ask
  CEPAL directly. All three are quoted in full in
  [`docs/sources.md`](./docs/sources.md).
- **Publishers' edge rules, stated in two parts rather than as one absolute.**

  **REIM does not defeat an active access control.** `www.bcn.gob.ni` sits
  behind a Radware bot manager that answers every automated request with a
  JavaScript challenge; REIM does not execute it, and that has not changed. The
  consequence is real: the BCN's monthly bulletins stay out of reach, so
  monetary aggregates and remittances are absent — Nicaragua reports neither to
  the IMF. For the aggregates there is now a route that needs no account:
  CEPALSTAT publishes M1, M2 and M3 for Nicaragua from 2001, not yet ingested
  and recorded in [`docs/sources.md`](./docs/sources.md).

  **REIM does satisfy a static header check.** SIECA's edge allows or denies on
  the `User-Agent` string alone: REIM's own identifier receives `202` with an
  empty body, `curl` receives `403`, a browser string receives the data. REIM
  sends a string the host accepts, changes nothing else, keeps the same timeout
  and retry policy as every other source, and declares it in the catalog entry.

  These are different things, and the project's rule is stated in both parts
  rather than as one absolute that its own catalog would contradict. See
  [`docs/sources.md`](./docs/sources.md).
- **Five families are rescaled, and all five say so.** SIECA publishes
  services trade in **millions of USD** and CEPAL publishes its GDP totals the
  same way; REIM stores whole USD, multiplying by 10⁶ in `Decimal`. CEPAL's
  monetary aggregates are published in **millions of each country's own
  currency** and are rescaled the same way, to whole units of that currency —
  not to dollars. CEPAL's central government debt stock is published in
  **millions of USD** and is rescaled to whole USD the same way, while its
  companion percent-of-GDP ratio is stored **untouched**, exactly as published.
  All twenty-five balance-of-payments series are published in **millions of
  USD** and rescaled to whole USD identically — CEPAL declares zero decimals
  there and publishes up to **twenty-two**, and not one of those digits is
  rounded away, including the `8.881784e-16` that is a float64 residue rather
  than a figure. CEPAL's two per-inhabitant GDP series are also stored exactly as
  published. Every rescaled observation keeps the published value, the published
  unit and the scale applied in `raw_metadata`, so the original figure is
  recoverable exactly. These five rescalings are the whole of it: nothing in REIM restates
  a unit, and no stored figure is ever a converted one. `/compare?convert_to=`
  derives dollars at request time, beside the published figure and never in
  place of it; nothing derived is written to the database.
- **The consumer price indices are not comparable across countries either, and
  for a different reason.** Each country is on its own base period, so a
  Guatemalan 104 and a Honduran 104 do not mean the same thing. CEPAL declares
  a base year per country and **three of the five it declares do not hold**, so
  REIM states none: the unit is `index`, and `docs/sources.md` records the
  month each series measurably passes 100. Movements are comparable; levels are
  not. Guatemala's series also carries an unnormalised splice at 2010-01 — a
  42.6% fall that is a change of base — so inflation computed across that month
  is meaningless. Nicaragua has two of these indices, REIM's from INIDE and
  CEPAL's from the central bank, which differ by about 4% in level.
- **The interest rates are not comparable across countries either, and CEPAL
  says so itself.** `calculation_methodology` on all three series reads
  "According to the definition from each country", and the definitions differ
  in substance: Belize's "monetary policy rate" is its central bank's own
  lending rate, El Salvador's is a stock-exchange repo yield over 1–7 days, and
  Nicaragua's is the yield on 180-day central bank bonds. The three indicators
  declare `methodology_varies_by_country`, so `/compare` returns a note saying
  levels are not comparable while movements are — and leaves `comparable`
  alone, because that flag describes unit and currency agreement. **Panama has
  no policy rate here by decision**: it is dollarised and has no central bank,
  and CEPAL's sixteen zero-valued, unattributed 2022 cells for it are an
  artifact REIM does not store. Nicaragua's two genuine 2010 zeros, inside a
  real attributed series, are stored. See
  [`docs/sources.md`](./docs/sources.md).
- **The balance of payments carries a contradiction in its own metadata, and
  two items that are not what they look like.** CEPAL declares the IMF's
  **fifth** Balance of Payments Manual while footnote 10138 cites the **sixth**
  on every row of six of the seven countries — all but Guatemala. The split is
  by country, not by year. REIM records it and does **not** declare
  `methodology_varies_by_country`, because the break that would matter is
  measurably absent: BPM6 reverses BPM5's financial-account sign convention, and
  averaging the financial account across every current-account deficit quarter
  puts Guatemala at **+345.0** inside a range of +34.3 to +677.0 for the other
  six. The labels disagree; the figures do not. Separately,
  `bop_reserve_assets_quarterly` is the quarterly **flow** in reserve assets and
  **not the reserves stock**, and `bop_current_transfers_credit_quarterly` is
  the whole current-transfers account and **not remittances** — both are
  documented traps for gaps `ROADMAP.md` still lists as open, and both warnings
  are in the indicators' own descriptions. Honduras also stops publishing
  current transfers (debit) at **2023-Q4** while publishing its other
  twenty-four series through 2026-Q1, so that one series warns on freshness on
  every run rather than having its threshold widened to hide it. See
  [`docs/sources.md`](./docs/sources.md).
- **The monetary aggregates are not comparable across countries.** M1, M2 and
  M3 are each in the publishing country's own currency — córdobas, quetzales,
  lempiras, colones, balboas, Belize dollars — and **as stored they cannot be
  summed, ranked or charted on a shared axis**. El Salvador and Panama are
  dollarised, so those two alone line up with each other. Every observation
  carries its `currency_code`, so the mismatch is visible rather than implicit.
  `/compare?convert_to=USD` will derive a comparable view at request time from
  CEPAL's published monthly rate, labelled indicative and never written to the
  database; the published figures stay exactly as they are.
- **The public debt ratio's GDP is not REIM's GDP.** CEPAL's
  `public_debt_pct_gdp_annual` divides by each country's GDP in local currency
  converted at the IMF's 31 December rate — **not** REIM's own
  `gdp_current_usd_annual`, which is CEPAL's harmonised-USD series on its own
  conversion. Dividing `public_debt_usd_annual` by `gdp_current_usd_annual`
  does not reconcile with the published ratio: across the 225 country-years
  both cover, 52 disagree by 5% or more, worst Honduras 1990 at 23.7%. REIM
  stores both series exactly as CEPAL published them rather than choosing
  between them or reconciling one against the other.
- **The BCN endpoint requires a TLS 1.0 handshake.** REIM relaxes the protocol
  version and cipher security level for that one host, declared and justified in
  `sources/catalog.yml`. Certificate and hostname verification stay enforced.
- **INIDE publishes no monthly CPI for 2008-2010.** That gap is in the source
  itself; REIM reports it rather than filling it.
- **World Bank data lags.** Annual figures for year *Y* land during *Y+1*, so
  freshness thresholds are measured in hundreds of days, not days.
- **Coverage is uneven, and only two countries have a national primary
  source.** Nicaragua has the BCN's daily exchange rate and INIDE's monthly
  CPI; Guatemala has Banguat's daily rate pair. Every other country is read
  through multilaterals alone — the IMF's monthly merchandise trade, SIECA's
  quarterly services, and CEPAL's annual GDP and public debt plus its four
  monthly families: monetary aggregates, exchange rate, consumer prices and
  interest rates. **Belize is CEPAL-only**: it reports nothing to the IMF
  dataflow at any frequency and is not one of SIECA's six, so every figure REIM
  holds for it comes from CEPALSTAT.
- **No authentication or rate limiting.** Do not expose this publicly without
  putting a gateway in front and narrowing `REIM_CORS_ALLOW_ORIGINS`.
- **Revisions are recorded, not reconciled.** REIM keeps the history but does
  not attempt to explain *why* a source revised a figure.
- **Not investment advice.** REIM redistributes official figures with their
  provenance; consult the original publication before relying on any number.

## Roadmap

More Central American countries, national primary sources, a web dashboard,
economic news and event correlation, alerting, RAG and AI summaries, API keys, a
Python SDK, a distributable CLI and an MCP server. See [ROADMAP.md](./ROADMAP.md).

## Contributing

Contributions are welcome — especially connectors for official sources REIM
cannot yet reach. [CONTRIBUTING.md](./CONTRIBUTING.md) walks through adding a
source, an indicator and a connector, and the standards each must meet.

Security issues: see [SECURITY.md](./SECURITY.md).

## Data licensing

REIM's **code** is Apache 2.0. The **data** it ingests remains subject to each
publisher's terms — the World Bank Indicators API is CC-BY-4.0; BCN and INIDE
material is public official data. Three sources are **not** openly licensed and
carry attribution requirements you inherit if you redistribute:

| Source | Terms | Attribution REIM ships |
|---|---|---|
| **IMF** | © IMF, all rights reserved; redistribution permitted with attribution, commercial reuse needs `copyright@imf.org` | the Fund's suggested citation, in `raw_metadata.imf_citation` |
| **SIECA** | All rights reserved; no licence grant and no terms page found | SIECA publishes no citation string; the catalog entry and `/api/v1/sources` name it as publisher |
| **CEPAL** | Personal, non-commercial use only, expressly **without** the right to resell, redistribute or create derivative works | CEPALSTAT's own `credits` block, in `raw_metadata.cepalstat_credits` |

Each source's licence is recorded in `sources/catalog.yml` and exposed through
`/api/v1/sources`; [`docs/sources.md`](./docs/sources.md) quotes the terms
verbatim and states plainly where REIM's use conflicts with them. Check them
before redistributing.

## License

[Apache License 2.0](./LICENSE).
