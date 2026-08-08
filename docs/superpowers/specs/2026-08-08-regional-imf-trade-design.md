# Regional IMF merchandise trade — design

Status: **approved, not yet implemented**
Date: 2026-08-08
Roadmap item: v0.3.0, first sub-project

---

## 1. Scope, and why v0.3.0 was decomposed

v0.3.0 as written is five independent subsystems, one of which is really six
separate research efforts:

| Piece | Cost and risk | Depends on |
|---|---|---|
| **A. Regional IMF trade** | Low, measured — the connector exists | — |
| **B. Cross-country comparison endpoints** | Medium, API work, no external unknowns | A |
| **C. National central banks** (Banguat, BCR, BCH, BCCR, INEC, Belize) | **High, six independent investigations** | — |
| **D. SIECA** | Unknown, unresearched | — |
| **E. CEPALSTAT** | Unknown; a probe of its API returned 404 | — |
| **F. Currency handling** | Medium; not needed yet — everything multi-country is USD | C |

**This spec covers A only.** It was chosen because it is measured rather than
hoped: the connector shipped hours earlier already reads this dataflow, and all
six countries carry identical coverage. It also unblocks B, which has nothing to
compare today.

## 2. What is actually available

Measured against `IMF.STA,IMTS` with key `{country}..G001.M`:

| Country | Observations | Months | Span |
|---|---|---|---|
| Nicaragua (`NIC`) | 1,308 | 436 | 1990-M01 … 2026-M04 |
| Guatemala (`GTM`) | 1,308 | 436 | 1990-M01 … 2026-M04 |
| El Salvador (`SLV`) | 1,308 | 436 | 1990-M01 … 2026-M04 |
| Honduras (`HND`) | 1,308 | 436 | 1990-M01 … 2026-M04 |
| Costa Rica (`CRI`) | 1,308 | 436 | 1990-M01 … 2026-M04 |
| Panama (`PAN`) | 1,308 | 436 | 1990-M01 … 2026-M04 |
| **Belize (`BLZ`)** | **0** | — | **reports nothing** |

Belize was probed at monthly, quarterly and annual frequency, and without any
counterpart filter. It returns nothing in every case.

Total after this increment: **7,848 observations**, of which 1,308 already
exist for Nicaragua.

## 3. Decisions

| # | Decision | Rationale |
|---|---|---|
| R1 | The three IMTS indicators take **country-neutral codes**: `exports_goods_monthly`, `imports_goods_monthly`, `trade_balance_goods_monthly`. | `observations` already carries a country. Six country-prefixed variants of one concept would force B to map concept → six codes, duplicating what the country column resolves. |
| R2 | The other 16 `ni_*` indicator codes are **left alone**. | The rule is: prefix by country when the source is national and the methodology differs — a Guatemalan CPI is not a Nicaraguan one — and drop the prefix when the source is multilateral and the methodology is shared. Renaming all 19 would mark 8,388 stored observations as revised. |
| R3 | **Six catalog entries**, one per country, all pointing at the same connector module. | `source_key` is part of an observation's natural key, and seeding never deletes a source dropped from the catalog. Turning `imf_imts_nicaragua` into one regional source would leave its 1,308 rows orphaned under the old key and create 1,308 duplicates under the new one. Six entries is also idiomatic here: the catalog already holds six separate World Bank sources for Nicaragua. |
| R4 | The connector takes its country from the **catalog entry**, not a class constant. | Six sources, one module. `SourceEntry.country` is ISO-2; the ISO-3 the observation needs comes from `COUNTRIES_BY_ISO2`. |
| R5 | Belize gets **no catalog entry**, and its absence is documented. | An entry that can only fail is worse than a recorded gap. |
| R6 | The five inactive countries are **activated** in the country registry. | `Country.is_active` is seeded into the database and the `/countries` endpoint filters on it. Holding observations for a country marked inactive would be incoherent. |
| R7 | Quality rules are **unchanged**. | Verified against all six countries: the existing rules constrain sign only and set no upper bound, so they already span Nicaragua's smallest month (12.7 M USD) to Guatemala's largest (3,225 M USD). `min_observations: 300` still holds — each country's run produces 436 per series. |

### The cost of R1, stated plainly

`indicator_code` is part of the natural key, so renaming the three IMTS
indicators means their existing rows stay under the old codes and new rows
appear under the new ones.

That cost is **1,308 rows, one commit old, in a local test database that is
regenerated in four seconds**, and there is no deployment anywhere. It is not
the 8,388-row migration rejected in R2. Anyone who has run the pipeline should
delete observations for `ni_exports_goods_monthly`,
`ni_imports_goods_monthly` and `ni_trade_balance_goods_monthly` once, or drop
and reseed.

## 4. Components

### 4.1 `reim/domain/indicators/registry.py`

The three IMTS entries are renamed and their descriptions generalised: they no
longer say "Nicaragua", because one definition now serves six countries. Name
becomes e.g. "Merchandise exports FOB (monthly)". Category, frequency, unit
(`current USD`), value type (`LEVEL`) and `methodology_url` are unchanged.

`COUNTRIES` gains `is_active=True` for Guatemala, El Salvador, Honduras, Costa
Rica and Panama. **Belize stays `is_active=False`** — REIM holds no data for it.

### 4.2 `sources/quality_rules.yml`

The three rule-set keys are renamed to match R1. **No threshold changes.** The
comment explaining why the balance carries no lower bound is updated to say the
figure is negative in the great majority of months across the region, not just
in 433 of Nicaragua's 436.

### 4.3 The connector: a shared base plus six thin subclasses

This follows the pattern the codebase already uses for the World Bank — a base
in `connectors/common/` and one small subclass per catalog entry, each setting
little more than `connector_key`.

* **`reim/ingestion/connectors/common/imf_imts.py`** — the existing connector
  body moves here as `ImfImtsTradeConnector`, with **no** `connector_key`. It
  becomes the shared base, next to `common/worldbank.py`.
* **`reim/ingestion/connectors/nicaragua/imf_imts_trade.py`** stays where it is,
  reduced to a subclass with `connector_key = "imf_imts_nicaragua"`. Its module
  path and catalog key are unchanged, so the Nicaragua entry needs no edit at
  all.
* **Five new country packages** — `guatemala/`, `el_salvador/`, `honduras/`,
  `costa_rica/`, `panama/` — each with an `__init__.py` and one
  `imf_imts_trade.py` holding an eight-line subclass. They will hold that
  country's national connectors when piece C arrives.

An earlier draft of this design instead kept one class for all six entries and
loosened `BaseConnector`'s guard that `source.key == connector_key`. That was
rejected: the guard is what stops a catalog entry pointing at the wrong module,
and the codebase already had a better idiom that leaves the contract untouched.

In the base, `country_iso3` stops being a `ClassVar` and becomes a property:

```python
@property
def country_iso3(self) -> str:
    """ISO-3 of the country this catalog entry covers."""
    iso2 = self.source.country_iso2
    if iso2 is None:
        msg = f"{self.source.key} must declare a country"
        raise ExtractionError(msg, source_key=self.source.key)
    definition = COUNTRIES_BY_ISO2.get(iso2)
    if definition is None:
        msg = f"{self.source.key} names unknown country {iso2!r}"
        raise ExtractionError(msg, source_key=self.source.key)
    return definition.iso3
```

`request_url` interpolates `self.country_iso3` instead of the constant.
`INDICATORS` maps to the new country-neutral codes. `transform` is otherwise
unchanged; it already reads each row's own fields.

`validate` gains one check: **every observation must carry the catalog entry's
country**. A row for another country means the key or the response was wrong.

### 4.4 `sources/catalog.yml`

Six entries, `imf_imts_{nicaragua,guatemala,el_salvador,honduras,costa_rica,panama}`,
differing only in `key`, `name`, `country`, `description` and `connector`. All
carry `license: imf_terms_of_use`.

The **Nicaragua entry is untouched**: its key and connector path are the ones it
already has. Only five entries are added.

## 5. Testing

The recorded Nicaragua fixture is reused, and one Guatemala fixture is recorded
alongside it so the tests can prove the country comes from the catalog rather
than a constant.

New or changed unit tests:

* each of the six catalog entries builds a connector whose `country_iso3`
  matches its declared country
* transforming the Guatemala fixture yields `country_iso3 == "GTM"` on every
  observation, and the Nicaragua fixture `"NIC"`
* **Guatemala's and Nicaragua's exports differ for the same month** — the one
  failure mode counts cannot catch, since both countries return 436 identical-shaped
  months; a country-mapping bug would look like success
* a response carrying a foreign country fails the new validate check
* a catalog entry without a country raises rather than defaulting to Nicaragua
* the existing Nicaragua assertions keep passing with the renamed indicators

## 6. Expected result

Six pipelines, ~790 KB each, **7,848 observations** across three shared
indicators and six countries, 1990-01 to the latest published month.

## 7. Risks

| Risk | Mitigation |
|---|---|
| A country-mapping bug files Guatemala's data under Nicaragua. | Counts cannot detect it — all six countries have identical shape. The "Guatemala differs from Nicaragua" test exists for exactly this, plus the per-country validate check. |
| The rename leaves duplicate Nicaragua rows behind. | Documented in §3 with the one-line cleanup; the affected data is one commit old and regenerable. |
| Six pipelines multiply requests against an official service. | Six requests of ~790 KB per run. The alternative — one multi-country key, which does work and returns all 7,848 rows in 1.38 s — was rejected under R3 because it would duplicate Nicaragua's stored series. |

## 8. Out of scope

* Pieces B–F of v0.3.0, each of which gets its own spec.
* Belize, which reports nothing to IMTS.
* Trade by partner country — the data supports 103 counterparts, but that is a
  different shape of series needing its own indicator modelling.
* Renaming the 16 `ni_*` indicators that come from national or annual sources.
