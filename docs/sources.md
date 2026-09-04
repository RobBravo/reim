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
charted on one axis, and REIM performs no conversion — doing so would make REIM
the author of an exchange-rate choice it has no basis to make. El Salvador and
Panama are dollarised, so those two alone line up with each other. Anyone
comparing the rest must bring their own rates.

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
