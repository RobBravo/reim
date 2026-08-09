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

## 12. Post-MVP increment — BCN daily exchange rate (2026-08-08)

Enabled `bcn_exchange_rate`, giving REIM its first daily-frequency series and
its second national primary source.

**The v0.1.0 blocker was misdiagnosed.** §5 recorded that the host "only
negotiates a pre-TLS 1.2 handshake, which OpenSSL 3.x rejects". The host does
negotiate only TLS 1.0, but the handshake failed one stage later, at
`ServerKeyExchange`, on Fedora's ban on **SHA-1 signatures**. An
`ssl.SSLContext` pinned to TLS 1.0 at `SECLEVEL=0`, verifying against certifi,
connects with no environment changes and with certificate and hostname
verification intact.

**Verification**

| Check | Result |
|-------|--------|
| `reim catalog validate` | ✅ 8 sources, 8 enabled, all connectors import |
| Live `pipeline run bcn_exchange_rate` | ✅ 39 observations (2026-07-01 … 2026-08-08) |
| Second run | ✅ 0 inserted, 39 unchanged |
| Historical backfill (`start_month: 2012-01`) | ✅ 5,295 inserted, 5,334 total, 0 rejected, 31 s |
| Backfill continuity | ✅ 5,334 days = exactly the calendar span 2012-01-01 → 2026-08-08, no gaps |
| Run after removing `start_month` | ✅ back to 2 requests, 0 inserted |
| Quality checks | ✅ 0 failing at `error` or `critical`; the three BCN checks pass |
| No future data stored | ✅ `max(period_start) = 2026-08-08` = today |
| API + CSV export | ✅ 5,334 served with full provenance |
| Live contract test (`pytest -m live`) | ✅ passes against the real service |
| `pytest` / `ruff` / `mypy --strict` | ✅ 240 passed / clean / clean |

**Judgement calls**

* Rows dated after today are discarded and the count reported as an `info`
  check. The service projects the frozen rate forward to the end of the calendar
  year; publishing that as observed would be a factual error, and discarding it
  silently would hide that the source projects at all.
* The scheduled window is two months. The 2012-onwards backfill is an explicit
  one-off range, capped at 400 months, because the HTTP layer exists so that no
  connector accidentally hammers an official source.
* `RecuperaTC_Dia` is not used. `RecuperaTC_Mes` is a strict superset at a
  thirtieth of the request count.
* A day returned twice with two different values raises rather than picking a
  winner.

**Deviation from the design.** The design said the legacy profile "emits a
structured warning naming the host". `http_client` does not know the host, so
the warning is split: `http.legacy_tls_enabled` in the HTTP layer guarantees no
connector can downgrade silently, and `bcn.legacy_tls` in the connector adds the
hostname. Both fire on every run.

## 13. Post-MVP increment — INIDE regional CPI (2026-08-08)

Added the Managua and rest-of-country CPI breakdowns, taking `inide_cpi_monthly`
from three series to nine.

**The roadmap understated how close the data was.** It described the regional
series as sitting "in the same workbook alongside the national series". They sit
in the **same worksheet and the same rows**: sheet `2-1-06` is three symmetric
four-column blocks, and the connector already walked past columns 6-13. No new
download, sheet parser or network call was needed.

**Verification**

| Check | Result |
|-------|--------|
| `reim catalog validate` | ✅ 8 sources, quality rule sets 10 → 16 |
| Live `pipeline run inide_cpi_monthly` | ✅ 1,746 observations, 0 rejected |
| Second run | ✅ 0 inserted, 1,746 unchanged |
| **Refactor safety** — new connector run over rows written by the pre-refactor one | ✅ 1,164 inserted, **582 unchanged, 0 updated** |
| Regions distinct in stored data | ✅ mean index 220.569 / 220.417 / 220.850 over the same 198 months |
| Quality checks | ✅ 4 INIDE checks pass; 0 failures at `error` or `critical` |
| `pytest` / `ruff` / `mypy --strict` | ✅ 343 passed / clean / clean |

The refactor-safety row is the one that mattered. The risk was that rewriting
the column map would silently change a national value; running the new connector
over a database populated by the old one and getting `updated = 0` proves every
one of the 582 national observations hashes identically.

**Judgement calls**

* Region is modelled as new indicator codes, not a dimension on `observations`.
  A geography column would mean a migration touching every observation, the
  repositories and the API, for one source that needs it today.
* The three national codes were not renamed, so the existing series keeps its
  history. The national block simply carries an empty indicator suffix.
* Regional indicators reuse their national counterpart's quality thresholds
  verbatim. Inventing tighter bounds per region is how v0.1.0 rejected 31
  legitimate exchange-rate figures.
* The year-to-date column stays unread for every region, but its header is still
  asserted: twelve headers are checked, not nine, because dropping the existing
  "Acumulada" assertion would have been a regression.

## 14. Post-MVP increment — IMF monthly trade (2026-08-08)

The roadmap asked for **BCN monthly statistics**. The BCN cannot be read:
`www.bcn.gob.ni` redirects every automated request to a Radware bot-manager
challenge at `validate.perfdrive.com`, including requests carrying a browser
User-Agent. Defeating it would mean circumventing an access control the
publisher installed deliberately, so the same indicators were sought elsewhere.

Only one of the four families could be delivered honestly. Measured, not
assumed: `MFS_MA` returns 0 observations for Nicaragua against 183 for Costa
Rica; `BOP` returns 0 at every frequency; `IRFCL` has 1,740 monthly Nicaraguan
observations whose 60 indicator codes cannot be named from anything the API
exposes. `IMTS` has three self-describing codes and shipped.

**Verification**

| Check | Result |
|-------|--------|
| `reim catalog validate` | ✅ 9 sources, 9 enabled, 19 rule sets |
| Live `pipeline run imf_imts_nicaragua` | ✅ 1,308 observations, 0 rejected |
| Second run | ✅ 0 inserted, 1,308 unchanged |
| Stored signs | ✅ exports/imports minima positive; balance minimum **−520,784,262** |
| Coverage | ✅ 436 months, 1990-01 … 2026-04, three series |
| Quality checks | ✅ 3 IMF checks pass; 0 failures at `error` or `critical` |
| Live contract test (`pytest -m live`) | ✅ passes against the real API |
| `pytest` / `ruff` / `mypy` | ✅ 278 passed / clean / clean |

**Three things the plan had wrong, all caught by measuring the recording**

1. The dataflow metadata row is the **last** row, not the first.
2. The 1990 figures carry 16 significant digits; the expected balance is
   `-50033856.85436923`, not the `-50033856.9` a formatted print had suggested.
3. **The balance identity is not exact.** The IMF rounds `TBG`, so 12 of 436
   months differ from `XG − MG` in their last digit, by at most 5e-8 USD. The
   check as first designed used exact equality and would have reported an
   `error` on every single run. It now allows a one-cent tolerance.

**Judgement calls**

* The counterpart is filtered in the SDMX key, not after download: 789 KB
  instead of 62.9 MB for the same 1,308 rows.
* A response with no `G001` row fails at `critical`. The alternative — summing
  103 overlapping counterpart groups — would report 1,804 M where the real
  figure is 481 M.
* `SCALE=6` is recorded and never applied; the values are already full USD.
* The CSV media type is pinned and enforced, because the API ignores content
  negotiation and answers SDMX-ML to a JSON request.

**Licence deviation.** This is the only REIM source whose data is not openly
licensed: it carries "All Rights Reserved". The catalog says
`license: imf_terms_of_use`, and `docs/sources.md` states the deviation plainly
rather than disguising it. The IMF's terms page could not be retrieved
programmatically, so its contents are not summarised anywhere in this repo.

## 15. Post-MVP increment — regional IMF trade (2026-08-08)

REIM's **first data for more than one country**, and the first piece of v0.3.0.

**v0.3.0 was decomposed before anything was built.** As written it is five
independent subsystems, one of which is really six separate investigations:

| Piece | Status |
|---|---|
| **A. Regional IMF trade** | ✅ this increment |
| **B. Cross-country comparison endpoints** | open — now has something to compare |
| **C. National central banks** (six countries) | open, six independent investigations |
| **D. SIECA** | open, unresearched |
| **E. CEPALSTAT** | open; a probe of its API returned 404 |
| **F. Currency handling** | open, and not needed yet — everything multi-country is USD |

A was chosen because it was measured rather than hoped: the connector shipped
hours earlier already read this dataflow, and all six countries carry identical
coverage.

**Verification**

| Check | Result |
|-------|--------|
| `reim catalog validate` | ✅ 14 sources, 14 enabled, 19 rule sets |
| Six live pipeline runs | ✅ 1,308 observations each, 0 rejected |
| Second run of all six | ✅ 0 inserted, 1,308 unchanged each |
| **Six countries are distinct series** | ✅ mean monthly exports 730 M (CRI) / 618 M (GTM) / 318 M (SLV) / 246 M (HND) / 157 M (NIC) / 93 M (PAN) |
| Quality checks | ✅ all four IMF checks pass; 0 failures at `error` or `critical` |
| Superseded rows cleared | ✅ 1,308 rows under the old prefixed codes deleted once |
| Total held | 14,928 observations |
| `pytest` / `ruff` / `mypy` | ✅ 379 passed / clean / clean |

**Judgement calls**

* Indicator codes lost their country prefix, because `observations` already
  carries a country. The rule: prefix for national sources whose methodology
  differs, none for shared multilateral ones. The 16 `ni_*` codes were left
  alone — renaming all 19 would have marked 8,388 observations as revised.
* Six catalog entries rather than one regional source. A single SDMX key does
  return all 7,848 rows in 1.38 s, but `source_key` is part of an observation's
  natural key, so it would have duplicated Nicaragua's stored series.
* The connector is a shared base plus six eight-line subclasses, following the
  World Bank pattern. An earlier design loosened `BaseConnector`'s guard that
  the catalog key matches the connector key; that was rejected in review.
* Belize gets no entry: it reports nothing to IMTS at any frequency.

**The check that mattered.** All six countries return 436 identically shaped
months, so a country-mapping bug would have produced plausible figures under
the wrong flag with every count intact. A `critical` check asserts each row
belongs to the declared country, and a test compares Guatemala's exports
against Nicaragua's for the same month.

## 16. Post-MVP increment — comparison endpoint (2026-08-08)

`GET /api/v1/compare`: one indicator across two to twenty countries, aligned by
period. Piece B of v0.3.0, and the first thing REIM offers that the previous
increment made possible — until six countries existed there was nothing to
compare.

**Verification**

| Check | Result |
|-------|--------|
| Real six-country request | ✅ 436 aligned periods, `comparable: true`, no notes |
| Newest row | ✅ six values, zero nulls: NIC 601,982,690 … PAN 158,395,970 |
| Value parity with `/observations` | ✅ identical for the same country and period |
| An indicator only Nicaragua holds | ✅ GTM reported with 0 observations, column all `null`, note names it |
| One country | ✅ `422`; twenty-one countries `422`; unknown indicator or country `422`/`404` |
| `pytest` / `ruff` / `mypy` | ✅ 405 passed / clean / clean |

**A finding from real data that the design had not anticipated.** The first
run against the six countries emitted `Sources differ across countries:
imf_imts_costa_rica, imf_imts_el_salvador, …` — because REIM holds the IMF
under one catalog entry per country. That note would have fired on **every**
regional comparison, which is exactly the "crying wolf" the design argued
against for the `comparable` flag itself. The note is now keyed on the
publishing **organization** rather than the catalog key, and `series` exposes
both. Against the real data it is now silent, and it still speaks when
publishers genuinely differ.

**Judgement calls**

* Rows are rectangular with explicit `null`s. An absent key would force the
  caller to cross-reference `series[].observations` to notice a hole.
* `comparable` turns on unit and currency only. Differing publishers are noted
  but do not flip it.
* No currency conversion, now or ever: it would publish figures no official
  source published.
* Pagination slices **periods**, not observation rows, so a page always carries
  every country's figure for the periods it covers.

## 10. Follow-up work (not in v0.1.0)

- Verify the BCN SOAP contract from a network/TLS environment that can reach it, then enable it.
- Add INIDE monthly CPI and BCN monthly monetary statistics once a stable export is identified.
- Additional Central American countries (registry entries already exist).
- See [`ROADMAP.md`](../ROADMAP.md).
