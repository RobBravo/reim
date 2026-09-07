# Currency handling for multi-currency comparisons — design

REIM's first derived figures: a converted view on `/compare` that puts a dollar
figure beside a córdoba one without ever replacing it, backed by a new monthly
exchange-rate series read from CEPALSTAT.

Every figure below was measured against the live API on 2026-09-06, not read
from documentation — CEPALSTAT publishes none.

## 1. The roadmap asks for something this repository forbids

`ROADMAP.md` closes v0.3.0 with "currency handling for genuinely multi-currency
comparisons — always alongside the original figure, never replacing it."

Two other documents forbid exactly that:

* `docs/superpowers/specs/2026-08-08-comparison-endpoint-design.md`, decision
  **C5**: "**No currency conversion, ever.** It would require exchange rates and
  would publish figures no official source published."
* `docs/sources.md` on the monetary aggregates: "REIM performs no conversion —
  doing so would make REIM the author of an exchange-rate choice it has no basis
  to make."

C5's premise was that conversion requires a rate REIM would have to choose. That
premise held while REIM's only rates were Nicaragua's and Guatemala's — two of
the four non-dollar countries, on two different national methodologies. It stops
holding once one publisher covers all seven on one method, which section 2
establishes is the case.

**This document supersedes C5.** The reasoning it replaces C5 with is narrower
than "conversion is fine": REIM converts only with a single published series,
only where an exact period matches, only when the indicator declares itself
convertible, and only into a field that sits beside the original. Every one of
those constraints exists to keep REIM from authoring a number, and section 5
records each as a decision. `docs/sources.md`'s sentence is amended in the same
increment rather than left to contradict the code.

## 2. The source

| | |
|---|---|
| **Organization** | Comisión Económica para América Latina y el Caribe (`CEPAL`) |
| **Endpoint** | `GET /cepalstat/api/v1/indicator/2179/data?lang=en` |
| **Auth** | None |
| **Requests** | Two — data (1.19 MB, 1.8–4.7 s) and `dimensions?lang=es` (28 KB, 1.2 s) |
| **Rows returned** | 11,496, covering 30 countries |
| **Rows for the seven** | 2,749 |
| **Frequency** | Monthly |
| **Licence** | ⚠️ **Not open** — CEPAL's terms, already quoted in the GDP section of `docs/sources.md` |

Published metadata, read from `body.metadata`:

| Field | Value |
|---|---|
| `indicator_name` | Nominal exchange rate |
| `area` | Exchange indicators |
| `unit` | `National currency by USA dolar` (CEPAL's own spelling) |
| `calculation_methodology` | `Daily exchange rate, monthly average` |
| `data_features` | `Source Bloomberg` |
| `decimals` | 2 |
| `last_update` | Aug 31 2026 12:22PM |

Three dimensions: country (208), **months (515, twelve members)** and years
(29117). That is the monetary aggregates' shape exactly — a period-within-year
dimension over the country-by-year matrix — so the second request for
`dimensions?lang=es` is needed for the same reason and nothing from it is
stored: the English response names months only in the untranslated
`descripcion_ingles`, and the member ids are not in calendar order.

### Coverage, verified per country

| Country | Rate span | Months | Gaps |
|---|---|---|---|
| Panama | 1990-01 … 2025-09 | 429 | none |
| Costa Rica | 1994-02 … 2025-09 | 380 | none |
| Belize, El Salvador, Guatemala, Honduras, Nicaragua | 1993-06 … 2025-09 | 388 each | none |

No cell is null or empty, every row cites `source_id` 424, and no row carries a
footnote.

## 3. What measuring established

### 3.1 El Salvador is still quoted in a currency it retired in 2001

CEPAL publishes El Salvador at **8.7–8.8 colones per dollar through 2025**,
twenty-four years after dollarisation. This is the colón's fixed legal
conversion rate, which CEPAL never stopped publishing.

REIM stores El Salvador's M1 and M2 with `currency_code = "USD"`, taken from the
country registry. A conversion keyed on the **country** would find 8.8 and
divide El Salvador's already-dollar figures by it, understating them ninefold —
silently, with no error and no null to notice.

The rule in decision D3 defuses this: conversion is keyed on **the observation's
own `currency_code`**. El Salvador's rows are already at the target and pass
through untouched. The 8.8 is stored, and never applies to anything, because
REIM holds no observation denominated in `SVC`.

This also settles the rate series' own unit. Taking it from the country registry
would label El Salvador's rate `USD per USD`, which is nonsense. The connector
carries its own seven-entry table of the currency each rate *quotes* — `NIO`,
`GTQ`, `HNL`, `CRC`, `SVC`, `PAB`, `BZD` — which is not the same question the
registry answers.

### 3.2 A monthly average against an end-of-period stock

`calculation_methodology` is `Daily exchange rate, monthly average`. M1, M2 and
M3 are **end-of-period** stocks — `docs/sources.md` records them as such.
Converting a month-end stock at that month's average rate is a real mismatch,
and it is the largest methodological caveat in this design.

**A single-publisher fix was looked for and does not exist.** CEPALSTAT's
thematic tree was searched on 2026-09-06 under both themes that could hold one —
`BADECON` (theme 6) and `COYUNTURA` (theme 24). They return exactly two
exchange-rate indicators between them: 2179, the monthly average read here, and
1901, the real effective exchange rate, which measures something else entirely.
**CEPAL publishes no end-of-period nominal rate.**

REIM will not derive one either: taking the last daily observation from BCN or
Banguat for two countries and CEPAL's average for the other five is precisely
the mixed-method authorship section 1 rules out.

So the mismatch cannot be fixed, and the design's job is to stop it from being
read as something it is not. Three measures, all in decision D11:

1. Every converted cell is accompanied by `rate_basis`, whose only value today
   is `"monthly average"`. It is a field rather than a sentence in the docs
   because a client charting `values_converted` will never read the docs, and a
   field travels with the number.
2. The `conversion` block states in words that the target series are
   end-of-period stocks converted at a within-period average, and that the
   converted figures are therefore **indicative**.
3. The same statement goes in the indicator description and in
   `docs/sources.md`.

The alternative — refusing to convert stocks at all — was considered and
rejected: M1, M2 and M3 are the only multi-currency series REIM holds, so it
would leave increment B with no case at all. Converting them with a stated
basis is more useful than converting nothing, and more honest than converting
silently.

### 3.3 The payload contradicts itself about provenance

`data_features` says `Source Bloomberg`. The `sources` array says
`On the basis of official figures.` One is a commercial vendor and the other is
a claim of officialdom; they are in the same response.

REIM's position is unchanged by this — it stores what a named publisher
published, with the terms recorded — but it will not repeat CEPAL's "official
figures" claim for this series. The indicator description says ECLAC publishes
it and that the payload names Bloomberg as the underlying source, so a reader
weighing the rate against a central bank's own daily rate knows they are not the
same kind of figure.

### 3.4 Declared two decimals, published one

`decimals` is 2. Across the 2,749 rows for the seven countries, **1,813 carry
one decimal and 936 carry none. None carries two.**

So `GTQ 7.8` is two significant figures, and a converted quetzal figure inherits
up to ~0.6% of rounding error from the rate alone. This is the same class of
discrepancy the monetary connector already documented between declared and
published decimals, and it is handled the same way: measured, stated, and
carried in the `conversion` block rather than implied away by digit count.

### 3.5 What actually converts

Against the 5,383 stored monetary observations:

| | Observations | |
|---|---:|---|
| Converted at a published rate | **4,755** | of which Panama's 780 convert at a published rate of exactly 1 |
| Already at the target | 546 | El Salvador's M1 and M2, `currency_code = USD` |
| No rate for the period | 82 | Belize M1 and M3, 1990-01 … 1993-05 |
| **Total** | **5,383** | |

Belize's 82 cells are the whole of the coverage gap. Its peg is 2:1 and it is
published as 2 from 1993-06 onward, so supplying it for the earlier 41 months
would be nearly certainly right — and would be REIM inventing a figure its
publisher did not publish. They stay null, and the `conversion` block counts
them.

Every other country's monetary series begins at 2001-12 or later, comfortably
inside the rate's span, and the rate runs to 2025-09 against a monetary series
ending 2024-08.

## 4. Two increments, one design

The decisions interlock — 3.1 is only safe if the connector and the conversion
layer agree on it — so this is one spec and **two implementation plans**, merged
separately:

* **A.** `cepalstat_exchange_rate_monthly`: the connector and one indicator.
  Rates become ordinary REIM observations with full provenance, useful on their
  own whatever happens to B.
* **B.** `?convert_to=USD` on `/compare`. Cannot be built until A's data exists.

## 5. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Supersede C5. Conversion is permitted under D2–D8 and nowhere else. | C5's premise — that REIM would have to choose a rate — stops holding when one publisher covers all seven on one method. |
| D2 | Computed at request time. **No derived row is ever written to `observations`.** | The observation store stays a record of what publishers published. A derived figure that can be persisted is a derived figure that can be mistaken for a source's. |
| D3 | Keyed on the observation's `currency_code`, never on its country. | Defuses 3.1. An observation already in USD passes through at an implied rate of 1. |
| D4 | `convert_to` accepts `USD` only. | Rates are local-currency-per-USD. NIO→GTQ means triangulating through the dollar and squaring the rounding error of 3.4 for a comparison nobody has asked for. |
| D5 | The indicator must declare `currency_convertible`. | `ni_exchange_rate_official_daily` carries `currency_code = NIO` and means "36.8 NIO **per** USD". Dividing it by a rate returns a confident `1.00`. An amount denominated in a currency and a ratio expressed per that currency are different things and only the registry can tell them apart. |
| D6 | Both gate failures return **422**, naming the reason. | Silently ignoring a parameter the client asked for is worse than refusing it. |
| D7 | Exact period match only. No nearest rate, no carry-forward, no annual average standing in for a month. | That is imputation, which `ROADMAP.md` lists under "explicitly not planned". A missing rate yields `null` and a count. |
| D8 | `comparable` keeps describing the **published** figures and is unaffected by conversion. | Flipping it to `true` because a derived view exists would tell a client that CEPAL published comparable data. |
| D9 | Per-cell rates are returned alongside per-cell converted values. | Every derived figure must be recomputable by hand from the response alone. Provenance that requires a second request is not provenance. |
| D10 | Converted values quantize to two decimal places. | An amount, by convention. The real precision limit is the rate's one decimal, stated once in `conversion` rather than implied by twenty digits of `Decimal` division. |
| D11 | Every converted cell carries `rate_basis`, and `conversion` calls the figures **indicative**. | The rate is a within-period average and the target series are end-of-period stocks (§3.2). No single-publisher end-of-period rate exists, so the mismatch is permanent; a field that travels with the number is what stops it being read as an exact conversion. |

## 6. Components

### 6.1 `reim/domain/indicators/registry.py`

`IndicatorDefinition` gains one field, defaulted so no existing entry changes:

```text
currency_convertible: bool = False
```

Set `True` on `money_m1_monthly`, `money_m2_monthly` and `money_m3_monthly`, and
on nothing else. Their descriptions lose the clause "without a conversion REIM
does not perform", which stops being true in increment B.

One new indicator:

| Code | Name | Frequency | Unit | Value type |
|---|---|---|---|---|
| `exchange_rate_nominal_monthly` | Nominal exchange rate (monthly average) | `MONTHLY` | `units of local currency per USD` | `LEVEL` |

Its description states 3.2 and 3.3: a monthly average of daily rates, published
by ECLAC, with Bloomberg named in the payload as the underlying source, and El
Salvador quoted in a currency retired in 2001.

### 6.2 `sources/catalog.yml`

One entry, `cepalstat_exchange_rate_monthly`, on the established CEPALSTAT
shape: same `base_url`, same organization, same non-open licence text as the GDP
and monetary entries.

### 6.3 `reim/ingestion/connectors/regional/cepalstat_exchange_rate.py`

Subclasses `CepalstatConnector` for the envelope, decode and member table.
Its own `extract` (two requests), `transform` (country × year × month, unit and
`currency_code` from the connector-local table of 3.1) and `validate`.

Values are stored as published — no scaling. Unlike the monetary family there is
no `× 10^6`.

### 6.4 `reim/domain/conversion.py` (new)

Pure functions over cells, summaries and a rate table: the D3–D7 gates and the
arithmetic, with no database and no session. This is where the El Salvador rule
and the exact-period rule are tested directly.

Kept out of `reim/schemas/comparison.py`, which already holds
`assess_comparability`, and out of `reim/repositories/comparison.py`, which is
where the rate fetch goes and is already at 214 lines.

### 6.5 `apps/api/routers/comparison.py` and `reim/schemas/comparison.py`

`convert_to: Literal["USD"] | None = None` on the query. When set and the gates
pass, each `ComparisonRow` gains `values_converted`, `rates` and `rate_basis`,
all keyed by ISO-3 like `values`, and the response gains a `conversion` block:
target currency, rate indicator code, rate source key, the 3.2 and 3.4 caveats
in words, the word **indicative** applied to the figures, and counts of
converted / already-at-target / no-rate cells.

`rate_basis` is `"monthly average"` wherever a rate was applied and `null`
wherever one was not — including El Salvador's pass-throughs, which had no rate
applied and so have no basis to report.

When `convert_to` is absent the response is byte-identical to today's.

## 7. Quality

Three connector checks on the rate series, following the monetary family's
pattern:

| Check | Severity | What it catches |
|---|---|---|
| `cepalstat_fx_expected_countries` | `critical` | A country dropping out of the rate matrix, keyed per series rather than pooled |
| `cepalstat_monthly_continuity` | `warning` | A hole inside one country's own span |
| `cepalstat_fx_pegs_hold` | `error` | Panama or Belize more than 10% off their peg in any month from 1993-06 |

The third is worth its own check because both pegs are legal facts rather than
market outcomes: a value drifting off them means the matrix has been misread —
a dimension mis-keyed, a country column shifted — far more probably than that
Panama has floated the balboa.

**It is a band, not an equality, and the data is why.** Measured on the
recording: Panama is exactly 1 in all 429 months, but Belize is **1.9 in ten of
its 388** — October 2009 and October 2012. Belize's dollar has been pegged at
2:1 since 1976 and has never moved, so those tens are not a currency event.
They are §3.4 and §3.3 compounding: a Bloomberg market quote that wandered a
fraction below the official parity, averaged over the month, then rounded to
the one decimal CEPAL publishes. 1.9 against 2 is exactly 5%, so the band is
10% — twice the largest artefact, and still far tighter than any real
misreading, since the next smallest rate in the matrix is Guatemala's ~7.7,
some 285% off Belize's peg.

This is also the sharpest evidence for §3.3. A series carrying the official
parity would read 2 in every month; one carrying a market quote does not. What
CEPAL's `sources` array calls "official figures" behaves like what its
`data_features` calls Bloomberg.

The continuity check is **not** reusable as it stands: it is
`_check_monthly_continuity`, a private method on the monetary connector. Its
body is entirely about periods and country-series and knows nothing about
monetary aggregates, so this increment lifts it to `CepalstatConnector` rather
than copying it. That widens the base class's stated scope, whose docstring
currently claims it holds "the protocol — and nothing about any indicator
family's shape"; the docstring is amended in the same commit to admit a second
category of shared behaviour that is about periods rather than families.

`min_value: 0` for all seven, inclusive — the schema has no exclusive bound.
A tighter `min_value: 1` would fit every rate in the series, whose minimum is
Panama's 1, but `docs/sources.md` already records `min_value: 1` as a past
mistake on the Nicaraguan rate, and repeating the shape of a documented error
to buy a bound nothing needs is not worth it. `max_value` stays null: Costa
Rica is already past 500 colones and rising.

## 8. Testing

Recordings for both requests, as every CEPALSTAT connector already does.

Connector: the two-request extract, the month-name resolution from the Spanish
dimensions, the seven-entry currency table producing `SVC` for El Salvador, and
each of the three checks passing and failing.

Conversion, as pure unit tests with no database:

* El Salvador passes through untouched at an implied rate of 1 — the regression
  test for 3.1, and the one that would have caught the ninefold error.
* A period with no rate yields `null`, not a neighbouring month's rate.
* A non-convertible indicator returns 422; `ni_exchange_rate_official_daily`
  named explicitly, since it is the trap D5 exists for.
* `convert_to=EUR` returns 422.
* The arithmetic, including D10's quantization.

One integration test through the real writer, database and endpoint, following
the pattern the existing `comparable: false` test established: two countries,
one indicator, differing currencies, converted and unconverted responses
compared.

## 9. Volume

Increment A adds **2,749 observations** — the seven countries' rows, from two
requests and about 6 s. REIM's catalog gains its eighth monthly series and its
first indicator whose values are rates rather than amounts or ratios.

Increment B adds no observations at all.

## 10. Out of scope

* **Storing converted figures.** See D2. If a converted series is ever wanted as
  data rather than as a view, it is a new increment with its own provenance
  design, not a flag on this one.
* **Any target but USD**, and any cross-rate — D4.
* **End-of-period rates**, whether published or derived from BCN and Banguat
  dailies — 3.2. CEPAL publishes none, verified across both candidate themes;
  if one ever appears, using it for stocks is a single-publisher change and
  needs no new argument, only a new increment.
* **Conversion on `/observations` or the CSV export.** `/observations` returns
  what the publisher published, unconditionally; keeping one endpoint with no
  derived mode is worth more than the reach.
* **Real effective exchange rates.** CEPALSTAT indicator 1901 exists and is a
  different concept measuring a different thing.
* **Filling Belize's 82 pre-1993 cells from its peg** — 3.5.
