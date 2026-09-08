# CEPALSTAT interest rates — design

REIM's first interest-rate data, and its first use of the `financial` indicator
category: nominal lending rates, nominal deposit rates and monetary policy
rates for the seven Central American countries, monthly, from 1990.

Every figure below was measured against the live API on 2026-09-07, not read
from documentation — CEPALSTAT publishes none.

## 1. What REIM already has, and what this adds

REIM holds no interest rate of any kind. Its monetary data is three aggregates
— M1, M2 and M3 — which say how much money exists and nothing about its price.
The `IndicatorCategory.FINANCIAL` member has existed since v0.1.0 and has never
been used.

This increment adds the price of money on both sides of a bank's balance sheet
and the rate the central bank sets, for all seven countries. It is the shortest
path to a genuinely new indicator family available anywhere in the catalog: the
shape is one REIM has already implemented twice.

## 2. The source

| | |
|---|---|
| **Organization** | Comisión Económica para América Latina y el Caribe (`CEPAL`) |
| **Host** | `https://api-cepalstat.cepal.org` |
| **Endpoints** | `GET /cepalstat/api/v1/indicator/{856,857,1206}/data?lang=en` |
| | `GET /cepalstat/api/v1/indicator/856/dimensions?lang=es` — once, see §4.2 |
| **Auth** | None |
| **Volume** | 1.70 MB / 1.80 MB / 1.38 MB, 7–13 s each |
| **Frequency** | Monthly |
| **Licence** | ⚠️ **Not open** — CEPAL's terms, already recorded in the GDP section |

Published metadata, from `body.metadata`:

| Field | 856 | 857 | 1206 |
|---|---|---|---|
| `indicator_name` | Nominal lending rate | Nominal deposit rate | Monetary policy rate |
| `theme` | Economic Indicators and Statistics | " | " |
| `area` | Financial indicators | " | " |
| `unit` | `Annual percentage` | " | " |
| `calculation_methodology` | `According to the definition from each country.` | " | " |
| `decimals` | 0 | 1 | 2 |
| `last_update` | Aug 27 2026 1:34PM | Aug 27 2026 7:00PM | Aug 31 2026 11:48AM |
| `data_features` | empty | empty | empty |
| Rows, all countries | 14,952 | 16,022 | 12,242 |
| Rows, the seven | 3,397 | 3,348 | 2,251 |

Three dimensions on all three indicators — country (208), period-in-year (3981)
and years (29117). That is `cepalstat_monetary.py`'s shape exactly, **including
the untranslated period members** described in §3.1.

### 2.1 Coverage, verified per country

Monthly members only, after the exclusions of §3.3.

| Country | 856 lending | 857 deposit | 1206 policy |
|---|---|---|---|
| Belize | 429 — 1990-01 … 2025-09 | 428 — 1990-01 … 2025-08 | 429 — 1990-01 … 2025-09 |
| Honduras | 406 — 1991-12 … 2025-09 | 405 — 1991-12 … 2025-08 | 246 — 2005-04 … 2025-09 |
| El Salvador | 369 — 1995-01 … 2025-09 | 369 — 1995-01 … 2025-09 | 297 — 2001-01 … 2025-09 |
| Guatemala | 357 — 1996-01 … 2025-09 | 357 — 1996-01 … 2025-09 | 249 — 2005-01 … 2025-09 |
| Costa Rica | 322 — 1999-01 … 2025-10 | 320 — 1999-01 … 2025-08 | 235 — 2006-03 … 2025-09 |
| Nicaragua | 321 — 1999-01 … 2025-09 | 321 — 1999-01 … 2025-09 | 165 — 2007-01 … 2025-10, **61 gaps** |
| Panama | 286 — 2001-12 … 2025-09 | 253 — 2001-12 … 2025-09, **33 gaps** | **excluded, §3.3** |
| **Total** | **2,490** | **2,453** | **1,621** |

**6,564 observations.** Only Panama's deposit rate and Nicaragua's policy rate
have interior gaps; every other span is complete.

### 2.2 Attribution is per country, and names the national central bank

Unlike the GDP and debt families, where CEPAL is the compiler, each row cites
the publisher it came from through `source_id`:

| Country | 856 | 857 | 1206 |
|---|---|---|---|
| Belize | CBB-Belize | CBB-Belize | CBB-Belize |
| Costa Rica | CBCR | ⚠️ **CBBO** | CBCR |
| Guatemala | BANGUAT | BANGUAT | BANGUAT |
| Honduras | CBH | CBH | ⚠️ **null** |
| Nicaragua | CBN | CBN | CBN |
| El Salvador | RBC | RBC | RBC |
| Panama | untranslated | untranslated | ⚠️ **null** |

Two defects, both stored as published and neither corrected:

* **857 attributes Costa Rica to `CBBO`, the Central Bank of Bolivia**, where
  856 and 1206 both say `CBCR`. This is a CEPAL attribution error. REIM does
  not silently repair a publisher's provenance, so the value is stored with the
  attribution CEPAL gives it and the discrepancy is recorded in
  `docs/sources.md` and pinned by a test.
* **`source_id` is null on 345 rows of 1206** — every Honduran and Panamanian
  row. The connector must tolerate a null rather than assume attribution is
  always present, which the two shipped CEPALSTAT connectors do assume.

## 3. What measuring established

### 3.1 The English period members are untranslated, exactly as in the monetary family

In `lang=en`, all seventeen members of dimension 3981 come back as the literal
string `descripcion_ingles` — the untranslated column name of CEPAL's own
database — on all three indicators. The member ids cannot be pinned either:
they run 3982–3998 out of calendar order, with September at 3993 and July at
3994.

So the member table is fetched separately in Spanish, and only the member
table: the data stays `lang=en` and every string REIM stores stays English.
This is `cepalstat_monetary.py`'s documented workaround, reproduced without
change.

### 3.2 The annual and quarterly members are means, not restatements

The monetary connector drops dimension 3981's `Anual` and `Trimestre N`
members because each is an exact restatement of a month — the annual figure is
December's stock, each quarter its closing month. **That reasoning does not
hold here, and the opposite one does.**

| Test | 856 | 857 | 1206 |
|---|---|---|---|
| quarter equals its closing month | 46 / 695 | 316 / 681 | 291 / 466 |
| quarter ≈ mean of its three months (±0.05) | **693 / 693** | 611 / 676 | **460 / 460** |
| annual ≈ mean of its twelve months (±0.05) | **202 / 202** | 191 / 199 | **122 / 122** |

These are rates, so CEPAL averages them rather than taking a period end. The
decision is the same — store the twelve monthly members only — but for the
opposite reason, and the connector docstring must say so. Storing a mean beside
its own inputs would be REIM publishing a derived figure as if published, which
`ROADMAP.md` rules out.

857 is the untidy one: 65 of its quarters and 8 of its annuals match neither
identity. They are dropped with the rest, so this affects nothing REIM stores.

### 3.3 Panama has no monetary policy rate, and CEPAL publishes twelve zeros anyway

Panama's entire presence in indicator 1206 is **16 rows, every one `'0'`, every
one with `source_id: null`**, all inside 2022 — twelve months, `Anual`, and
three of the four quarters, with `Trimestre 3` missing.

Panama is dollarised and has no central bank. There is no policy rate to
publish. Twelve uniformly zero, wholly unattributed cells in a single year are
an artifact of CEPAL's table, not a measurement.

**Decision: Panama is excluded from `policy_rate_monthly` only.** It keeps its
lending and deposit series, which are real, attributed and 286 and 253
observations long. The exclusion is a named constant with the reason beside it,
encoded in `EXPECTED_COUNTRIES` so a future appearance of real Panamanian data
is visible rather than silently dropped.

This is a deliberate departure from *store what is published*, and the only one
in this design. The alternative — storing them — would put "Panama: 0.00%" into
every `/compare` response for 2022 beside real policy rates, with the caveat
reachable only in the notes.

**Nicaragua's two zeros are a different thing and are stored.** 2010-03 and
2010-04 read `0` inside a real, fully attributed 165-month series. That is the
El Salvador corrupt-cell situation from the CPI work: one or two bad cells in a
live series are stored, pinned by a test, and documented — not deleted.

### 3.4 CEPAL declares that each country measures a different instrument

`calculation_methodology` reads, on all three indicators:

> According to the definition from each country.

and `definition` spells that out. For the seven, on indicator 856:

| Country | What CEPAL says the "lending rate" is |
|---|---|
| Costa Rica, Guatemala, Honduras | weighted average for lending rate in local currency |
| El Salvador | basic lending rate for up to one year |
| Nicaragua | weighted average of short-term lending rates in local currency |
| Panama | interest rate on one-year trade credit |
| Belize | weighted average rate for personal and business loans, residential and other construction loans |

Belize's entry is keyed **`Belice`** — the Spanish spelling, inside the English
`definition` string. A reader searching that text for "Belize" finds nothing,
which is how this row was first missed. It is the same untranslated-string
class as §3.1 and §2.2.

On 1206 the divergence is wider still: Belize's "monetary policy rate" is
**the Central Bank's lending rate**, El Salvador's is a stock-exchange repo
yield (1–7 days), Nicaragua's is the yield on 180-day central bank bonds, and
Costa Rica's is the rate on its central bank's local-currency operations.

857's text carries a defect of its own: Guatemala's *deposit* rate is described
as the "weighted average of the system **lending** rates in local currency".
The data is a deposit rate — it is below Guatemala's 856 series in all 357
shared months, by 7.34 to 12.17 points — so this is a wrong word in CEPAL's
prose, not a wrong series. Recorded, not corrected.

`assess_comparability` turns on **unit and currency only**
(`reim/schemas/comparison.py:67`). All three series are `percent per annum`
with no currency and one publisher, so `/compare` would report
`comparable: true` — technically correct on the axes it checks, and misleading
about levels. §5 resolves this.

**Belize's 856 and 1206 are not duplicates**, despite both definitions naming a
lending rate: 429 shared months, **zero identical values**.

### 3.5 The declared decimals are wrong for 856

| Indicator | `decimals` declares | Actually published |
|---|---|---|
| 856 | 0 | 2 decimals in 2,065 of 2,490 cells, 1 in 391, 0 in 34 |
| 857 | 1 | 1 decimal in 2,205 of 2,453, 0 in 248 |
| 1206 | 2 | 2 in 641, 1 in 227, 0 in 765 |

857 and 1206 declare their maximum honestly; 856 declares zero and publishes
two. This is the third CEPALSTAT family whose declared precision does not match
its payload, after the exchange rate's *declared two decimals, published one*.

**Values are stored exactly as published.** No rounding to any declared figure,
in either direction.

### 3.6 The family is maintained but not extended

The newest monthly cell **across all 145 countries** is 2025-10 on all three
indicators, while `last_update` is 27–31 August 2026. CEPAL touched these
tables two weeks before this was written and did not add a month.

This is not a Central American lag and not an abandoned table: it is the same
~11-month publication lag `docs/sources.md` already records for
`exchange_rate_nominal_monthly`, which ends 2025-09 against a `last_update` of
2026-08. §6.2 sets the freshness threshold from it.

### 3.7 The lending rate exceeds the deposit rate everywhere

In all **2,453** months where a country publishes both, 856 > 857 without
exception. The spread runs from **1.18 points** (El Salvador) to **18.84**
(Honduras). A bank charging less than it pays is not a rounding artifact, so
this is enforceable rather than advisory — the analogue of the monetary
family's `M1 ≤ M2 ≤ M3` nesting, but exact, with no tolerance needed.

### 3.8 No move exceeds 8 percentage points, and percentage change is useless here

Across all 6,523 calendar-adjacent pairs:

| Threshold | 856 | 857 | 1206 |
|---|---|---|---|
| moves > 25% | 17 | 79 | 85 |
| moves > 60% | 0 | 31 | 24 |
| moves > 5 points | 0 | 1 | 2 |
| moves > 8 points | **0** | **0** | **0** |

The percentage-change tripwire collapses on the deposit and policy rates
because they sit near zero: Nicaragua's deposit rate moving 0.5 → 1.7 is
**+240%** and 1.2 points, and El Salvador's policy rate 1.47 → 4.87 is +231%
and 3.4 points. Both are ordinary. This is why `ni_cpi_inflation_monthly`
already sets `max_period_change_pct` null.

The largest absolute move anywhere is **Belize's policy rate stepping 18 → 11
in December 2010**, 7 points — a real, discrete decision. §6.2 sets the
tripwire at 8 points, and keeps `max_period_change_pct` only for the lending
rate, whose largest real move is Nicaragua's +45.1% in December 2011.

## 4. Architecture

### 4.1 One connector, three series

`reim/ingestion/connectors/regional/cepalstat_rates.py`, a `CepalstatConnector`
subclass whose `SERIES` tuple holds three `SeriesSpec` entries, exactly as
`cepalstat_monetary.py` holds M1, M2 and M3.

Three connectors were considered and rejected: they would triple the
boilerplate, make 6–9 requests instead of 4, and put the §3.7 spread invariant
out of reach, since no connector would see both series.

### 4.2 The period dimension is fetched once

`cepalstat_monetary.py` fetches `dimensions?lang=es` once per indicator — six
requests for three series. The period member table belongs to **dimension
3981**, not to any indicator, and it was measured byte-identical across 856,
857 and 1206 (the country table too). So this connector makes **four
requests**: three for data, one for dimensions.

To keep that from becoming an unchecked assumption, the connector asserts that
every period member id appearing in each data payload is present in the fetched
table. `_month_of` already raises `TransformationError` on an unknown member
id, so this falls out of the existing contract rather than needing new code.

### 4.3 The shared period logic moves into the base class

These five names move from `cepalstat_monetary.py` into
`reim/ingestion/connectors/regional/cepalstat.py`:

`PERIOD_DIMENSION`, `MONTHS_BY_SPANISH_NAME`, `NON_MONTH_MEMBERS`,
`_months_of`, `_month_of`

`cepalstat.py` is already where the shared CEPALSTAT concerns live —
`_members_of`, `_label_of`, `_value_of`, `_ensure_envelope_ok`,
`_check_monthly_continuity`. Dimension 3981's handling is one of them: it
belongs to the dimension, not to the monetary family.

This is a pure move — no behaviour change, no signature change — and
`cepalstat_monetary.py`'s existing tests pin the result. Copying the ~80 lines
instead would leave two implementations of the `descripcion_ingles` workaround
to fix when CEPAL renames a member.

### 4.4 Normalization

For each row whose country is one of the seven and whose period member is a
month:

| Field | Value |
|---|---|
| `indicator_code` | from the `SeriesSpec` |
| `period` | `parse_period(f"{year}-{month:02d}", Frequency.MONTHLY)` |
| `value_numeric` | the published `Decimal`, **unscaled** |
| `unit` | `percent per annum` |
| `currency_code` | `None` |
| `source_record_id` | `cepalstat:{cepal_id}:{iso3}:{year}-{month:02d}` |

`raw_metadata` carries `cepalstat_indicator_id`,
`cepalstat_published_value`, `cepalstat_published_unit`,
`cepalstat_source` (empty string when `source_id` is null),
`cepalstat_credits` and `contract_status`, matching the monetary connector.
There is no `cepalstat_scale_applied` key, because nothing is scaled.

`credits[0]` is CEPAL's own fetch date and changes between runs; it is dropped,
as elsewhere.

## 5. Comparability

`IndicatorDefinition` gains one field, beside `currency_convertible` and
documented the same way:

```text
#: Whether the publisher defines this indicator differently in each
#: country, so that levels may not be read against each other even when
#: the unit and currency match. CEPAL's interest rates declare this in
#: their own `calculation_methodology` field.
methodology_varies_by_country: bool = False
```

`assess_comparability` appends a note when any requested indicator declares it:

> CEPAL defines this rate differently in each country, so levels are not
> comparable; movements over time are.

**`comparable` stays `true`.** The flag's documented meaning is unit and
currency agreement, and the endpoint's rule is that comparability is declared,
never enforced — `/compare` states caveats and never refuses. Flipping the flag
would also widen what `comparable` means for every existing caller, and would
misreport a legitimate use: comparing how Guatemala's and Honduras's lending
rates *moved* is sound, and only the levels are not.

This requires threading the flag into `SeriesSummary`, which is the one place
`/compare` reads indicator metadata.

## 6. Indicators and quality rules

### 6.1 Indicator definitions

| Code | CEPAL | Name |
|---|---|---|
| `lending_rate_nominal_monthly` | 856 | Nominal lending rate (monthly) |
| `deposit_rate_nominal_monthly` | 857 | Nominal deposit rate (monthly) |
| `policy_rate_monthly` | 1206 | Monetary policy rate (monthly) |

Region-wide codes carry no country prefix, following `cpi_index_monthly`.

All three: `category=IndicatorCategory.FINANCIAL`, `frequency=MONTHLY`,
`unit="percent per annum"`, `value_type=ValueType.PERCENT`,
`currency_convertible=False`, `methodology_varies_by_country=True`,
`methodology_url` = the CEPALSTAT dashboard scoped to the indicator id.

Each `description` names the per-country instruments of §3.4, because that is
the caveat a reader needs at the point of reading the figure.
`policy_rate_monthly`'s also states that Panama is excluded and why.

### 6.2 Declarative rules

| Rule | lending | deposit | policy |
|---|---|---|---|
| `min_value` | 0 | 0 | 0 |
| `max_value` | null | null | null |
| `allow_negative` | false | false | false |
| `allow_zero` | false | false | **true** |
| `max_period_change_pct` | 60 | **null** | **null** |
| `monotonic_increasing` | false | false | false |
| `freshness_max_age_days` | 450 | 450 | 450 |
| `min_observations` | 2400 | 2350 | 1550 |

* **`allow_zero` is true for the policy rate only**, for Nicaragua's 2010-03
  and 2010-04 (§3.3). The other two series never publish a zero; their minima
  are 5.02 and 0.5.
* **`max_period_change_pct` is null for deposit and policy**, per §3.8.
  `cepalstat_rates_step` does the work instead.
* **`freshness_max_age_days` is 450**, the value
  `exchange_rate_nominal_monthly` already uses for the identical ~11-month
  CEPAL lag. Measured staleness on 2026-09-07 is 311–342 days, except the
  deposit rate for Belize, Costa Rica and Honduras at **372**. 450 passes that
  with 78 days of headroom and still fires if CEPAL stops extending the family.
  A threshold at the monthly cadence a reader would expect (90 days) would warn
  on **all twenty country-series on every run**, which is not the Honduras and
  Belize precedent: those work because the threshold fits the publication cycle
  and a single laggard breaks it.
* **`min_observations`** sits just under the measured 2,490 / 2,453 / 1,621.

### 6.3 Connector checks

| Check | Type | Severity | What it asserts |
|---|---|---|---|
| `cepalstat_rates_spread` | consistency | `critical` | lending > deposit in every shared country-month (§3.7) |
| `cepalstat_rates_step` | validity | `warning` | no calendar-adjacent move beyond 8 percentage points (§3.8) |
| `cepalstat_rates_expected_countries` | completeness | `critical` | each series covers exactly the countries measured, Panama's policy-rate absence encoded |
| `cepalstat_monthly_continuity` | completeness | `warning` | inherited; per country, so Panama's 33 deposit gaps and Nicaragua's 61 policy gaps are each reported |

`cepalstat_rates_step` compares **calendar-adjacent months only**, the rule
`cepalstat_cpi_known_splices` already establishes: comparing across a gap
manufactures a break that is really an absence.

### 6.4 Expected first-run result

`cepalstat_rates_expected_countries` and `cepalstat_rates_spread` pass.
`cepalstat_rates_step` passes. `cepalstat_monthly_continuity` warns on Panama's
deposit rate and Nicaragua's policy rate. Freshness passes on all twenty
country-series. Anything else is a finding, and `docs/sources.md` records this
expectation so a later reader can tell a regression from a known state.

## 7. Catalog entry

One entry, `cepalstat_rates_monthly`, listing all three indicators — the shape
`cepalstat_monetary_monthly` already uses for M1/M2/M3.

| Field | Value |
|---|---|
| `organization` | `CEPAL` |
| `category` | `financial` |
| `access_type` | `http_api` |
| `frequency` | `monthly` |
| `format` | `json` |
| `base_url` | `https://api-cepalstat.cepal.org/cepalstat/api/v1` |
| `connector` | `reim.ingestion.connectors.regional.cepalstat_rates` |
| `license` | `cepal_terms_of_use` |
| `official` | `true` |
| `enabled` | `true` |

## 8. Testing

**No test calls CEPAL.** The three data responses and the dimensions response
are recorded to `tests/fixtures/` as gzip and replayed through `respx`, as
every CEPALSTAT connector's tests already do.

Unit tests pin, at minimum:

* the `descripcion_ingles` trap — an English-only run must fail, proving the
  Spanish fetch is load-bearing rather than incidental;
* four requests, not six, and the dimensions request naming indicator 856;
* annual and quarterly members dropped, and a row naming an unknown period
  member raising `TransformationError`;
* Panama absent from `policy_rate_monthly` and present in the other two;
* Nicaragua's 2010-03 and 2010-04 zeros stored as zeros;
* values unscaled, and 856's two-decimal cells keeping both decimals against
  its declared `decimals: 0` (§3.5);
* Costa Rica's deposit rows carrying CEPAL's `CBBO` attribution unaltered
  (§2.2), so a later correction by CEPAL is visible as a test failure;
* null `source_id` on 1206 producing an empty attribution, not an exception;
* `cepalstat_rates_spread` failing on a constructed inversion and passing on
  the fixture;
* `cepalstat_rates_step` firing at 8.01 points and not at 7.

Behaviour tests cover the new comparability note appearing for these indicators
and staying absent for every existing one, and `comparable` remaining `true`.

`cepalstat_monetary.py`'s existing tests are the regression gate for the §4.3
move and must pass unchanged.

## 9. Decisions

| | Decision | Rationale |
|---|---|---|
| **D1** | All three indicators in one increment | Same shape, same requests, and the §3.7 spread invariant needs two of them in one connector |
| **D2** | Store the twelve monthly members only | Annual and quarterly are means of them (§3.2); storing a derived figure as published is ruled out |
| **D3** | Exclude Panama from `policy_rate_monthly` | 16 uniformly zero, wholly unattributed cells for a country with no central bank (§3.3) |
| **D4** | Store Nicaragua's two zeros | Real cells in a live attributed series; the El Salvador corrupt-cell precedent |
| **D5** | Values exactly as published, unscaled | Repo rule; and 856's declared decimals are wrong (§3.5) |
| **D6** | Declare varying methodology, note it, do not refuse | `/compare` states caveats and never refuses; movements remain comparable (§5) |
| **D7** | `max_period_change_pct` null for deposit and policy | Near-zero series make percentage change unbounded and meaningless (§3.8) |
| **D8** | `freshness_max_age_days` 450 | Matches `exchange_rate_nominal_monthly` at the identical CEPAL lag; 90 would warn on all twenty series forever (§6.2) |
| **D9** | Lift dimension-3981 handling into `cepalstat.py` | It belongs to the dimension, not the monetary family; avoids a second copy of the workaround (§4.3) |
| **D10** | One dimensions request, not three | The member table is dimension 3981's and was measured identical across all three indicators (§4.2) |
| **D11** | Store CEPAL's `CBBO` attribution for Costa Rica unaltered | REIM does not silently repair a publisher's provenance; it records the defect (§2.2) |

## 10. Out of scope

* **Deriving a spread series.** `lending − deposit` is a useful figure and REIM
  does not publish derived indicators without the transparency discipline
  `ROADMAP.md` reserves for v0.8.0. The spread is used as a *check*, not stored.
* **Real interest rates.** Deflating by the CPI would be a REIM derivation over
  two sources with different country coverage.
* **Indicator 857's quarterly and annual inconsistencies.** Measured in §3.2
  and dropped with the rest; nothing REIM stores depends on them.
* **The other five CEPALSTAT families** named in `docs/sources.md` under
  "Reachable, not ingested" — 547 and 361 remain there.
