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
    (indicator 547) **is now read**, and it does **not** close this gap:
    `bop_current_transfers_credit_quarterly` is the whole current-transfers
    account, official transfers included, and none of the 66 item members breaks
    personal remittances out. Reading it did establish where a partial answer
    might come from — items 1298 and 1303, *employees compensation*, are one
    half of the World Bank's definition and are measured but unstored. SECMCA,
    behind a credentialed account, remains the only route to the whole concept
    named so far. See `docs/sources.md`.
  - **reserves** — the IMF has 1,740 monthly observations, but its indicator
    codes cannot be named from anything its API exposes. CEPALSTAT's quarterly
    balance of payments **is now read**, and it does **not** close this gap
    either: `bop_reserve_assets_quarterly` is the *flow* over the quarter and
    not the *stock* this item wants. The 784 observations are stored and the
    warning is in the indicator's own description. See `docs/sources.md` for
    the unblocking step and for both traps.

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
  by SIECA's services trade in v0.3.0 — and, since 2026-09-09, by CEPALSTAT's
  quarterly balance of payments, which is one of the two IMF
  balance-of-payments candidates this line named arriving by a third route. The
  catalog holds 8 annual, 11 monthly, 2 daily and 2 quarterly. **Weekly,
  semiannual and irregular remain unexercised** — `Frequency` defines all three and the period model parses
  `YYYY-Wnn` and `YYYY-Hn`, but no source REIM reads publishes at those
  cadences.

## v0.3.0 — Central America

This release is ten independent pieces, not one increment. Nine are done,
and the tenth — the national central banks — has its first country.

- ~~**Regional merchandise trade**~~ ✅ **done** — REIM's first data for more
  than one country: 7,848 monthly observations for Nicaragua, Guatemala, El
  Salvador, Honduras, Costa Rica and Panama, from the IMF's IMTS dataflow, all
  six with identical coverage back to 1990-01. **Belize is excluded**: it
  reports nothing to that dataflow at any frequency. See `docs/sources.md`.
- Connectors for the **national central banks**. This line said six independent
  investigations; there are **five**, because Panama is dollarised and has no
  central bank — INEC, listed here until 2026-09-11, is its statistics
  institute.
  **Banguat is done** ✅ — 26,730 observations, a buy and a sell rate for every
  day since 1990-01-01, the whole history in one request. The other four were
  probed and their state recorded in `docs/sources.md`: BCCR answers `503` and
  is known to need an account; BCR, BCH and the Central Bank of Belize are
  reachable but expose no machine-readable endpoint that could be found. None
  is behind a bot wall.

  **INEC was probed on 2026-09-11 and does have an open API** — recovered from
  its map application's own JavaScript, with a 218-variable catalogue that
  needs no authentication. It is not ingested because it carries **one
  reference year, not a series**: `anio=2023` returns data and 2022 returns
  nothing. Its value is subnational, which is a v0.6.0 concern, and the routes
  and parameters are recorded so that increment starts from a measurement. See
  `docs/sources.md`.
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
- ~~**CEPALSTAT quarterly balance of payments**~~ ✅ **done** — REIM's **first
  balance-of-payments data of any kind** and its **second quarterly source**:
  **19,582 observations** across 25 indicators, all seven countries, quarterly
  from 1993-Q1, from one request. Until this landed REIM's external sector was
  merchandise trade and annual remittances — it could say what a country sold
  abroad and nothing about how it paid for what it bought. It now holds the
  current, capital and financial accounts, four sub-balances and fifteen
  components. Four countries reach **2026-Q1**, and **not one of the seven has
  an interior gap**, which no other family REIM reads can say.

  Four things measuring settled. The metadata **contradicts itself about the
  IMF manual**: `calculation_methodology` declares the fifth edition while
  footnote 10138 cites the sixth on every row of six countries — all but
  Guatemala, a split by country and not by year. It is recorded and
  `methodology_varies_by_country` is **deliberately not declared**, because
  BPM6's reversal of the financial-account sign convention is measurably absent:
  averaging the financial account over every current-account deficit quarter
  gives Guatemala **+345.0** against a range of +34.3 to +677.0 for the other
  six. The labels disagree; the figures do not. **Four accounting identities
  hold** — 781/781, 784/784, 784/784, and 782/784 with Panama's 2004-Q3 and
  2021-Q4 allow-listed by name — and `V + VI = 0` holds in 773 of 784, every
  failure El Salvador from 2023-Q1. **There is no server-side filtering**:
  `?members=` answers 500 while `?dim_208=` and `?filters=` answer 200 with the
  full 20.3 MB and ignore the parameter, which is the more dangerous of the two
  failures. And **Honduras stops publishing one of the twenty-five in 2023-Q4**,
  so `freshness` warns at 984 days against 550 on every run, reported rather
  than accommodated.

  CEPAL declares **zero decimals and publishes up to twenty-two**, the worst of
  three CEPALSTAT families whose declared precision contradicts its payload —
  Panama 1998-Q3 carries `8.881784e-16`, which is 2⁻⁵⁰ and a float64 residue
  where the publisher meant zero. Values are stored exactly as published,
  that one included. **25 of the 55 items with data are
  stored** and the other 30 are named in `docs/sources.md` so a later increment
  starts from a measurement. See `docs/sources.md`.

## v0.4.0 — Making the data visible

- ~~**Make `methodology_varies_by_country` machine-readable.**~~ ✅ **done** —
  the flag existed on every indicator and three declared it, but it was read
  in exactly one place — `assess_comparability` — and reached a client only as
  free text inside `comparability_notes`, nowhere in the indicator schema
  itself. `IndicatorRead` now carries the flag directly, alongside
  `currency_convertible` (the other registry flag a client could not
  discover), and `/compare` carries a structured `levels_comparable` beside
  `comparable` rather than instead of it — `comparable` keeps turning on unit
  and currency, so no existing caller changes meaning. Flipping it was
  rejected in decision D6 of the interest-rates design for that reason.
- ~~**Web dashboard**~~ ✅ **done** — `/series`, REIM's third web page: one
  indicator plotted over time across up to seven countries, chosen from an
  ordinary `<form method="get">` with no JavaScript at all. The chart is
  server-rendered SVG, not a library or a CDN script: every earlier decision
  about this project — no dependency, no build step, self-hostable on a
  restricted network — would have been reopened by shipping a vendored
  charting blob for one page. Two lines share an axis only when both
  `comparable` and `levels_comparable` hold; either flag failing (differing
  units or currencies, or a publisher measuring a different instrument per
  country, as CEPAL's interest rates do) draws small multiples instead, one
  independently-scaled panel per country, so a shared axis never implies a
  comparison the data cannot support. A country whose own series crosses a
  unit change is named in the table but not drawn at all — its own axis
  cannot rescue a line that lies within a single country. A missing period
  breaks the line rather than bridging it, the same "never fill a gap"
  promise the ingestion layer already keeps, now also a drawing rule. Nothing
  is downsampled; instead a request denser than 1,500 periods is refused with
  a sentence naming the count and asking for narrower dates — a cap that
  bites only the two daily exchange-rate sources, since 1,500 points is four
  years of daily data but 125 years of monthly and 375 of quarterly.
- ~~**Data catalog browser**~~ ✅ **done** — REIM's **first web page**: what
  REIM holds, how fresh it is, and what is disabled and why, server-rendered
  beside the API rather than as a separate application. All 23 sources, their
  organization, frequency, indicators and licence; the three publishers whose
  terms forbid redistribution marked as such; freshness per source from the
  same pipeline-run history `/api/v1/pipelines` exposes; and an explicit "no
  source is disabled" rather than a silently empty section, since nothing is
  disabled today. Views call services and repositories directly, never the
  application's own API — a rule now pinned by a guard test, since nothing
  else would have caught a later page getting that wrong. The one-stylesheet,
  Jinja2-templates, no-build skeleton this introduced is what the dashboard
  and observability pages below reuse.
- ~~**Pipeline observability page**~~ ✅ **done** — two more server-rendered
  pages beside the catalog: `/runs`, the last 100 pipeline runs (roughly four
  sweeps of the 23 pipelines; deeper history is the paginated API's job), and
  `/runs/{run_id}`, one run's counters, metadata and every quality check it
  recorded. `/runs` also carries a failed-check trends block over the last 30
  days — wider than `SystemStatus`'s seven, because these series are ingested
  infrequently and a block that is always empty stops being read. Seven empty
  states across the two pages, each distinct because they call for different
  responses: the run history's database unreachable, no run has happened yet,
  no run in the trends window, no failures in the trends window, a run with
  no checks recorded, an unknown or malformed run id (which renders as HTML
  with status 404 rather than the API's JSON error envelope, left untouched
  for API clients), and the run-detail page's own database unreachable state.
  Staleness stayed on the catalog page rather than repeating it
  here — this page is about history, not freshness. The one backend addition
  is `summarize_failed_checks_by_name`, which groups failures by check name
  in SQL rather than in Python, so a check failing more often than a query's
  row cap is not undercounted.

## v0.5.0 — Operations

- ~~**API keys and rate limiting**~~ ✅ **done** — a key raises a caller's
  allowance rather than gating access, because REIM publishes open data and
  invites redistribution: gating it would contradict what the platform is
  for. Anonymous requests keep working, at 60 per minute by default; a key
  raises that to 600. Counters are kept in memory rather than in the
  database, since the shipped deployment is a single uvicorn worker and that
  makes the count exact — a worker count above one would multiply the
  effective limit by that count, an explicit caveat rather than a hidden one.
  Identity is the socket peer unless `REIM_TRUSTED_PROXY_HOPS` opts in,
  because trusting `X-Forwarded-For` by default builds a limiter any client
  bypasses by setting a header. Keys are minted from `reim key
  create|list|revoke`, never over HTTP, since the API stays read-only by
  decision D13. The README's "put a gateway in front" advice is retired.
- ~~**Alerting**~~ ✅ **done** — four conditions: pipelines stale by their
  indicator age thresholds, runs that failed mid-pipeline, runs stuck in
  `running` state longer than a configured window (visibility into killed
  ingestion processes), and data quality regressions. Evaluation runs as a
  cron'd CLI command because staleness is invisible from inside an active run
  and only the metrics snapshot sees it; staleness policy stays in
  `sources/quality_rules.yml` where it is tuned. A state table reconciles each
  run's alerts against open history, emitting ~21 messages over a three-week
  outage rather than 500: one notice per distinct condition and pipeline when
  it first fires, silence for a configurable repeat interval, and exactly one
  "resolved" notice when it clears. State is recorded only after a successful
  webhook delivery, so transient HTTP failures cost repetition rather than a
  lost alert.
- ~~**Scheduler integration**~~ ✅ **done** — `pipeline schedule` reads the
  catalog and prints an installable crontab fragment, one line per cadence in
  use plus the alert check, rather than implementing a scheduler: the
  operator's cron stays the scheduler, as this document has said since the
  MVP. Cadences come from the catalog instead of a single blanket cron line,
  so the two daily exchange-rate sources stop waiting on a monthly sweep and
  the eight annual series stop being fetched twelve times a year. The emitter
  rewrites only each cadence's minute field, staggering cadences that would
  otherwise all start at 13:00 from `DEFAULT_CRON_BY_FREQUENCY` and collide.
  `PipelineScheduler` remains an unimplemented seam, deliberately: this gives
  cron something correct to run, not a runtime that replaces it.
- ~~**Prometheus metrics**~~ ✅ **done** — `/metrics` now exports per-pipeline
  volumes, run durations and freshness gauges alongside `reim_database_up`,
  one series per catalog entry, on top of the process-level defaults it
  already carried. Every figure is derived from `pipeline_runs` at scrape
  time rather than kept as an in-process counter: ingestion runs in a CLI
  process that has exited long before any scrape arrives, so a counter kept
  there would never be visible to the process answering Prometheus, and a
  Pushgateway that would fix that is infrastructure this project does not
  take on. Data age and its threshold ship as two separate gauges rather than
  a single `is_stale` boolean, so the staleness policy stays where it is
  tuned — `sources/quality_rules.yml` — instead of being re-encoded a second
  time in the exporter. Reading them costs six grouped queries per scrape,
  replacing the 115 round trips `build_pipeline_summaries` costs for the same
  catalog: right for an occasional JSON request, wrong at a 15-second scrape
  interval. A database outage still answers `reim_database_up 0` at status
  200 rather than a failed scrape, because the scrape that matters most is
  the one taken during the outage.
- ~~**Public deployment guide with hardening notes**~~ ✅ **done** — the
  deployment ships as files under `deploy/` rather than as prose, because a
  file can be started and measured and a fenced code block cannot;
  `docs/deployment.md` was written while standing that stack up under Podman.
  Caddy terminates TLS and writes `X-Forwarded-For`, which is what makes
  `REIM_TRUSTED_PROXY_HOPS=1` correct; `/metrics` is closed at the proxy
  rather than left to the application; and the rate limit counts requests,
  not bytes, so `/api/v1/observations/export.csv`'s row cap is a separate
  concern the guide states plainly.

## v0.6.0 — Context

Economic figures become far more useful next to what happened around them.

- **Economic news ingestion** from official communiqués and press releases —
  central bank statements, ministry announcements — with the same provenance
  discipline applied to text.
- **Event correlation**: link a datapoint to publications and policy events in
  its period. Correlation surfaced as *context*, never asserted as causation.
- **Geospatial data** where it exists at subnational resolution. One route is
  already measured: **INEC Panama** serves 218 variables — 25 of them economic
  — at provincial and district level through an open, unauthenticated API,
  recovered from its map application's JavaScript on 2026-09-11. It carries a
  single reference year rather than a series, which is why it is not in v0.3.0;
  for this line that matters far less. `docs/sources.md` records the base URL,
  the routes and the two parameter traps that cost the probing most of its
  time.

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
