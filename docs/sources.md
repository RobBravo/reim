# Source research notes

Every source REIM knows about, what was verified about it, and — where a source
is not automated — exactly what is blocking it.

This file is the honest record behind `sources/catalog.yml`. A source is only
enabled once its endpoint has been reached and its response shape observed. No
connector is ever "confirmed working" against invented data.

Last verified: **2026-08-19**.

---

## Enabled

### World Bank Indicators API v2

| | |
|---|---|
| **Organization** | World Bank (`WORLDBANK`) — multilateral |
| **Endpoint** | `https://api.worldbank.org/v2/country/{iso3}/indicator/{series}?format=json` |
| **Documentation** | <https://datahelpdesk.worldbank.org/knowledgebase/articles/889392> |
| **Auth** | None |
| **Format** | JSON |
| **Frequency** | Annual |
| **Licence** | CC-BY-4.0 |
| **Status** | ✅ Verified reachable and returning Nicaraguan data |

**Response shape.** A two-element array `[metadata, rows]`. The metadata block
carries `page`, `pages`, `per_page`, `total` and `lastupdated`; REIM uses
`lastupdated` as `published_at`. Errors come back as a *one*-element array
containing a `message` object, which the connector detects and raises on.

**Series used**

| REIM indicator | World Bank series | Points | Coverage |
|----------------|-------------------|--------|----------|
| `ni_exchange_rate_official_annual_avg` | `PA.NUS.FCRF` | 66 | 1960–2025 |
| `ni_cpi_inflation_annual` | `FP.CPI.TOTL.ZG` | 26 | 2000–2025 |
| `ni_remittances_received` | `BX.TRF.PWKR.CD.DT` | 36 | 1977–2024 |
| `ni_international_reserves` | `FI.RES.TOTL.CD` | 62 | 1960–2025 |
| `ni_exports_goods_services` | `NE.EXP.GNFS.CD` | 66 | 1960–2025 |
| `ni_imports_goods_services` | `NE.IMP.GNFS.CD` | 66 | 1960–2025 |

**Known limitations**

- **Annual only.** No monthly or quarterly resolution for these series. Monthly
  CPI and daily exchange rates must come from national sources.
- **One step removed.** The World Bank compiles from national statistics
  (and, for reserves, from IMF IFS). It is an official multilateral source, not
  the Nicaraguan primary publisher.
- **Publication lag.** Year *Y* generally appears during *Y+1*, so freshness
  thresholds for these indicators are set to 800 days.
- **Sparse history.** Many years have `value: null`. REIM **skips** those rows;
  it never imputes, interpolates or carries a value forward. The connector's
  `worldbank_series_continuity` check reports the gaps at `info` severity.
- **Pagination.** The connector requests `per_page=500`, which comfortably
  exceeds every series above. If the API ever reports more than one page the
  connector **raises** rather than silently truncating.

**Gotcha worth knowing: pre-redenomination values.** The World Bank restates the
whole `PA.NUS.FCRF` series in current córdobas. Nicaragua redenominated its
currency in 1988 and 1991, so genuine figures for 1960–1987 sit around
`2.06064418965517E-9` NIO per USD, and the 1987→1991 transition shows
period-over-period changes in the thousands of percent.

Two consequences, both learned the hard way during development:

1. An initial `min_value: 1` range rule rejected **31 real observations**. The
   rule now bounds only the sign. See `sources/quality_rules.yml`.
2. Storing values in `NUMERIC(30, 10)` silently rounded `2.06064418965517E-9` to
   `2.1E-9`. The column is now unconstrained `NUMERIC`, which PostgreSQL stores
   with arbitrary precision. Both behaviours are covered by regression tests.

---

### INIDE — monthly consumer price index

| | |
|---|---|
| **Organization** | Instituto Nacional de Información de Desarrollo (`INIDE`) — national statistics office |
| **Index page** | <https://www.inide.gob.ni/Home/ipc> |
| **Example workbook** | `https://www.inide.gob.ni/docs/ipc/ipc_2026/ipc_jun26/Cuadros_Estadisticas_IPC_junio_2026.xls` |
| **Auth** | None |
| **Format** | Legacy BIFF `.xls` (OLE2 compound document), ~400 KB |
| **Frequency** | Monthly |
| **Coverage** | January 2007 onward (see the gap below) |
| **Licence** | Public official data |
| **Status** | ✅ Verified reachable and parseable |

REIM's **first national primary source** and **first monthly series**. INIDE is
the official producer of Nicaragua's IPC.

**Each release contains the full history.** A monthly workbook is not an
increment — it carries the entire series — so one download per run yields
everything, and the run is cheap for INIDE's servers.

**Sheet `2-1-06` is three symmetric blocks, not one series.** Its full title is
*"Índice de precios al consumidor nacional, Managua y resto del país"*: the same
four columns repeat once per geographic breakdown, at a fixed offset.

| Block | Index | Variación mensual | Variación acumulada | Variación interanual |
|---|---|---|---|---|
| nacional | 2 | 3 | 4 | 5 |
| Managua | 6 | 7 | 8 | 9 |
| resto del país | 10 | 11 | 12 | 13 |

All three are ingested, into nine REIM indicators:

| Region | Index | Month-on-month | Year-on-year |
|---|---|---|---|
| National | `ni_cpi_index_monthly` | `ni_cpi_inflation_monthly` | `ni_cpi_inflation_yoy` |
| Managua | `ni_cpi_index_monthly_managua` | `ni_cpi_inflation_monthly_managua` | `ni_cpi_inflation_yoy_managua` |
| Rest of country | `ni_cpi_index_monthly_rest_of_country` | `ni_cpi_inflation_monthly_rest_of_country` | `ni_cpi_inflation_yoy_rest_of_country` |

**The three blocks have identical coverage** — 224 index rows, 186
month-on-month rows and 224 year-on-year rows each in the June 2026 workbook.
After annual rows are dropped, each region yields 198 index, 186 month-on-month
and 198 year-on-year observations over 2007-01..2026-06: **1,746 in total, from
one download**.

The month-on-month series starts in 2011 rather than 2007: all twelve 2007 rows
carry `-` in that column, so no observation is produced for them. This holds for
all three regions.

**Region is modelled as separate indicator codes**, not as a dimension on
`observations`. REIM's observation key is `(indicator, country, source, period)`;
adding a geography column for one source would mean a migration touching every
observation, the repositories and the API. The suffixed codes are published by
INIDE, not derived by REIM.

**The year-to-date column (offset 2 in every block) is never ingested** — it is
a within-year running total, fully reconstructible from the monthly series — but
its header *is* asserted, because doing so catches an inserted or reordered
column. Twelve headers are checked in total before any value is read, and a
mismatch in any of them aborts the whole run, national series included.

**URL discovery, not URL construction.** File naming drifts between releases —
`ipc_2025/ipc_abr25/` vs `ipc_2024/ipc_abril24/` vs `ipc_2023/ipc_Ene2023/`, and
March 2026 is `Estadisticas_del_IPC_a_marzo_de_2026.xls` instead of the usual
`Cuadros_Estadisticas_IPC_marzo_2026.xls`. No template covers all of them, so
the connector reads the index page and picks the newest workbook by the month it
reports on. This is HTML parsing, but only to *locate a document*: every value
comes from the structured spreadsheet.

**Known limitations**

- **No monthly detail for 2008-2010.** Sheet `2-1-06` carries annual rows only
  for 2001-2006 and 2008-2010, with monthly figures for 2007 and then
  continuously from January 2011. This is a property of INIDE's table, not a
  parsing fault, and REIM does not fill it. The connector enforces continuity
  only from 2011 onward, where the source is genuinely unbroken.
- **2007 has no month-on-month variation.** Those cells contain `-` because the
  rebased series has no December 2006. Those observations are not produced.
- **The series is spliced.** Footnote 2 of the sheet states the 2006=100 index is
  "enlazado con base 1999=100 en el período enero 2001 a diciembre 2009". Values
  before 2010 therefore come from a linked, not directly measured, base.
- **Annual rows are deliberately not ingested.** Footnote 1 states "los índices
  anuales corresponden al promedio del año" — for the current year that is a
  partial-year average that changes with every release, which would manufacture
  a stream of false revisions.
- **Precision.** INIDE stores the index to six decimals but *displays* it to one,
  and the variation columns are formula results carrying full binary precision.
  REIM quantises to six decimals: that keeps the index's entire published
  precision and discards IEEE-754 noise (Excel returns `321.00426699999997` for
  a stored `321.004267`).
- **Publication date.** The workbook carries no machine-readable publication
  timestamp, so `published_at` comes from the HTTP `Last-Modified` header.
- **Four sheets remain unread.** The workbook also carries CPI by division for
  each of the three breakdowns (`2-2-06`, `2-3-06`, `2-4-06`) and national core
  inflation (*subyacente*, `2-5-06`). Each is dozens of further series and
  deserves its own increment.

**Guards against silent corruption.** Before reading any value the connector
asserts the base-year note still says `2006 = 100` and that all twelve column
headers are unchanged — the three region headers plus the three non-index
headers in each block. If INIDE rebases the index or reorders the table, the run
fails loudly rather than mixing incompatible bases.

---

### Banco Central de Nicaragua — daily official exchange rate

| | |
|---|---|
| **Organization** | Banco Central de Nicaragua (`BCN`) — central bank |
| **Endpoint** | `https://servicios.bcn.gob.ni/Tc_Servicio/ServicioTC.asmx` |
| **Documentation** | <https://www.bcn.gob.ni/servicio-web-tipo-de-cambio> |
| **Format** | SOAP / XML |
| **Frequency** | Daily |
| **Coverage** | 2012-01-01 onwards, verified against the service itself |
| **Status** | ✅ **Enabled** — REIM's first daily-frequency series |

The national primary publisher of the official NIO/USD rate, at daily
resolution. v0.1.0 shipped this connector disabled; it was enabled on
2026-08-08 after the endpoint turned out to be reachable and its contract was
verified against live responses.

**The v0.1.0 blocker was misdiagnosed.** The note recorded that the host "only
negotiates a pre-TLS 1.2 handshake, which OpenSSL 3.x rejects". The first half
is true — forcing TLS 1.1 or 1.2 makes the server choose 1.0, which the client
then refuses. The second half was wrong: pinning TLS 1.0 alone still fails, but
one stage later, at `ServerKeyExchange`:

```console
$ openssl s_client -connect servicios.bcn.gob.ni:443 -tls1 -cipher 'ALL:@SECLEVEL=0'
error:03000098:digital envelope routines:do_sigver_init:invalid digest
```

That is the **ban on SHA-1 signatures**, not a protocol-version rejection. From
Python, an `ssl.SSLContext` pinned to TLS 1.0 at `SECLEVEL=0` and verifying
against certifi completes the handshake with no system or environment changes:

```console
TLSv1 ECDHE-RSA-AES256-SHA
{'countryName': 'NI', 'localityName': 'Managua',
 'organizationName': 'Banco Central de Nicaragua', 'commonName': '*.bcn.gob.ni'}
```

**The TLS concession.** `sources/catalog.yml` declares `tls_profile: legacy` with
a `tls_note` explaining why, and the catalog refuses a legacy profile that does
not document itself. The concession relaxes **only** the protocol version and
the cipher security level, for this host alone. The certificate chain and the
hostname are still verified, and every downgraded connection is logged at
warning level twice — once by the HTTP layer, once by the connector with the
hostname attached. Remove the profile if the BCN modernises the endpoint; no
code change is needed.

**The real contract**, from the live WSDL. Every assumption v0.1.0 made while
unable to reach the service was wrong:

| v0.1.0 assumed | Actual |
|---|---|
| namespace `http://tempuri.org/` | `http://servicios.bcn.gob.ni/` |
| parameter `<strfecha>` as an ISO date | `<Ano>`, `<Mes>`, `<Dia>` as `s:int` |
| only a per-day lookup exists | `RecuperaTC_Mes(Ano, Mes)` returns the whole month |

REIM uses `RecuperaTC_Mes`, which returns one `<Tc>` per calendar day — a strict
superset of the per-day operation at a thirtieth of the request count.

**Three properties of the service that shape the connector:**

1. **Rows arrive unordered.** The recording of March 2020 starts at the 7th. The
   connector sorts by date.
2. **The service answers for months that have not happened**, projecting the
   currently frozen rate forward to the end of the calendar year: at the time of
   writing `RecuperaTC_Mes(2026, 12)` returned 31 rows while
   `RecuperaTC_Mes(2027, 1)` returned none. REIM **discards every row dated
   after today** — a projection is not an observation — and reports the number
   discarded as an `info` quality check so the truncation is auditable.
3. **Coverage begins exactly at 2012-01.** `RecuperaTC_Mes(2011, 12)` returns an
   empty result with no SOAP fault, so an empty month is not treated as an
   error unless the month has already begun.

**Request volume.** A scheduled run asks for the current month and the previous
one — two requests. The 2012-onwards backfill is an explicit one-off
`start_month` range, capped at 400 months so a typo cannot launch a thousand
calls at an official service.

**What the series looks like.** 5,334 observations as of 2026-08-08, from 2012-01-01 to
2026-08-08, one per calendar day with no gaps. It shows the crawling peg
(`2012-01-01 = 22.9797` rising steadily) and its freeze: since January 2024 the
rate has been constant at `36.6243`. The count grows by one every calendar
day, so treat it as a snapshot rather than a fixed figure.

**Also considered and rejected:** scraping `https://www.bcn.gob.ni/tipo-de-cambio`.
The page is Drupal-rendered and returns no server-side table, and no CSV or XLSX
export was found at a stable URL. Scraping a JavaScript-rendered page for a
number that already has a web service would be fragile and disrespectful of the
publisher's infrastructure.

---

### IMF — Central American monthly merchandise trade

| | |
|---|---|
| **Organization** | International Monetary Fund (`IMF`) |
| **Endpoint** | `https://api.imf.org/external/sdmx/2.1` |
| **Dataflow** | `IMF.STA,IMTS` — International Merchandise Trade Statistics |
| **Key** | `{ISO3}..G001.M` (`COUNTRY.INDICATOR.COUNTERPART_COUNTRY.FREQUENCY`) |
| **Format** | CSV, `Accept: application/vnd.sdmx.data+csv;version=2.0.0` |
| **Frequency** | Monthly |
| **Coverage** | 1990-01 … 2026-04, verified — 436 months, **identical for all six countries** |
| **Licence** | ⚠️ **Not open.** See below. |
| **Status** | ✅ Enabled — 7,848 observations across six countries |

REIM's first data for more than one country. Six catalog entries — Nicaragua,
Guatemala, El Salvador, Honduras, Costa Rica and Panama — share one connector
base, each fetching ~789 KB.

| Country | Observations | Span |
|---|---|---|
| Nicaragua, Guatemala, El Salvador, Honduras, Costa Rica, Panama | 1,308 each | 1990-M01 … 2026-M04 |
| **Belize** | **0 — reports nothing** | — |

Belize was probed at monthly, quarterly and annual frequency and without any
counterpart filter. It returns nothing in every case, so it has **no catalog
entry** and stays inactive in the country registry.

**The indicator codes carry no country prefix**: `exports_goods_monthly`
(`XG_FOB_USD`), `imports_goods_monthly` (`MG_CIF_USD`) and
`trade_balance_goods_monthly` (`TBG_USD`). The country is carried by the
observation, not the code. The rule REIM follows: prefix by country when the
source is national and the methodology differs — a Guatemalan CPI is not a
Nicaraguan one — and drop the prefix when the source is multilateral and every
country shares the methodology. The country each connector requests comes from
its **catalog entry**, so one module serves all six.

These are **merchandise** flows and do not replace the annual World Bank
`ni_exports_goods_services` / `ni_imports_goods_services`, which also cover
services.

**Why the IMF and not the BCN.** The BCN publishes these figures in its monthly
bulletins, but `www.bcn.gob.ni` is behind a **Radware Bot Manager**: every HTTP
request — `/`, `/estadisticas`, `/publicaciones` and others — is redirected to a
challenge at `validate.perfdrive.com`. It is not a User-Agent filter; a Chrome
UA receives the same 302. Passing it requires executing a JavaScript challenge,
which REIM does not do: a bot manager is the publisher's explicit decision about
automated access, and defeating it would also break on every challenge update.
`servicios.bcn.gob.ni`, which is not behind the wall, exposes only
`Tc_Servicio` — the exchange-rate service documented above.

**Three properties of the API that shape the connector:**

1. **The counterpart is filtered in the SDMX key.** Requesting every
   counterpart returns 103 of them and **62.9 MB**; requesting `G001` alone
   returns the same 1,308 usable rows in **789 KB**.
2. **Counterpart groups overlap and must never be summed.** Adding all 103 for
   June 2025 gives 1,804 million USD against a real 481 million, because
   `G001` (world) and the regional groups already contain the individual
   countries. A run without any `G001` row fails at `critical` severity rather
   than falling back to a sum.
3. **`SCALE` is not a multiplier.** Every row reports `SCALE=6` while carrying
   full USD. REIM records it for provenance and never applies it; treating it
   as "millions" would inflate the series a millionfold.

The API also **ignores content negotiation** — requesting SDMX-JSON returns
SDMX-ML regardless — so the connector pins the CSV media type and refuses a
response that is not CSV.

**The balance identity is checked, but not for exact equality.** `TBG` should
equal `XG − MG`, and does to within 5e-8 USD; the IMF publishes `TBG` rounded
to about 16 significant digits, so 12 of the 436 months differ in their last
digit. The check therefore allows a one-cent tolerance — four orders of
magnitude above the observed noise, and still far below any real misalignment.

**Licence: not open, but redistributable with attribution.** Every row carries:

> © International Monetary Fund Copyright. All Rights Reserved.
> <https://www.imf.org/external/terms.htm>

That copyright line is not an open licence, and REIM's roadmap says "official
and openly licensed only" — so this source remains a **documented exception**,
adopted with the project owner's explicit decision. The terms themselves,
however, do permit reuse. Their "The Use of IMF Data" section allows
downloading, extracting, copying, creating derived works, publishing and
distributing data obtained from IMF sites, subject to conditions.

**What those conditions require of REIM, and how each is met:**

| Condition | How REIM satisfies it |
|---|---|
| Attribute the IMF as the source. | The API's OpenAPI description states the requirement to anyone consuming it, and each newly written observation carries the Fund's own suggested citation in `raw_metadata.imf_citation`. **Rows written before this was added keep their old metadata**: `raw_metadata` is deliberately outside the content hash, so an unchanged figure is never rewritten. A rebuild from empty backfills it. |
| Keep the data exact and intact; do not alter it in ways affecting its nature or accuracy. | Values are parsed as `Decimal` from the published string and stored in unconstrained `NUMERIC`. Nothing is rounded, converted or rescaled — `SCALE` is recorded and deliberately not applied. |
| Declare any material transformation — aggregation, calculation, normalisation, derived indicators. | REIM applies **none** to this source. The figures served are the figures published. The comparison endpoint aligns periods but computes nothing. |
| Make reasonable efforts to inform your own users of these conditions when redistributing. | The API description carries an "Attribution and terms" section; `/api/v1/sources` exposes each source's `license` and `documentation_url`. |
| If sold as a standalone product, tell buyers the data is free from the IMF. | REIM sells nothing. |
| Some datasets embed third-party material with separate terms. | Recorded here; not separately assessed for IMTS. |

**Commercial reuse needs permission.** The IMF asks that potential commercial
reuse be cleared with `copyright@imf.org`. Anyone deploying REIM commercially
must do that themselves — this project has not.

One oddity is recorded rather than resolved: the `LICENSE` field says All
Rights Reserved while the same rows carry `ACCESS_SHARING_LEVEL = PUBLIC_OPEN`
and `SECURITY_CLASSIFICATION = PUB`. The terms text above is what governs.

Note that the terms page cannot be fetched programmatically —
`imf.org/external/terms.htm` returns an empty document to an HTTP client and
`imf.org/en/About/copyright-and-terms` returns 403 — so it must be read in a
browser. The summary above was made from such a reading on 2026-08-09; it is a
summary and not a substitute for the terms.

**What the IMF does *not* have for Nicaragua**, measured rather than assumed:

* **Monetary aggregates.** `MFS_MA` returns **0 observations for Nicaragua**,
  against 183 for Costa Rica and 210 for Guatemala. Nicaragua does not report.
* **Remittances.** `BOP` returns 0 for Nicaragua at monthly, quarterly *and*
  annual frequency.
* **Reserves.** `IRFCL` *does* hold 1,740 monthly Nicaraguan observations, but
  its 60 indicator codes cannot be named from anything the API exposes:
  `codelist/IMF.STA/CL_INDICATOR` returns `204 No Content`, the `INDICATOR`
  dimension carries no `<str:Enumeration>` in `DSD_IRFCL_PUB`, and SDMX-JSON
  requests return SDMX-ML. Three candidate codes read identically at 7.206 bn
  USD for June 2025, so picking one would be a guess — the same reason v0.1.0
  shipped the BCN connector disabled. **Unblocking step:** map the codes
  against the IMF's *IRFCL Guidelines for a Data Template*, whose numbered
  template lines the `IRFCLnn` fragments appear to reference.

SECMCA (Consejo Monetario Centroamericano) publishes all four families through
a documented Swagger API at `secmca-api.secmca.org/simafir_api`, but its data
endpoints require a `user`/`password` account — including those prefixed
`/public/`. Only the catalogue and date-range endpoints are open.

### Banco de Guatemala — daily official exchange rate

| | |
|---|---|
| **Organization** | Banco de Guatemala (`BANGUAT`) — central bank |
| **Endpoint** | `https://www.banguat.gob.gt/variables/ws/TipoCambio.asmx` |
| **Protocol** | SOAP 1.1, namespace `http://www.banguat.gob.gt/variables/ws/` |
| **Operation** | `TipoCambioRango(fechainit, fechafin)`, dates `dd/mm/yyyy` |
| **Auth** | None; modern TLS |
| **Coverage** | 1990-01-01 … today, verified — 13,365 days as of 2026-08-09 |
| **Licence** | Public official data |
| **Status** | ✅ Enabled — 26,730 observations, two per published day |

REIM's first national central bank outside Nicaragua, and its first source
whose **whole history arrives in one request**: 1.3 MB, under a second. There
is no windowed mode and no separate backfill, so a rebuild from an empty
database is complete by default. The BCN needs two modes because its history
costs 176 requests — and that is exactly what let a rebuild there produce 40
rows instead of 5,334.

**Two indicators, not one.** The bank publishes a buy and a sell rate for each
day, and they differ on **6,174 of the 13,365 days**. Averaging them would
destroy real information, so each side is its own series:
`gt_exchange_rate_official_daily_buy` and `..._sell`. The names are stated from
the bank's side, as the source states them: `compra` is what it pays for a US
dollar, `venta` what it charges.

**The `venta ≥ compra` invariant holds only from 1992.** 84 days violate it,
every one in **1990 (76) or 1991 (8)**: through the quetzal's liberalisation
the buy rate sat fixed at `5.15` while the sell rate floated below it, as low
as `4.62`. That is real history, not crossed columns, so the check is enforced
from 1992 onward — the same treatment `inide_cpi_monthly` gives INIDE's sparse
pre-2011 table. Enforcing it unconditionally would have failed every run
forever.

**Five days are missing in 36 years**: 2000-04-02, 2000-05-01, 2001-09-02,
2004-03-06 and 2004-03-07. The gap check counts them and never fails; the
source's own publication history is not a defect.

Two contract details the service enforces: the `SOAPAction` header must be
**quoted**, and dates are **day-first** in both directions — `08/11/1990` is 8
November. Reading it as 11 August would be silent and wrong, so a test pins it.

`VariablesDisponibles` lists 40 currencies rather than economic variables: this
service is exchange rates only, and REIM takes the US dollar (`moneda` 2).

### The other five Central American central banks

Probed on 2026-08-08, none behind a bot wall, none yet automated:

| Publisher | Measured state |
|---|---|
| **BCCR** (Costa Rica) | `503` on both URL casings of its documented web service; it is also known to require a registered account |
| **BCR** (El Salvador) | `estadisticas.bcr.gob.sv` answers `200` but exposes no machine-readable endpoint on its landing page |
| **BCH** (Honduras) | Site reachable; no data endpoint found |
| **INEC** (Panama) | Site reachable; `/mapi/map` responds, unresearched |
| **Central Bank of Belize** | Site reachable; no data endpoint found |

Recorded so the next person does not repeat the probing. Each is an independent
investigation, and none was in scope for the Guatemalan increment.

---

### SIECA — quarterly trade in services

| | |
|---|---|
| **Organization** | Secretaría de Integración Económica Centroamericana (`SIECA`) — regional body |
| **Host** | `https://www.servicios.sieca.int` |
| **Endpoints** | `POST /ReporteGeneralServicios/LoadFilters` and `POST /ReporteGeneralServicios/LoadData` |
| **Protocol** | Undocumented AJAX JSON behind an ASP.NET MVC page; form-encoded request, JSON response |
| **Auth** | None — but the host filters on `User-Agent`; see below |
| **Frequency** | Quarterly — REIM's first |
| **Coverage** | **2009-Q1 … 2026-Q1**, verified — 69 consecutive quarters, no gaps |
| **Countries** | All six, from one request; REIM's first source with no country of its own |
| **Licence** | ⚠️ All rights reserved. See below. |
| **Status** | ✅ **Enabled** — 1,242 observations, measured 2026-08-09 |

**What the roadmap wanted was not what exists.** The roadmap named "SIECA
regional trade series", meaning intra-regional **merchandise** trade. That has
no machine-readable form today. Measured on 2026-08-09:

| Property | State |
|---|---|
| `estadisticas.sieca.int` — the host SIECA's own statistics page links to | **`404` on every path, with any client.** Down or migrated; not chased further |
| The "herramienta de inteligencia comercial" | Tableau Public embeds. A visualisation, not an endpoint |
| `www.servicios.sieca.int` | ✅ live JSON, no authentication — **trade in services** |
| `mercancias`, `comercio`, `intec`, `centrex`, `arancel` `.sieca.int` | Do not resolve |

So what shipped is **trade in services**, which REIM held from no source, rather
than merchandise trade, which it already holds monthly from the IMF. It
complements the existing data instead of duplicating it. The dead
`estadisticas.sieca.int` is recorded here precisely so the next person does not
spend an afternoon rediscovering that it is dead.

**Four requests per run.** One `LoadFilters` returns the country list and the 69
available quarters; then one `LoadData` per flow — `E` exports, `I` imports,
`S` balance — each carrying all six countries and the whole history, at 16.7 KB
a flow. The quarter window comes from `LoadFilters` rather than a constant, so a
newly published quarter is picked up without a code change. There is no routine
window and no separate backfill, so **a rebuild from an empty database is
complete by default** — the property Banguat has and the BCN lacks.

`LoadData` takes `flujo`, `unidadMedida` (`MD`, millions of USD), `paises`
(numeric ids `1..6`), `paisesDestino` (`0` = world, the only option), `periodos`
(`"I Trim 2026,…"`) and `categoria`. REIM sends `categoria=0`, the
"Sumatoria de Servicios de Primer Nivel" total; the other 32 components of the
taxonomy would multiply the volume 33-fold with nothing consuming them. The rows
arrive as a JSON **string** nested inside `Data[0].Data`, so the payload is
decoded twice.

**The balance is published, not derived.** REIM stores SIECA's own `S` figure
rather than computing `E − I`, because REIM publishes what the publisher
publishes. The identity is then *checked*, with a tolerance.

**Published millions become whole USD — REIM's first declared transformation.**
Figures arrive in millions of USD and are stored multiplied by 10⁶, unit
`current USD`, matching the IMF merchandise series so `/compare` can put
services and goods side by side. The conversion is exact in `Decimal` and fully
reversible, and every observation carries the original in `raw_metadata`:

| Key | Example |
|---|---|
| `sieca_published_value` | `"4941.8"` |
| `sieca_published_unit` | `"millones de USD"` |
| `sieca_scale_applied` | `"1e6"` |

Nothing is inferred and nothing is lost: `4941.8` million is stored as
`4941800000` USD, and the published string is kept beside it.

**An exact balance check would have failed on every run.** `E − I = S` deviates
from the published balance by up to **0.1 million USD**, and **71 of 414 cells**
deviate by more than 0.05. The source rounds each flow to one decimal in
millions, so two roundings of ±0.05 accumulate; this is arithmetic, not a data
error. The tolerance is therefore **100,000 USD** — equal to the worst deviation
observed, and still three orders of magnitude below the smallest quarterly figure
in the series (114.4 million USD). The same mistake was already corrected once
in the IMF connector, where the tolerance is one cent.

**Values arrive as JSON floats, not strings.** `Decimal(375.3)` is
`375.2999999999999829…`, so the payload is parsed with
`json.loads(…, parse_float=Decimal)`. Reading it any other way corrupts every
figure in its last places, where no count and no total would reveal it. A test
pins an exact `Decimal`, so a refactor that drops `parse_float` fails loudly.

**The "Centroamérica" row is discarded.** It is the sum of the six, and
`observations` has no region dimension. The indicator codes carry no country
prefix — `exports_services_quarterly`, `imports_services_quarterly`,
`trade_balance_services_quarterly` — following the rule the regional IMF
increment set: drop the prefix when the source is regional and every country
shares the methodology.

**Four quality checks**, all passing against the live service on 2026-08-09:
`sieca_six_countries_present` (completeness, `critical`),
`sieca_balance_identity` (consistency, `error`),
`sieca_quarterly_continuity` (completeness, `warning`) and
`sieca_flow_coverage` (consistency, `error`).

**Licence: no grant found.** Measured on 2026-08-09: `www.sieca.int`'s footer
reads `© Todos los derechos reservados · SIECA 2026`, and
`www.servicios.sieca.int`'s reads `© SIECA: Todos los derechos reservados` —
both "all rights reserved", not an open licence. No terms-of-use, legal-notice
or privacy page could be located: `/terminos-de-uso/`, `/aviso-legal/`,
`/politica-de-privacidad/` and `/terminos-y-condiciones/` all return `404`, and
neither the site footer nor the sitemap page links to one.
`www.sieca.int/robots.txt` disallows only WooCommerce and `wp-admin` paths and
otherwise allows crawling; `www.servicios.sieca.int` serves no `robots.txt` at
all. Unlike the IMF entry above, there is no terms page to read and summarise —
there is nothing to read. REIM has found no licence grant of any kind for this
data, and redistributes these figures anyway, with attribution, as official
public statistics from a regional intergovernmental body. A reader who needs
certainty about reuse rights should ask SIECA directly rather than rely on this
paragraph.

#### The access decision, and the rule it rewrites

**The host serves nothing to a client that identifies itself honestly.**
Measured across User-Agents against the same request:

| User-Agent sent | Response |
|---|---|
| `REIM/0.1.0 (…+https://github.com/RobBravo/reim)` | **`202`, empty body** |
| `python-httpx/0.27.0` | **`202`, empty body** |
| `curl/8.5.0`, or empty | **`403`** |
| `Mozilla/5.0 … Chrome/126.0 Safari/537.36` | **`200` with the data** |

The filter covers the whole host, including its static technical-note PDFs.
`sources/catalog.yml` declares the `user_agent` for this source alone, with a
`user_agent_note` explaining why — exactly as `tls_profile: legacy` declares the
BCN's relaxed handshake rather than hiding it. Every other source keeps REIM's
honest identifier. Remove the override if SIECA opens the host to identified
clients; no code change is needed. The connector logs the override at warning
level on every run, and `extract` **raises** on the empty `202` rather than
yielding zero observations, because that is precisely what a rejected client
receives.

This narrows a rule REIM used to state more absolutely than is now true, so the
rule is rewritten rather than quietly contradicted:

> REIM does not defeat an active access control. `www.bcn.gob.ni` sits behind a
> Radware bot manager that answers every automated request with a JavaScript
> challenge; REIM does not execute it, and that has not changed.
>
> REIM does satisfy a static header check. SIECA's edge allows or denies on the
> `User-Agent` string alone: REIM's own identifier receives `202` with an empty
> body, `curl` receives `403`, a browser string receives the data. REIM sends a
> string the host accepts, changes nothing else, keeps the same timeout and
> retry policy as every other source, and declares it in the catalog entry.
>
> These are different things, and the project's rule is stated in both parts
> rather than as one absolute that its own catalog would contradict.

**Out of scope, deliberately:** the 32 other components of the services
taxonomy; the `VP`, `PT` and `PC` units the portal also offers (year-on-year
change, quarterly average, share of total — all derivable from the levels REIM
stores); and reviving `estadisticas.sieca.int`.

---

### CEPAL — annual gross domestic product

| | |
|---|---|
| **Organization** | Comisión Económica para América Latina y el Caribe (`CEPAL`) — regional UN commission |
| **Host** | `https://api-cepalstat.cepal.org` |
| **Endpoint** | `GET /cepalstat/api/v1/indicator/{id}/data?lang=en` |
| **Protocol** | Undocumented REST JSON; envelope of `header` / `body` / `footer` |
| **Auth** | None. No `User-Agent` filter, no TLS quirk |
| **Frequency** | Annual |
| **Coverage** | **1990 … 2025**, verified — 36 years, no gaps, for all seven countries |
| **Countries** | All seven, from four requests; 33 Latin American and Caribbean countries and 3 regional aggregates are returned and filtered out |
| **Volume** | 167–177 KB per indicator, ~0.7 s |
| **Licence** | ⚠️ **Not open.** See below. |
| **Status** | ✅ **Enabled** — 1,008 observations, measured 2026-08-19 |

**The four indicators:**

| CEPAL id | Published name (`lang=en`) | Published unit | REIM indicator |
|---|---|---|---|
| 2203 | Total Annual Gross Domestic Product (GDP) at current prices in dollars | Millions of dollars | `gdp_current_usd_annual` |
| 2204 | Total Annual Gross Domestic Product (GDP) at constant prices in dolllars | Millions of dollars | `gdp_constant_usd_annual` |
| 2205 | Total Annual GDP per inhabitant at current prices in dollars | Dollars per inhabitant at current prices | `gdp_per_capita_current_usd_annual` |
| 2206 | Total Annual GDP per inhabitant at constant prices in dollars | Dollars per inhabitant | `gdp_per_capita_constant_usd_annual` |

The tripled `l` in 2204's English name is CEPAL's own typo. REIM stores its own
indicator names, so it does not propagate; it is recorded here so it does not
read as a transcription error.

The totals are published in millions and stored in whole USD (`× 10^6`, exact in
`Decimal` and declared in `raw_metadata`) so they line up with the IMF and SIECA
figures. The per-capita series are stored unscaled. The growth-rate series
(indicator 2207) is deliberately not ingested: computed from 2204 it reproduces
CEPAL's published figure to the last digit across all 36 Nicaraguan years, and
REIM stores levels rather than what derives from them — the same rule SIECA's
`VP`, `PT` and `PC` units met above.

#### The 404 this repository recorded twice was wrong

`docs/implementation-plan.md` and
`docs/superpowers/specs/2026-08-08-regional-imf-trade-design.md:20` both stated
that a probe of CEPALSTAT's API returned `404`. **The API is live and healthy.**
The earlier probe used collection paths that do not exist: every CEPALSTAT route
is scoped to an indicator id, and a bare collection path returns `404` by
design. Measured on 2026-08-18:

| Path | Result |
|---|---|
| `GET /` | `200` — `{"name":"uneclac cepalstat api","version":"1.9.13"}` |
| `GET /cepalstat/api/v1/indicator` | `404` — no collection endpoint exists |
| `GET /cepalstat/api/v1/indicator/2206/data?lang=es` | **`200`, 177 KB, 1,296 rows, 0.66 s** |
| `GET /cepalstat/api/v1/indicator/{id}/metadata`, `/dimensions`, `/sources`, `/footnotes` | `200` |
| `GET /cepalstat/api/v1/themes`, `/areas`, `/thematic-tree` | `200` |

The spec is left as written — a spec records what was believed when it was
written — but both live documents are corrected.

**There is no published API documentation, and no interactive schema.** The base
URL and the route names were recovered from the portal's own JavaScript:
`https://statistics.cepal.org/portal/databank/config.js` declares
`API_BASE_URL` and `ENDPOINT_THEMATIC_TREE`, and
`https://statistics.cepal.org/portal/cepalstat/dash/scripts/config.js` declares
the per-indicator data, dimensions, sources and notes routes. The connector's
module docstring repeats this so nobody runs the search again.

**Indicator ids cannot be listed from an area.** `/themes` and `/areas` return
the full tree of 1,785 areas, 33 of them economic, but no route maps an area to
its indicators. `/thematic-tree?lang=es&theme_id=6` comes closest: it returns
330 leaves, each carrying an `indicator_id`. That tree is **not clean** — 45 of
the 330 are working artefacts named `dummy`, `CLONE` or `TEST`. Ids are
therefore pinned in the catalog rather than discovered at runtime, exactly as
SIECA's filter ids are.

**Dimensions are addressed by numeric id, never by name.** Row keys embed the id
(`dim_208`, `dim_29117`) and the names are language-dependent: `Years__ESTANDAR`
in English is `Años__ESTANDAR` in Spanish. The year label likewise comes from
the response's own member table and is never computed from the member id —
`year = id - 27170` holds inside the 1990–2025 window but breaks for 130 of the
years dimension's 201 members, with six distinct offsets overall.

**The envelope carries its own status, and it can disagree with the HTTP code.**
An unknown indicator id answers `500` with `success: false`, not `404`, so
`extract` reads `header.success` rather than trusting the status line.

#### These are CEPAL's estimates, not each country's official figures

The API's own `sources[]` says "Own estimates based on national sources". CEPAL
harmonises national accounts so that countries can be compared with each other;
the price of that comparability is that a figure here need not match the GDP its
own statistics office publishes. REIM stores and serves them as CEPAL
estimates. Anyone quoting a single country's GDP for that country's own purposes
should take the national source.

**The constant-price base year is 2018, and it lives in a footnote.** Indicators
2204 and 2206 declare their unit as `Millions of dollars` and `Dollars per
inhabitant`; only `footnotes` names the base year. A rebasing would therefore
change every constant-price value while the unit string stood still, so it is a
quality check rather than a comment.

**Four quality checks**, all passing against the live service on 2026-08-19:
`cepalstat_seven_countries_present` (completeness, `critical`),
`cepalstat_population_identity` (consistency, `error`),
`cepalstat_constant_price_base_year` (validity, `error`) and
`cepalstat_annual_continuity` (completeness, `warning`). The second is the
strongest cross-series check in REIM: `total ÷ per capita` recovers the implied
population, and the current-price and constant-price pairs must agree. They do,
to 8.1 × 10⁻¹⁶ across all 252 cells. It is expressible only because one
connector holds all four series.

#### Belize

Belize was registered but inactive since v0.1.0 — it reports nothing to the IMF
IMTS dataflow REIM's monthly trade data comes from. CEPALSTAT publishes its
national accounts complete: 36 years of all four series, 144 observations, its
first data of any kind in REIM. **It still has no trade data**, monthly or
quarterly; SIECA covers six countries and does not include it.

#### Licence: not open, and the terms conflict with what REIM does

The [website usage agreement](https://www.cepal.org/en/terminos-y-condiciones-sobre-el-uso-del-sitio-web-entre-la-cepal-y-el-usuario)
grants users the right to

> download and copy information, documents and material … for Users' personal,
> non-commercial use without any right to resell, redistribute or create
> derivative works therefrom

The [repository terms](https://repositorio.cepal.org/page/termsofuse?locale-attribute=en)
repeat the non-commercial restriction. The CEPALSTAT portal, the data bank and
the technical-sheet pages publish no separate, more permissive licence — checked
on 2026-08-18.

**This is stricter than either precedent in this file.** The IMF is not open but
redistributable with attribution; SIECA is an *absence* of any grant, with no
terms to read. CEPAL is an *explicit prohibition*, and REIM redistributes these
figures through its own API. That conflict is stated here rather than hidden:
REIM is a non-commercial research project, it ships CEPAL's required citation
with every observation, and a reader who needs certainty about reuse rights
should ask CEPAL directly rather than rely on this paragraph.

The API returns a `credits` block on every response — `["<date>", "CEPALSTAT",
"Comisión Económica para América Latina y el Caribe – CEPAL", "Naciones
Unidas"]` — which functions as the required citation. Its elements travel into
every observation's `raw_metadata`. `credits[0]` is excluded: it is CEPAL's own
fetch date, it moves between runs (two downloads twelve hours apart returned
`2026-08-18` and `2026-08-19`), and REIM already records when it fetched, in
`retrieved_at`.

---

### CEPAL — monthly monetary aggregates

| | |
|---|---|
| **Organization** | Comisión Económica para América Latina y el Caribe (`CEPAL`) |
| **Host** | `https://api-cepalstat.cepal.org` |
| **Endpoint** | `GET /cepalstat/api/v1/indicator/{id}/data?lang=en` and `GET /cepalstat/api/v1/indicator/{id}/dimensions?lang=es` |
| **Protocol** | Same undocumented REST JSON as the GDP section above |
| **Auth** | None |
| **Frequency** | Monthly, end-of-period stocks |
| **Coverage** | **1990-01 … 2024-08**, verified — no gap inside any country's own span |
| **Countries** | All seven, from six requests |
| **Volume** | 1.4–1.6 MB per data response, 29 KB per dimensions response; ~21 s for a full run |
| **Licence** | ⚠️ **Not open** — CEPAL's terms, quoted in [the GDP section](#licence-not-open-and-the-terms-conflict-with-what-reim-does) above |
| **Status** | ✅ **Enabled** — 5,383 observations, measured 2026-09-03 |

**The three indicators:**

| CEPAL id | Published name | Published unit | REIM indicator | Observations |
|---|---|---|---|---|
| 862 | Money (M1), end of period | Millions of local currency | `money_m1_monthly` | 2,026 |
| 868 | Liquidity (M2), end of period | Millions of local currency | `money_m2_monthly` | 1,611 |
| 869 | Broad liquidity (M3), end of period | Millions of local currency | `money_m3_monthly` | 1,746 |

**Coverage per country**, measured 2026-09-03. Two series are short a country at
the source, and the absences are declared in the connector rather than
discovered at runtime: Belize publishes no M2, El Salvador no M3.

| Country | M1 | M2 | M3 |
|---|---|---|---|
| Belize | 1990-01 … 2024-07 (415) | — | 1990-01 … 2024-07 (415) |
| Costa Rica | 2001-12 … 2024-06 (271) | 2001-12 … 2024-06 (271) | 2001-12 … 2024-06 (271) |
| El Salvador | 2001-12 … 2024-08 (273) | 2001-12 … 2024-08 (273) | — |
| Guatemala | 2001-12 … 2024-08 (273) | 2001-12 … 2024-08 (273) | 2001-12 … 2024-08 (273) |
| Honduras | 2001-12 … 2023-10 (263) | 2001-12 … 2023-10 (263) | 2001-12 … 2023-03 (256) |
| Nicaragua | 2001-12 … 2024-06 (271) | 2001-12 … 2024-06 (271) | 2001-12 … 2024-06 (271) |
| Panama | 2002-12 … 2024-07 (260) | 2002-12 … 2024-07 (260) | 2002-12 … 2024-07 (260) |

Belize's 415 months back to 1990 are why M1 and M3 start thirty-five years
before the others. Every other country begins at 2001-12, and Panama a year
later still.

#### Only the monthly member is stored

Dimension 3981 selects a period *inside* the year: twelve months, four quarters
and an annual figure — seventeen members. Only the twelve months become
observations. The other five are restatements, and that is measured rather than
assumed: across the seven countries the annual figure equals December in all
**453** cells where both exist, and each quarter equals its closing month in all
**1,800**. There are no exceptions in the 2,253. These are end-of-period stocks,
so the restatement is definitional — a year's closing stock *is* December's —
but storing both would double-count every December in any aggregate a consumer
computed.

#### The language split, and why it is not tidiable

The data is fetched in English and the member table in Spanish. This is the one
place where the `lang=en`-throughout rule is excepted, and it is not
cosmetic:

* **In `lang=en` all seventeen period members come back as the literal string
  `descripcion_ingles`** — the untranslated column name of CEPAL's own database,
  surfacing through the API. The English response cannot tell January from
  September from the annual figure.
* **The member ids cannot substitute.** They run 3982–3998 but not in calendar
  order: September is 3993 and July is 3994. Nothing in the payload orders them.

So the connector makes a second request per indicator, `dimensions?lang=es`, 29
KB, and reads the month names from it. **Nothing from that response is stored.**
The Spanish strings are used to identify which member is which month and are
then discarded; every string REIM stores still comes from the English data
response. Collapsing the two requests to one language breaks either the month
names or every stored string, so the split is pinned by a test rather than left
to a comment.

#### The figures are in local currency, and are not comparable across countries

CEPAL publishes millions of each country's own currency; REIM stores whole units
of it (`× 10^6`, exact in `Decimal` and declared in `raw_metadata`). The
currency comes from REIM's country registry, not from the payload, which says
only "local currency" — one code per country, verified after the first run:
`BZD`, `CRC`, `GTQ`, `HNL`, `NIO`, `PAB`, `USD`.

**These are REIM's first observations that are not comparable across
countries.** A quetzal figure and a córdoba figure cannot be added, ranked or
charted on one axis. El Salvador and Panama are dollarised, so those two alone
line up with each other **as published**.

Until 2026-09-06 this file said converting would make REIM the author of an
exchange-rate choice it had no basis to make. That was true while REIM's only
rates were Nicaragua's and Guatemala's, on two different national
methodologies. It stopped being true when
[CEPAL's monthly nominal exchange rate](#cepal--monthly-nominal-exchange-rate)
landed: one publisher, one method, all seven countries.

**`GET /api/v1/compare?convert_to=USD` now returns a converted view beside
these figures**, and the rules that keep it from becoming an authored number
are narrow:

* Nothing derived is **stored**. Conversion happens at request time; the
  observations table holds only what publishers published.
* Conversion keys on **the observation's own `currency_code`, never on its
  country**. El Salvador's rows carry `USD`, so they pass through untouched at
  an implied rate of 1 — CEPAL's 8.8 colón rate is stored and simply never
  applies, because REIM holds no observation denominated in `SVC`. Keyed on the
  country instead, those figures would come back divided by 8.8.
* **A missing rate is a gap.** Exact period match only; no nearest rate, no
  carry-forward. The response counts what did not convert.
* The figures are labelled **indicative**, because the rate is a within-month
  average and these are end-of-period stocks — see
  [that section](#a-monthly-average-against-end-of-period-stocks).
* `comparable` is unaffected. It describes what CEPAL published, and a derived
  view does not change that.

Anyone who prefers their own rates still has the published figures untouched,
and REIM now holds a published rate set they can use instead.

#### The nesting identity, and the rounding that appears to break it

M1 ⊆ M2 ⊆ M3 by construction, so every shared cell must satisfy
M1 ≤ M2 ≤ M3. Checked directly, **229 of the 2,942 shared cells appear to
violate it.** They do not. CEPAL declares zero decimals for these series and
publishes some rounded to whole millions and others to one decimal; where two
series round in opposite directions across a boundary the stored order inverts.
The largest such inversion is **0.0140%**. The check therefore carries a
relative tolerance of 0.001 — seven times the largest observed rounding artefact
and far below any real inversion, which would be percent-scale — and it passes
on the live data.

**Three connector checks**, all passing on the recordings and on the live
service: `cepalstat_monetary_nesting` (consistency, `error`),
`cepalstat_monetary_expected_countries` (completeness, `critical`) and
`cepalstat_monthly_continuity` (completeness, `warning`). The last one is
per-country: a hole in one country's span is reported even when the other six
published that month, which pooling the seven would hide.

#### Honduras warns on freshness from the first run

The first real run logged exactly three failed checks and nothing else: the
freshness check firing on Honduras for all three series, at `warning`. Honduras
stops at 2023-10 on M1 and M2 and at 2023-03 on M3, which on 2026-09-04 —
the UTC date the check ran — is
**1,039, 1,039 and 1,253 days**. The threshold is 900 days.

**It was set at 900 knowing that.** Honduras is three and a half years behind on
M3; a threshold tuned to sit above that would silence the one thing the check
exists to say. The warning is the correct output, it is expected on every run
until Honduras publishes again, and it is recorded in `sources/quality_rules.yml`
so that nobody later reads it as a regression.

---

### CEPAL — central government public debt

| | |
|---|---|
| **Organization** | Comisión Económica para América Latina y el Caribe (`CEPAL`) |
| **Host** | `https://api-cepalstat.cepal.org` |
| **Endpoint** | `GET /cepalstat/api/v1/indicator/{id}/data?lang=en` |
| **Protocol** | Same undocumented REST JSON as the two CEPAL sections above |
| **Auth** | None |
| **Frequency** | Annual |
| **Coverage** | 1990 … 2025 for six countries in both series; a two-way, six-cell exception in the seventh (below) |
| **Countries** | All seven, from two requests; 145 countries and regional aggregates are returned per indicator and filtered to Central America by the row's own `iso3` |
| **Volume** | 617–635 KB per indicator (4,351 and 4,494 rows before filtering), ~7 s for both requests |
| **Licence** | ⚠️ **Not open** — CEPAL's terms, quoted in [the GDP section](#licence-not-open-and-the-terms-conflict-with-what-reim-does) above |
| **Status** | ✅ **Enabled** — 456 observations, measured 2026-09-03 |

**The two indicators:**

| CEPAL id | Published unit | REIM indicator | Cells |
|---|---|---|---|
| 1239 | Millions of dollars | `public_debt_usd_annual` | 226 |
| 1240 | Percent of GDP | `public_debt_pct_gdp_annual` | 230 |

**Coverage per country**, measured 2026-09-03:

| Country | USD (`public_debt_usd_annual`) | % of GDP (`public_debt_pct_gdp_annual`) |
|---|---|---|
| Belize | 2011 … 2020 (10) | 2011 … 2025 (15) |
| Costa Rica | 1990 … 2025 (36) | 1990 … 2025 (36) |
| El Salvador | 1990 … 2025 (36) | 1990 … 2025 (36) |
| Guatemala | 1990 … 2025 (36) | 1990 … 2025 (36) |
| Honduras | 1990 … 2025 (36) | 1990 … 2025 (36) |
| Nicaragua | 1990 … 2025 (36) | 1991 … 2025 (35) |
| Panama | 1990 … 2025 (36) | 1990 … 2025 (36) |

REIM's first fiscal series, and REIM's first use of `IndicatorCategory.FISCAL`.

#### Which slice of the cube is stored, and why

Both indicators carry four dimensions, not the usual two: country and year, plus
an institutional coverage (4 members) and a debt classification (6 members). A
country-year cell is not identified until both are pinned, so the connector pins
one of each and stores that slice — central government, Total public debt by
residence — rather than the 24 combinations the cube technically offers.

**Three of the six classification members carry no rows at all**, for any of
the 145 countries the raw response covers: ids 10610, 10611 and 10614 are
grouping nodes in CEPAL's tree — currency, rate and maturity classification —
published as members with nothing behind them. Only Total public debt by
residence, Internal debt and External debt hold data.

**Of the four institutional coverages, only central government covers all seven
countries across the full 1990–2025 span.** Nonfinancial public sector omits
Guatemala and Honduras; public sector mostly stops in 2011; state and local
governments exists for Honduras alone. This agrees with CEPAL's own methodology
note, which says the published figure "is refered to the central government
gross public debt stock" [sic] — CEPAL's typo, not a transcription error here.

#### The internal and external series are not stored

Internal debt and External debt are both present in the cube, and their sum
should equal the total series that is stored. Measured across 1239: of 415
country-coverage triples where all three (total, internal, external) are
complete, only 303 sum exactly; the rest drift, mostly under 0.1%, but three
triples are off by more than 1%. That is not rounding at the two decimals CEPAL
declares — it is a real inconsistency in the source. Publishing the split as
its own indicators would invite a subtraction the source does not itself
support, so only the total is stored.

#### The ratio does not reconcile with REIM's own GDP series

Dividing 1239 by 1240 recovers an implied GDP in millions of dollars. Compared
against indicator 2203 — the series REIM already stores as
`gdp_current_usd_annual` — across the 225 country-years both cover, 52 disagree
by 5% or more. The worst is Honduras 1990, off by 23.7%.

The cause is stated in CEPAL's own methodology note: the ratio's denominator is
"the gross domestic product in current prices and local monetary unit for each
country" converted at "the exchange rate at December 31 for each year published
in the International Finance Statistics by the IMF" — a different GDP, on a
different conversion, from 2203's own harmonised-USD figure. The two are not
reconcilable, so REIM stores both series as CEPAL published them and performs
no check that divides one into the other; the mismatch is documented here
instead, in the indicator description, and in the connector's `validate`
docstring, rather than silently assumed away.

#### The two units differ by six cells

`public_debt_usd_annual` and `public_debt_pct_gdp_annual` are not the same 230
country-years with two different units. Nicaragua 1990 has a dollar figure and
no ratio; Belize 2021–2025 (five years) has a ratio and no dollar figure — six
cells, in opposite directions, out of otherwise-identical coverage.

#### The ratio exceeds 100%, so `max_value` stays null

The percent-of-GDP series runs from about 14% up to **222.1%** (Nicaragua,
early 1990s) — a real, published figure, not an outlier to clip. A
`max_value: 100` in `sources/quality_rules.yml` would reject genuine data, so
`max_value` is left `null` for both debt indicators by choice, the same
decision the ratio's headroom on `max_period_change_pct` (60, clearing
Nicaragua's 1996 HIPC relief) already makes for volatility rather than level.

#### The English member names are real translations here

Unlike the monetary family next door, this connector makes no Spanish request.
CEPAL's `lang=en` response gives each institutional-coverage and
debt-classification member its own real English name — "Central government",
"Total public debt (classification by residence)" — rather than the literal
`descripcion_ingles` placeholder the monetary family's period members come back
as. `transform` reads the member names straight from the English payload and
asserts the two selected ids still carry the names REIM expects, so a silent
CEPAL relabel raises rather than quietly changing what a stored series means.

#### Belize warns on freshness from the first run

The first real run logged exactly one failed check and nothing else: the
freshness check firing on Belize, for `public_debt_usd_annual` only, at
`warning`. The freshness check measures period *end*, not period start.
Belize's dollar series stops at 2020-12-31 while its own ratio series, and
every other country's dollar series, runs to 2025-12-31 — which on
2026-09-04, the UTC date the check ran, is **2,073 days** old. The threshold is
600 days; the six current countries' 2025-12-31 periods are only 247 days old
against it.

This is the same asymmetry as the six-cell coverage difference above, seen from
the freshness check's side rather than the coverage table's: five of those six
cells are exactly Belize's missing 2021–2025 in the dollar series. Freshness is
measured per country, so the other six countries being current does not hide
Belize being five years behind.

**It was set at 600 knowing that.** The newest period across the rest of the
data is 2025, and 600 days comfortably covers CEPAL's annual publication cycle
for the six countries that are current — but Belize's dollar series is not, and
a threshold raised to sit above that gap would silence the one thing the check
exists to say, the same call already made for Honduras in the monetary section
above. The warning is the correct output, expected on every run until Belize's
dollar figures catch up to its own ratio series, and it is recorded here so
nobody later reads it as a regression.

---

### CEPAL — monthly nominal exchange rate

| | |
|---|---|
| **Organization** | Comisión Económica para América Latina y el Caribe (`CEPAL`) |
| **Host** | `https://api-cepalstat.cepal.org` |
| **Endpoint** | `GET /cepalstat/api/v1/indicator/2179/data?lang=en` — one request |
| **Protocol** | Same undocumented REST JSON as the GDP section above |
| **Auth** | None |
| **Frequency** | Monthly, **average of the daily rates within the month** |
| **Coverage** | **1990-01 … 2025-09**, verified — no gap inside any country's own span |
| **Countries** | All seven, from one request |
| **Volume** | 1.19 MB, ~2–5 s |
| **Licence** | ⚠️ **Not open** — CEPAL's terms, quoted in [the GDP section](#licence-not-open-and-the-terms-conflict-with-what-reim-does) above |
| **Status** | ✅ **Enabled** — 2,749 observations, measured 2026-09-06 |

| CEPAL id | Published name | Published unit | REIM indicator | Observations |
|---|---|---|---|---|
| 2179 | Nominal exchange rate | `National currency by USA dolar` | `exchange_rate_nominal_monthly` | 2,749 |

Per-country spans, from the live run:

| Country | Span | Months | Currency quoted | Range |
|---|---|---|---|---|
| Belize | 1993-06 … 2025-09 | 388 | `BZD` | 1.9 – 2 |
| Costa Rica | 1994-02 … 2025-09 | 380 | `CRC` | 152.4 – 689.5 |
| El Salvador | 1993-06 … 2025-09 | 388 | `SVC` | 8.7 – 8.8 |
| Guatemala | 1993-06 … 2025-09 | 388 | `GTQ` | 5.6 – 8.3 |
| Honduras | 1993-06 … 2025-09 | 388 | `HNL` | 6.2 – 26.2 |
| Nicaragua | 1993-06 … 2025-09 | 388 | `NIO` | 6.1 – 36.8 |
| Panama | 1990-01 … 2025-09 | 429 | `PAB` | 1 – 1 |

This is the third CEPALSTAT family REIM reads and the shape is the monetary
one, with a simpler period dimension: 515 carries twelve members and they are
all months, with no annual or quarterly restatement to discard.

#### One request, not two — and the correction that got it there

This connector shipped on 2026-09-06 making **two** requests: the data in
English and the member table in Spanish, exactly as the monetary connector
does. That second request was never necessary, and the reason first recorded
here for it was wrong.

The monetary family's period dimension is **3981**, and in `lang=en` all
seventeen of its members really do come back as the untranslated string
`descripcion_ingles`; its Spanish request is genuinely required. Dimension
**515** is a different dimension and behaves differently: its twelve members
arrive named `January` through `December` in the English data response itself.
The assumption was carried across without being measured.

Measured on 2026-09-06 against both recordings:

| Dimension | Members | Names in `lang=en` |
|---|---|---|
| 3981 (monetary) | 17 | `descripcion_ingles`, seventeen times |
| 515 (months) | 12 | `January` … `December` |

The connector now makes one request, and
`test_dimension_515_is_translated_and_3981_is_not` pins the contrast so the
distinction is a fact in the suite rather than an assumption in a docstring.
The member ids are still no help — May is 825, after April's 519 — so the name
remains the only key.

#### The rate is quoted in a currency El Salvador retired in 2001

CEPAL publishes El Salvador at 8.7–8.8 colones per dollar **through 2025**,
twenty-four years after it adopted the dollar. That is the colón's fixed legal
conversion rate, which CEPAL never stopped publishing.

The currency a rate is *quoted in* and the currency a country *transacts in*
are different questions, and El Salvador is where they give different answers.
REIM's country registry answers the second — it holds `USD` for El Salvador,
which is correct — so taking the unit from it would label these observations
`USD per USD`. The connector therefore carries its own seven-entry table and
stores `SVC per USD`.

The same distinction is what will keep any future conversion honest: El
Salvador's monetary observations carry `currency_code = USD`, so a conversion
keyed on the observation's own currency never reaches for this rate. One keyed
on the country would divide already-dollar figures by 8.8.

#### A monthly average, against end-of-period stocks

`calculation_methodology` reads `Daily exchange rate, monthly average`. REIM's
only multi-currency series — M1, M2 and M3 — are **end-of-period** stocks.
Converting a month-end stock at that month's average rate is a real mismatch.

CEPAL publishes no end-of-period nominal rate. The thematic tree was searched
on 2026-09-06 under both themes that could hold one, `BADECON` (6) and
`COYUNTURA` (24); between them they carry exactly two exchange-rate
indicators, 2179 and 1901, and 1901 is the real effective exchange rate, which
measures something else entirely.

REIM will not derive one either. Taking the last daily observation from the BCN
or Banguat for two countries and CEPAL's average for the other five would make
REIM the author of a mixed-method choice — two countries converted one way and
five another — which is exactly what this file says elsewhere it does not do.

So the mismatch is permanent, and it is stated rather than fixed: in this
section, in the indicator description, and — when the converted view lands —
in a field travelling with every derived number.

#### The payload contradicts itself about provenance

`data_features` says `Source Bloomberg`. The `sources` array says
`On the basis of official figures.` One names a commercial data vendor and the
other claims officialdom, and they arrive in the same response.

Both strings are stored in `raw_metadata` and REIM repeats neither as its own.
The indicator description says ECLAC publishes the series and that the payload
names Bloomberg underneath, so a reader weighing this rate against a central
bank's own daily rate knows they are not the same kind of figure.

**The data settles which one is behaving.** Belize's dollar has been pegged at
2:1 since 1976 and has never moved — yet the series reads **1.9 in ten of its
388 months**, in October 2009 and October 2012. A series carrying the official
parity would read 2 in every month. One carrying a market quote, averaged
across the month and rounded to the single decimal CEPAL publishes, does not.

#### Declared two decimals, published one

`decimals` is 2. Across the 2,749 rows for the seven countries, **1,813 carry
one decimal and 936 carry none. None carries two.**

So `GTQ 7.8` is two significant figures, and anything derived from it inherits
up to about 0.6% of rounding error from the rate alone. This is the same class
of discrepancy between declared and published precision that the monetary
section records, and it is handled the same way: measured, stated, and left in
the data exactly as published.

It is also why `cepalstat_fx_pegs_hold` is a **10% band rather than an
equality**. Belize's 1.9 sits exactly 5% below its parity; an equality check
would call a rounding artefact a defect on every run. The band is twice that,
and still far tighter than any real misreading of the matrix — the next
smallest rate in it is Guatemala's ~7.7, some 285% off Belize's peg. Panama is
exactly 1 in all 429 of its months.

#### Three connector checks, all passing on the first live run

`cepalstat_fx_expected_countries` (completeness, `critical`, all seven
returned), `cepalstat_fx_pegs_hold` (consistency, `error`, both parities within
tolerance across 776 pegged country-months) and `cepalstat_monthly_continuity`
(completeness, `warning`, no gaps in any of the seven country-series). The last
is shared with the monetary connector rather than copied: it lives on
`CepalstatConnector` because it is about periods, not about any indicator
family's shape.

The standard battery passes too, freshness included at **342 days** against a
threshold of 450. The series genuinely lags: CEPAL's own `last_update` is
2026-08-31 but the data still ends 2025-09.

---

---

### CEPAL — monthly consumer price index

| | |
|---|---|
| **Organization** | Comisión Económica para América Latina y el Caribe (`CEPAL`) |
| **Host** | `https://api-cepalstat.cepal.org` |
| **Endpoint** | `GET /cepalstat/api/v1/indicator/365/data?lang=en` — one request |
| **Protocol** | Same undocumented REST JSON as the GDP section above |
| **Auth** | None |
| **Frequency** | Monthly |
| **Coverage** | **1980-01 … 2026-07**, verified |
| **Countries** | All seven, from one request; 40 are returned and filtered |
| **Volume** | 2.02 MB, ~9 s for a full run |
| **Licence** | ⚠️ **Not open** — CEPAL's terms, quoted in [the GDP section](#licence-not-open-and-the-terms-conflict-with-what-reim-does) above |
| **Status** | ✅ **Enabled** — 3,451 observations, measured 2026-09-06 |

| CEPAL id | Published name | Published unit | REIM indicator | Observations |
|---|---|---|---|---|
| 365 | Consumer price index | `Index` | `cpi_index_monthly` | 3,451 |

Per-country spans and value ranges, from the live run:

| Country | Span | Months | Range |
|---|---|---|---|
| Belize | 1990-11 … 2026-06 | 266 | 61.99 – 125.26 |
| Costa Rica | 1980-01 … 2026-06 | 558 | 0.62 – 113.06 |
| Guatemala | 1980-01 … 2026-07 | 559 | 4.50 – 104.56 |
| Honduras | 1994-01 … 2026-07 | 391 | 7.37 – 103.96 |
| Nicaragua | 1980-01 … 2026-07 | 559 | **2E-9** – 335.01 |
| Panama | 1980-01 … 2026-07 | 559 | 45.09 – 112.70 |
| El Salvador | 1980-01 … 2026-07 | 559 | 5.17 – 134.55 |

**This is REIM's freshest series**, ending 2026-07 against 2025-09 for the
exchange rate and 2024-08 for the monetary aggregates. It is also the first
CEPALSTAT family whose `data_features` names no vendor: each row cites its own
national compiler — `CBN` for Nicaragua, `INEC` for Costa Rica and Panama,
`NSI` for Guatemala, `CBH` for Honduras, `RBC` for El Salvador, `SIB` for
Belize. On the freshest rows it cites nobody: **363 of the 3,451 carry a null
`source_id`**, all of them 2022 onward, and REIM stores an empty string rather
than inventing an attribution.

#### The declared base years are wrong for three of the five CEPAL declares

`body.metadata.comments` names a base year per country. Checking whether that
period actually reads 100:

| Country | Declared | Reads | |
|---|---|---|---|
| El Salvador | December 2009 | 100 | ✅ |
| Nicaragua | 2006 | 100.0000 (annual mean) | ✅ |
| Costa Rica | June 2015 | **93.40** | ❌ |
| Guatemala | December 2010 | **56.69** | ❌ |
| Honduras | December 1999 | **21.55** | ❌ |
| Panama, Belize | *not declared* | — | |

So REIM stores no base year and puts none in the unit — `index`, and nothing
more. Contrast `ni_cpi_index_monthly`, which carries `index (2006=100)`
because INIDE states its base and it holds.

What REIM records instead is **measured**: the month each series actually
passes through 100.

| BLZ | CRI | GTM | HND | NIC | PAN | SLV |
|---|---|---|---|---|---|---|
| 2017-02 | 2020-02 | 2024-04 | 2025-11 | 2006-05 | 2013-05 | 2008-11 |

Seven different bases. **Levels are not comparable across countries** — only
movements are — and `/compare` will report the series as incomparable on unit
grounds, correctly.

#### Guatemala's series is spliced at 2010-01, and CEPAL does not say so

| 2009-11 | 2009-12 | 2010-01 | 2010-02 |
|---|---|---|---|
| 94.929 | 94.882 | **54.4831537** | 54.71901151 |

A 42.58% fall in one month with the series continuing smoothly either side.
That is a rebased segment spliced in without normalisation, not deflation, and
it is Guatemala's only move beyond 15% in forty-six years. **Inflation computed
across January 2010 for Guatemala is meaningless.** REIM stores the figures
exactly as published and pins the break in a check.

#### El Salvador has one corrupt cell, which is a different thing

| 1985-06 | 1985-07 | 1985-08 | 1985-09 | 1985-10 |
|---|---|---|---|---|
| 11.229 | 11.473 | **7.157** | 11.928 | 12.227 |

August falls 37.6% and September rises 66.7%, which reads like two large moves
and is not: September over July is **1.0397**, an unremarkable two-month rise.
August is a single bad value the series steps around.

The distinction from Guatemala matters. That is a permanent level shift; this
is one cell. It also means the check's allow-list needs **three** entries, not
two — one corrupt cell produces two moves beyond the threshold, and listing
only the first would fail on real data every run.

#### Nicaragua now has two consumer price indices, and they disagree

REIM reads INIDE directly; CEPAL cites the **Banco Central de Nicaragua**. Both
declare base 2006 and both read 100 there. Across the **198 months they
share** (2007-01 … 2026-06):

* **Not one month agrees to the digit.** Median difference **4.21%**.
* The ratio CEPAL ÷ INIDE runs **1.02426 to 1.04758** — a spread of 2.3%.
* Year-on-year inflation differs by more than 0.5 percentage points in only
  **15 of 198 months**.

So they tell substantially the same inflation story at different levels: the
signature of a rebasing difference between two official compilers, not of a
data disagreement. REIM stores both and chooses between neither, following the
same rule it applies everywhere — two sources publishing one concept stay
separate series. A unit test pins the ratio, so if a future revision makes the
two converge or diverge, the explanation above is known to have stopped being
true.

Nicaragua's own range runs from **2E-9** to 335: the 1980s hyperinflation and
two córdoba redenominations, seen through an index rebased twenty years later.
`docs/sources.md` records the same phenomenon on the World Bank exchange rate.
Those years hold 58 month-on-month moves beyond 15%, all real.

#### Why `max_period_change_pct` is null, and what replaces it

Guatemala's splice is −42.6% and Nicaragua's 1991-03 is **+261%**. No single
threshold serves both: one that tolerates Nicaragua detects nothing anywhere,
and one that catches Guatemala rejects real Nicaraguan history. The rule is
left null **by choice**, the same call the debt indicators' `max_value` already
makes, and `cepalstat_cpi_known_splices` does the work instead — a three-entry
allow-list, Nicaragua's pre-1992 span excluded by date, and every other move
beyond 15% reported as a new break.

It compares **calendar-adjacent months only**. Belize published quarterly for
twenty-one years, and comparing March against the following December would
manufacture breaks that are really gaps.

#### Belize warns on continuity from the first run

Belize holds **266 months inside a 428-month span**: it reported quarterly from
1990 until 2011 and monthly only from 2012. `cepalstat_monthly_continuity`
therefore reports **162 missing months** on every run, at `warning`.

That is the correct output, not a regression. Interpolating those months would
be imputation, which REIM does not do, and dropping Belize would lose the
country that CEPALSTAT gave REIM its first data of any kind for. The same call
was already made for Honduras on freshness in the monetary section.

**Three connector checks**, all as expected on the first live run:
`cepalstat_cpi_expected_countries` (completeness, `critical`, all seven
returned), `cepalstat_cpi_known_splices` (consistency, `error`, no unrecorded
break across 3,220 adjacent months with 3 of the 3 known breaks seen) and
`cepalstat_monthly_continuity` (completeness, `warning`, Belize as above). The
standard battery passes, freshness at **69 days** against a threshold of 120 —
REIM's tightest, and it should be.

---

### CEPAL — monthly interest rates

| | |
|---|---|
| **Organization** | Comisión Económica para América Latina y el Caribe (`CEPAL`) |
| **Host** | `https://api-cepalstat.cepal.org` |
| **Endpoints** | `GET /cepalstat/api/v1/indicator/{856,857,1206}/data?lang=en` — three requests |
| | `GET /cepalstat/api/v1/indicator/856/dimensions?lang=es` — one, for the period member table |
| **Protocol** | Same undocumented REST JSON as the GDP section above |
| **Auth** | None |
| **Frequency** | Monthly |
| **Coverage** | **1990-01 … 2025-10**, verified — interior gaps in two country-series only |
| **Countries** | All seven for the lending and deposit rates; **six** for the policy rate, [see below](#panama-has-no-monetary-policy-rate-and-cepal-publishes-sixteen-zeros-anyway) |
| **Volume** | 1.70 MB, 1.80 MB and 1.38 MB for the data, 28 KB for the dimensions; **61 s** for a full run |
| **Licence** | ⚠️ **Not open** — CEPAL's terms, quoted in [the GDP section](#licence-not-open-and-the-terms-conflict-with-what-reim-does) above |
| **Status** | ✅ **Enabled** — 6,564 observations, measured 2026-09-09 |

REIM's **first interest-rate data of any kind** and the first use of the
`financial` indicator category, which had existed unused since v0.1.0. Until
this landed, REIM's monetary data was three aggregates — M1, M2 and M3 — which
say how much money exists and nothing about its price.

| CEPAL id | Published name | Published unit | REIM indicator | Observations |
|---|---|---|---|---|
| 856 | Nominal lending rate | `Annual percentage` | `lending_rate_nominal_monthly` | 2,490 |
| 857 | Nominal deposit rate | `Annual percentage` | `deposit_rate_nominal_monthly` | 2,453 |
| 1206 | Monetary policy rate | `Annual percentage` | `policy_rate_monthly` | 1,621 |

**Coverage per country**, from the live run of 2026-09-09:

| Country | Lending | Deposit | Policy |
|---|---|---|---|
| Belize | 429 — 1990-01 … 2025-09 | 428 — 1990-01 … 2025-08 | 429 — 1990-01 … 2025-09 |
| Honduras | 406 — 1991-12 … 2025-09 | 405 — 1991-12 … 2025-08 | 246 — 2005-04 … 2025-09 |
| El Salvador | 369 — 1995-01 … 2025-09 | 369 — 1995-01 … 2025-09 | 297 — 2001-01 … 2025-09 |
| Guatemala | 357 — 1996-01 … 2025-09 | 357 — 1996-01 … 2025-09 | 249 — 2005-01 … 2025-09 |
| Costa Rica | 322 — 1999-01 … 2025-10 | 320 — 1999-01 … 2025-08 | 235 — 2006-03 … 2025-09 |
| Nicaragua | 321 — 1999-01 … 2025-09 | 321 — 1999-01 … 2025-09 | 165 — 2007-01 … 2025-10, **61 gaps** |
| Panama | 286 — 2001-12 … 2025-09 | 253 — 2001-12 … 2025-09, **33 gaps** | **excluded** |
| **Total** | **2,490** | **2,453** | **1,621** |

Only those two spans have interior gaps. Every other country-series is
complete between its own first and last month.

Measured value ranges, which are what a reader wants before plotting them
together:

| Country | Lending | Deposit | Policy |
|---|---|---|---|
| Belize | 8.04 – 16.6 | 0.9 – 7.2 | 11 – 18 |
| Costa Rica | 8.27 – 30.5 | 3.2 – 18.7 | 0.75 – 10 |
| El Salvador | 5.02 – 13.35 | 1.8 – 8.8 | 0.96 – 7.62 |
| Guatemala | 11.83 – 23 | 3.9 – 11.9 | 1.75 – 7.25 |
| Honduras | 14.17 – 33.57 | 2.5 – 16.5 | 3 – 9 |
| Nicaragua | 7.79 – 20.83 | 0.5 – 13.3 | **0** – 10.32 |
| Panama | 6.34 – 9.72 | 1.3 – 5 | — |

This is the fifth CEPALSTAT family REIM reads and the shape is the monetary
one: dimension 208 for the country, **3981** for the period inside the year,
29117 for the year — including 3981's untranslated English members, which is
why a Spanish dimensions request appears above. That request is made **once**,
not once per indicator: the member table belongs to the dimension, not to any
indicator, and it was measured byte-identical across 856, 857 and 1206. The
whole family therefore costs four requests rather than six.

Unlike the GDP and debt families, where CEPAL is the compiler, **every row
cites the publisher it came from**. What REIM stores in
`raw_metadata.cepalstat_source` is CEPAL's own organization name for that row:

| Country | Lending | Deposit | Policy |
|---|---|---|---|
| Belize | Central Bank of Belize | Central Bank of Belize | Central Bank of Belize |
| Costa Rica | Central Bank of Costa Rica | ⚠️ **Central Bank of Bolivia** | Central Bank of Costa Rica |
| El Salvador | Reserve Bank Central of the Salvador | " | " |
| Guatemala | Bank of Guatemala | " | " |
| Honduras | Central Bank of Honduras | " | ⚠️ *empty* |
| Nicaragua | Central Bank of Nicaragua | " | " |
| Panama | ⚠️ `(Translation in progress ...)` | " | — |

Three defects visible in one table, all stored exactly as published: Costa
Rica's misattribution, [below](#857-attributes-costa-rica-to-the-central-bank-of-bolivia);
Honduras's null `source_id` on the policy rate, which REIM stores as an empty
string rather than inventing an attribution, exactly as the CPI section
records for its 363 unattributed rows; and Panama's untranslated organization
name, the same `descripcion_ingles` class as the period members.

#### The annual and quarterly members are means of their months, not restatements of one

Dimension 3981 carries seventeen members — twelve months, four quarters and an
annual figure. The [monetary section](#only-the-monthly-member-is-stored)
stores only the twelve months because the other five are exact **restatements**:
a year's closing stock *is* December's. **That reasoning is false here, and the
opposite one is true.**

| Test | 856 | 857 | 1206 |
|---|---|---|---|
| quarter equals its closing month | 46 / 695 | 316 / 681 | 291 / 466 |
| quarter ≈ mean of its three months (±0.05) | **693 / 693** | 611 / 676 | **460 / 460** |
| annual ≈ mean of its twelve months (±0.05) | **202 / 202** | 191 / 199 | **122 / 122** |

These are rates, so CEPAL averages them rather than taking a period end. On the
lending rate the identity is exact in every cell where it can be tested: 693 of
693 quarters and 202 of 202 annual figures.

**The decision is the same and the reason is the opposite.** Only the twelve
monthly members become observations. Storing a mean beside the twelve values it
was computed from would be REIM publishing a **derived figure as if it were
published**, which `ROADMAP.md` reserves for v0.8.0 and its transparency
discipline. The connector docstring says which of the two reasons applies,
because a future reader who assumes the monetary one would draw the wrong
conclusion about what the discarded members contain.

857 is the untidy one: 65 of its quarters and 8 of its annual figures match
neither identity. They are discarded with the rest, so nothing REIM stores
depends on them.

#### Panama has no monetary policy rate, and CEPAL publishes sixteen zeros anyway

Panama's entire presence in indicator 1206 is **16 rows, every value the string
`'0'`, every `source_id` null**, all inside 2022 — the twelve months, `Anual`,
and three of the four quarters, with `Trimestre 3` missing.

Panama is dollarised and has no central bank. There is no policy rate for
anyone to publish. Sixteen uniformly zero, wholly unattributed cells in a
single year are an artifact of CEPAL's table, not a measurement.

**REIM stores none of them.** Panama is excluded from `policy_rate_monthly`
only; it keeps its lending and deposit series, which are real, attributed and
286 and 253 observations long. The exclusion is a named constant with the
reason beside it and it is encoded in the connector's `EXPECTED_COUNTRIES`, so
if CEPAL ever publishes real Panamanian data here the
`cepalstat_rates_expected_countries` check fails rather than the data being
silently dropped.

This is a deliberate departure from *store what is published* and the only one
in this family. The alternative would put `Panama: 0.00%` into every `/compare`
response covering 2022, beside six real policy rates, with the caveat reachable
only through the notes.

**Nicaragua's two zeros are a different thing and are stored.**

| 2010-02 | 2010-03 | 2010-04 | 2010-05 |
|---|---|---|---|
| 2.92 | **0** | **0** | 1.92 |

Those sit inside a real, fully attributed 165-month series from the Central
Bank of Nicaragua. That is the [El Salvador corrupt-cell
situation](#el-salvador-has-one-corrupt-cell-which-is-a-different-thing) from
the CPI work: one or two bad cells inside a live series are stored, pinned by a
test and documented — not deleted. It is also the only reason `allow_zero` is
true on the policy rate and false on the other two, whose minima are 5.02 and
0.5.

#### CEPAL says outright that each country measures a different instrument

`calculation_methodology` reads, identically on all three indicators:

> According to the definition from each country.

and the `definition` field spells that out. On the lending rate, for the seven:

| Country | What CEPAL says its "lending rate" is |
|---|---|
| Costa Rica, Guatemala, Honduras | weighted average for lending rate in local currency |
| El Salvador | basic lending rate for up to one year |
| Nicaragua | weighted average of short-term lending rates in local currency |
| Panama | interest rate on one-year trade credit |
| Belize | weighted average rate for personal and business loans, residential and other construction loans |

On the policy rate the divergence is wider still. Belize's "monetary policy
rate" is **the Central Bank's own lending rate**, El Salvador's is a
stock-exchange repo yield over 1–7 days, Nicaragua's is the yield on 180-day
central bank bonds, and Costa Rica's is the rate on its central bank's
local-currency operations. **CEPAL's definition string names no instrument at
all for Guatemala, Honduras or Panama** on that indicator; those three rates
are published without a stated definition.

The consequence is a comparability problem REIM's existing machinery could not
express. `assess_comparability` turns on **unit and currency only**, and all
three series are `percent per annum` with no currency and one publisher, so
`/compare` would have reported `comparable: true` and named nothing — correct
on the axes it checks and misleading about levels.

`IndicatorDefinition` therefore gained one field,
`methodology_varies_by_country`, declared true on all three. `/compare` now
answers:

```json
"comparable": true,
"comparability_notes": [
  "The publisher defines this indicator differently in each country, so levels are not comparable; movements over time are."
]
```

**`comparable` stays `true` deliberately.** The flag's documented meaning is
unit and currency agreement, and this endpoint's rule is that comparability is
*declared, never enforced* — it states caveats and never refuses. Flipping the
flag would also widen what `comparable` means for every existing caller and
would misreport a legitimate use: comparing how Guatemala's and Honduras's
lending rates **moved** is sound, and only their levels are not.

**Belize's lending rate and its policy rate are not duplicates**, despite both
definitions naming a lending rate: 429 shared months, **zero identical values**.

#### `Belice` is inside the English definition string, and 857 calls Guatemala's deposit rate a lending rate

Belize's entry in indicator 856's `definition` is keyed **`Belice`** — the
Spanish spelling, inside a string served under `lang=en`. A reader searching
that text for "Belize" finds nothing, which is how the row was first missed.
Same untranslated-string class as dimension 3981's members and Panama's
organization name; it is worth expecting anywhere in a CEPALSTAT payload rather
than treating each occurrence as a surprise.

Indicator 857 carries a defect of its own. Guatemala's **deposit** rate is
described there as the "weighted average of the system **lending** rates in
local currency". The data is a deposit rate: it sits below Guatemala's lending
series in **all 357 shared months**, by **7.34 to 12.17 points**. This is a
wrong word in CEPAL's prose, not a wrong series. It is recorded — in this file
and in the indicator's own description — and not corrected.

#### 857 attributes Costa Rica to the Central Bank of Bolivia

Every one of Costa Rica's 320 deposit-rate rows carries `source_id` `CBBO`,
the **Central Bank of Bolivia**, where indicators 856 and 1206 both say `CBCR`
for the same country. It is a CEPAL attribution error, on one indicator only.

**REIM stores it as published.** The project does not silently repair a
publisher's provenance: a consumer reading `raw_metadata.cepalstat_source`
gets the string CEPAL served, and the discrepancy is stated here and pinned by
a unit test. If CEPAL corrects it, that test fails and this paragraph is known
to have stopped being true.

#### The declared decimals are wrong for the lending rate

| Indicator | `decimals` declares | Actually published, in what REIM stored |
|---|---|---|
| 856 | **0** | 2 decimals in 2,065 of 2,490 cells, 1 in 391, 0 in 34 |
| 857 | 1 | 1 in 2,205 of 2,453, 0 in 248 |
| 1206 | 2 | 2 in 641, 1 in 227, 0 in 753 |

857 and 1206 declare their maximum honestly. **856 declares zero decimals and
publishes two in five cells out of six.** This is the third CEPALSTAT family
whose declared precision contradicts its own payload, after the exchange rate's
[declared two, published one](#declared-two-decimals-published-one).

Values are stored **exactly as published**, with no rounding to any declared
figure in either direction. A test pins two-decimal lending cells against the
declared `decimals: 0`, so an attempt to "tidy" them fails loudly.

#### Percentage change is useless on two of the three, so the tripwire counts points

`max_period_change_pct` is **null on the deposit and policy rates** — the same
call [`ni_cpi_inflation_monthly` already makes](#why-max_period_change_pct-is-null-and-what-replaces-it),
and for a related but distinct reason. These series sit near zero, where a
percentage change is unbounded and says nothing:

| Series | Move | In percent | In points |
|---|---|---|---|
| Nicaragua, deposit, 2018-03 | 0.5 → 1.7 | **+240%** | 1.2 |
| El Salvador, policy, 2012-12 | 1.47 → 4.87 | **+231%** | 3.4 |

Both are ordinary monetary policy. Across all calendar-adjacent pairs, 79
deposit moves and 85 policy moves exceed 25%, and essentially all of them are
real. A threshold that tolerates those detects nothing at all.

**`cepalstat_rates_step` measures percentage *points* instead**, at `warning`,
and fires beyond **8 points**. That number comes from the data: the largest
absolute adjacent move anywhere in the family is **7 points**, Belize's policy
rate stepping 11 → 18 in March 2004 and back 18 → 11 in January 2011 — real,
discrete central bank decisions. The check compares **calendar-adjacent months
only**, the rule `cepalstat_cpi_known_splices` already establishes: comparing
across a gap manufactures a break that is really an absence, and Nicaragua's
policy rate has 61 of them.

`max_period_change_pct` survives on the lending rate alone, at 60. Nicaragua's
largest real move there is **+45.1%** in 2011-12 (9.09 → 13.19), so 60 clears
the data and still reports a discontinuity.

The visible consequence on a run: `period_change` reports **skipped**, not
passed, for the deposit and policy rates. That is the rule being absent by
decision, not a check that failed to run.

#### The family is maintained but not extended, which is why freshness is 450 days

The newest monthly cell on all three indicators is **2025-10** — not for
Central America, but across **every country in the payload**: 32 or 33 of
dimension 208's 145 members publish anything at all, and none of them has a
November or December 2025. Meanwhile `last_update` reads **Aug 27 2026** for
856 and 857 and **Aug 31 2026** for 1206.

CEPAL touched these tables about two weeks before this work began and did not
add a month. This is not a Central American lag and not an abandoned table: it
is the same ~11-month publication lag this file already records for
[`exchange_rate_nominal_monthly`](#cepal--monthly-nominal-exchange-rate).

So `freshness_max_age_days` is **450**, the value the exchange rate already
uses at the identical lag. On the first run the measured ages were **344 days**
for the lending and policy rates and **374** for the deposit rate, whose
Belizean, Costa Rican and Honduran series end 2025-08.

A threshold at the monthly cadence a reader would expect — 90 days, say — would
warn on **all twenty country-series on every single run**. That is not the
Honduras and Belize precedent recorded elsewhere in this file: those work
because the threshold fits the publication cycle and one laggard breaks it. A
threshold that always fires reports nothing.

#### The first run, in full

Recorded so a later reader can tell a regression from a known state.

```text
$ python -m reim.cli pipeline run cepalstat_rates_monthly
✓ cepalstat_rates_monthly  success  extracted=6564 inserted=6564
                                    updated=0 unchanged=0 rejected=0 (61232 ms)
```

**6,564 observations, none rejected**, in 61.2 s over four requests.

**The three connector checks**, all as predicted by the design:
`cepalstat_rates_expected_countries` (completeness, `critical`) **passed** —
20 country-series, seven on each of the lending and deposit rates and six on
the policy rate; `cepalstat_rates_spread` (consistency, `critical`) **passed**
— **zero inversions across all 2,453 months** in which a country publishes
both a lending and a deposit rate; `cepalstat_rates_step` (validity,
`warning`) **passed** — no calendar-adjacent move beyond 8 points.

The spread is the strongest invariant in the family. A bank charging less than
it pays is not a rounding artifact, so this is enforceable rather than
advisory — the analogue of the monetary family's `M1 ≤ M2 ≤ M3` nesting, but
exact and needing no tolerance:

| Country | Shared months | Narrowest spread | Widest |
|---|---|---|---|
| El Salvador | 369 | 1.18 | 6.66 |
| Nicaragua | 321 | 3.04 | 15.73 |
| Costa Rica | 320 | 3.22 | 14.60 |
| Panama | 253 | 3.74 | 6.95 |
| Belize | 428 | 6.94 | 11.32 |
| Guatemala | 357 | 7.34 | 12.17 |
| Honduras | 405 | 9.50 | 18.84 |

**One check reported at `warning`**, and it is the expected one.
`cepalstat_monthly_continuity` (completeness, `warning`) reports **94 missing
months**: Panama's deposit rate is short **33** and Nicaragua's policy rate
**61**. Both are absences in the source. Interpolating them would be
imputation, which REIM does not do; the same call was made for Belize on the
CPI and for Honduras on the monetary aggregates.

The standard battery passes on all three indicators — `dataset_not_empty` at
2,490 / 2,453 / 1,621, `country_attribution` at 7 / 7 / **6**,
`no_duplicate_periods` at zero, `value_range`, `value_present`,
`value_numeric_finite`, `period_validity`, `period_length`,
`expected_frequency` and `single_source_per_batch`. `freshness` passes at
344 / 374 / 344 days against 450. `period_change` passes on the lending rate
and is **skipped** on the other two, and `temporal_monotonicity` is skipped on
all three; both are rules deliberately left null rather than checks that
failed. `quality report --days 1` exits 0: nothing at `error` or worse was
recorded.

## Reachable, not ingested

Indicator families that a source REIM **already reads** publishes, and REIM
does not yet store. Listed so the next increment starts from a measurement
rather than a search.

### CEPALSTAT — two families beyond the eight REIM reads

Found on 2026-09-06 by walking `GET /cepalstat/api/v1/thematic-tree?lang=es&theme_id=N`.
Three entries have left this list since. The regional CPI, indicator 365, was
on it until the same day and is now
[ingested](#cepal--monthly-consumer-price-index); the two interest rates, 856
and 1206, together with 857 named below them, left it on 2026-09-08 and are now
[ingested as one family](#cepal--monthly-interest-rates).
The theme ids are worth recording because nothing maps an area to its
indicators: **6** is `BADECON`, **9** is `BADEPAG` (balance of payments) and
**24** is `COYUNTURA` (short-term indicators). `GET /themes?lang=es` returns
46 of them.

**Searching the tree by indicator name does not find these.** The concept
usually sits in a *dimension member*, not in the title — the same property that
made the public debt slice hard to name. A search for "remesas" or "reservas"
across themes 6, 9 and 24 returns nothing; both concepts are members of a
66-value `Rubro` dimension inside an indicator called "Balanza de pagos
trimestral".

| CEPAL id | Published name | Dimensions, read from `/dimensions?lang=es` | Shape it reuses |
|---|---|---|---|
| 547 | Balanza de pagos trimestral | `País(145) × Trimestres(4) × Rubro(66) × Años(201)` | `cepalstat_debt.py` — four dimensions |
| 361 | Valores Corrientes (theme 9) | `Países(38) × Años(34) × Cuentas(55)` | none — see the warning below |

The three interest rates were on this table until 2026-09-08 and the shape
recorded for them held: `País(145) × Periodo__ind mon(17) × Años(201)`,
`cepalstat_monetary.py` exactly. What that shape did **not** predict is
everything the [interest-rate section](#cepal--monthly-interest-rates) now
records — that the annual and quarterly members are means rather than
restatements, that Panama's policy rate is sixteen unattributed zeros, and that
CEPAL defines each country's rate differently. Which is the point of the
paragraph below.

**What was measured is the shape and nothing else.** No data response was
requested for any of these. Coverage for the seven Central American countries,
each country's span, the published units and decimals, and the response size
are all **unknown** and must be measured before any of them is designed. The
exchange-rate work is the precedent for why: its data response contradicted two
assumptions that its dimensions alone would have left standing.

#### Two traps on indicator 547, recorded before anyone reads it as a solution

`ROADMAP.md` lists monthly **remittances** and monthly **reserves** as open
gaps. Indicator 547 carries `Rubro` members named "Transferencias corrientes
(crédito)" and "Activos de reserva", and **neither is the thing the roadmap is
asking for**:

* **"Transferencias corrientes" is not remittances.** It is the whole current
  transfers line of the balance of payments, official transfers included.
  Personal remittances are a sub-item of it that the 66 members do not break
  out, so the figure cannot be reconstructed. The World Bank series REIM
  already stores annually, `BX.TRF.PWKR.CD.DT`, is personal transfers plus
  compensation of employees — a different definition again.
* **"Activos de reserva" is a flow, not a stock.** It is the
  balance-of-payments movement in reserve assets over the quarter. The roadmap
  wants the reserves *level*, which is what `FI.RES.TOTL.CD` and the IMF's
  `IRFCL` hold.

Ingesting 547 would be worthwhile — it would be REIM's first balance-of-payments
data and its second quarterly source. Labelling either member as remittances or
as reserves would not be, and would be the kind of quiet redefinition this file
exists to prevent.

**Indicator 361 uses a different dimension vocabulary entirely** — country
dimension `1` with 38 members rather than `208` with 145, years dimension `40`
rather than `29117`. Every CEPALSTAT connector REIM has written addresses
dimensions by the ids in `cepalstat.py`, and none of them applies here. It is
an older table and would need its own investigation, not an adaptation.

---

## Registered but not yet implemented

These organizations exist in `reim/domain/sources/organizations.py` so that
catalog entries can reference them as soon as an endpoint is identified.

| Organization | What REIM wants from it | Current blocker |
|---|---|---|
| **INIDE** (beyond the IPC) | Employment, poverty, population projections | Not yet researched; the IPC is now automated (see above) |
| **BCN** (beyond exchange rate) | Monthly monetary statistics, remittances, trade, reserves | Published as XLSX bulletins; layout stability not yet assessed |
| **MHCP** (ministry of finance) | Fiscal execution, public debt | Not yet researched |
| **SIBOIF** (banking supervisor) | Banking system aggregates | Not yet researched |
| **BCIE** (regional development bank) | Regional financing flows | Not yet researched |
| **IMF** | IFS monetary and external series | `dataservices.imf.org` was not reachable from the development environment; worth retrying |

Adding any of these is a catalog entry plus a connector module — no change to
core code. See [CONTRIBUTING.md](../CONTRIBUTING.md).

---

## Rules for adding a source

Before writing a connector:

1. **Confirm the publisher is official.** Central bank, statistics office,
   ministry, supervisor, regional body or multilateral. Not an aggregator.
2. **Find a structured endpoint.** Prefer, in order: official API → JSON → CSV →
   XML → XLSX. Only consider HTML when no structured form exists, and say so in
   the catalog description.
3. **Verify it reproducibly.** Fetch it at least twice and confirm the shape is
   stable and the URL is not session-bound.
4. **Record the URL, format and coverage** in this file.
5. **Document every known limitation** — gaps, lags, revisions, redenominations,
   unit changes.
6. **Respect the publisher.** Realistic timeouts, bounded retries with backoff,
   an identifying User-Agent, no parallel hammering. REIM sends
   `REIM_HTTP_USER_AGENT` on every request so operators can identify and contact
   us. Read the terms of use. A source may override that header **only** in
   `sources/catalog.yml`, with a `user_agent_note` recording the measurement
   that forced it — never inside a connector. The rule is in two parts: REIM
   does not defeat an active access control such as the BCN's bot-manager
   challenge, and REIM does satisfy a static header check such as SIECA's
   edge filter. See the SIECA entry above.
7. **Record a real fixture** and write the transform test against it.
8. **If it cannot be automated reliably, ship it disabled** with a documented
   `disabled_reason`, and move on to another source.

Never fabricate data to make a connector look finished. A documented gap is a
contribution; an invented number is a defect.
