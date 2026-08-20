# CEPALSTAT monetary aggregates — design

Status: **approved, not yet implemented**
Date: 2026-08-19
Roadmap item: v0.2.0, the monetary-aggregates line the roadmap gave up on

---

## 1. What the roadmap recorded, and what is actually there

`ROADMAP.md` states, under v0.2.0, that Nicaragua's monetary aggregates are
reachable only from SECMCA, which requires a credentialed account. That was the
reason the item stayed open.

**CEPALSTAT publishes them, monthly, with no authentication.** Indicators 862,
868 and 869 carry M1, M2 and M3 for the seven Central American countries. The
GDP increment shipped on 2026-08-19 recorded this in `docs/sources.md` as
reachable-but-not-ingested; this increment ingests it.

Nothing in the earlier record was wrong. It was written before anyone probed
these three ids.

## 2. The source

Same host, same protocol and the same two dimension ids as the GDP connector
(`docs/superpowers/specs/2026-08-18-cepalstat-gdp-design.md` §2 covers the API,
its lack of documentation, and how its routes were recovered — none of that is
repeated here).

| | |
|---|---|
| **Organization** | Comisión Económica para América Latina y el Caribe (`CEPAL`) |
| **Endpoint** | `GET /cepalstat/api/v1/indicator/{id}/data?lang=en` |
| **Dimensions** | country `208`, **period `3981`** (new), years `29117` |
| **Frequency** | Monthly |
| **Volume** | 1.4–1.6 MB per indicator, ~9 s |
| **Licence** | Unchanged from the GDP entry: not open, non-commercial only |

| CEPAL id | Published name (`lang=en`) | Published unit | REIM indicator |
|---|---|---|---|
| 862 | Money (M1), end of period | Millions of units in local currency | `money_m1_monthly` |
| 868 | Liquidity (M2), end of period | Millions of units in local currency | `money_m2_monthly` |
| 869 | Broad liquidity (M3), end of period | Millions of units in local currency | `money_m3_monthly` |

The API's own `calculation_methodology` defines the family: M1 is currency with
the public plus demand deposits, `M2 = M1 + savings deposits`, and
`M3 = M2 + foreign currency deposits`. That definition is the basis of the
nesting check in §7.

## 3. The period dimension, and why one request is made in Spanish

Dimension 3981 has 17 members: twelve months, four quarters and an annual
figure. **In `lang=en` all seventeen come back as the literal string
`descripcion_ingles`** — the untranslated column name of CEPAL's own database
leaking through the API. The English response cannot tell a month from a
quarter from the annual figure.

The member ids cannot be pinned or inferred either, because **they are not in
calendar order**:

```text
3982 Anual         3987 Enero      3993 Septiembre
3983 Trimestre 1   3988 Febrero    3994 Julio
3984 Trimestre 2   3989 Marzo      3995 Agosto
3985 Trimestre 3   3990 Abril      3996 Diciembre
3986 Trimestre 4   3991 Mayo       3997 Octubre
                   3992 Junio      3998 Noviembre
```

September, July, August, December, October and November are scrambled. This is
the same lesson the GDP connector recorded about year members — `year = id -
27170` looked true and was not — arriving in a form where the arithmetic is not
merely undocumented but visibly false.

**The resolution keeps decision C7 (`lang=en`) intact for the data.** `extract`
makes six requests: three for data in `lang=en`, and three to
`/indicator/{id}/dimensions?lang=es` at 29 KB each, whose only purpose is to
learn which member id is which month. Everything REIM stores — unit, `sources`,
`credits` — stays English and consistent with what the GDP connector already
wrote to the same database. Requesting the bulk data in Spanish would have
translated all of it.

The 17 member ids are identical across the three indicators, so one dimensions
request would serve all three. Each indicator fetches its own anyway: a payload
is interpreted with its own member table rather than one borrowed from a
sibling, which is the same principle by which the GDP connector reads year
labels from the response instead of computing them. The cost is 87 KB against
4.8 MB.

## 4. What measuring established

Measured on 2026-08-19 against complete responses for all three indicators.

**Only the monthly member carries information.** The annual figure is exactly
December's, and each quarter is exactly its closing month:

| Identity | Cells compared | Exceptions |
|---|---|---|
| `Anual` == `Diciembre` | 453 | **0** |
| `Trimestre N` == its closing month | 1,800 | **0** |

These are end-of-period stocks, so the restatement is definitional rather than
coincidental. The annual and quarterly members are therefore excluded, on the
rule that already excluded the GDP growth-rate series 2207 and SIECA's `VP`,
`PT` and `PC` units.

**The family nests, and the apparent violations are rounding.** CEPAL declares
`decimals: 0` but publishes some series rounded to whole millions and others to
one decimal:

| Identity | Shared cells | Violations | Worst absolute | Worst relative |
|---|---|---|---|---|
| M1 ≤ M2 | 1,611 | 116 | 0.4 million | 0.014040 % |
| M2 ≤ M3 | 1,331 | 113 | 0.5 million | 0.005047 % |
| M1 ≤ M3 | 1,746 | **0** | — | — |

Every one of the 229 violations has an integer-formatted value on one side of
the comparison. M1 ≤ M3 never fails because the gap between the narrowest and
widest aggregate is far wider than a rounding step.

**Coverage is complete but uneven, and the unevenness is the source's.** No gaps
in any of the 21 country-indicator series:

| | M1 (862) | M2 (868) | M3 (869) |
|---|---|---|---|
| **BLZ** | 1990-01 … 2024-07 (415) | **absent** | 1990-01 … 2024-07 (415) |
| **CRI** | 2001-12 … 2024-06 (271) | 2001-12 … 2024-06 (271) | 2001-12 … 2024-06 (271) |
| **GTM** | 2001-12 … 2024-08 (273) | 2001-12 … 2024-08 (273) | 2001-12 … 2024-08 (273) |
| **HND** | 2001-12 … 2023-10 (263) | 2001-12 … 2023-10 (263) | 2001-12 … **2023-03** (256) |
| **NIC** | 2001-12 … 2024-06 (271) | 2001-12 … 2024-06 (271) | 2001-12 … 2024-06 (271) |
| **PAN** | 2002-12 … 2024-07 (260) | 2002-12 … 2024-07 (260) | 2002-12 … 2024-07 (260) |
| **SLV** | 2001-12 … 2024-08 (273) | 2001-12 … 2024-08 (273) | **absent** |
| | **2,026** | **1,611** | **1,746** |

Belize contributes thirty-five years where the others contribute twenty-three,
and is absent from M2. El Salvador is absent from M3. No single "seven countries
present" expectation fits; each indicator carries its own.

**The data is old, and Honduras is much older than the rest.** Ages as of
2026-08-19: 718 days for Guatemala and El Salvador, 749 for Belize and Panama,
780 for Costa Rica and Nicaragua, **1,023** for Honduras M1 and M2, and
**1,237** for Honduras M3. The source itself is maintained — 862's `last_update`
reads July 2026 — so the roughly two-year lag is how this dataset is published,
not evidence of a frozen feed.

**Worst real month-on-month movement:** 45.93 % (Panama, November 2006, M1
moving from 1,984.6 to 2,896.2 and settling at 2,610.3 the next month), then
25.55 % (Panama, January 2014, M2) and 30.10 % (Guatemala, December 2003, M3).

**Values arrive as JSON strings**, as in the GDP payloads, so `Decimal(str)` is
exact. The parser is pinned with `parse_float=Decimal` anyway, for the reason
SIECA's design records.

## 5. Decisions

| # | Decision | Rationale |
|---|---|---|
| M1 | **One connector, one catalog entry, three indicators.** | The nesting identity is only expressible when one connector sees all three, exactly as the population identity was for GDP. |
| M2 | **Only the monthly member is stored.** | The annual and quarterly members are exact restatements — 2,253 cells checked, zero exceptions. Same rule as GDP 2207 and SIECA's derived units. |
| M3 | **Three indicator codes, unit and currency per observation.** | REIM's first indicator whose unit varies by country. The alternative — 21 country-prefixed codes — would inflate the registry from 28 to 49 and contradict decision C8, which drops the country prefix for regional sources. |
| M4 | **Currency comes from the country registry**, not from the payload. | The registry already holds `NIO`, `GTQ`, `HNL`, `CRC`, `BZD`, `USD` (SLV) and `PAB` (PAN). CEPAL says only "local currency". No new configuration. |
| M5 | **Stored in whole units of local currency** (`× 10^6`). | Every level series in REIM is in whole units of its currency; three indicators in millions would force consumers to read the unit string to know the magnitude. Exact in `Decimal`, and the published figure is kept in `raw_metadata`. Makes CEPAL the third converted source, where the README currently says two. |
| M6 | **No conversion to USD, and comparability left declared-false.** | REIM holds daily rates for two of the seven currencies only, so a conversion would be both impossible for most and an invention. `/compare` already declares comparability rather than enforcing it. El Salvador and Panama are dollarised, so those two series alone are directly comparable. |
| M7 | **Bulk data in `lang=en`; one 29 KB dimensions request per indicator in `lang=es`.** | See §3. Keeps C7 and keeps stored metadata in one language. |
| M8 | **An unknown period member raises.** | If CEPAL renames a month or adds a member, the connector fails loudly rather than silently dropping rows — the rule the GDP connector applies to unmapped years. |
| M9 | **The shared CEPALSTAT base class is extracted last**, once both connectors exist. | Deciding what to share before writing the second implementation is predicting the shared surface rather than reading it. Sequenced as its own task with its own commit so that an interrupted increment leaves a working duplicate rather than a half-built abstraction. |

## 6. Components

### 6.1 `reim/domain/indicators/registry.py`

Three definitions, category `MONETARY` — declared in `IndicatorCategory` since
v0.1.0 and unused until now — frequency `MONTHLY`, value type `LEVEL`.

The indicator-level `unit` reads `units of local currency`, which is the only
honest thing it can say for a code spanning seven currencies. Each observation
then carries the concrete pair: `unit="NIO"` with `currency_code="NIO"` for
Nicaragua, `unit="CRC"` with `currency_code="CRC"` for Costa Rica, and so on.
The indicator names the family; the observation names the money.

### 6.2 `sources/catalog.yml`

One entry, `cepalstat_monetary_monthly`, licence `cepal_terms_of_use`,
`official: true`, listing the three indicators. Ships `enabled: false` with a
`disabled_reason` and is enabled only after a real end-to-end run, as every
connector before it.

### 6.3 `reim/ingestion/connectors/regional/cepalstat_monetary.py`

`extract` issues six requests — three data, three dimensions — validating each
envelope with CEPAL's own `header.success`, which can disagree with the HTTP
status. The payload is a mapping of indicator id to both texts.

`transform` builds the period member table from the Spanish dimensions
response, keeps the twelve months, drops the annual and quarterly members,
filters rows to `CENTRAL_AMERICA` membership (regional aggregates arrive with
`iso3: null` and fall out of the same test), assembles `YYYY-MM` periods,
resolves each country's currency from the registry and scales by `10^6`.

`raw_metadata` carries `cepalstat_published_value`, `cepalstat_published_unit`,
`cepalstat_scale_applied`, `cepalstat_indicator_id`, `cepalstat_credits` and
`cepalstat_source`, matching the GDP connector. `credits[0]` is excluded: it is
CEPAL's own fetch date and moves between runs.

The connector declares no `currency_code` class variable, because it has no
single one.

### 6.4 `reim/domain/quality/checks.py`

No change. The per-country walk added on 2026-08-19 already covers
`period_change`, `temporal_monotonicity` and `freshness` for a batch holding
seven countries.

## 7. Quality

**Three connector checks.** A fourth — asserting each observation's currency
matches the registry — was considered and rejected: both sides are static, so
it is a code invariant belonging in a unit test, not a per-run check.

| Check | Type | Severity | What it asserts |
|---|---|---|---|
| `cepalstat_monetary_nesting` | consistency | `error` | M1 ≤ M2 ≤ M3 in every shared cell, within a 0.1 % relative tolerance |
| `cepalstat_monetary_expected_countries` | completeness | `critical` | The expected country set **per indicator**: seven for M1, six without Belize for M2, six without El Salvador for M3 |
| `cepalstat_monthly_continuity` | completeness | `warning` | No gaps inside each country's own span |

The tolerance on the nesting check is seven times the worst rounding artefact
measured (0.014 %) and orders of magnitude below any real inversion, which would
be percent-scale. Encoding the two absences in the second check turns "Belize is
missing from M2" from an accident into a stated expectation, so that its
appearance — or another country's disappearance — is visible.

**Rules in `sources/quality_rules.yml`:**

| | `min_observations` | `max_period_change_pct` | `freshness_max_age_days` |
|---|---|---|---|
| `money_m1_monthly` | 1950 | 60 | 900 |
| `money_m2_monthly` | 1550 | 60 | 900 |
| `money_m3_monthly` | 1680 | 60 | 900 |

The 60 % ceiling clears the worst real movement (45.93 %) while still catching a
`10^6` scale error, which would present as roughly one hundred million percent.

**The freshness threshold is deliberately one that Honduras fails.** At 900
days, Honduras warns on all three indicators from the first run and the other
six countries pass. Setting it at 1,300 would turn every light green, but that
is tuning a threshold until it stops speaking: Honduras M3 really is three and a
half years behind. The check is `warning` severity, so nothing is blocked, and
the YAML comment records the measured ages so the next reader knows the warning
is expected rather than new.

## 8. Testing

Six recordings, complete and byte-for-byte, gzipped as
`tests/fixtures/README.md` requires — roughly 310 KB in total (107, 85 and
105 KB of data, plus about 4 KB per dimensions response). This is the largest
fixture set in the repository; the precedent is Banguat's 1.33 MB XML stored at
90 KB. The responses are kept complete rather than trimmed to the seven
countries because the 145 countries they carry are what proves the connector's
filter works at all.

Unit tests cover the fixtures' own shape, the transform, the three checks and
`extract`'s six requests. Two are specific to this increment: one pinning that
the annual and quarterly members are discarded, and one checking the nesting
against the three published series rather than a computed one. An opt-in `live`
test confirms the API still answers in the recorded shape.

## 9. Volume, and what it changes

**5,383 observations** — 2,026 + 1,611 + 1,746 — from six requests. REIM moves
from roughly 43,000 observations to 48,400, from 28 indicators to 31, and from
17 pipelines to 18. It is the first use of the `monetary` category and the first
data REIM holds in a currency other than the US dollar, the córdoba and the
quetzal.

`docs/sources.md` gains a section for the family and loses its
reachable-but-not-ingested row. `ROADMAP.md` closes the v0.2.0 monetary line,
which named SECMCA and a credentialed account as the only route. The README
gains the source row, the counts, and a third entry in its converted-sources
statement.

## 10. Out of scope

* **Public debt, indicators 1239 and 1240.** Reachable, and recorded in
  `docs/sources.md`. Four dimensions, with institutional coverage and a debt
  classification to select; it needs its own design.
* **The annual and quarterly members**, as exact restatements of a month.
* **The 138 other countries and the regional aggregates.**
* **Any conversion to a common currency.** REIM would become the author of a
  figure CEPAL does not publish.
* **Filling Belize's M2 gap or El Salvador's M3 gap** from another publisher.
  Mixing sources inside one indicator would break the provenance guarantee REIM
  exists to keep.
