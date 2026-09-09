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
  - ~~**monetary aggregates**~~ ✅ **done** — M1, M2 and M3, monthly, for all
    seven countries: **5,383 observations**, with Nicaragua from 2001-12. This
    line named SECMCA and a credentialed account as the only route; CEPALSTAT
    publishes indicators 862, 868 and 869 unauthenticated. They are REIM's first
    figures in a currency other than the dollar, the córdoba and the quetzal,
    and its first that are **not comparable across countries** — each is in its
    own local currency and REIM does not convert. Honduras warns on freshness
    from the first run, deliberately. See `docs/sources.md`.
  - **remittances** — still absent. Nicaragua reports none to the IMF (0
    observations, against 183 for Costa Rica), and CEPALSTAT's monetary family
    does not carry them. CEPALSTAT's **quarterly balance of payments**
    (indicator 547) carries a "Transferencias corrientes" line, and it is
    **not** remittances: it is the whole current-transfers account, official
    transfers included, with no sub-item breaking personal remittances out.
    SECMCA, behind a credentialed account, remains the only route named so
    far. See `docs/sources.md`.
  - **reserves** — the IMF has 1,740 monthly observations, but its indicator
    codes cannot be named from anything its API exposes. CEPALSTAT's quarterly
    balance of payments carries an "Activos de reserva" line, which is the
    *flow* over the quarter and not the *stock* this item wants. See
    `docs/sources.md` for the unblocking step and for both traps.

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
  balance-of-payments candidates this line named. The catalog holds 8 annual,
  11 monthly, 2 daily and 1 quarterly. **Weekly, semiannual and irregular remain
  unexercised** — `Frequency` defines all three and the period model parses
  `YYYY-Wnn` and `YYYY-Hn`, but no source REIM reads publishes at those
  cadences.

## v0.3.0 — Central America

This release is nine independent pieces, not one increment. Eight are done,
and the ninth — the national central banks — has its first country.

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
- ~~**CEPALSTAT central government public debt**~~ ✅ **done** — REIM's first
  fiscal data: **456 observations**, central government gross public debt for
  all seven countries, 1990–2025, in dollars and as a share of GDP, from two
  requests. The wider institutional coverages are not stored — only central
  government covers all seven countries — and the internal/external split is
  not stored either, because it does not sum to the total. See
  `docs/sources.md`.
- ~~**CEPALSTAT regional consumer price index**~~ ✅ **done** — REIM's first
  inflation data for more than one country: **3,451 observations**, all seven,
  monthly from 1980-01, from one request. It ends **2026-07**, which makes it
  REIM's freshest series by more than a year, and it lets `/compare` answer the
  most ordinary question anyone brings to a regional monitor.

  Three things measuring settled. CEPAL's declared base years **do not hold**
  for three of the five it declares — Guatemala's declared December 2010 reads
  56.69 — so REIM stores no base and records the month each series measurably
  passes 100 instead; levels are not comparable across countries, only
  movements. Guatemala's series is **spliced at 2010-01** without
  normalisation, a 42.6% fall that is a change of base. And Nicaragua now has
  **two official CPIs that disagree** by a median 4.2%: REIM reads INIDE, CEPAL
  cites the central bank. Both are stored. See `docs/sources.md`.

- ~~**Cross-country comparison endpoints**~~ ✅ **done** — `GET /api/v1/compare`
  takes one indicator and two to twenty countries and returns a **rectangular**
  matrix: every row carries an entry for every country asked for, `null` where
  that country publishes no figure, so a gap is stated rather than inferred.
  Comparability is declared, never enforced: the flag turns on unit and
  currency, differing publishers are noted, and the endpoint never refuses and
  never converts. See `docs/sources.md` and the API section of the README.
- ~~**Currency handling for genuinely multi-currency comparisons**~~ ✅ **done**
  — always alongside the original figure, never replacing it, in two pieces.
  The rate series first: CEPALSTAT's monthly nominal exchange rate, **2,749
  observations**, all seven countries, 1993-06 onward (Panama 1990-01, Costa
  Rica 1994-02), REIM's first indicator whose values are rates rather than
  amounts or ratios. Then `/compare?convert_to=USD`, which derives dollars **at
  request time** and writes nothing: each row gains `values_converted`, `rates`
  and `rate_basis` beside the published `values`, and omitting the parameter
  returns a payload with none of those keys.

  This reverses decision **C5** of the comparison-endpoint design, "no currency
  conversion, ever". That decision's premise was that REIM would have to author
  an exchange-rate choice; one publisher covering all seven countries on one
  method ended it. The replacement rule is narrower, not absent: REIM converts
  only with a single published series, only on an exact period match, only for
  indicators that declare themselves convertible, and only into a field beside
  the original.

  Three things the work had to settle. Conversion keys on **the observation's
  own currency, never on its country** — CEPAL still quotes El Salvador in
  colones twenty-four years after dollarisation, and keying on the country
  would divide its already-dollar figures by 8.8. The rate is a within-month
  average while the monetary series are end-of-period stocks, and CEPAL
  publishes no end-of-period alternative, so converted figures are labelled
  **indicative** rather than silently mismatched. And a missing rate is a gap:
  `null`, counted, never a neighbouring month's rate. See `docs/sources.md`
  and `docs/superpowers/specs/2026-09-06-currency-conversion-design.md`.
- ~~**CEPALSTAT interest rates**~~ ✅ **done** — REIM's **first interest-rate
  data of any kind** and the first use of the `financial` indicator category,
  unused since v0.1.0: **6,564 observations**, nominal lending rates, nominal
  deposit rates and monetary policy rates, monthly from 1990-01, from four
  requests. Until this landed REIM's monetary data was M1, M2 and M3, which say
  how much money exists and nothing about its price.

  Four things measuring settled. The annual and quarterly members of the period
  dimension are **means of their months**, not the period-end restatements the
  monetary family publishes — 693 of 693 quarters and 202 of 202 annual figures
  on the lending rate. REIM stores the twelve monthly members only: the same
  decision as the monetary connector, for the opposite reason, because storing
  a mean beside its own inputs would publish a derived figure as if it were
  published. **Panama's policy rate is absent by decision**: CEPAL publishes
  sixteen rows for it, every value zero, every one unattributed, all inside
  2022, for a dollarised country with no central bank; Nicaragua's two genuine
  2010 zeros, inside a real attributed series, **are** stored. **CEPAL defines
  each country's rate differently and says so** in its own
  `calculation_methodology` — Belize's "policy rate" is its central bank's
  lending rate — so `IndicatorDefinition` gained
  `methodology_varies_by_country` and `/compare` now states that levels are not
  comparable while movements are, without flipping `comparable` to false. And
  percentage change is **useless** on two of the three: a policy rate moving
  1.47 → 4.87 is +231% and 3.4 points, so `max_period_change_pct` is null there
  and a check measuring percentage *points* does the work.

  CEPAL's own defects are recorded rather than repaired: indicator 857
  attributes Costa Rica to the **Central Bank of Bolivia**, describes
  Guatemala's deposit rate as a lending rate, and indicator 856 declares zero
  decimals while publishing two in five cells out of six. See `docs/sources.md`.

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
