# CEPALSTAT regional consumer price index — design

REIM's first inflation data for more than one country: a monthly consumer price
index for the seven Central American countries, from 1980, in one request.

Every figure below was measured against the live API on 2026-09-06, not read
from documentation — CEPALSTAT publishes none.

## 1. What REIM already has, and what this adds

REIM holds a consumer price index for **Nicaragua only**, read from INIDE at
monthly resolution: `ni_cpi_index_monthly` plus month-on-month and
year-on-year rates, and the same three again for Managua and the rest of the
country. Nothing for the other six.

`/compare` therefore cannot answer the most ordinary question anyone brings to
a regional economic monitor — how does inflation here compare with next door.
This increment makes it answerable.

It also gives REIM a second Nicaraguan CPI, from a different publisher, that
disagrees with the first. Section 3.5 measures that disagreement and section 4
decides what to do about it.

## 2. The source

| | |
|---|---|
| **Organization** | Comisión Económica para América Latina y el Caribe (`CEPAL`) |
| **Host** | `https://api-cepalstat.cepal.org` |
| **Endpoint** | `GET /cepalstat/api/v1/indicator/365/data?lang=en` — one request |
| **Auth** | None |
| **Volume** | 2.02 MB, 11–19 s |
| **Rows returned** | 16,913, covering 40 countries |
| **Rows for the seven** | 3,451 |
| **Frequency** | Monthly |
| **Licence** | ⚠️ **Not open** — CEPAL's terms, already recorded in the GDP section |

Published metadata, from `body.metadata`:

| Field | Value |
|---|---|
| `indicator_name` | Consumer price index |
| `area` | Monthly |
| `unit` | `Index` |
| `data_features` | `Official country figures` |
| `decimals` | 2 |
| `last_update` | Aug 31 2026 11:13AM |

Three dimensions — country (208), months (515) and years (29117) — which is
the exchange-rate connector's shape exactly, **including that dimension 515
arrives translated in the English data response**. One request is enough; see
the correction recorded in `docs/sources.md` for why that is worth stating.

Unlike every other CEPALSTAT family REIM reads, `data_features` names no
vendor: each row cites its own national compiler through `source_id` —
`CBN` for Nicaragua, `INEC` for Costa Rica and Panama, `NSI` for Guatemala,
`CBH` for Honduras, `RBC` for El Salvador, `SIB` for Belize.

### Coverage, verified per country

| Country | Span | Months | Interior gaps |
|---|---|---|---|
| Costa Rica, Guatemala, Nicaragua, Panama, El Salvador | 1980-01 … 2026-07 | 559 | none |
| Honduras | 1994-01 … 2026-07 | 391 | none |
| Belize | 1990-11 … 2026-06 | 266 | **162 months, in 81 runs** |

**This is REIM's freshest series.** It ends 2026-07, five weeks before this was
written, against 2025-09 for the exchange rate and 2024-08 for the monetary
aggregates.

## 3. What measuring established

### 3.1 CEPAL's declared base years are wrong for three of the five it declares

`body.metadata.comments` carries a base year per country. Checking whether that
period actually reads 100:

| Country | Declared | Reads | |
|---|---|---|---|
| El Salvador | December 2009 | 100 | ✅ |
| Nicaragua | 2006 | 100.0000 (annual mean) | ✅ |
| Costa Rica | June 2015 | **93.40** | ❌ |
| Guatemala | December 2010 | **56.69** | ❌ |
| Honduras | December 1999 | **21.55** | ❌ |
| Panama | *not declared* | — | |
| Belize | *not declared* | — | |

So `comments` cannot be repeated as fact. **REIM does not store a base year and
does not put one in the unit.** `ni_cpi_index_monthly` carries
`index (2006=100)` because INIDE states its base and it holds; this indicator
carries `index` and nothing more.

What REIM records instead is measured: the month each series actually passes
through 100.

| BLZ | CRI | GTM | HND | NIC | PAN | SLV |
|---|---|---|---|---|---|---|
| 2017-02 | 2020-02 | 2024-04 | 2025-11 | 2006-05 | 2013-05 | 2008-11 |

This table goes in `docs/sources.md`, described as measured rather than
published, so a reader comparing levels across countries can see immediately
that they are on seven different bases and must not be read against each other.

### 3.2 Guatemala's series is spliced at 2010-01 and CEPAL does not say so

| 2009-11 | 2009-12 | 2010-01 | 2010-02 |
|---|---|---|---|
| 94.929 | 94.882 | **54.4831537** | 54.71901151 |

A 42.58% fall in one month, with the series continuing smoothly on either side.
That is a change of base spliced in without normalisation, not deflation. It is
Guatemala's **only** move beyond ±15% in forty-six years.

Anything computing inflation across January 2010 for Guatemala gets a
meaningless answer. REIM stores the series exactly as published — the figures
are what CEPAL publishes — and records the break here, in the indicator
description, and in a quality check that pins it.

### 3.3 El Salvador has one corrupt cell, which is a different thing

| 1985-06 | 1985-07 | 1985-08 | 1985-09 | 1985-10 |
|---|---|---|---|---|
| 11.229 | 11.473 | **7.157** | 11.928 | 12.227 |

August 1985 falls 37.6% and September rises 66.7%, which reads like two large
moves and is not. September over July is **1.0397** — an unremarkable two-month
rise. August is a single bad value that the series steps around.

It matters that this is distinguished from 3.2: Guatemala's is a permanent
level shift, El Salvador's is one cell. REIM stores both as published and
pins both, but describing them as the same kind of event would be wrong.

### 3.4 Nicaragua's 1980s are real, and they are enormous

Nicaragua carries **58 month-on-month moves beyond ±15%**, all between 1981 and
1991, and **104 values in scientific notation**, the smallest `2E-9`. This is
the hyperinflation and the two córdoba redenominations, seen through an index
rebased to a period twenty years later.

`docs/sources.md` already records the same phenomenon on the World Bank
exchange rate — "pre-1991 figures down to ~2e-9 NIO per USD" — and the same
conclusion applies: the figures are real, and `Decimal` holds them exactly.

The consequence is a quality rule. Nicaragua's worst month is **+261.15%** at
1991-03; from 1992 onward its worst is **+9.28%**. No single
`max_period_change_pct` serves both: a threshold that tolerates 261% detects
nothing anywhere, and one that catches Guatemala's splice rejects real
Nicaraguan history. **The rule is therefore `null`, and the connector carries a
check instead** — see section 6.

### 3.5 Nicaragua's two consumer price indices disagree by about 4%

REIM stores INIDE's index; CEPAL cites the **Banco Central de Nicaragua**.
Both declare base 2006, and 2006 reads 100 in both. Across the **198 months
they share** (2007-01 … 2026-06):

* **Not one month agrees to the digit.** Median difference 4.21%.
* The ratio CEPAL ÷ INIDE runs **1.02426 to 1.04758** — a spread of 2.3%.
* Year-on-year inflation differs by more than 0.5 percentage points in only
  **15 of 198 months**.

So the two tell substantially the same inflation story at different levels.
That is the signature of a rebasing difference between two official compilers,
not of a data disagreement, and it is what section 4's D3 turns on.

### 3.6 Declared two decimals, published up to eight

`decimals` is 2. Across the 3,451 rows for the seven:

| decimals | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| rows | 86 | 87 | 658 | 1,085 | 239 | 19 | 101 | 466 | 710 |

More precision than declared, not less — the opposite of the exchange rate's
case, where CEPAL declared two and published one. Both are stored exactly as
published; neither is rounded to the declared figure.

### 3.7 The freshest rows are the least attributed

`source_id` is **null on 52 rows per country** (51 for Costa Rica), and they are
the most recent: 2022 through 2026. Older rows all cite a national compiler.

REIM stores `cepalstat_source` as the empty string for those rows rather than
inventing an attribution, and this is recorded so nobody reads the gap as a
parsing failure.

## 4. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | One indicator, `cpi_index_monthly`, **unprefixed**. | The publisher is regional and the concept is one, as with `gdp_current_usd_annual`, `public_debt_usd_annual` and `money_m1_monthly`. The prefix rule keys on whether the source is national, not on whether the methodologies match — the monetary aggregates are unprefixed and each is in its own currency. |
| D2 | **Only the index.** No derived month-on-month or year-on-year. | CEPAL publishes no rate here. INIDE's connector stores inflation because INIDE publishes it; computing one from this index would be REIM publishing a figure no source published. |
| D3 | Store all seven, **Nicaragua included**, as a series separate from INIDE's. | `README.md` already states the rule: "Two sources publishing the same concept stay separate series." Excluding Nicaragua would break regional symmetry at the project's own country and make `/compare` return null for it on REIM's only regional CPI. The 4.2% difference is documented with its cause. |
| D4 | **No base year in the unit**, and none stored. `unit="index"`. | 3.1 — CEPAL's declared bases are wrong for three of five. A unit that stated one would be asserting something measured to be false. |
| D5 | `max_period_change_pct: null`. | 3.4 — no single threshold separates Guatemala's 42.6% splice from Nicaragua's real +261%. A rule that cannot be set honestly is left unset, and the connector check does the work. |
| D6 | The known breaks are **encoded, not thresholded**: Guatemala 2010-01 and El Salvador 1985-08 are named in the connector, and any *other* move beyond ±15% fails the check. | An expectation rather than a floor, matching `cepalstat_fx_expected_countries`. A new splice is reported; the two measured ones do not cry wolf on every run. |
| D7 | Belize is stored as published, at whatever cadence it publishes. | 162 of its months are absent because it reported **quarterly until 2011** and monthly only from 2012. Interpolating them is imputation; dropping Belize loses REIM's hardest-won country. The continuity check warns from the first run, deliberately, as Honduras does on freshness in the monetary section. |
| D8 | The whole history from 1980, Nicaragua's `2E-9` included. | The figures are published and exact in `Decimal`. Truncating the series to avoid awkward numbers would be REIM deciding which official history counts. |

## 5. Components

### 5.1 `reim/domain/indicators/registry.py`

One new indicator:

| Code | Name | Category | Frequency | Unit | Value type |
|---|---|---|---|---|---|
| `cpi_index_monthly` | Consumer price index (monthly) | `PRICES` | `MONTHLY` | `index` | `INDEX` |

Its description states 3.1 (no reliable published base, so levels are not
comparable across countries), 3.2 (Guatemala's break), and that Nicaragua also
has `ni_cpi_index_monthly` from INIDE which differs by about 4%.

`currency_convertible` stays `False`: an index is not an amount in a currency.

### 5.2 `sources/catalog.yml`

One entry, `cepalstat_cpi_monthly`, on the established CEPALSTAT shape:
same `base_url`, same organization, same non-open licence, `category: prices`.

### 5.3 `reim/ingestion/connectors/regional/cepalstat_cpi.py`

Subclasses `CepalstatConnector`. One request; the month member table comes from
the data response, exactly as the exchange-rate connector now does.

`transform` filters to the seven, reads country × year × month, and stores the
value as published with no scaling. `raw_metadata` carries the published value,
the published unit, `data_features`, the row's `source_id` description (empty
where 3.7 applies) and the credits.

The two connectors are close enough that the temptation to merge them will
arise. They are not merged: this one has no currency table, no pegs, and a
different quality battery, and `cepalstat.py`'s docstring already records that
merging family transforms was rejected in design.

## 6. Quality

| Check | Severity | What it catches |
|---|---|---|
| `cepalstat_cpi_expected_countries` | `critical` | A country dropping out of, or arriving in, the matrix |
| `cepalstat_cpi_known_splices` | `error` | Any month-on-month move beyond ±15% **other than** the two measured ones |
| `cepalstat_monthly_continuity` | `warning` | Holes inside a country's own span — inherited from `CepalstatConnector` |

The second check is the one that carries this design's judgement. It holds a
**three-entry** allow-list, keyed on the month moved *into*:
`("GTM", "2010-01")`, `("SLV", "1985-08")` and `("SLV", "1985-09")`. El
Salvador needs two entries because one corrupt cell produces two large moves —
the fall into August and the recovery into September — and listing only the
first would fail the check on the second every run.

Nicaragua's whole pre-1992 span is excluded by date rather than enumerated: it
contains 58 legitimate moves beyond the threshold, and its worst move from 1992
onward is 9.28%, so the cut is clean. Everything else beyond ±15% is a new
break and fails.

The continuity check will **warn on Belize on every run**, reporting its 162
absent months. That is the correct output for a country that published
quarterly for twenty-one years, and it is recorded in `docs/sources.md` so
nobody later reads it as a regression.

Value rules: `min_value: 0` inclusive, `allow_zero: false`, `max_value: null`
(Nicaragua reaches 335 and every series is on its own base, so no ceiling is
meaningful), `max_period_change_pct: null` per D5,
`freshness_max_age_days: 120` — the series ends 2026-07 and CEPAL updates it
monthly, so this is REIM's tightest freshness threshold and it should be.

`min_observations: 3400`.

## 7. Testing

One recording: the complete data response, gzipped. No dimensions recording —
this connector makes one request.

Connector tests, each pinning a measurement from section 3:

* The seven are filtered out of 40 countries; 3,451 observations.
* Each country's span and month count.
* Guatemala 2009-12 reads 94.882 and 2010-01 reads 54.4831537 — the splice, as
  a stored fact rather than a comment.
* El Salvador 1985-08 reads 7.157 between 11.473 and 11.928.
* Nicaragua's smallest value parses exactly from scientific notation.
* Values are stored unscaled and at full published precision, including an
  eight-decimal row.
* Rows with a null `source_id` store an empty `cepalstat_source`, not `"None"`.
* All three checks pass on the recording, except that continuity reports
  Belize — asserted as a **passing expectation of a warning**, not as a pass.
* Each check fails when given data that should fail it: a country removed, a
  fabricated splice at a date not on the allow-list, and a splice at a date
  that **is** on the allow-list passing.

One comparison test against INIDE, with no database: transform both fixtures
and assert the 198 shared months, that none is identical, and that the ratio
stays inside 1.02–1.05. This is the regression test for 3.5 — if a future
CEPAL revision makes the two series converge or diverge sharply, the
documented explanation has stopped being true and someone must look.

## 8. Volume

**3,451 observations** from one request of 2.02 MB. REIM's catalog gains its
ninth monthly series, its first regional price data, and its first indicator
whose values are an index rather than an amount, a rate or a ratio.

Nicaragua's CPI observation count roughly triples, across two publishers that
do not agree.

## 9. Out of scope

* **Deriving inflation rates** from this index — D2. If a regional inflation
  series is wanted, the honest route is a source that publishes one.
* **Splicing Guatemala's two segments** into a continuous series, or rebasing
  any country onto a common period. Both would publish figures no source
  published, and the second would make cross-country levels look comparable
  when they are not.
* **Reconciling Nicaragua's two indices**, or preferring one. They are stored
  side by side with the difference measured; choosing between two official
  compilers is not REIM's call.
* **Filling Belize's quarterly years** — D7.
* **The CPI sub-indices** CEPALSTAT publishes as indicators 762 and 763
  (tradables and non-tradables). A separate increment if wanted; they carry the
  same dimensions and would reuse this connector's shape.
