# CEPALSTAT annual GDP — design

Status: **approved, not yet implemented**
Date: 2026-08-18
Roadmap item: v0.3.0, piece E

---

## 1. What the roadmap recorded, and what is actually there

Two places in this repository state that CEPALSTAT's API answers `404`:
`docs/implementation-plan.md:388` ("open; a probe of its API returned 404") and
`docs/superpowers/specs/2026-08-08-regional-imf-trade-design.md:20`.

**Both are wrong, and this increment corrects them.** The API is live and
healthy. The earlier probe used paths that do not exist; every CEPALSTAT
endpoint is scoped to an indicator id, and a bare collection path returns `404`
by design. Measured on 2026-08-18:

| Path | Result |
|---|---|
| `GET /` | `200` — `{"name":"uneclac cepalstat api","version":"1.9.13"}` |
| `GET /cepalstat/api/v1/indicator` | `404` — no collection endpoint exists |
| `GET /cepalstat/api/v1/indicator/2206/data?lang=es` | **`200`, 177 KB, 1,296 rows, 0.66 s** |
| `GET /cepalstat/api/v1/indicator/{id}/metadata`, `/dimensions`, `/sources`, `/footnotes` | `200` |
| `GET /cepalstat/api/v1/themes`, `/areas`, `/thematic-tree` | `200` |

**There is no published API documentation.** The base URL and the endpoint
names were recovered from the portal's own JavaScript:
`https://statistics.cepal.org/portal/databank/config.js` declares
`API_BASE_URL` and `ENDPOINT_THEMATIC_TREE`, and
`https://statistics.cepal.org/portal/cepalstat/dash/scripts/config.js` declares
the per-indicator data, dimensions, sources and notes routes. The connector
module docstring records this so nobody repeats the search.

**Indicator ids cannot be listed from an area.** `/themes` and `/areas` return
the full tree of 1,785 areas — 33 of them economic — but no route maps an area
to its indicators. `/thematic-tree?lang=es&theme_id=6` does: it returns 330
leaves, each with an `indicator_id`. That tree is also **not clean** — 45 of the
330 leaves are working artefacts named `dummy`, `CLONE` or `TEST`. Ids are
therefore pinned in this design and in the catalog, not discovered at runtime,
exactly as SIECA's filter ids are.

## 2. The source

| | |
|---|---|
| **Organization** | Comisión Económica para América Latina y el Caribe (`CEPAL`) — in `organizations.py:103` since v0.1.0, never used |
| **Host** | `https://api-cepalstat.cepal.org` |
| **Endpoint** | `GET /cepalstat/api/v1/indicator/{id}/data?lang=en` |
| **Protocol** | Undocumented REST JSON. Envelope of `header` / `body` / `footer` |
| **Auth** | None. No User-Agent filter, no TLS quirk |
| **Coverage** | **1990 … 2025**, verified — 36 years, no gaps, for all seven countries |
| **Countries** | 33 Latin American and Caribbean, plus 3 regional aggregates |
| **Volume** | 167–177 KB per indicator, 0.66 s |

One request returns an indicator's entire matrix: every country, every year, no
pagination and no window to compute. `body` carries `metadata` (unit,
definition, theme, area), `data`, `dimensions` with their members, `sources`,
`footnotes` and `credits`. Each data row carries its own `iso3`, `source_id`
and `notes_ids`.

**The four indicators this increment ingests:**

| CEPAL id | Published name (`lang=en`) | Published unit |
|---|---|---|
| 2203 | Total Annual Gross Domestic Product (GDP) at current prices in dollars | Millions of dollars |
| 2204 | Total Annual Gross Domestic Product (GDP) at constant prices in dolllars | Millions of dollars |
| 2205 | Total Annual GDP per inhabitant at current prices in dollars | Dollars per inhabitant at current prices |
| 2206 | Total Annual GDP per inhabitant at constant prices in dollars | Dollars per inhabitant |

The tripled `l` in 2204's English name is CEPAL's own typo, recorded here so it
does not read as a transcription error. REIM stores its own indicator names, so
it does not propagate.

## 3. The licence decision

**CEPAL's terms expressly prohibit what REIM does with the data.** The
[website usage agreement](https://www.cepal.org/en/terminos-y-condiciones-sobre-el-uso-del-sitio-web-entre-la-cepal-y-el-usuario)
grants users the right to

> download and copy information, documents and material … for Users' personal,
> non-commercial use without any right to resell, redistribute or create
> derivative works therefrom

The [repository terms](https://repositorio.cepal.org/page/termsofuse?locale-attribute=en)
repeat the non-commercial restriction. The CEPALSTAT portal, the data bank and
the technical-sheet page publish no separate, more permissive licence — checked
on 2026-08-18. The API itself returns a `credits` block on every response
(`["<date>", "CEPALSTAT", "Comisión Económica para América Latina y el
Caribe – CEPAL", "Naciones Unidas"]`), which functions as a required citation.

This is **stricter than either precedent in the catalog.** The IMF is "not open,
but redistributable with attribution" (`docs/sources.md:348`). SIECA is an
*absence* of any grant — there are no terms to read (`docs/sources.md:564`).
CEPAL is an *explicit prohibition*, and REIM redistributes through its API.

**Decision, taken explicitly by the project owner: ingest, and document the
exception rather than hide it.** Concretely:

* `license: cepal_terms_of_use` in the catalog entry.
* A `docs/sources.md` section quoting the terms verbatim and stating the
  conflict in plain words.
* The API's `credits` block propagated into every observation's `raw_metadata`,
  so the required citation travels with the data.
* **The ROADMAP line is rewritten, not excepted.** "Explicitly not planned —
  Scraping paywalled or licence-restricted data. Official and openly licensed
  only" (`ROADMAP.md:172-173`) is already contradicted by the IMF and SIECA
  entries that shipped after it. It gets restated as what the project actually
  does: official publishers only, licence terms recorded honestly per source,
  and no source whose access requires defeating an active control. This follows
  the pattern SIECA set — when a new source contradicts a stated rule, the rule
  is rewritten rather than quietly broken.

## 4. What measuring established

**The four series share a checkable internal identity.** `total ÷ per capita`
recovers the implied population, and it must agree between the current-price
and constant-price pair. Measured across all 252 country-year cells, the worst
relative disagreement is **8.1 × 10⁻¹⁶** — floating-point noise. Nicaragua 2024
yields exactly 7,142,500 by both routes. This is the strongest cross-series
consistency check in REIM to date, and **it exists only because all four series
live in one connector**.

**The growth-rate series is exactly derivable and is therefore excluded.**
CEPAL publishes indicator 2207 (growth rate of constant-price GDP). Computed
from 2204 it reproduces the published figure to the last digit across all 36
Nicaraguan years — worst deviation **0.000000 percentage points**. SIECA's
design excluded its `VP`, `PT` and `PC` units on exactly this ground
(`docs/sources.md:618-621`); the same rule applies here rather than being
excepted for one source.

The per-capita series are **not** derivable. They divide by CELADE's harmonised
population estimates, and REIM stores no population series, so 2205 and 2206
carry information that 2203 and 2204 cannot reconstruct.

**The base year lives in a footnote, not in the unit.** 2204 and 2206 declare
their unit as `Millions of dollars` and `Dollars per inhabitant`; the only
statement of the base year is `footnotes: [{"id": 12080, "description": "At
prices 2018"}]`. A rebasing would change every constant-price value while the
unit string stayed still. That is a quality check, not a comment.

**Belize is fully covered.** All 36 years, all four indicators. Belize is
registered in `countries/registry.py:93` as `is_active=False` because it reports
nothing to the IMF's IMTS dataflow; CEPALSTAT gives it its first data.

**Values arrive as JSON strings, but the connector still parses with
`parse_float=Decimal`.** `body.data[].value` is a quoted string today
(`"3324.993693403936"`), so `Decimal(str)` is exact. The parser is pinned
anyway: if CEPAL ever emits bare JSON numbers, plain `json.loads` would corrupt
every figure in its last places, where no count or total would reveal it — the
failure SIECA's design documents.

**Worst real year-on-year change across the four series is 23.0 %** (Guatemala,
1991, current-price total; the other three peak at 18.0 %, 22.2 % and 19.0 %).
That sets a `max_period_change_pct` which catches a scale error without
rejecting real history.

## 5. Decisions

| # | Decision | Rationale |
|---|---|---|
| C1 | **One connector, one catalog entry, four indicators.** | The population identity is only expressible when one connector sees all four series. Four separate entries would also multiply near-identical configuration for a family the publisher issues as one. |
| C2 | **No generic id-parameterised CEPALSTAT engine.** | Speculative generality that would not serve what comes next: the monetary indicators carry three dimensions and the public-debt ones four, with members to select. An engine built today on country × year absorbs neither. |
| C3 | **Seven Central American countries only**; the other 26 and the 3 aggregates are filtered out. | REIM is a Central American monitor. Filtering on `iso3` membership needs no name table — the aggregates arrive with `iso3: null` and fall out of the same condition. |
| C4 | **Belize is activated.** | It has complete coverage here. Enabling a country is a data change, as `countries/registry.py:5` already states. |
| C5 | **The growth-rate series (2207) is excluded.** | Exactly derivable from 2204. Same rule SIECA applied to its derived units. |
| C6 | **Totals converted to whole USD** (`× 10^6`); per-capita figures stored unscaled. | Matches the IMF and SIECA series so `/compare` can put them side by side. The conversion is exact in `Decimal`, reversible, and declared in `raw_metadata`. |
| C7 | **`lang=en`.** | REIM's stored metadata is English throughout. Spanish remains available and the choice is one query parameter. |
| C8 | **Indicator codes carry no country prefix.** | The rule the regional-trade increment set and SIECA followed: drop the prefix when the source is regional and every country shares the methodology. |
| C9 | **Figures are labelled as CEPAL estimates, not national statistics.** | The API's own `sources[]` says "Own estimates based on national sources". Regional comparability is bought at the price of figures that need not match any country's official GDP, and `docs/sources.md` says so in prose, not only in a JSON field. |

## 6. Components

### 6.1 `reim/domain/indicators/registry.py`

Four definitions, category `REAL_SECTOR`, frequency `ANNUAL`, value type
`LEVEL`. REIM holds no GDP from any source today; this is the catalog's largest
single gap.

| Code | CEPAL id | REIM unit | Scale |
|---|---|---|---|
| `gdp_current_usd_annual` | 2203 | `current USD` | × 10^6 |
| `gdp_constant_usd_annual` | 2204 | `constant 2018 USD` | × 10^6 |
| `gdp_per_capita_current_usd_annual` | 2205 | `current USD per person` | × 1 |
| `gdp_per_capita_constant_usd_annual` | 2206 | `constant 2018 USD per person` | × 1 |

Descriptions state that these are CEPAL's harmonised estimates and that the
constant-price pair is expressed at 2018 prices using CEPAL's base-year
reference exchange rate.

`methodology_url` points at the indicator's own dashboard page, the closest
stable reference CEPAL publishes — the same accommodation already made for
Banguat and SIECA.

### 6.2 `sources/quality_rules.yml`

One rule set shared by the two totals, one by the two per-capita series. Every
threshold below is anchored to a measured figure rather than chosen:

* `min_observations: 240` — the real count is 252 per indicator (7 × 36). The
  margin absorbs a year of genuine gap while still catching a truncated run.
* `max_period_change_pct: 40` — the worst real change across the four series is
  23.0 %. This catches the failure that matters most, a mistaken `× 10^6`,
  which would appear as a jump of eight figures.
* `allow_negative: false`, `allow_zero: false` — the smallest real total is
  546.75 million USD and the smallest real per-capita figure is 704.39 USD.
  Neither series approaches zero, and a GDP that did would be news, not noise.
* `freshness_max_age_days: 600` — the newest period ends 2025-12-31, 230 days
  before this design. 600 tolerates CEPAL's annual publication cycle and still
  reports a source that has frozen.

### 6.3 `reim/ingestion/connectors/regional/cepalstat_gdp.py`

`CepalstatGdpConnector`, in the existing `regional` package next to SIECA.
`connector_key = "cepalstat_gdp_annual"`, `version = "1.0.0"`,
`expected_frequency = Frequency.ANNUAL`.

**`extract`** issues four `GET` requests, one per indicator id, and returns the
four response bodies keyed by id. `ensure_ok` requires a JSON content type.

Two source-specific failures are handled beyond that:

* **The envelope carries its own status, and the HTTP code can disagree with
  it.** An unknown indicator id returns **HTTP `500`** with `success: false` —
  not `404`. `extract` reads `header.success` explicitly and raises
  `ExtractionError` quoting CEPAL's `header.code` and `header.message`, the same
  pattern SIECA applies to `Resultado` / `Mensaje`.
* **An empty `body.data` raises rather than yielding zero observations.** A run
  that returns nothing is a failure, and silencing it turns a broken source into
  a quiet one.

**`transform`** is a pure function of the payload. It builds the
`member_id → year` map from the `Years__ESTANDAR` dimension, keeps only rows
whose `iso3` is one of the seven, parses values with `parse_float=Decimal`,
scales the totals, and emits one observation per indicator, country and year
with `source_record_id = cepalstat:{indicator_id}:{iso3}:{year}`.

`raw_metadata` keeps the published value and unit, the scale applied, the
`source_id` with its description, the `notes_ids` with their footnote text, and
the `credits` block.

A missing years dimension, an unmapped `dim_29117` member or an unparseable
value raises `TransformationError`. Dropping a non-Central-American `iso3` is
not a failure — it is the deliberate filter of C3, and the completeness check
below is what guards it.

**`validate`** returns four checks:

| Check | Type | Severity on failure |
|---|---|---|
| `cepalstat_seven_countries_present` — all seven, Belize included | completeness | `critical` |
| `cepalstat_population_identity` — implied population agrees between the current and constant pairs, relative tolerance 10⁻⁹ | consistency | `error` |
| `cepalstat_constant_price_base_year` — the footnote on 2204 and 2206 still names 2018 | validity | `error` |
| `cepalstat_annual_continuity` — no missing year between first and last | completeness | `warning` |

All four are dataset-level, carrying no `observation_index`, so an `error` marks
the whole dataset per `runner.py:309-316`. That is the intended reading: if the
population identity breaks there is no single guilty row, there are two series
that stopped agreeing.

The tolerance of 10⁻⁹ sits six orders of magnitude above the worst observed
disagreement, so the check cannot fire on arithmetic noise.

### 6.4 `sources/catalog.yml`

One entry, `cepalstat_gdp_annual`: no `country`, organization `CEPAL`, category
`real_sector`, `access_type: http_api`, `frequency: annual`, `format: json`,
`license: cepal_terms_of_use`, enabled.

`base_url` is `https://api-cepalstat.cepal.org/cepalstat/api/v1`.
`documentation_url` points at the CEPALSTAT portal, with the connector docstring
recording that no API documentation exists and how the routes were found.

No `user_agent` override and no `tls_profile` change: the host serves REIM's own
identifier without complaint.

### 6.5 `reim/domain/countries/registry.py`

Belize becomes `is_active=True`. Its comment currently asserts that REIM holds
no data for it; that stops being true with this increment, so the comment is
rewritten to name what it now has and why it is still absent from the IMF
series.

## 7. Testing

Four fixtures recorded live at `lang=en`, byte for byte, gzipped: 167–177 KB
each uncompressed, **about 100 KB for all four compressed** — comparable to the
Banguat recording. They go to `tests/fixtures/` with their rows in that
directory's `README.md`, and are replayed through `respx` so the suite never
calls CEPAL.

**They are recorded complete, with all 33 countries and the 3 aggregates
inside.** Not trimmed to seven — the full response is the only thing that
proves the filter works. A pre-trimmed fixture would pass a connector that
filters nothing.

Unit tests:

* the catalog entry loads and validates, referencing the four new codes and the
  `CEPAL` organization; the four indicators exist in the registry with the
  expected unit and category
* four requests are issued, to the four expected URLs
* `header.success: false` raises `ExtractionError`; an empty `data` array raises
  `ExtractionError`
* exactly 1,008 observations are produced, 252 per indicator
* the 26 other countries and the 3 aggregates produce nothing
* the `× 10^6` scale is applied to the totals and not to the per-capita series
* one value verified by hand against the source: Nicaragua 2024,
  `19696.31184918235` million becomes exactly `19696311849.18235` USD, with the
  published figure preserved in `raw_metadata`
* the exact `Decimal` is pinned, so a future refactor that drops
  `parse_float=Decimal` fails
* the four checks pass on the real fixture, and each fails on a doctored set:
  Belize removed, the identity broken, the footnote reading 2020, a year cut out
* `COUNTRIES_BY_ISO3["BLZ"].is_active` is true and Belize receives 144
  observations
* one opt-in `-m live` test against the real API

## 8. Expected result

**1,008 observations** — 4 series × 7 countries × 36 years — from four
requests, covering 1990 to 2025. REIM's first GDP data, its second regional
source with no country of its own, and Belize's first data of any kind.

## 9. Out of scope

* The growth-rate series 2207, and the other 24 indicators in the same CEPALSTAT
  area. 2207 is derivable from what this increment stores; the rest are not part
  of the GDP family.
* Monetary aggregates (862, 868, 869) and public debt (1239, 1240). Both are
  reachable and their shape is recorded in `docs/sources.md` for whoever takes
  them next — monetary in particular would unblock the v0.2.0 item that the
  roadmap currently gives up on for Nicaragua. They carry three and four
  dimensions respectively and need their own design.
* The 26 non-Central-American countries and the 3 regional aggregates. The API
  returns them; REIM has no country codes for a region and no mandate beyond
  Central America.
* Population as a stored series, even though the four GDP indicators imply it
  exactly. Deriving and publishing it would make REIM the author of a figure
  CEPAL did not publish in this form.
