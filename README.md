# REIM — Regional Economic Intelligence Monitor

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)

**An open economic data platform for Central America.** REIM collects, normalizes,
stores and publishes economic indicators from official sources, keeping complete
provenance for every figure it holds.

REIM covers **six countries**: Nicaragua, Guatemala, El Salvador, Honduras,
Costa Rica and Panama. Depth varies sharply — Nicaragua reads its national
central bank and statistics office directly, Guatemala its central bank; the
other four currently have merchandise trade only. Belize is registered but
inactive: it reports nothing to the dataflow the others come from.

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

**16 live pipelines feeding 24 indicators**, every one verified against its
source. Nothing here is a scrape of an aggregator.

| Source | Countries | Frequency | Series | Coverage |
|--------|-----------|-----------|--------|----------|
| **BCN** — Banco Central de Nicaragua | Nicaragua | **daily** | official NIO/USD rate | 2012-01 onward |
| **Banguat** — Banco de Guatemala | Guatemala | **daily** | official GTQ/USD rate, buy and sell | 1990-01 onward |
| **INIDE** — national statistics office | Nicaragua | **monthly** | CPI index, month-on-month, year-on-year, each for the country, Managua and the rest of the country | 2007 onward |
| **IMF** — International Merchandise Trade Statistics | all six | **monthly** | exports FOB, imports CIF, trade balance | 1990-01 onward |
| **SIECA** — Secretaría de Integración Económica Centroamericana | all six | **quarterly** | services exports, imports, balance | 2009-Q1 onward |
| **World Bank** — Indicators API v2 | Nicaragua | annual | exchange rate, inflation, remittances, reserves, exports, imports | 1960 onward |

The BCN, Banguat and INIDE series are **national primary sources** — the
publisher itself, not a multilateral restatement. The IMF series are the exception to
REIM's "openly licensed only" rule and carry attribution requirements; see the
limitations below.

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
python -m reim.cli pipeline run-all          # ~37,000 observations
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

Everything else — INIDE, Banguat, SIECA and the six IMF trade series — ships its
full history in the routine run, because each of those sources publishes the
complete series on every request. Banguat's 36 years cost one request of 1.3 MB;
SIECA's 69 quarters for six countries cost four requests of 16.7 KB each.

A complete rebuild lands on the order of **42,000 observations**. No exact
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

The MVP has no built-in scheduler by design. `pipeline list` prints a suggested
cron expression per source; wire the CLI into cron, a systemd timer or a
scheduled CI job. `reim.domain.pipelines.scheduling.PipelineScheduler` is the
interface a real scheduler would implement later.

```cron
# Annual World Bank series: check monthly, revisions land unpredictably
0 13 5 * * cd /opt/reim && .venv/bin/python -m reim.cli pipeline run-all
```

---

## Using the API

Base URL `/api/v1`. OpenAPI at `/docs` and `/openapi.json`. Read-only.

### Endpoints

```text
GET /health                              liveness (touches no dependency)
GET /ready                               readiness (checks PostgreSQL)
GET /metrics                             Prometheus text format
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

GET /api/v1/pipelines                    health, volumes and freshness
GET /api/v1/pipelines/runs               ?pipeline_key &status
GET /api/v1/pipelines/runs/{run_id}      run + its quality checks
```

Observation filters: `country` (ISO2 or ISO3), `indicator`, `source`,
`category`, `date_from`, `date_to`, `validation_status`, `status`, plus
`limit`, `offset`, `sort_by`, `order`.

`/compare` takes one `indicator` and a repeated `country`, and returns a
**rectangular** matrix: every row carries an entry for every country asked
for, `null` where that country publishes no figure, so a gap is stated rather
than inferred. It reports whether the series are comparable — the flag turns
on unit and currency — and names what differs. It **never converts
currencies**: heterogeneous units are surfaced, not reconciled.

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

493 tests — 377 offline, 112 integration and 4 opt-in live. Integration tests
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
  connectors read the World Bank, the IMF and SIECA, which compile from national
  statistics and are one step removed from it.
- **Subnational coverage is two regions, not a geography model.** INIDE's
  Managua and rest-of-country breakdowns are separate indicator codes.
  `observations` has no region dimension, so this does not generalise to
  finer geography without a schema change.
- **One source is not openly licensed, though it may be redistributed.** The
  IMF merchandise-trade series carries "© International Monetary Fund. All
  Rights Reserved", unlike every other source here. Its terms **do permit
  redistribution with attribution**: cite the IMF — every observation carries
  the Fund's suggested citation in `raw_metadata.imf_citation` once written —
  keep the
  figures exact, and declare any transformation. **Commercial reuse requires
  permission from `copyright@imf.org`**, which this project has not sought. See
  [`docs/sources.md`](./docs/sources.md).
- **Publishers' edge rules, stated in two parts rather than as one absolute.**

  **REIM does not defeat an active access control.** `www.bcn.gob.ni` sits
  behind a Radware bot manager that answers every automated request with a
  JavaScript challenge; REIM does not execute it, and that has not changed. The
  consequence is real: the BCN's monthly bulletins stay out of reach, so
  monetary aggregates and remittances are absent — Nicaragua reports neither to
  the IMF, and the regional alternative requires a credentialed account.

  **REIM does satisfy a static header check.** SIECA's edge allows or denies on
  the `User-Agent` string alone: REIM's own identifier receives `202` with an
  empty body, `curl` receives `403`, a browser string receives the data. REIM
  sends a string the host accepts, changes nothing else, keeps the same timeout
  and retry policy as every other source, and declares it in the catalog entry.

  These are different things, and the project's rule is stated in both parts
  rather than as one absolute that its own catalog would contradict. See
  [`docs/sources.md`](./docs/sources.md).
- **One source is converted, and says so.** SIECA publishes services trade in
  **millions of USD**; REIM stores whole USD, multiplying by 10⁶ in `Decimal`.
  It is the project's first declared transformation and the only one: every
  observation keeps `sieca_published_value`, `sieca_published_unit` and
  `sieca_scale_applied` in `raw_metadata`, so the published figure is
  recoverable exactly. Nothing else in REIM rescales, converts a currency or
  restates a unit.
- **The BCN endpoint requires a TLS 1.0 handshake.** REIM relaxes the protocol
  version and cipher security level for that one host, declared and justified in
  `sources/catalog.yml`. Certificate and hostname verification stay enforced.
- **INIDE publishes no monthly CPI for 2008-2010.** That gap is in the source
  itself; REIM reports it rather than filling it.
- **World Bank data lags.** Annual figures for year *Y* land during *Y+1*, so
  freshness thresholds are measured in hundreds of days, not days.
- **Six countries, but only two of them beyond trade.** Nicaragua has the
  BCN's daily exchange rate and INIDE's monthly CPI; Guatemala has Banguat's
  daily rate pair. El Salvador, Honduras, Costa Rica and Panama have **trade
  only** — monthly merchandise from the IMF and quarterly services from SIECA.
  Belize has neither: it reports nothing to the IMF dataflow at any frequency
  and is not one of SIECA's six, so it stays inactive in the registry.
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
publisher's terms — the World Bank Indicators API is CC-BY-4.0; BCN material is
public official data. Each source's licence is recorded in
`sources/catalog.yml` and exposed through `/api/v1/sources`. Check it before
redistributing.

## License

[Apache License 2.0](./LICENSE).
