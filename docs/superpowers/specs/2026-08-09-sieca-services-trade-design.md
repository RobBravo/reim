# SIECA quarterly services trade — design

Status: **approved, not yet implemented**
Date: 2026-08-09
Roadmap item: v0.3.0, piece D

---

## 1. What the roadmap wanted, and what exists

The roadmap names "SIECA regional trade series", meaning intra-regional
merchandise trade. **That does not exist in machine-readable form today.**
Measured on 2026-08-09:

| Property | State |
|---|---|
| `estadisticas.sieca.int` — the host SIECA's own statistics page links to | `404` on every path, with any client. Down or migrated. |
| The "herramienta de inteligencia comercial" | Tableau Public embeds. A visualisation, not an endpoint. |
| `www.servicios.sieca.int` | ✅ **Live JSON, no authentication — trade in services** |
| `mercancias`, `comercio`, `intec`, `centrex`, `arancel` `.sieca.int` | Do not resolve |

So piece D becomes **trade in services**, which REIM does not hold from any
source, rather than merchandise trade, which it already holds from the IMF.
This complements the existing data instead of duplicating it, and it is REIM's
**first quarterly series**.

## 2. The source

| | |
|---|---|
| **Organization** | Secretaría de Integración Económica Centroamericana (`SIECA`) — already in the registry, never used |
| **Host** | `https://www.servicios.sieca.int` |
| **Endpoints** | `POST /ReporteGeneralServicios/LoadFilters` and `POST /ReporteGeneralServicios/LoadData` |
| **Protocol** | Undocumented AJAX JSON behind an ASP.NET MVC page; form-encoded request, JSON response |
| **Auth** | None |
| **Coverage** | **2009-Q1 … 2026-Q1**, verified — 69 quarters, no gaps |
| **Countries** | The six REIM countries, plus a "Centroamérica" aggregate |
| **Volume** | 16.7 KB per flow, under two seconds |

`LoadData` takes `flujo` (`E` exports / `I` imports / `S` balance),
`unidadMedida` (`MD` millions of USD), `paises` (numeric ids `1..6`),
`paisesDestino` (`0` = world, the only option), `periodos` (`"I Trim 2026,…"`)
and `categoria` (component id).

`LoadFilters` returns the country list, the 69 available quarters and a
33-component services taxonomy.

## 3. The access decision

**The host serves nothing to a client that identifies itself honestly.**
Measured across User-Agents against the same request:

| User-Agent sent | Response |
|---|---|
| `REIM/0.1.0 (…+https://github.com/RobBravo/reim)` | **`202`, empty body** |
| `python-httpx/0.27.0` | **`202`, empty body** |
| `curl/8.5.0`, or empty | **`403`** |
| `Mozilla/5.0 … Chrome/126.0 Safari/537.36` | **`200` with the data** |

The filter covers the whole host: REIM's own User-Agent cannot fetch even the
site's technical-note PDF.

**Decision, taken explicitly by the project owner: ingest, sending a browser
User-Agent for this host, and say so plainly.** The catalog entry declares it
and carries a note, exactly as `tls_profile: legacy` declares the BCN's
relaxed handshake rather than hiding it.

**This narrows a rule REIM currently states more absolutely than it will now be
true**, so the rule gets rewritten rather than quietly contradicted. The
distinction REIM draws from here on:

* **An active control is not defeated.** `www.bcn.gob.ni` sits behind a Radware
  Bot Manager that redirects every request to a JavaScript challenge. REIM does
  not execute it, and that stays true.
* **A static header check is satisfied.** SIECA's edge allows or denies on the
  `User-Agent` string alone. REIM sends one it accepts, changes nothing else,
  respects the same retry and timeout policy as every other source, and
  documents it in `docs/sources.md` and the README.

Both statements are about the publisher's edge rules; they differ in kind, and
the docs will say which is which instead of implying REIM never touches either.

## 4. What measuring corrected

**The balance identity is not exact.** `E − I = S` deviates by up to
**0.1 million USD**, and **71 of 414 cells** deviate by more than 0.05. The
source publishes each flow rounded to one decimal in millions, so two roundings
of ±0.05 accumulate. A check asserting exact equality would have failed on
every run — the same error already corrected in the IMF connector, where the
tolerance is one cent. Here the tolerance is **100,000 USD**, equal to the worst
deviation observed and still four orders of magnitude below the smallest
quarterly figure in the series (147.5 million USD).

**Values arrive as JSON floats, not strings.** `Decimal(375.3)` is
`375.2999999999999829…`. The payload must be parsed with
`json.loads(…, parse_float=Decimal)` so the published digits survive. Reading
them any other way corrupts every figure silently, in the last places, where no
count or total would reveal it.

## 5. Decisions

| # | Decision | Rationale |
|---|---|---|
| S1 | **Four requests per run**: one `LoadFilters`, then one `LoadData` per flow, each covering the whole history. | 16.7 KB per flow. No routine window, no separate backfill, so a rebuild is complete by default — the property Banguat has and the BCN lacks. |
| S2 | **The balance is taken from the source, not derived.** | REIM publishes what the publisher publishes. The identity is checked, not assumed. |
| S3 | **Values are converted to whole USD** (`× 10^6`), unit `current USD`. | Matches the IMF merchandise series, so `/compare` can put services and goods side by side. The conversion is exact in `Decimal` and reversible, and it is **declared**: `raw_metadata` keeps `sieca_published_value`, `sieca_published_unit` and `sieca_scale_applied`. |
| S4 | **Only the "Sumatoria de Servicios de Primer Nivel" component.** | The other 32 would multiply the volume 33-fold with nothing in REIM consuming them. YAGNI. |
| S5 | **The "Centroamérica" row is discarded.** | It is the sum of the six, and REIM has no country code for a region. `observations` has no region dimension. |
| S6 | **Indicator codes carry no country prefix.** | The rule set by the regional-trade increment: drop the prefix when the source is regional and every country shares the methodology. |
| S7 | **One country-agnostic catalog entry.** | One request returns all six countries. `SourceEntry.country_iso2` is already `str \| None`, and `country_attribution` reports the set rather than enforcing one. |

## 6. Components

### 6.1 `reim/domain/indicators/registry.py`

Three definitions, category `EXTERNAL_SECTOR`, frequency `QUARTERLY`, unit
`current USD`, value type `LEVEL`:

* `exports_services_quarterly`
* `imports_services_quarterly`
* `trade_balance_services_quarterly`

Descriptions state that these are **services**, not merchandise, and do not
replace the IMF's `exports_goods_monthly` family or the World Bank's annual
goods-and-services aggregates.

### 6.2 `sources/quality_rules.yml`

Two rule sets. Exports and imports: `min_value: 0`, no ceiling, `allow_zero:
false`. The balance: **`allow_negative: true`** — 99 of 414 quarters are
deficits, and the sign is the point. Freshness is generous: the newest quarter
is 2026-Q1 measured in August 2026, so a quarterly source runs months behind by
construction — `freshness_max_age_days: 250`.

### 6.3 `reim/ingestion/connectors/regional/sieca_services_trade.py`

A new `regional` package, alongside the existing per-country ones. This is
REIM's first source belonging to no single country.

`connector_key = "sieca_services_trade"`, `version = "1.0.0"`,
`expected_frequency = Frequency.QUARTERLY`.

**`extract`** POSTs `LoadData` three times, once per flow, with all six country
ids and all 69 quarters read from `LoadFilters` — so the window follows the
source rather than a hardcoded list. Four requests total. `ensure_ok` requires
a JSON content type; a `202` with an empty body must raise rather than yield
zero observations, because that is precisely what a rejected client receives.

**`transform`** parses each flow's payload with `parse_float=Decimal`, reads the
nested JSON string in `Data[0].Data`, maps the source's Spanish country names to
ISO3 and its `"I Trim 2026"` labels to `2026-Q1`, discards the "Centroamérica"
row, multiplies by `10^6`, and emits one observation per country, quarter and
flow. An unknown country name raises; a `null` value is skipped, never imputed.

**`validate`** returns four checks:

| Check | Type | Severity on failure |
|---|---|---|
| `sieca_six_countries_present` — all six in every flow | completeness | `critical` |
| `sieca_balance_identity` — `E − I = S` within 100,000 USD | consistency | `error` |
| `sieca_quarterly_continuity` — no missing quarter between first and last | completeness | `warning` |
| `sieca_flow_coverage` — the three flows cover the same country-quarter set | consistency | `error` |

An unrecognised country name is a `TransformationError`, not a check: it must
stop the run rather than be reported after the fact.

### 6.4 `sources/catalog.yml`

One entry, `sieca_services_trade`: no `country`, organization `SIECA`, category
`external_sector`, `access_type: http_api`, `frequency: quarterly`,
`format: json`, `license: public_official_data`, enabled, plus the declared
browser User-Agent and its note.

The User-Agent is declared per source in the catalog — a new optional field —
rather than changed globally. Every other source keeps REIM's honest
identifier.

## 7. Testing

`LoadFilters` and the three `LoadData` responses are recorded verbatim into
`tests/fixtures/` — **59 KB in total**, small enough to store uncompressed —
and replayed through `respx`.

Unit tests:

* all 1,242 observations produced, 414 per flow
* `"I Trim 2026"` becomes `2026-Q1`, spanning 2026-01-01 … 2026-03-31
* the six Spanish names map to the right ISO3 codes
* the "Centroamérica" row produces nothing
* an unknown country name raises
* `375.3` becomes exactly `375300000`, and `raw_metadata` keeps `"375.3"`
* a value read through `float` would differ — pinned by asserting the exact
  `Decimal`, so a future refactor that drops `parse_float` fails
* the real 0.1-million rounding deviations **do not** fail the identity check
* a doctored deviation of 200,000 USD **does** fail it, at `error`
* a `202` with an empty body raises `ExtractionError`
* a missing quarter is reported at `warning`
* one opt-in `-m live` test against the real service

## 8. Expected result

**1,242 observations** — 3 flows × 6 countries × 69 quarters — from four
requests, covering 2009-Q1 to 2026-Q1. REIM's first quarterly data, and its
first source with no country of its own.

## 9. Out of scope

* The 32 other components of the services taxonomy.
* Intra-regional merchandise trade: it has no machine-readable endpoint today,
  and that finding is recorded in `docs/sources.md`.
* The `VP`, `PT` and `PC` units the portal also offers — year-on-year change,
  quarterly average and share of total. All three are derivable from the
  levels, and REIM stores levels.
* Reviving `estadisticas.sieca.int`. It is recorded as dead, not chased.
