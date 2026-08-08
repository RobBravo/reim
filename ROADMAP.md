# REIM Roadmap

What exists, what comes next, and why in that order.

The ordering principle: **breadth and depth of trustworthy data before anything
built on top of it.** A dashboard over three annual series is a demo; a
dashboard over reliable monthly national data is a tool. Every phase below
assumes the layer under it is solid.

Dates are intentionally absent — this is an open project and sequencing depends
on contributors and on which official endpoints turn out to be automatable.

---

## v0.1.0 — MVP ✅ shipped

Nicaragua, foundations, correctness.

- Declarative source catalog with Pydantic validation.
- `BaseConnector` contract and a shared runner owning persistence, transactions,
  idempotency, quality gating, error handling and structured logging.
- Six live connectors reading the World Bank Indicators API (exchange rate,
  inflation, remittances, reserves, exports, imports).
- One documented-disabled connector (BCN daily exchange rate).
- PostgreSQL 16 schema with full provenance, idempotent upserts and a revision
  audit trail.
- Configurable per-indicator quality checks with four severity levels.
- Read-only REST API: countries, organizations, sources, indicators,
  observations, pipelines, CSV export.
- Operations CLI, Docker Compose, Alembic migrations, 242 tests, CI.

---

## v0.2.0 — National primary sources

The most important gap in v0.1.0: every working connector reads a multilateral
aggregator rather than the Nicaraguan publisher itself.

- ~~**INIDE monthly IPC**~~ ✅ **done** — the national CPI is live at monthly
  resolution (index, month-on-month and year-on-year), replacing reliance on the
  World Bank's annual restatement. See `docs/sources.md`.
- ~~**Unblock the BCN exchange-rate connector**~~ ✅ **done** — REIM's first
  daily-frequency series: 5,334 observations from 2012-01-01, one per calendar
  day. The v0.1.0 blocker was misdiagnosed — the handshake failed on the SHA-1
  signature ban, not the protocol version — and the real WSDL contract differed
  from every assumption made while the service was unreachable. See
  `docs/sources.md`.
- **BCN monthly statistics** — ⚠️ **partly delivered, partly blocked.** The
  layout question never arose: `www.bcn.gob.ni` redirects every automated
  request to a Radware bot-manager challenge, and REIM will not defeat an
  access control the publisher installed deliberately. Of the four families:
  - ~~**merchandise trade**~~ ✅ **done** — monthly exports, imports and balance
    from the IMF's IMTS instead, 1,308 observations from 1990-01. Note this is
    REIM's only source whose data is **not openly licensed**.
  - **monetary aggregates and remittances** — Nicaragua reports neither to the
    IMF (0 observations, against 183 for Costa Rica). Available from SECMCA,
    which requires a credentialed account.
  - **reserves** — the IMF has 1,740 monthly observations, but its indicator
    codes cannot be named from anything its API exposes. See `docs/sources.md`
    for the unblocking step.
- ~~**INIDE regional CPI**~~ ✅ **done** — Managua and rest-of-country, nine
  series and 1,746 observations from the same single download. They turned out
  to sit not merely in the same workbook but in the same worksheet and the same
  rows, in columns the connector already walked past. See `docs/sources.md`.
- **XLSX ingestion support** in the shared connector toolkit (pandas is already
  an approved dependency for exactly this).
- Monthly and quarterly frequency exercised end to end. The period model already
  supports it; no schema change needed.

## v0.3.0 — Central America

- Connectors for **Guatemala (Banguat), El Salvador (BCR), Honduras (BCH),
  Costa Rica (BCCR), Panama (INEC) and Belize (Central Bank of Belize)**.
  Country registry entries already exist and are inactive.
- **SIECA** regional trade series.
- **CEPALSTAT** for cross-country comparable series.
- Cross-country comparison endpoints: one indicator, many countries, aligned
  periods, with the unit and vintage differences made explicit rather than
  smoothed over.
- Currency handling for genuinely multi-currency comparisons — always alongside
  the original figure, never replacing it.

## v0.4.0 — Making the data visible

- **Web dashboard.** Read-only, server-rendered or a small SPA over the existing
  API. Time series, country comparison, source and freshness transparency.
  Every chart links back to the source URL for the underlying figure.
- **Data catalog browser** — what REIM holds, how fresh it is, what is disabled
  and why.
- **Pipeline observability page** — run history, quality trends, staleness.

## v0.5.0 — Operations

- **API keys and rate limiting** for public deployment.
- **Alerting** on stale pipelines, failed runs and quality regressions
  (webhook / email; no new infrastructure).
- **Scheduler integration** behind the existing `PipelineScheduler` interface.
- **Prometheus metrics** beyond the current process-level defaults: per-pipeline
  volumes, durations, freshness gauges.
- Public deployment guide with hardening notes.

## v0.6.0 — Context

Economic figures become far more useful next to what happened around them.

- **Economic news ingestion** from official communiqués and press releases —
  central bank statements, ministry announcements — with the same provenance
  discipline applied to text.
- **Event correlation**: link a datapoint to publications and policy events in
  its period. Correlation surfaced as *context*, never asserted as causation.
- **Geospatial data** where it exists at subnational resolution.

## v0.7.0 — Interfaces

- **Python SDK** — typed client over the REST API.
- **Distributable CLI** (`pipx install reim-cli`) for querying and exporting.
- **MCP server** so assistants can query REIM's data with provenance intact.
- Bulk export snapshots (Parquet), versioned and checksummed.

## v0.8.0 — Analysis

Deliberately last, and deliberately constrained.

- **RAG over official documents** — answers grounded in, and citing, the actual
  publication.
- **AI summaries** of economic developments, always with the underlying figures
  and their sources attached.
- **Transparent composite indicators.** Any index REIM publishes ships with its
  full formula, inputs and weights, and is clearly labelled as REIM-derived
  rather than official.
- **Forecasting** only if it can be done with published methodology, versioned
  models and honest uncertainty intervals.

---

## Explicitly not planned

Saying no keeps the project coherent.

- **Scraping paywalled or licence-restricted data.** Official and openly
  licensed only.
- **Unofficial or crowd-sourced figures**, including parallel exchange rates,
  presented as if official. If ever added, they would be a clearly separated
  category.
- **Imputation or interpolation of missing values.** Gaps are reported as gaps.
- **Silent methodology changes.** Any change to how REIM derives anything is
  versioned and documented.
- **Distributed infrastructure** (Kafka, Airflow, Celery, Kubernetes,
  microservices) until the monolith is genuinely the bottleneck.
- **Investment recommendations.** REIM publishes data, not advice.

---

## How priorities change

The roadmap follows what is actually achievable. If an official endpoint turns
out to be automatable, it moves up; if a source becomes unreachable, that gets
documented in [`docs/sources.md`](./docs/sources.md) and the work moves down.

Contributions reorder this list. A working connector for a national source is
worth more than any feature further down the page — see
[CONTRIBUTING.md](./CONTRIBUTING.md).
