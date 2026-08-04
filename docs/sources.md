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

## Implemented but disabled

### Banco Central de Nicaragua — daily official exchange rate

| | |
|---|---|
| **Organization** | Banco Central de Nicaragua (`BCN`) — central bank |
| **Endpoint** | `https://servicios.bcn.gob.ni/Tc_Servicio/ServicioTC.asmx` |
| **Documentation** | <https://www.bcn.gob.ni/servicio-web-tipo-de-cambio> |
| **Format** | SOAP / XML |
| **Frequency** | Daily |
| **Coverage** | January 2012 onwards (per BCN documentation) |
| **Status** | ⛔ **Disabled — endpoint unreachable, response contract unverified** |

This is the source REIM most wants: the national primary publisher of the
official NIO/USD rate, at daily resolution. The connector is written. It is
disabled anyway.

**The blocker.** The host only negotiates a pre-TLS 1.2 handshake. Modern
OpenSSL 3.x under a standard system crypto policy refuses it:

```console
$ curl -sv "https://servicios.bcn.gob.ni/Tc_Servicio/ServicioTC.asmx?WSDL"
* Trying 165.98.219.12:443...
* TLSv1.3 (OUT), TLS handshake, Client hello (1):
* TLSv1.3 (IN), TLS handshake, Server hello (2):
* TLSv1.3 (OUT), TLS alert, protocol version (582):
* TLS connect error: error:0A000102:SSL routines::unsupported protocol
```

The main site `https://www.bcn.gob.ni` responds normally (HTTP 200); only the
`servicios.` subdomain carrying the web service is affected.

**Why that means disabled rather than "probably fine".** No live response was
ever observed. The connector's request is built from the published service
description, and its parsing is written defensively — it takes the first element
whose tag ends in `Result` rather than hard-coding a path — but *defensive
parsing of an unobserved format is still a guess*. Shipping it enabled would
mean claiming a connector works when nobody has seen it work. So:

- `sources/catalog.yml` carries `enabled: false` with `disabled_reason`.
- The connector version is `0.1.0-unverified`.
- Every observation it would produce is tagged `contract_status: "unverified"`.
- Its test fixture is **clearly labelled synthetic** in `tests/fixtures/README.md`.

**To verify and enable it**, from a host that can complete the handshake (an
older OpenSSL, `SECLEVEL=0`, or a relaxed system crypto policy):

1. Fetch the WSDL and confirm the operation name and parameter
   (`RecuperaTC_Dia` / `strfecha` per the published documentation).
2. Call it for a known date and record the real envelope.
3. Save that recording as `tests/fixtures/bcn_exchange_rate_soap.xml`, replacing
   the synthetic one, and update `tests/fixtures/README.md`.
4. Adjust `transform()` if the real shape differs.
5. Bump `version` to `1.0.0` and set `enabled: true` in the catalog.
6. Run `python scripts/smoke_test_sources.py --source bcn_exchange_rate`.

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
| **INIDE** (statistics office) | Monthly IPC, employment, population | No stable machine-readable endpoint identified; releases are PDF/XLSX at changing URLs |
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
