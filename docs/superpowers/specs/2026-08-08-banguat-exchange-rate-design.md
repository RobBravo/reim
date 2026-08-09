# Banguat daily exchange rate — design

Status: **approved, not yet implemented**
Date: 2026-08-08
Roadmap item: v0.3.0, piece C — first country

---

## 1. Scope: Guatemala now, the other five recorded

Piece C names six national central banks. They are six independent
investigations, and only one is measured feasible today:

| Publisher | Measured state |
|---|---|
| **Banguat (Guatemala)** | ✅ **SOAP, no authentication, 13,364 rows in one 1.3 MB request, 1990-01-01 → today** |
| BCCR (Costa Rica) | ❌ `503` on both URL casings of its documented web service; it is also known to require a registered account |
| BCR (El Salvador) | ⚠️ `estadisticas.bcr.gob.sv` responds `200` but exposes no machine-readable endpoint on its landing page |
| BCH (Honduras) | ⚠️ site reachable; no data endpoint found |
| INEC (Panama) | ⚠️ site reachable; `/mapi/map` responds, unresearched |
| Central Bank of Belize | ⚠️ site reachable; no data endpoint found |

None of the six is behind a bot wall, unlike the BCN's statistics site.

**This spec covers Guatemala only.** The other five states are recorded in
`docs/sources.md` so the next person does not repeat the probing.

## 2. The source

| | |
|---|---|
| **Organization** | Banco de Guatemala (`BANGUAT`) — **not yet registered in REIM** |
| **Endpoint** | `https://www.banguat.gob.gt/variables/ws/TipoCambio.asmx` |
| **Protocol** | SOAP 1.1, namespace `http://www.banguat.gob.gt/variables/ws/` |
| **Operation** | `TipoCambioRango(fechainit, fechafin)`, dates as `dd/mm/yyyy` |
| **Auth** | None |
| **Coverage** | **1990-01-01 → 2026-08-08**, verified — 13,364 rows |
| **Volume** | 1.3 MB in a single request, under a second |

The response is `<Var><moneda><fecha><venta><compra></Var>` repeated. `moneda`
is uniformly `2` (US dollar). `VariablesDisponibles` lists 40 currencies, not
economic variables — this service is exchange rates only, and REIM takes the US
dollar.

## 3. Decisions

| # | Decision | Rationale |
|---|---|---|
| G1 | **Two indicators**, not one: `gt_exchange_rate_official_daily_buy` and `gt_exchange_rate_official_daily_sell`. | **6,174 of 13,364 rows have `compra ≠ venta`.** Collapsing them would destroy real information, and REIM publishes what the publisher publishes. |
| G2 | Country-prefixed codes (`gt_`). | The rule set in the regional-trade increment: prefix when the source is national and its methodology is its own; drop the prefix only for shared multilateral series. |
| G3 | **One request for the whole history on every run.** No routine window, no separate backfill. | The whole series is 1.3 MB in one call. The two-mode design the BCN needed — because its history costs 176 requests — is what caused a rebuild to silently produce 40 rows instead of 5,334. Guatemala does not need it, so it does not get it, and a rebuild is complete by default. |
| G4 | `BANGUAT` is added to the organization registry. | It is not there; the catalog validator rejects an unknown organization. |
| G5 | The buy ≤ sell check is enforced **only from 1992 onward**. | See §4. |
| G6 | Gaps are **reported, not failed**. | Five days are missing in 36 years. That is the source's history, not a fault. |

## 4. The two things measuring corrected

The design as first presented was wrong twice, and both were caught by
measuring the full response rather than a sample.

**"`venta ≥ compra` in every row" is not true.** 84 rows violate it — and every
one falls in **1990 (76) or 1991 (8)**, during the quetzal's liberalisation:
the buy rate sat fixed at `5.15` while the sell rate floated below it, as low
as `4.62`. That is real history, not crossed columns. A check asserting the
invariant unconditionally would have failed on every run forever.

The check therefore applies **from 1992 onward**, exactly as
`inide_cpi_monthly` enforces continuity only from `CONTIGUOUS_FROM_YEAR = 2011`
because INIDE's own table is sparse before it. Same precedent, same reasoning:
constrain the stretch where the source actually behaves that way, and document
why the early history differs.

**"The series has gaps, so no continuity check" was based on a misreading.** A
single year returning 364 rows looked like frequent holes. Across the whole
series there are **five missing days**: `2000-04-02`, `2000-05-01`,
`2001-09-02`, `2004-03-06`, `2004-03-07`. A gap check is therefore cheap and
informative — as an `info` report of how many days are missing, never a
failure.

## 5. Components

### 5.1 `reim/domain/sources/organizations.py`

One new entry: `BANGUAT`, Banco de Guatemala, central bank, country `GT`,
website `https://www.banguat.gob.gt`.

### 5.2 `reim/domain/indicators/registry.py`

Two new definitions, category `EXCHANGE_RATE`, frequency `DAILY`, unit
`GTQ per USD`, value type `RATE`:

* `gt_exchange_rate_official_daily_buy` — the rate at which the bank **buys**
  US dollars, the lower of the pair.
* `gt_exchange_rate_official_daily_sell` — the rate at which it **sells** them,
  the higher.

Both descriptions state the direction explicitly, because "compra" and "venta"
are from the bank's side and read backwards to anyone expecting the customer's.

### 5.3 `sources/quality_rules.yml`

Two rule sets. Bounds constrain the **sign only**, with no ceiling: the quetzal
ran from `3.41332` in 1990 to `8.39482` at its peak, and any narrow band would
reject legitimate history — the lesson v0.1.0 learned when `min_value: 1`
rejected 31 real exchange-rate observations. `freshness_max_age_days: 7`,
matching the BCN's daily series. No `max_period_change_pct`: the 1990-1991
liberalisation moved the rate sharply and genuinely.

### 5.4 `reim/ingestion/connectors/guatemala/banguat_exchange_rate.py`

Alongside `imf_imts_trade.py`, which already lives in that package.

`connector_key = "banguat_exchange_rate"`, `version = "1.0.0"`,
`expected_frequency = Frequency.DAILY`.

**`extract`** POSTs one `TipoCambioRango` envelope covering
`START_DATE = date(1990, 1, 1)` to today's UTC date, formatted `dd/mm/yyyy`,
through the shared `post` helper and its retry policy. `ensure_ok` requires an
XML content type. The payload is the response text.

**`transform`** parses the envelope, raising `TransformationError` on malformed
XML or a `soap:Fault`. For each `<Var>` it reads `fecha`, `venta` and `compra`,
builds `Decimal` from the raw strings, converts `dd/mm/yyyy` to a REIM daily
period, and emits **two** observations. Rows are sorted by date; a date
appearing twice with different values raises rather than picking a winner.
`source_record_id` is `f"tc_rango:{iso_date}:{side}"` so the two sides cannot
collide.

**`validate`** returns three checks:

| Check | Type | Severity on failure |
|---|---|---|
| `banguat_both_sides_present` — both indicators produced observations | completeness | `critical` |
| `banguat_sell_not_below_buy` — for every day **from 1992**, sell ≥ buy | consistency | `error` |
| `banguat_calendar_gaps` — counts missing calendar days between first and last | completeness | `info`, always passes |

Generic bounds, sign and freshness come from `quality_rules.yml`.

### 5.5 `sources/catalog.yml`

One entry, `banguat_exchange_rate`: country `GT`, organization `BANGUAT`,
category `exchange_rate`, `access_type: soap`, `frequency: daily`,
`format: xml`, `license: public_official_data`, enabled.

### 5.6 `README.md`

The "Rebuilding from an empty database" section gains one line: Banguat, like
INIDE and the IMF, ships its full history in the routine run. Only the BCN
needs the one-off.

## 6. Testing

The full response is recorded and committed gzipped: **1.33 MB → 90 KB**, a
14.5x reduction. That is larger than the IMF fixture's 18 KB but well within
what this repository already carries — the INIDE workbook is 157 KB — and the
tests that matter need the whole history: the 1990-1991 inversions and the five
missing days exist nowhere else.

Unit tests, replayed through `respx`:

* both series parsed, 13,364 observations each side
* the SOAP contract sent: namespace, `SOAPAction`, `dd/mm/yyyy` dates
* `dd/mm/yyyy` becomes a single-day closed period
* exact `Decimal`s: 1990-01-01 sell `3.41332`, buy `3.4081`
* buy and sell differ where the source says they differ, and the count matches
* the 1990-1991 inversions **do not** fail validation
* an inversion dated after 1992, doctored in, **does** fail at `error`
* the gap check reports five missing days and still passes
* a `soap:Fault`, malformed XML and a non-numeric rate each raise
* one opt-in `-m live` test against the real service

## 7. Expected result

**26,728 observations** — 13,364 days × two sides — from one request, covering
1990-01-01 to the present.

## 8. Out of scope

* The other five central banks; their measured state is documented, not acted on.
* Banguat's other 39 currencies. REIM's indicators are US-dollar denominated.
* `TipoCambioDia`, `TipoCambioFechaInicial` and the other operations —
  `TipoCambioRango` is a strict superset for REIM's purposes.
