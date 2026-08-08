# Source research notes

Every source REIM knows about, what was verified about it, and — where a source
is not automated — exactly what is blocking it.

This file is the honest record behind `sources/catalog.yml`. A source is only
enabled once its endpoint has been reached and its response shape observed. No
connector is ever "confirmed working" against invented data.

Last verified: **2026-08-04**.

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

**What the series looks like.** 5,334 observations from 2012-01-01 to
2026-08-08, one per calendar day with no gaps. It shows the crawling peg
(`2012-01-01 = 22.9797` rising steadily) and its freeze: since January 2024 the
rate has been constant at `36.6243`.

**Also considered and rejected:** scraping `https://www.bcn.gob.ni/tipo-de-cambio`.
The page is Drupal-rendered and returns no server-side table, and no CSV or XLSX
export was found at a stable URL. Scraping a JavaScript-rendered page for a
number that already has a web service would be fragile and disrespectful of the
publisher's infrastructure.

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
| **SIECA** (regional) | Intra-regional trade | Not yet researched; relevant once more countries are added |
| **BCIE** (regional development bank) | Regional financing flows | Not yet researched |
| **CEPAL** | CEPALSTAT regional series | Has an API; useful for cross-country comparison in a later phase |
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
   us. Read the terms of use.
7. **Record a real fixture** and write the transform test against it.
8. **If it cannot be automated reliably, ship it disabled** with a documented
   `disabled_reason`, and move on to another source.

Never fabricate data to make a connector look finished. A documented gap is a
contribution; an invented number is a defect.
