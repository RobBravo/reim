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
  daily-frequency series: 5,334 observations as of 2026-08-08 from 2012-01-01,
  one per calendar day. The v0.1.0 blocker was misdiagnosed — the handshake failed on the SHA-1
  signature ban, not the protocol version — and the real WSDL contract differed
  from every assumption made while the service was unreachable. See
  `docs/sources.md`.
- **BCN monthly statistics** — ⚠️ **partly delivered, partly blocked.** The
  layout question never arose: `www.bcn.gob.ni` redirects every automated
  request to a Radware bot-manager challenge, and REIM does not execute it —
  passing an active control is where the project draws the line, as
  `docs/sources.md` now states in full. Of the four families:
  - ~~**merchandise trade**~~ ✅ **done** — monthly exports, imports and balance
    from the IMF's IMTS instead, 1,308 observations from 1990-01. Note this is
    REIM's only source whose data is **not openly licensed**.
  - **monetary aggregates and remittances** — Nicaragua reports neither to the
    IMF (0 observations, against 183 for Costa Rica). This line named SECMCA,
    which requires a credentialed account, as the only route. That is no longer
    true for the aggregates: **CEPALSTAT indicator 862 (M1) covers Nicaragua
    from 2001 to 2024 with no authentication at all**, and 868 (M2) and 869 (M3)
    alongside it. Not yet ingested — they carry a period-within-year dimension
    and are published in local currency; `docs/sources.md` records their shape
    and the two traps in reading them.
  - **reserves** — the IMF has 1,740 monthly observations, but its indicator
    codes cannot be named from anything its API exposes. See `docs/sources.md`
    for the unblocking step.

  This also retired the planned **XLSX ingestion support** in the connector
  toolkit. It was listed only to read these bulletins, and nothing else in the
  roadmap needs it: INIDE publishes legacy `.xls`, which `xlrd` already handles.
  If a future source arrives as XLSX, add the support then, for that source.
- ~~**INIDE regional CPI**~~ ✅ **done** — Managua and rest-of-country, nine
  series and 1,746 observations from the same single download. They turned out
  to sit not merely in the same workbook but in the same worksheet and the same
  rows, in columns the connector already walked past. See `docs/sources.md`.
- ~~**Monthly frequency exercised end to end**~~ ✅ **done**, and daily with it,
  which this item had not even anticipated. **Quarterly is now exercised too**,
  by SIECA's services trade in v0.3.0 — not by the SECMCA or IMF
  balance-of-payments candidates this line named. The catalog holds 6 annual,
  7 monthly, 2 daily and 1 quarterly. **Weekly, semiannual and irregular remain
  unexercised** — `Frequency` defines all three and the period model parses
  `YYYY-Wnn` and `YYYY-Hn`, but no source REIM reads publishes at those
  cadences.

## v0.3.0 — Central America

This release is five independent pieces, not one increment. Three are done,
and a fourth has its first country.

- ~~**Regional merchandise trade**~~ ✅ **done** — REIM's first data for more
  than one country: 7,848 monthly observations for Nicaragua, Guatemala, El
  Salvador, Honduras, Costa Rica and Panama, from the IMF's IMTS dataflow, all
  six with identical coverage back to 1990-01. **Belize is excluded**: it
  reports nothing to that dataflow at any frequency. See `docs/sources.md`.
- Connectors for the **national central banks**. Six independent
  investigations, each the size of the BCN work, taken one country at a time.
  **Banguat is done** ✅ — 26,730 observations, a buy and a sell rate for every
  day since 1990-01-01, the whole history in one request. The other five were
  probed and their state recorded in `docs/sources.md`: BCCR answers `503` and
  is known to need an account; BCR, BCH, INEC and the Central Bank of Belize
  are reachable but expose no machine-readable endpoint that could be found.
  None is behind a bot wall.
- ~~**SIECA** regional trade series~~ ✅ **done** — not the intra-regional
  merchandise trade this line originally imagined, which has no
  machine-readable endpoint today, but **quarterly trade in services**: 1,242
  observations, six countries, 2009-Q1 onward, from four requests. REIM's first
  quarterly series and its first source with no country of its own. See
  `docs/sources.md`.
- ~~**CEPALSTAT** for cross-country comparable series~~ ✅ **done** — annual
  GDP: totals and per-inhabitant figures, each at current and at constant 2018
  prices, **1,008 observations** for all seven countries from 1990 to 2025, from
  four requests. REIM's first GDP data and **Belize's first data of any kind**;
  Belize reports nothing to the IMF dataflow REIM's trade series come from, and
  CEPALSTAT publishes its national accounts complete. The API is **not** the
  `404` this repository recorded twice — every route is scoped to an indicator
  id. CEPAL's terms are **not open** and expressly forbid redistribution; see
  `docs/sources.md`, which quotes them and states the conflict.
- ~~**Cross-country comparison endpoints**~~ ✅ **done** — `GET /api/v1/compare`
  takes one indicator and two to twenty countries and returns a **rectangular**
  matrix: every row carries an entry for every country asked for, `null` where
  that country publishes no figure, so a gap is stated rather than inferred.
  Comparability is declared, never enforced: the flag turns on unit and
  currency, differing publishers are noted, and the endpoint never refuses and
  never converts. See `docs/sources.md` and the API section of the README.
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

- **Defeating an active access control.** A JavaScript bot-manager challenge,
  a login, a paywall: REIM does not pass any of them. `www.bcn.gob.ni` sits
  behind a Radware bot manager and stays unread. Satisfying a static header
  check is a different thing, and `docs/sources.md` states which sources need
  one and why.
- **Hiding a licence.** REIM prefers openly licensed sources and says so, but
  three of its sources are not openly licensed — the IMF, SIECA and CEPAL.
  Each carries its real terms in the catalog, each has a section in
  `docs/sources.md` quoting them, and each ships the attribution its publisher
  asks for. The rule is that the terms are recorded, not that they are always
  permissive.
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
