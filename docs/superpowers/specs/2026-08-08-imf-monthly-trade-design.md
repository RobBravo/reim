# IMF monthly merchandise trade — design

Status: **approved, not yet implemented**
Date: 2026-08-08
Roadmap item: v0.2.0, "BCN monthly statistics" — redirected, see §1

---

## 1. How this increment changed shape

The roadmap asked for **BCN monthly statistics**: monetary aggregates,
remittances, trade and reserves from the central bank's bulletins, "once XLSX
layout stability is assessed". The assessment never got as far as the layout.

**`www.bcn.gob.ni` blocks automated access.** Every HTTP request — `/`,
`/estadisticas`, `/publicaciones` and others, ~7 in total — is redirected to a
**Radware Bot Manager** challenge at `validate.perfdrive.com`. It is not a
User-Agent filter: a Chrome UA gets the same 302. Passing it requires executing
a JavaScript challenge.

REIM does not do that. A bot manager is the publisher's explicit decision about
automated access, and `docs/sources.md` already rejects scraping that is
"fragile and disrespectful of the publisher's infrastructure". It would also
break on every challenge update.

`servicios.bcn.gob.ni` — the host behind the exchange-rate SOAP service, which
is not behind the wall — exposes only `Tc_Servicio`. Plausible names for a
statistics service return 404 and directory listing is off.

**So the same indicators were sought from another official publisher.** What is
actually available for Nicaragua, measured rather than assumed:

| Family | BCN direct | IMF (no credentials) | SECMCA (credentialed) |
|---|---|---|---|
| Merchandise trade | bot wall | ✅ **IMTS, monthly** | `XG`, `MG_CIF` |
| Reserves | bot wall | ⚠️ IRFCL, monthly, but see §6 | `NIR_USD` |
| Monetary aggregates | bot wall | ❌ **Nicaragua does not report** | `MM1`, `MM2`, `MM3` |
| Remittances | bot wall | ❌ **Nicaragua does not report** | `WRI`, `WRO`, `WR` |

The IMF absences are measured, not inferred: `MFS_MA` returns 183 observations
for Costa Rica and 210 for Guatemala against **0 for Nicaragua**, and `BOP`
returns 0 for Nicaragua at monthly, quarterly *and* annual frequency.

SECMCA has all four families behind a documented Swagger API, but its data
endpoints require a `user`/`password` account — including the ones prefixed
`/public/`. Only the catalogue and date-range endpoints are open.

**This spec therefore covers monthly merchandise trade from the IMF, and
nothing else.** Reserves are documented as deferred with a concrete unblocking
step (§6).

## 2. The source

| | |
|---|---|
| **Publisher** | International Monetary Fund (`IMF`, already registered) |
| **Endpoint** | `https://api.imf.org/external/sdmx/2.1` |
| **Protocol** | SDMX 2.1 REST |
| **Dataflow** | `IMF.STA,IMTS` — International Merchandise Trade Statistics |
| **Key** | `NIC..G001.M` |
| **Format** | CSV via `Accept: application/vnd.sdmx.data+csv;version=2.0.0` |
| **Coverage** | **1990-M01 … 2026-M04**, verified — 436 months |
| **Volume** | 1,308 observations (436 × 3), 791 KB, 1.27 s |

The old `dataservices.imf.org` SDMX endpoint no longer resolves; `api.imf.org`
replaces it and needs no authentication.

The `IMTS` key dimensions are, in order, `COUNTRY.INDICATOR.COUNTERPART_COUNTRY.FREQUENCY`.

### Series ingested

| IMF indicator | REIM indicator | Unit | Sign |
|---|---|---|---|
| `XG_FOB_USD` | `ni_exports_goods_monthly` | current USD | positive |
| `MG_CIF_USD` | `ni_imports_goods_monthly` | current USD | positive |
| `TBG_USD` | `ni_trade_balance_goods_monthly` | current USD | **negative in 433 of 436 months** |

These are **merchandise** flows. They do not replace the World Bank's annual
`ni_exports_goods_services` / `ni_imports_goods_services`, which cover goods
*and services* at annual frequency. Both are kept, and the difference is
documented rather than smoothed over.

## 3. Decisions

| # | Decision | Rationale |
|---|---|---|
| T1 | Filter the counterpart **in the SDMX key** (`NIC..G001.M`), not after download. | The unfiltered query returns 103 counterparts and **62.9 MB**; the filtered one returns the same 1,308 usable rows in **791 KB**. An 80× reduction on an official service. |
| T2 | `G001` (world aggregate) is **required**. If no row carries it, the run fails. | Counterpart groups overlap: summing all 103 gives 1,804 M against a real 481 M for June 2025, because `G001` and regional groups already contain the individual countries. Summing would be silently wrong. |
| T3 | **`SCALE` is ignored** as a multiplier and recorded in `raw_metadata`. | Every row carries `SCALE=6`, but the values are already full USD — June 2025 exports read `481,429,757`. Treating it as "millions" would inflate the series a millionfold. |
| T4 | The connector **pins `Accept` to CSV and rejects a non-CSV response**. | The API ignores content negotiation: requesting `application/vnd.sdmx.data+json` returns SDMX-ML anyway. A silent format switch must fail loudly, not be parsed as garbage. |
| T5 | Reserves (`IRFCL`) are **not implemented**, only documented. | See §6. Its indicator codes cannot be named from anything the API exposes. |
| T6 | The catalog declares `license: imf_terms_of_use`, and the docs state plainly that this is **not** an open licence. | See §5. |
| T7 | Trade balance identity `TBG = XG − MG` is asserted as a quality check. | Verified exact at both ends of the series: 2026-M04 gives `601,982,690 − 876,915,315 = −274,932,625`, and 1990-M01 `20,429,862.1 − 70,463,719.0 = −50,033,856.9`. A break means a parsing or alignment fault. |

## 4. Components

### 4.1 `reim/domain/indicators/registry.py`

Three new `IndicatorDefinition` entries, category `IndicatorCategory.EXTERNAL_SECTOR`,
frequency `Frequency.MONTHLY`, `value_type=ValueType.LEVEL` and
`unit="current USD"` — matching the existing `ni_exports_goods_services` and
`ni_remittances_received`, so the monthly and annual trade series describe
their magnitudes the same way. Each description states that the figure is
merchandise trade compiled by the IMF from national customs data, and names the
annual World Bank series it does **not** replace.

### 4.2 `sources/quality_rules.yml`

| Indicator | Bounds | Notes |
|---|---|---|
| `ni_exports_goods_monthly` | `min_value: 0`, `allow_negative: false`, `allow_zero: false` | |
| `ni_imports_goods_monthly` | `min_value: 0`, `allow_negative: false`, `allow_zero: false` | |
| `ni_trade_balance_goods_monthly` | `allow_negative: true`, `allow_zero: true`, no `min_value` | A trade balance crosses zero; a sign constraint would reject 433 of 436 real months. |

None of the three gets `max_period_change_pct`: monthly trade is genuinely
volatile, and the balance crosses zero, which makes a percentage change of it
unbounded and meaningless — the same reasoning already applied to
`ni_cpi_inflation_monthly`. `freshness_max_age_days: 120`, because the IMF
publishes a month roughly two months after it closes. `min_observations: 300`,
against a 436-month series.

### 4.3 `sources/catalog.yml`

One new entry, `imf_imts_nicaragua`:

```yaml
  - key: imf_imts_nicaragua
    name: Nicaragua merchandise trade (monthly)
    country: NI
    organization: IMF
    category: external_sector
    access_type: http_api
    frequency: monthly
    format: csv
    base_url: https://api.imf.org/external/sdmx/2.1
    documentation_url: https://www.imf.org/external/terms.htm
    connector: reim.ingestion.connectors.nicaragua.imf_imts_trade
    indicators:
      - ni_exports_goods_monthly
      - ni_imports_goods_monthly
      - ni_trade_balance_goods_monthly
    license: imf_terms_of_use
    official: true
    enabled: true
```

### 4.4 `reim/ingestion/connectors/nicaragua/imf_imts_trade.py`

`connector_key = "imf_imts_nicaragua"`, `version = "1.0.0"`,
`expected_frequency = Frequency.MONTHLY`.

**`extract`** issues one GET to
`{base_url}/data/IMF.STA,IMTS/NIC..G001.M?startPeriod={start}` with the pinned
`Accept` header, through the existing `fetch` helper and its retry policy. The
catalog option `start_period` (default `1990-01`) bounds the request. It calls
`ensure_ok(response, expected_content_type="csv")`, which enforces T4, and
returns the CSV text as `payload`. The live endpoint answers
`content-type: application/vnd.sdmx.data+csv;version=2.0.0`, so the substring
check `ensure_ok` performs matches; an SDMX-ML fallback would not contain
`csv` and would raise.

**`transform`** parses the CSV with `csv.DictReader`, then for each row:

* skips rows without a `TIME_PERIOD` — the CSV's first row is a dataflow
  metadata row with every key field empty;
* keeps only `COUNTERPART_COUNTRY == "G001"`;
* maps `INDICATOR` through a three-entry constant to the REIM code and unit,
  skipping any code REIM does not ingest;
* converts `TIME_PERIOD` from SDMX `YYYY-Mmm` to REIM's `YYYY-MM` before
  `parse_period(..., Frequency.MONTHLY)`;
* builds `Decimal` **from the raw string**, never through `float`;
* records `source_record_id = f"imts:{imf_code}:{period.label}"` and
  `raw_metadata` carrying the IMF indicator code, the counterpart, the reported
  `SCALE` and the dataflow version from the `DATAFLOW` column.

Malformed CSV, an unparseable period and a non-numeric value each raise
`TransformationError` naming the offending row.

**`validate`** returns three source-specific checks:

| Check | Type | Severity on failure |
|---|---|---|
| `imf_imts_world_aggregate_present` — at least one `G001` row was kept | completeness | `critical` |
| `imf_imts_all_indicators_present` — all three series produced observations | completeness | `error` |
| `imf_imts_balance_identity` — for every month holding all three, `TBG == XG − MG` | consistency | `error` |

Generic bounds, sign and freshness come from `quality_rules.yml`.

## 5. Licence, stated plainly

The IMF data carries, in its own `LICENSE` field:

> © International Monetary Fund Copyright. All Rights Reserved.
> https://www.imf.org/external/terms.htm

That is **not** an open licence, and REIM's `ROADMAP.md` lists "scraping
paywalled or licence-restricted data" under what it will not do, promising
"official and openly licensed only". This increment is a documented exception,
taken with the project owner's explicit decision.

Two facts are recorded rather than reconciled, because they sit awkwardly
together and resolving them is a legal question this project has not answered:

* the `LICENSE` field says All Rights Reserved;
* the same rows carry `ACCESS_SHARING_LEVEL = PUBLIC_OPEN` and
  `SECURITY_CLASSIFICATION = PUB`.

The terms page could not be retrieved programmatically — `imf.org/external/terms.htm`
returns an empty document and `imf.org/en/About/copyright-and-terms` returns
403 — so its contents are **not** summarised here. `docs/sources.md` links it
and says so.

Every observation carries the IMF's `SUGGESTED_CITATION` in `raw_metadata`, and
the catalog's `license` field reads `imf_terms_of_use` — deliberately not
`public_official_data`, which would imply openness this source does not grant.

## 6. Reserves: why they are not in this increment

`IRFCL` (International Reserves and Foreign Currency Liquidity) **does** hold
monthly Nicaraguan data — 1,740 observations, verified. It is not implemented
because its **60 indicator codes cannot be named** from anything the API
exposes:

* `codelist/IMF.STA/CL_INDICATOR` returns `204 No Content`;
* `datastructure/IMF.STA/DSD_IRFCL_PUB?references=children` returns concept
  schemes but no codes, and the `INDICATOR` dimension carries **no
  `<str:Enumeration>`** — it is not codelist-backed;
* requesting SDMX-JSON, whose structure section would carry names, returns
  SDMX-ML regardless of the `Accept` header.

Choosing among `IRFCLDT1_IRFCL65_USD`, `IRFCLDT1_IRFCL54_USD` and
`IRFCLDT1_IRFCLCDCFC_USD` by magnitude alone — three of them read identically
at 7.206 bn USD for June 2025 — would be a guess. v0.1.0 already refused that
for the BCN, on the grounds that "defensive parsing of an unobserved format is
still a guess", and shipped the connector disabled instead.

**Unblocking step, recorded for a future increment:** obtain the code-to-line
mapping from the IMF's *International Reserves and Foreign Currency Liquidity
Guidelines for a Data Template*, whose numbered template lines the `IRFCL nn`
fragments appear to reference, and pin the total-reserve-assets code against it.

## 7. Testing

One fixture recorded from the live API — `tests/fixtures/imf_imts_nic_g001.csv`,
the real response trimmed to a documented year range — replayed through `respx`.
No test touches the network except one opt-in `-m live` check.

Unit tests:

* the three series are parsed with the expected counts and units
* `G001` is kept and a non-`G001` counterpart row is discarded
* an absent `G001` raises the critical check
* `SCALE` is **not** applied: a value of `481429757` stays `481429757`
* `TIME_PERIOD` `2026-M04` becomes period label `2026-04`, a closed month
* values are exact `Decimal`s, including the negative balance
* the balance identity check passes on the fixture and fails on a doctored row
* an XML response raises `ExtractionError` rather than being parsed (T4)
* a CSV whose columns changed raises `TransformationError`

## 8. Expected result

1,308 observations across three monthly series, 1990-M01 to the latest
published month, from a single 791 KB request.

## 9. Out of scope

* IMF `IRFCL` reserves — §6.
* Monetary aggregates and remittances — Nicaragua does not report them to the
  IMF, and SECMCA requires credentials.
* Trade by partner country. The data supports it (103 counterparts), but that
  is a different shape of series and needs its own indicator modelling.
* Any attempt to reach `www.bcn.gob.ni` through its bot manager.
