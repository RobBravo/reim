# CEPALSTAT public debt stock — design

REIM's first fiscal indicators: central-government gross public debt for the
seven Central American countries, annually from 1990, in dollars and as a share
of GDP.

Every figure below was measured against the live API on 2026-09-03, not read
from documentation — CEPALSTAT publishes none.

## 1. What the roadmap recorded, and what is actually there

`docs/sources.md` has carried public debt in its "Reachable, not ingested"
table since 2026-08-19, described as "4 dimensions — country, institutional
coverage (4), year, debt classification (6)" with one trap noted: a country-year
cell is not identified until both extra dimensions are pinned, and deciding
which member of each is *the* public debt figure is a design decision rather
than a parsing one.

That is still the correct description, and this document makes that decision.
Ingesting this family empties the table, so the subsection goes with it.

## 2. The source

| | |
|---|---|
| **Endpoint** | `GET /cepalstat/api/v1/indicator/{1239,1240}/data?lang=en` |
| **Auth** | None |
| **Requests** | Two, ~620 KB each, ~3 s apiece |
| **Rows returned** | 4,351 (1239) and 4,494 (1240), all 145 countries |
| **Rows for the seven** | 1,326 and 1,358, before the coverage filter |
| **Licence** | CEPAL's terms — not open; already recorded in the GDP section |

| CEPAL id | `indicator_name` | `unit` | `decimals` |
|---|---|---|---|
| 1239 | Public debt stock in millions of dollars | In millions of dollars at current prices | 2 |
| 1240 | Public debt stock as a percentage of GDP | As a percentage of gross domestic product | 2 |

Both were last updated on 2026-08-20 and both carry the same four dimensions:
country (208), debt classification (10590, six members), institutional coverage
(10690, four members) and years (29117).

**The English member names are real translations here.** The monetary family's
`descripcion_ingles` defect does not appear: `lang=en` returns "Central
government" and "Total public debt (classification by residence)". This
connector therefore makes no Spanish request, and decision C7 — `lang=en`
throughout — needs no exception.

## 3. Which slice is *the* public debt figure

The cube offers 24 coverage × classification combinations per country-year.
Twelve of them are empty everywhere.

**Three of the six classification members carry no rows at all**, across all 145
countries: Currency classification (10610), Rate classification (10611) and
Maturity debt classification (10614). They are grouping nodes in CEPAL's own
tree, published as dimension members with nothing behind them. Only Total public
debt by residence (10609), Internal debt (10612) and External debt (10613) hold
data.

**Of the four institutional coverages, only central government is complete.**
Measured on the Total-by-residence member, for the seven:

| Coverage | Countries | Span |
|---|---|---|
| Central government | **all seven** | 1990–2025, no gaps |
| Nonfinancial public sector | five — no GTM, no HND | 1990–2025 |
| Public sector | five | mostly ends 2011 |
| State and local governments | one — HND | 2000–2011 |

CEPAL's own `calculation_methodology` settles it: "The information presented is
refered to the central government gross public debt stock in Latin American
countries." The other three are listed afterwards as available "when
available". REIM stores the central-government figure and says so in the
indicator description.

**Decision D1: one coverage, one classification, two units.** Central
government, Total public debt by residence, in each of 1239 and 1240. Storing
the internal/external split as four more indicators was considered and rejected:
their sum does not reconcile with the total (§4), so publishing them as REIM
series would invite a subtraction that does not hold.

## 4. What measuring established

**The internal/external split does not sum to the total.** Of 415 complete
triples in 1239, 303 are exact; the rest drift, mostly under 0.1% but with three
cells past 1%. In 1240, 265 of 423 are exact and four exceed 1%. This is not
rounding at the declared two decimals — it is a real inconsistency in the
source, and it is the reason D1 stores only the total.

**The implied GDP does not reconcile with CEPAL's own GDP series.** Dividing
1239 by 1240 recovers a GDP in millions of dollars. Compared against indicator
2203 — the series REIM already stores as `gdp_current_usd_annual` — across the
225 shared country-years:

| Disagreement | Country-years |
|---|---|
| under 0.1% | 38 |
| 0.1% to 1% | 31 |
| 1% to 5% | 104 |
| **5% or worse** | **52** |

The rows are exclusive buckets, not cumulative: 69 of 225 agree to within 1%,
and 52 are off by 5% or more.

The worst is Honduras 1990, off by 23.7%. The cause is in the methodology note:
the ratio uses "the gross domestic product in current prices and local monetary
unit for each country" converted at "the exchange rate at December 31 for each
year published in the International Finance Statistics by the IMF", while 2203
is CEPAL's harmonised USD GDP on its own conversion. **The two are not
reconcilable and REIM must not let a consumer assume otherwise.** This is
documented rather than checked: a check would fail permanently by design.

**Coverage of the two units differs by six cells.**

| Series | Cells | Belize | Nicaragua |
|---|---|---|---|
| 1239 (USD) | 226 | 2011–2020 | 1990–2025 |
| 1240 (% GDP) | 230 | 2011–2025 | 1991–2025 |

Every other country is 1990–2025 complete in both. So Nicaragua 1990 has a
dollar figure and no ratio, and Belize 2021–2025 has a ratio and no dollar
figure — six cells, in opposite directions.

**The largest year-on-year move is real.** Nicaragua 1996: debt falls from
185.3% to 96.7% of GDP and from 7,288.6 to 3,954.9 million dollars, a 47.8%
drop. That is the HIPC and Paris Club relief, not a data error, and every
threshold below is chosen to clear it rather than flag it.

**The value ranges are wider than a naive bound would allow.** The ratio runs
from 14% to **222.1%** of GDP (Nicaragua, early 1990s). A `max_value: 100` would
reject genuine figures.

**`credits[0]` is the fetch date again** — `2026-09-03` on both responses. It
moves between runs and is excluded from `raw_metadata`, exactly as in the GDP
and monetary connectors, which already record why.

## 5. Decisions

| | Decision |
|---|---|
| **D1** | Central government, Total public debt by residence, both units. Two indicators. |
| **D2** | No Spanish request: this family's English member names are real translations. |
| **D3** | Rows are selected by member **id** (10692, 10609), and `transform` asserts those ids still carry the expected names, raising `TransformationError` if not. |
| **D4** | The dollar series is scaled `× 10^6` to whole USD; the ratio is stored exactly as published. |
| **D5** | The internal/external split is not stored, because it does not sum to the total. |
| **D6** | The implied-GDP mismatch is documented, never checked — a check would fail permanently by design. |
| **D7** | A new connector module, not an extension of `cepalstat_gdp.py`: four dimensions, a different transform shape. Same reasoning that kept the monetary connector separate. |

## 6. Components

### 6.1 `reim/domain/indicators/registry.py`

Two definitions, REIM's first use of `IndicatorCategory.FISCAL`:

| Code | Unit | `value_type` |
|---|---|---|
| `public_debt_usd_annual` | `current USD` | `LEVEL` |
| `public_debt_pct_gdp_annual` | `percent of GDP` | `PERCENT` |

Both descriptions state that the figure is central-government gross debt, that
it is CEPAL's compilation rather than each country's own publication, and — on
the ratio — that its GDP denominator is not REIM's `gdp_current_usd_annual`.

### 6.2 `sources/catalog.yml`

One entry, `cepalstat_debt_annual`, category `fiscal`, frequency `annual`,
connector `reim.ingestion.connectors.regional.cepalstat_debt`, licence
`cepal_terms_of_use`. It ships `enabled: false` with a `disabled_reason` and is
enabled only after a real end-to-end run.

### 6.3 `reim/ingestion/connectors/regional/cepalstat_debt.py`

`CepalstatDebtConnector(CepalstatConnector)`. The base class extracted on
2026-09-03 supplies `_ensure_envelope_ok`, `_decode`, `_members_of`, `_label_of`
and `_value_of`, plus `COUNTRY_DIMENSION` and `YEARS_DIMENSION`.

This module adds `DEBT_CLASSIFICATION = 10590` and
`INSTITUTIONAL_COVERAGE = 10690` — this family's own dimensions, held here
rather than in the base, exactly as `PERIOD_DIMENSION` is the monetary
family's.

`extract` makes two requests, checks each envelope, and returns both texts keyed
by CEPAL id. `transform` reads each response's member tables, asserts the two
selected ids still carry their expected names (D3), filters rows to those two
members and to `CENTRAL_AMERICA` by the row's own `iso3` — regional aggregates
arrive with `iso3: null` and fall out of the membership test — and emits one
observation per country-year with `source_record_id` of
`cepalstat:{cepal_id}:{iso3}:{year}`. Year labels come from the member table,
never from id arithmetic.

## 7. Quality

Two connector checks, both dataset-level:

| Name | Type | Severity |
|---|---|---|
| `cepalstat_debt_seven_countries` | completeness | `critical` |
| `cepalstat_debt_annual_continuity` | completeness | `warning` |

The first requires all seven countries in both series. The second reports a gap
**inside a country's own span**, measured per country rather than pooled — the
fix applied to the freshness and continuity checks on 2026-08-19, and the reason
Belize's shorter span is not itself a finding. Both pass on the live data today.

Per-indicator rules in `sources/quality_rules.yml`:

```text
min_value: 0            allow_negative: false     allow_zero: false
max_period_change_pct: 60                         freshness_max_age_days: 600
min_observations: 220 (USD) / 224 (ratio)         max_value: null
```

`60` clears Nicaragua 1996's 47.8% with headroom and is set knowing that event.
`600` matches the GDP rules and CEPAL's annual cycle. `max_value` stays null
because the ratio genuinely reaches 222.1%.

## 8. Testing

Two recorded responses, gzipped into `tests/fixtures/`, replayed with `respx`.

Fixture tests pin what the recordings hold, so a re-record that moves the data
fails loudly: the 226 and 230 cell counts, the per-country spans, zero gaps, the
three empty classification members, the six coverage exceptions and Nicaragua
1996 as the largest real move.

Connector tests cover the filter (only central-government Total-by-residence
survives; the other eleven non-empty combinations and every regional aggregate
are discarded), the scaling (millions to whole USD, the ratio untouched), the
name assertion raising on a relabelled member, and both checks passing on the
recordings and failing on a doctored copy.

One `@pytest.mark.live` test proves the contract, not the values: shape, country
set, and all checks passing.

## 9. Volume, and what it changes

456 observations — 226 and 230. Two requests, ~1.2 MB, about 6 s.

REIM moves to 19 pipelines, 33 indicators and roughly 48,900 observations for a
complete rebuild. `IndicatorCategory.FISCAL` gets its first use, as
`MONETARY` did two weeks ago. Every one of the seven countries gains fiscal
data; none had any before.

## 10. Out of scope

- The internal and external debt series (D5).
- The other three institutional coverages (D1).
- Any reconciliation between the debt ratio and REIM's GDP series (D6).
- Debt service, interest, or maturity profiles — different CEPAL indicators,
  each with its own dimensions.
