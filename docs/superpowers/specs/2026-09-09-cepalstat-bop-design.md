# CEPALSTAT quarterly balance of payments — design

REIM's first balance-of-payments data and its second quarterly source: 25
indicators, **19,582 observations**, seven countries, from one request.

Every figure below was measured against the live API on 2026-09-09, not read
from documentation — CEPALSTAT publishes none.

## 1. What REIM already has, and what this adds

REIM's external sector today is merchandise trade from the IMF (monthly exports,
imports and balance) and remittances from the World Bank (annual). It holds no
current account, no financial account, and no capital account — so it can say
what a country sold abroad and nothing about how it paid for what it bought.

This adds the whole balance of payments at quarterly resolution: the six
headline balances, four sub-balances, and fifteen components. It is also REIM's
**second quarterly source**, after SIECA's trade in services.

## 2. The source

| | |
|---|---|
| **Organization** | Comisión Económica para América Latina y el Caribe (`CEPAL`) |
| **Endpoint** | `GET /cepalstat/api/v1/indicator/547/data?lang=en` — one request |
| **Auth** | None |
| **Volume** | **20.3 MB, 49 s** — ten times the consumer price index, the largest response REIM reads |
| **Rows returned** | 153,295, covering 23 countries of 145 dimension members |
| **Rows for the seven** | 43,078 across 55 items; **19,582** across the 25 stored |
| **Frequency** | Quarterly |
| **Licence** | ⚠️ **Not open** — CEPAL's terms, already recorded in the GDP section |

Published metadata, from `body.metadata`:

| Field | Value |
|---|---|
| `indicator_name` | Quarterly balance of payments |
| `area` | External sector |
| `unit` | `millions of dollars` |
| `data_features` | `Current values in millions of dollars` |
| `calculation_methodology` | *"…according to the analytical components of the **fifth edition** of the Balance of Payments Manual published by the IMF in 1993."* |
| `decimals` | 0 |
| `last_update` | Jul 16 2026 2:48PM |

Four dimensions — country (208), quarters (510), item (1272) and years (29117).
That is `cepalstat_debt.py`'s shape: four dimensions, of which one selects the
slice to store.

### 2.1 Coverage, verified per country

| Country | Span | Quarters | Interior gaps |
|---|---|---|---|
| Guatemala, Nicaragua | 1993-Q1 … 2025-Q4 | 132 | **none** |
| Panama | 1998-Q1 … 2026-Q1 | 113 | **none** |
| Costa Rica, El Salvador | 1999-Q1 … 2026-Q1 | 109 | **none** |
| Belize | 2001-Q1 … 2025-Q4 | 100 | **none** |
| Honduras | 2004-Q1 … 2026-Q1 | 89 | **none** |

**Not one interior gap in any country.** No other family REIM reads is complete
in that sense: the CPI has 162 missing months for Belize, the interest rates
have 94 across two countries. Four countries reach **2026-Q1**, which makes this
REIM's second-freshest source after the regional CPI.

### 2.2 There is no server-side filtering, so the whole cube travels every run

Three forms were probed on 2026-09-09: `?members=208:241` answers **500**, while
`?dim_208=241` and `?filters=208:241` both answer **200 with the full
20,346,031 bytes** — the parameter is ignored rather than rejected, which is the
more dangerous failure of the two. A future reader who assumes a filter worked
would be silently reading the whole cube.

So the connector downloads 20.3 MB, decodes it, and discards 87% of it. That is
acceptable at quarterly cadence and is stated here so nobody looks for the
optimisation twice.

## 3. What measuring established

### 3.1 The metadata contradicts itself about which IMF manual this is

`calculation_methodology` declares the **fifth edition** (BPM5, 1993). But
footnote **10138**, carried by 16,282 of the 19,582 stored rows, reads:

> Analytical presentation based on the official figures of the countries
> according to the **6th version** of the IMF

The split is **by country, not by year**, and it is total:

| Carries footnote 10138 (BPM6) | Carries no footnote |
|---|---|
| Belize, Costa Rica, El Salvador, Honduras, Nicaragua, Panama — *every* row | **Guatemala — every row** |

So the indicator declares BPM5 while six of the seven countries are presented on
BPM6, and only Guatemala follows what the indicator says.

**This does not make the figures incomparable, and measurement is why we can say
so.** BPM6 reverses BPM5's financial-account sign convention, which would be a
real break. It is not present here. Taking every quarter where the current
account is in deficit and averaging the financial account:

| | BLZ | CRI | GTM | HND | NIC | PAN | SLV |
|---|---|---|---|---|---|---|---|
| mean financial account when I < 0 | +34.3 | +571.0 | **+345.0** | +285.7 | +123.0 | +677.0 | +199.2 |

Guatemala sits inside the range, not opposite it: a current-account deficit pairs
with a positive financial account everywhere, Guatemala included. CEPAL has
evidently normalised the presentation across the two manuals. The accounting
identities of §3.4 also hold for Guatemala exactly as for the other six.

**Decision: record the contradiction, do not declare
`methodology_varies_by_country`.** The flag exists for the interest rates, where
the publisher states each country measures a *different instrument* and levels
genuinely cannot be read against each other. Here the labels disagree and the
figures do not. Setting the flag would put a caveat on `/compare` that the
measurement contradicts, and the flag's value comes from being true when it
appears.

### 3.2 The declared decimals are wrong by up to twenty-two places

`decimals` declares **0**. The stored rows publish up to **22**:

| Decimals | 0 | 1 | 2 | 5 | 8 | 13 | ≥14 |
|---|---|---|---|---|---|---|---|
| Cells | 1,433 | 7,155 | 1,780 | 1,622 | 3,271 | 1,351 | 525 |

Values like `-9201.38034153` are floating-point noise in the producer's own
pipeline, not precision: these are millions of dollars, where the second decimal
is already a hundred dollars. This is the third CEPALSTAT family whose declared
precision does not match its payload, after the exchange rate (declares two,
publishes one) and the lending rate (declares zero, publishes two) — and by far
the worst.

**Values are stored exactly as published.** No rounding, in either direction.
REIM has never altered a published value and does not start here; the noise is
the producer's and is recorded as such. Anything else would be the first
silent edit in the project's history, for cosmetic gain.

### 3.3 Attribution is multiple per country, which is new for this source

Every other CEPALSTAT family cites one publisher per country. This one cites
several for the same country:

| Country | Cited |
|---|---|
| Nicaragua | CBN, ECLAC, IMF |
| Belize | ECLAC, IMF |
| Guatemala | BANGUAT, IMF |
| Costa Rica | CBCR, ECLAC |
| Honduras | CBH |
| Panama | DSC |
| El Salvador | RBC |

The connector stores each row's own `source_id` as published, so a country's
series can legitimately carry more than one attribution across its span. This is
also the first family whose `footnotes` block is populated — five notes, of which
10138 (§3.1) is the only one on stored rows.

### 3.4 Three accounting identities hold exactly; a fourth has two exceptions; a fifth does not hold at all

Measured across **784 country-quarters**, tolerance 0.5 million:

| Identity | Result | Worst residual |
|---|---|---|
| I = goods and services + income + current transfers | **781 / 781** | 0.109 |
| Balance on goods = exports f.o.b. + imports f.o.b. | **784 / 784** | 0.1 |
| Balance on goods and services = goods + services credit + services debit | **784 / 784** | 0.001 |
| V = I + II + III + IV | 782 / 784 | 14.104 |
| **V + VI = 0** | **2 / 784** | 6,939.24 |

The first three are exact enough to enforce. The fourth fails only on **Panama
2004-Q3 (−9.1)** and **Panama 2021-Q4 (+14.1)** — two cells in thirty-three
years, encoded rather than guessed.

**The fifth is the one worth writing down.** Anyone who knows the BPM5 structure
expects the global balance to be offset exactly by reserves and related items,
and it is not: it holds in 2 of 784 country-quarters and misses by up to 6,939
million. `VI` here is not the mirror of `V`. Recorded before someone builds a
check, a chart or a conclusion on the assumption.

Note that imports are published **negative**, which is why the goods identity is
a sum rather than a difference.

### 3.5 Negatives and zeros are ordinary here

Of the 19,582 stored values: **9,924 are negative** and **594 are zero**, with a
range of −9,201.38 to +6,971.40. Both are unremarkable in a balance of payments,
where a deficit is a negative number and an absent flow is a real zero. Every
other REIM family forbids one or both.

This also settles `max_period_change_pct`: these series **cross zero**, so a
percentage change of them is unbounded and meaningless. The rule is null on all
twenty-five, the same call `ni_cpi_inflation_monthly` already makes for the same
reason.

### 3.6 The item names are translated, unlike dimension 3981

In `lang=en`, dimension 1272 comes back as `Item__Balance of payments` with
genuine English member names. The interest rates and the monetary aggregates
must fetch a second, Spanish dimensions response because their period dimension
returns `descripcion_ingles` for all seventeen members. **This family needs no
second request.**

## 4. Scope: 25 of 55 items

55 of the 66 item members carry data for the seven; 11 are empty. Storing all 55
would mean 43,078 observations and **55 new indicators**, more than doubling a
registry that holds 41 today. Most of the excess is deep sectoral detail — *Other
investment liabilities: Monetary authorities* and its kin.

**Stored — 25 indicators, 19,582 observations:**

| Group | Items |
|---|---|
| Headline balances | I. Current account, II. Capital account, III. Financial account, IV. Errors and omissions, V. Global balance, VI. Reserves and related items |
| Sub-balances | Balance on goods, on goods and services, on income, on current transfers |
| Goods and services | Exports f.o.b., Imports f.o.b., Services (credit), Services (debit) |
| Income and transfers | Income (credit), Income (debit), Current transfers (credit), Current transfers (debit) |
| Financial account | Direct investment abroad, Direct investment in reporting economy, Portfolio investment assets, Portfolio investment liabilities, Other investment assets, Other investment liabilities, Reserve assets |

Four items carry 781, 775 or 780 rows rather than 784 — CEPAL publishes a few
fewer cells for *Balance on income*, *Income (credit)*, *Current transfers
(credit)* and *(debit)*. Those are gaps in the publisher's cube, reported by the
completeness check rather than filled.

### 4.1 Two items must carry a warning in their own description

`docs/sources.md` recorded both traps on 2026-09-06, before anyone read this
indicator as a solution to anything. The warnings move into the indicator
descriptions, where a reader meets them at the point of use:

* **`reserve_assets_quarterly` is a flow, not a stock.** It is the
  balance-of-payments *movement* in reserve assets over the quarter.
  `ROADMAP.md` asks for the reserves *level*, which is what `FI.RES.TOTL.CD`
  and the IMF's `IRFCL` hold. Labelling this as reserves would close that gap
  falsely.
* **`current_transfers_credit_quarterly` is not remittances.** It is the whole
  current-transfers account, official transfers included, and the 66 members do
  not break personal remittances out. The World Bank series REIM already stores
  annually, `BX.TRF.PWKR.CD.DT`, is personal transfers plus compensation of
  employees — a third definition again.

### 4.2 Goods overlap with the IMF series, and both are kept

REIM already holds monthly exports and imports from the IMF's IMTS. This adds
quarterly exports and imports f.o.b. on a different methodology.

**Both are stored and REIM chooses between neither**, which is the rule it
already applies to Nicaragua's two consumer price indices. Keeping the goods
items is also what makes the §3.4 identities checkable: without them the balance
on goods cannot be reconciled against anything.

## 5. Architecture

### 5.1 One connector, one request, twenty-five series

`reim/ingestion/connectors/regional/cepalstat_bop.py`, a `CepalstatConnector`
subclass on `cepalstat_debt.py`'s four-dimension shape.

`extract` makes **one request** and no Spanish dimensions fetch (§3.6).
`transform` walks the rows once, keeping those whose country is one of the seven
**and** whose item is one of the 25, and maps each item id to its REIM code.

### 5.2 Normalization

| Field | Value |
|---|---|
| `indicator_code` | from the item map |
| `period` | `parse_period(f"{year}-Q{quarter}", Frequency.QUARTERLY)` |
| `value_numeric` | the published `Decimal`, **unscaled and unrounded** |
| `unit` | `current USD` |
| `currency_code` | `USD` |
| `source_record_id` | `cepalstat:547:{iso3}:{item_id}:{year}-Q{quarter}` |

The published figures are **millions** of dollars. REIM's monetary aggregates
multiply by 1e6 to store whole units; **this family does the same**, so a
dollar amount means the same thing everywhere in the database. The published
value and the scale applied both go into `raw_metadata`, as they do there.

`currency_convertible` is **False** on all 25: they are already dollars, and the
conversion machinery exists to move *into* USD.

### 5.3 Indicator codes

Region-wide, no country prefix, `_quarterly` suffix — following
`exports_services_quarterly` from SIECA. All 25: `IndicatorCategory.EXTERNAL_SECTOR`,
`Frequency.QUARTERLY`, `unit="current USD"`, `ValueType.LEVEL`,
`methodology_url` = the CEPALSTAT dashboard scoped to indicator 547.

## 6. Quality

### 6.1 Declarative rules

Identical for all 25, because the family is one cube:

| Rule | Value | Why |
|---|---|---|
| `min_value` / `max_value` | null / null | A balance of payments has no natural bound in either direction |
| `allow_negative` | **true** | 9,924 of 19,582 are negative (§3.5) |
| `allow_zero` | **true** | 594 are zero, and an absent flow is a real zero |
| `max_period_change_pct` | **null** | These series cross zero; percentage change of them is unbounded (§3.5) |
| `monotonic_increasing` | false | |
| `freshness_max_age_days` | **550** | Four countries end 2026-Q1 (162 days old on 2026-09-09); Belize, Guatemala and Nicaragua end 2025-Q4 at 252. 550 clears CEPAL's quarterly cycle with headroom and still catches a family that has stopped being extended |
| `min_observations` | **19000** | 19,582 measured |

### 6.2 Connector checks

| Check | Type | Severity | Asserts |
|---|---|---|---|
| `cepalstat_bop_current_account` | consistency | `error` | I = goods and services + income + current transfers, within 0.5 |
| `cepalstat_bop_goods` | consistency | `error` | Balance on goods = exports + imports, within 0.5 |
| `cepalstat_bop_goods_services` | consistency | `error` | = goods + services credit + services debit, within 0.5 |
| `cepalstat_bop_global_balance` | consistency | `warning` | V = I + II + III + IV, within 0.5, with Panama 2004-Q3 and 2021-Q4 allow-listed |
| `cepalstat_bop_expected_countries` | completeness | `critical` | All seven in every series — via the base class's `_check_country_coverage` |

The tolerance is **0.5 million** against a worst real residual of 0.109 — five
times the largest observed rounding, and orders of magnitude below any genuine
break.

**There is no continuity check.** `_check_monthly_continuity` is monthly-only:
it splits `period.label` on `-`, which raises on a quarterly label. A quarterly
equivalent is not written here because there is nothing for it to find — every
country's span is complete (§2.1). If a gap ever appears, `min_observations`
falls and the run reports it.

### 6.3 Expected first run

All five checks pass. Freshness passes on all 25. Anything else is a finding to
record, not a threshold to adjust.

## 7. Testing

The recorded fixture is **trimmed**, which is a departure this section justifies.

The full response is 20.3 MB and **1.74 MB gzipped — more than every existing
fixture in the repository combined (1.18 MB)**. The recording keeps the seven
Central American countries **plus Mexico**, with all 66 item members: **0.53 MB**.

* **Mexico exists so the country filter is still genuinely tested.** Trimming to
  the seven alone would leave nothing for the filter to exclude, and a test that
  cannot fail is not a test.
* **All 66 items are kept** so the item filter is genuinely tested: 41 of them
  must be discarded, including the 11 that are empty for every country.

`tests/fixtures/README.md` records the trim and its reason, as it already does
for `worldbank_ni_cpi_inflation.json` ("trimmed to 2015–2024 with the metadata
block adjusted to match"). No test calls CEPAL.

Tests pin, at minimum: the 19,582 count and the per-indicator counts; Mexico
discarded and the seven kept; the 41 unstored items discarded; values unscaled
beyond the ×1e6 and unrounded, including a 13-decimal cell; negatives and zeros
stored; each of the four identity checks failing on a constructed break and
passing on the fixture; Panama's two allow-listed exceptions not firing while a
third constructed one does; and quarterly periods parsed to the right quarter
boundaries.

## 8. Decisions

| | Decision | Rationale |
|---|---|---|
| **D1** | 25 items, not 55 | 55 would more than double a 41-indicator registry with deep sectoral detail (§4) |
| **D2** | Keep the goods items despite the IMF overlap | Both series stored, neither chosen — the two-CPI precedent; and the identities need them (§4.2) |
| **D3** | Store values exactly as published | Repo rule; the 22-decimal noise is the producer's (§3.2) |
| **D4** | Scale millions to whole units | Matches the monetary aggregates so a dollar means one thing in the database (§5.2) |
| **D5** | Do **not** declare `methodology_varies_by_country` | The labels disagree, the measured figures do not (§3.1) |
| **D6** | `max_period_change_pct` null on all 25 | The series cross zero (§3.5) |
| **D7** | Trim the fixture to seven + Mexico, all 66 items | 1.74 MB would exceed every existing fixture combined; both filters stay tested (§7) |
| **D8** | No continuity check | The base class's is monthly-only and every span is complete (§6.2) |
| **D9** | `reserve_assets_quarterly` and `current_transfers_credit_quarterly` carry warnings in their descriptions | Both are documented traps for roadmap gaps they do not close (§4.1) |

## 9. Out of scope

* **The 30 unstored items with data**, and the 11 with none. Recorded in
  `docs/sources.md` so a later increment starts from this measurement.
* **Indicator 361**, which uses a different dimension vocabulary entirely.
* **Deriving annual figures** by summing quarters. REIM does not publish derived
  indicators.
* **Reconciling the goods items against the IMF's monthly series.** Worth doing
  and worth its own increment; it is a comparison of two publishers, not a
  property of this one.
