# REIM — Implementation Plan (MVP v0.1.0)

Status: **delivered** — all four verticals complete, every acceptance criterion met.
Last updated: 2026-08-04

---

## 1. Scope

Build the initial MVP of the **Regional Economic Intelligence Monitor (REIM)**: a reproducible,
traceable economic data platform for Central America, focused on **Nicaragua** for v0.1.0.

### In scope

1. Declarative source catalog (`sources/catalog.yml`) validated with Pydantic.
2. Ingestion connectors with a common contract (`extract` / `transform` / `validate`).
3. Shared pipeline runner owning persistence, quality gating, error handling and run bookkeeping.
4. Normalized economic observations stored in PostgreSQL 16 with full provenance.
5. Idempotent upserts plus an explicit revision audit trail.
6. Configurable data-quality checks with `info` / `warning` / `error` / `critical` severities.
7. Read-only REST API under `/api/v1` (countries, organizations, sources, indicators,
   observations, pipelines) with filtering, pagination, ordering and CSV export.
8. CLI for catalog validation, seeding, pipeline execution and quality reporting.
9. Docker Compose environment (`api` + `postgres`), Alembic migrations, Makefile.
10. Unit + integration tests, Ruff, MyPy (strict), GitHub Actions CI.
11. Documentation: README, CONTRIBUTING, ROADMAP, SECURITY, source notes.

### Explicitly out of scope for v0.1.0

News ingestion, RAG, forecasting, alerting, LLM/MCP integration, user authentication,
web dashboard, distributed infrastructure (Kafka / Airflow / Celery / Kubernetes / Redis).

---

## 2. Key decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Modular monolith**, packages `reim` (library) + `apps.api` (HTTP layer). | Smallest thing that keeps domain / persistence / ingestion / API separated. |
| D2 | **Synchronous SQLAlchemy 2.0 + psycopg 3**; FastAPI endpoints declared `def` (threadpool). | Avoids two DB stacks and async-session complexity. The only long-running work (ingestion) runs from the CLI, never from a request. |
| D3 | Connector `extract()` is `async` (uses `httpx.AsyncClient`); the runner is `async` and performs persistence synchronously inside it. | Matches the required connector contract while keeping persistence simple. Acceptable because the runner is CLI-driven, never inside the API event loop. |
| D4 | **UUIDv4 primary keys** on every table. | Stable identifiers that can be generated client-side and merged across country deployments later. |
| D5 | Economic values handled as `Decimal` in Python and stored in **unconstrained** PostgreSQL `NUMERIC`. | No binary floating point for economic magnitudes. A fixed scale was tried first and rejected — see §9. |
| D6 | Natural key for an observation: `(indicator_id, country_id, source_id, period_start, period_end)` with a DB `UNIQUE` constraint. | Deterministic idempotency that does not depend on the payload hash. |
| D7 | `content_hash` = SHA-256 over the canonical value payload (value, unit, currency, period). Used to distinguish *unchanged* from *revised*. | Cheap change detection; a differing hash on an existing natural key means the source revised the datapoint. |
| D8 | Revisions recorded in a dedicated `observation_revisions` table (snapshot of the previous values). No destructive updates. | Simple, queryable audit trail; satisfies "never silently delete". |
| D9 | Quality rules configured per indicator in `sources/quality_rules.yml` (Pydantic-validated). | Keeps thresholds out of code and reviewable in PRs. |
| D10 | A `critical` failing check aborts the transaction (rollback); `error` rejects the individual observation; `warning`/`info` are recorded only. | "A critical result must prevent invalid data from being committed." |
| D11 | Periods are stored as an explicit `[period_start, period_end]` date range plus a human `period_label`. Annual `2024` → `2024-01-01 .. 2024-12-31`, label `"2024"`. | Preserves the original economic meaning; no implicit collapse of a period into a single day. |
| D12 | All timestamps are `TIMESTAMPTZ` and produced with `datetime.now(UTC)`. | Single, unambiguous time base. |
| D13 | Pipelines are **not** triggerable over HTTP in this MVP; scheduling is a CLI concern behind a `PipelineScheduler` protocol. | Explicit MVP requirement; leaves room for an external scheduler later. |
| D14 | The catalog references connectors by dotted module path and the registry imports them lazily. | Adding a country/source requires no change to core code. |
| D15 | Primary verified data provider for v0.1.0 is the **World Bank Indicators API v2** (open, official multilateral source, no auth, stable, reproducible). BCN is implemented but shipped disabled — see §5. | Guarantees real, verifiable data for all five MVP indicators without fabricating anything. |

---

## 3. Work breakdown (vertical slices)

### Vertical 1 — Foundations ✅
- `pyproject.toml`, tooling config (Ruff, MyPy strict, pytest).
- `reim.core`: settings, structured logging, typed exceptions, enums/constants.
- `reim.database`: declarative base, mixins, engine/session management.
- SQLAlchemy models for all eight entities.
- Alembic environment + initial migration.
- Seed data for Nicaragua, its organizations and the MVP indicators.
- `GET /health`, `GET /ready`.
- Docker Compose (`api`, `postgres`) + Dockerfile + Makefile.

### Vertical 2 — Ingestion ✅
- Catalog schema + loader + `catalog validate` CLI command.
- `BaseConnector` ABC and the dataclasses it exchanges
  (`RawDataset`, `NormalizedObservation`, `QualityResult`).
- Connector registry (lazy import by dotted path).
- Shared HTTP client (timeouts, retries via tenacity, User-Agent).
- Pipeline runner: run record → extract → transform → quality → transactional persist → finalize.
- Idempotent writer with revision auditing.
- Reusable quality checks + per-indicator rules.
- Unit tests for periods, hashing, catalog, quality, connector transforms.

### Vertical 3 — Read API ✅
- Pydantic response schemas + consistent error envelope.
- Routers: countries, organizations, sources, indicators, observations.
- Filtering, pagination, ordering, max limits, CSV streaming export.

### Vertical 4 — Operations ✅
- Pipelines router (runs, freshness, quality summary), `/api/v1/status`, `/metrics`.
- Remaining connectors.
- Integration tests (PostgreSQL), CI workflow, documentation.

---

## 4. Data model

Eight tables. `countries`, `organizations`, `data_sources`, `indicators`, `observations`,
`observation_revisions`, `pipeline_runs`, `data_quality_checks`.

Indexes beyond the primary/unique keys:

- `observations (country_id, indicator_id, period_start DESC)` — the main query path.
- `observations (indicator_id, period_start DESC)`, `observations (source_id)`,
  `observations (validation_status)`, `observations (content_hash)`.
- `pipeline_runs (pipeline_key, started_at DESC)`, `pipeline_runs (status)`.
- `data_quality_checks (pipeline_run_id)`, `data_quality_checks (status, severity)`.

---

## 5. Source research notes

Full detail lives in [`docs/sources.md`](./sources.md). Summary:

| Source | Status | Notes |
|--------|--------|-------|
| World Bank Indicators API v2 | **Verified, enabled** | `https://api.worldbank.org/v2/country/NIC/indicator/{code}?format=json`. Open, no auth, JSON, annual frequency, stable pagination. Covers all five MVP indicators. |
| INIDE monthly IPC (`www.inide.gob.ni/Home/ipc`) | **Verified, enabled** | Monthly CPI index, month-on-month and year-on-year variation, from the legacy `.xls` workbook. First national primary source and first monthly series. Added after the initial MVP; see §11. |
| BCN exchange-rate SOAP service | **Implemented, disabled** | `https://servicios.bcn.gob.ni/Tc_Servicio/ServicioTC.asmx`. The host only negotiates a pre-TLS 1.2 handshake, which modern OpenSSL 3.x / Fedora crypto policies reject (`unsupported protocol`). Transform logic is unit-tested against a fixture, but the response shape is **not** verified against the live service, so the source ships `enabled: false`. |
| BCN statistics portal (`www.bcn.gob.ni`) | Reachable, unstructured | Drupal site; the exchange-rate page renders no server-side table and exposes no CSV/XLSX export at a stable URL. Not automatable reliably yet. |
| INIDE, MHCP, SIBOIF, SIECA, BCIE, CEPAL, IMF | Deferred | Registered in the catalog only where a stable machine-readable endpoint exists. Not implemented in v0.1.0. |

Nothing is simulated. Where a source could not be automated reliably, the connector ships
disabled with the blocker documented rather than backed by invented data.

---

## 6. Dependencies & risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Official Nicaraguan endpoints are unstable or use legacy TLS. | Cannot ingest national primary data. | Ship disabled connectors with documented blockers; rely on verified multilateral sources meanwhile. |
| World Bank data is annual only. | Low temporal resolution. | Model periods explicitly so higher-frequency sources drop in without schema change. |
| Upstream revisions silently change history. | Loss of auditability. | `content_hash` + `observation_revisions` snapshots. |
| Tests coupled to live networks. | Flaky CI. | All connector tests use `respx` mocks and recorded fixtures; live checks are opt-in (`-m live`). |
| Docker unavailable on a contributor's machine. | Cannot run integration tests. | Integration tests skip cleanly unless `REIM_TEST_DATABASE_URL` is set; `make db-up` works with Docker or Podman. |

---

## 7. Acceptance criteria

1. `docker compose up --build` starts PostgreSQL 16 and the API; `/health` and `/ready` respond.
2. `alembic upgrade head` builds the schema from scratch.
3. `reim catalog validate` validates the catalog and fails loudly on an invalid one.
4. At least three real connectors ingest live official data (v0.1.0 ships five).
5. Re-running a pipeline inserts zero duplicates.
6. Every observation is linked to a country, an indicator and a source.
7. Pipeline runs, errors and quality checks are persisted.
8. The API serves indicators and observations and exports CSV.
9. `pytest`, `ruff check`, `ruff format --check` and `mypy` all pass.
10. CI is configured; README / CONTRIBUTING / ROADMAP / SECURITY are complete.
11. No secrets and no fabricated data outside `tests/fixtures`.

---

## 8. Verification record (2026-08-04)

Executed against PostgreSQL 16.14 and the live World Bank API.

| Check | Result |
|-------|--------|
| `alembic upgrade head` from an empty database | ✅ single migration builds all 8 tables |
| `alembic downgrade base && alembic upgrade head` | ✅ round-trips |
| `alembic check` | ✅ no drift between models and migrations |
| `reim catalog validate` | ✅ 7 sources (6 enabled), 7 rule sets, 7 connectors import |
| `reim db seed` | ✅ 30 reference rows; re-run creates 0 |
| `reim pipeline run-all` (live) | ✅ 6/6 succeeded, **322 observations** ingested |
| Second `run-all` (idempotency) | ✅ 0 inserted, 322 unchanged, 0 duplicates |
| Decimal precision round trip | ✅ `2.06064418965517E-9` stored and exported exactly |
| API endpoints | ✅ all 16 respond, incl. CSV export and error envelope |
| Container build + boot (podman) | ✅ migrates, seeds, serves; runs as uid 10001 |
| `pytest` | ✅ 242 passed |
| `ruff check` / `ruff format --check` | ✅ clean, 94 files |
| `mypy --strict reim apps` | ✅ no issues in 77 source files |

## 9. Problems found and fixed during implementation

Both were caught by tests written against real data, and both are now covered by
regression tests.

1. **`NUMERIC(30, 10)` silently truncated real values.** The World Bank restates
   Nicaragua's exchange rate in current córdobas, so pre-redenomination figures
   are around `2.06064418965517E-9`; a scale of 10 rounded that to `2.1E-9`, and
   also clipped CPI figures to ten decimals. The column is now unconstrained
   `NUMERIC` (arbitrary precision). A fixed scale cannot serve a table holding
   both balance-of-payments aggregates in the billions and rates near 1e-9.

2. **A too-tight quality threshold rejected 31 legitimate observations.** An
   initial `min_value: 1` on the annual exchange rate treated every genuine
   1960–1990 figure as invalid. The rule now constrains only the sign. This is
   exactly the failure mode `sources/quality_rules.yml` warns against: thresholds
   are tripwires for a broken feed, not economic priors.

## 11. Post-MVP increment — INIDE monthly CPI (2026-08-04)

Added `inide_cpi_monthly`, closing the "no national primary source" gap the MVP
shipped with.

**Verification**

| Check | Result |
|-------|--------|
| Live `pipeline run inide_cpi_monthly` | ✅ 582 observations (198 index + 186 m/m + 198 y/y) |
| Second run | ✅ 0 inserted, 582 unchanged |
| Full `run-all` from an empty database | ✅ 7/7 pipelines, 904 observations |
| Unit tests | ✅ 38 new, replayed against a real recorded workbook |
| `pytest` / `ruff` / `mypy --strict` | ✅ 285 passed / clean / clean (78 files) |
| Container rebuild with `xlrd` | ✅ builds and serves |

**Two shared-layer defects the new source exposed**

1. **`check_period_change` compared across holes in a series.** INIDE publishes
   no monthly CPI for 2008-2010, and the check measured 2011-01 against 2007-12
   as a single "25.25% monthly change". It now compares only genuinely adjacent
   periods — two closed intervals one day apart, which is the adjacency test at
   every frequency. This also removed pre-existing false positives on the World
   Bank series, which have missing years.
2. **Dataset-level `error` checks had no effect on the run outcome.** An `error`
   result that names no specific row rejected nothing and left the run reporting
   `success`. Such a run is now `partial`: the data is still written (an error is
   not critical), but the outcome no longer hides a problem.

**Judgement calls, all documented in `docs/sources.md`**

* Annual rows are not ingested — they are year averages, and the current year's
  is a partial average that would churn as a false revision every month.
* Continuity is enforced only from 2011, where INIDE actually publishes without
  gaps; the sparse 2001-2010 history is reported, not flagged as a fault.
* Values are quantised to six decimals: the index's full published precision,
  minus Excel's IEEE-754 noise.
* The connector reads the index page to *discover* the newest workbook, because
  file naming drifts between releases and no URL template covers them all.

## 10. Follow-up work (not in v0.1.0)

- Verify the BCN SOAP contract from a network/TLS environment that can reach it, then enable it.
- Add INIDE monthly CPI and BCN monthly monetary statistics once a stable export is identified.
- Additional Central American countries (registry entries already exist).
- See [`ROADMAP.md`](../ROADMAP.md).
