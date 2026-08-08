# REIM — Regional Economic Intelligence Monitor

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)

**An open economic data platform for Central America.** REIM collects, normalizes,
stores and publishes economic indicators from official sources, keeping complete
provenance for every figure it holds.

v0.1.0 covers **Nicaragua**. The architecture is country-agnostic: adding
Guatemala, El Salvador, Honduras, Costa Rica, Panama or Belize is a catalog entry
plus a connector module, not a redesign.

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

### Data available in v0.1.0

Seven live pipelines, all verified against the source on 2026-08-04. INIDE is
Nicaragua's national statistics office — a primary national source, at monthly
resolution:

| Indicator | Source | Frequency | Coverage |
|-----------|--------|-----------|----------|
| **CPI index (2006=100)** | **INIDE** | **monthly** | **2007–2026** |
| **CPI inflation, month on month** | **INIDE** | **monthly** | **2011–2026** |
| **CPI inflation, year on year** | **INIDE** | **monthly** | **2007–2026** |
| Official exchange rate (annual avg) | World Bank `PA.NUS.FCRF` | annual | 1960–2025 |
| Consumer price inflation | World Bank `FP.CPI.TOTL.ZG` | annual | 2000–2025 |
| Personal remittances received | World Bank `BX.TRF.PWKR.CD.DT` | annual | 1977–2024 |
| Total international reserves | World Bank `FI.RES.TOTL.CD` | annual | 1960–2025 |
| Exports of goods and services | World Bank `NE.EXP.GNFS.CD` | annual | 1960–2025 |
| Imports of goods and services | World Bank `NE.IMP.GNFS.CD` | annual | 1960–2025 |

One connector ships **disabled**: the BCN daily exchange rate. Its endpoint only
negotiates a pre-TLS 1.2 handshake that modern OpenSSL rejects, so its response
contract was never verified. See [docs/sources.md](./docs/sources.md) — this is
recorded rather than papered over, on purpose.

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
git clone https://github.com/reim-project/reim.git
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
| `REIM_HTTP_USER_AGENT` | identifies REIM | Sent to every official source |
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

GET /api/v1/pipelines                    health, volumes and freshness
GET /api/v1/pipelines/runs               ?pipeline_key &status
GET /api/v1/pipelines/runs/{run_id}      run + its quality checks
```

Observation filters: `country` (ISO2 or ISO3), `indicator`, `source`,
`category`, `date_from`, `date_to`, `validation_status`, `status`, plus
`limit`, `offset`, `sort_by`, `order`.

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

343 tests. Integration tests skip cleanly when `REIM_TEST_DATABASE_URL` is unset,
so `pytest` works on a bare checkout.

**No test calls a live official source.** Connector tests replay recorded
fixtures through `respx`. To check the real services on purpose:

```bash
make smoke          # opt-in; makes real network calls
python scripts/smoke_test_sources.py --source worldbank_ni_cpi_inflation
```

---

## Limitations

Stated plainly, because a data platform that hides its gaps is worse than none:

- **Two national primary sources, six multilateral.** INIDE's monthly CPI —
  national, Managua and rest-of-country — and the BCN's daily exchange rate come
  straight from the publisher; the remaining six connectors read the World Bank,
  which compiles from national statistics and is one step removed from it.
- **Subnational coverage is two regions, not a geography model.** INIDE's
  Managua and rest-of-country breakdowns are separate indicator codes.
  `observations` has no region dimension, so this does not generalise to
  finer geography without a schema change.
- **The BCN endpoint requires a TLS 1.0 handshake.** REIM relaxes the protocol
  version and cipher security level for that one host, declared and justified in
  `sources/catalog.yml`. Certificate and hostname verification stay enforced.
- **INIDE publishes no monthly CPI for 2008-2010.** That gap is in the source
  itself; REIM reports it rather than filling it.
- **World Bank data lags.** Annual figures for year *Y* land during *Y+1*, so
  freshness thresholds are measured in hundreds of days, not days.
- **Only Nicaragua.** Other Central American countries are registered but
  inactive; no connectors exist for them yet.
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
