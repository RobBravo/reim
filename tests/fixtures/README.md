# Test fixtures

## Recorded from live official sources

These are **real** responses. Tests replay them through `respx` so the suite
never calls an official source.

| File | Origin | Recorded |
|------|--------|----------|
| `worldbank_ni_cpi_inflation.json` | `GET https://api.worldbank.org/v2/country/NIC/indicator/FP.CPI.TOTL.ZG?format=json&per_page=500`, trimmed to 2015–2024 with the metadata block adjusted to match | 2026-08-04 |
| `inide_ipc_junio_2026.xls.gz` | `GET https://www.inide.gob.ni/docs/ipc/ipc_2026/ipc_jun26/Cuadros_Estadisticas_IPC_junio_2026.xls`, byte-for-byte, gzipped only to keep the repo small (402 KB → 157 KB). Tests decompress it before parsing. | 2026-08-04 |
| `imf_imts_nic_g001.csv.gz` | `GET https://api.imf.org/external/sdmx/2.1/data/IMF.STA,IMTS/NIC..G001.M?startPeriod=1990-01` with `Accept: application/vnd.sdmx.data+csv;version=2.0.0`, byte-for-byte, gzipped only to keep the repo small (789 KB → 18 KB). Tests decompress it before parsing. The **complete** response, not a sample, so tests assert the real 1,308 observations across 436 months. | 2026-08-08 |
| `imf_imts_gtm_g001.csv.gz` | `GET https://api.imf.org/external/sdmx/2.1/data/IMF.STA,IMTS/GTM..G001.M?startPeriod=1990-01` with `Accept: application/vnd.sdmx.data+csv;version=2.0.0`, byte-for-byte, gzipped (791 KB → 18 KB). Recorded so tests can prove the country comes from the catalog entry rather than a constant. | 2026-08-08 |
| `banguat_tipocambio_rango.xml.gz` | `POST https://www.banguat.gob.gt/variables/ws/TipoCambio.asmx`, `TipoCambioRango(01/01/1990, 09/08/2026)`, byte-for-byte, gzipped only to keep the repo small (1.33 MB → 90 KB). Tests decompress it before parsing. The **complete** published history — 13,365 days — because the tests that matter need rows no excerpt holds: the 84 rows where the buy rate sat above the sell rate, and the five days the source skips. | 2026-08-09 |
| `bcn_tc_mes_2012_01.xml` | `POST https://servicios.bcn.gob.ni/Tc_Servicio/ServicioTC.asmx`, `RecuperaTC_Mes(2012, 1)` — the first month of coverage | 2026-08-08 |
| `bcn_tc_mes_2020_03.xml` | Same endpoint, `RecuperaTC_Mes(2020, 3)` — the crawling peg, rows in the source's own arbitrary order | 2026-08-08 |
| `bcn_tc_mes_2011_12.xml` | Same endpoint, `RecuperaTC_Mes(2011, 12)` — one month before coverage; the service answers with an empty result and no SOAP fault | 2026-08-08 |
| `bcn_tc_mes_2026_12.xml` | Same endpoint, `RecuperaTC_Mes(2026, 12)` — a month that has not happened. The service projects the frozen rate forward to the end of the current calendar year; the connector discards these rows | 2026-08-08 |
| `sieca_filters.json` | `POST https://www.servicios.sieca.int/ReporteGeneralServicios/LoadFilters` with `{}`, byte-for-byte. Holds the country list, the 69 available quarters and the 33-component services taxonomy. | 2026-08-09 |
| `sieca_flow_exports.json` | `POST .../LoadData` with `flujo=E`, `unidadMedida=MD`, `paises=1,2,3,4,5,6`, `paisesDestino=0`, all 69 quarters, `categoria=0`. The **complete** series — six countries × 69 quarters, no holes. | 2026-08-09 |
| `sieca_flow_imports.json` | Same request with `flujo=I`. | 2026-08-09 |
| `sieca_flow_balance.json` | Same request with `flujo=S`. Recorded so the balance identity is checked against the published figure rather than a computed one. | 2026-08-09 |
| `cepalstat_gdp_2203.json.gz` | `GET https://api-cepalstat.cepal.org/cepalstat/api/v1/indicator/2203/data?lang=en`, byte-for-byte, gzipped only to keep the repo small (163 KB → 23 KB). Tests decompress it before parsing. The **complete** response — all 33 countries and the 3 regional aggregates — because that is what proves the connector's filter to the seven Central American countries works at all. | 2026-08-18 |
| `cepalstat_gdp_2204.json.gz` | Same endpoint, indicator `2204` — total GDP at constant 2018 prices (171 KB → 24 KB). Recorded so the implied-population identity is checked against two published series rather than one computed one. | 2026-08-18 |
| `cepalstat_gdp_2205.json.gz` | Same endpoint, indicator `2205` — GDP per inhabitant at current prices (164 KB → 24 KB). | 2026-08-18 |
| `cepalstat_gdp_2206.json.gz` | Same endpoint, indicator `2206` — GDP per inhabitant at constant 2018 prices (173 KB → 25 KB). | 2026-08-18 |

The CEPALSTAT API needs no User-Agent override and no TLS accommodation; these
four were recorded with REIM's own identifier. `body.credits[0].description` is
CEPAL's own fetch date and differs between recordings — nothing asserts it, and
`raw_metadata` stores only the citation elements that follow it.

The SIECA host serves nothing to a client that identifies itself honestly: a
`202` with an empty body for REIM's own User-Agent, a `403` for `curl`. These
four recordings were therefore made with a browser User-Agent, which the
catalog entry declares and `docs/sources.md` explains.

The BCN service requires a TLS 1.0 handshake, so the four recordings above were
made through `reim.ingestion.http.legacy_tls_context()`. The exact script is in
`docs/superpowers/plans/2026-08-08-bcn-exchange-rate.md`, Task 4.

The projection horizon ends with the calendar year: at the time of recording,
`RecuperaTC_Mes(2026, 12)` returned 31 rows while `RecuperaTC_Mes(2027, 1)`
returned none. That is why the future-row fixture is a December of the current
year rather than an arbitrary future month.

## Excerpted from a live source

| File | What was changed |
|------|------------------|
| `inide_ipc_index.html` | Excerpt of `https://www.inide.gob.ni/Home/ipc`. All 74 `<a href>` workbook links are **verbatim** from the live page; only the surrounding site chrome was removed, because the real page is ~220 KB of navigation markup. The link set — which is what the connector parses — is unmodified. |

## Synthetic

| File | Why it is synthetic |
|------|---------------------|
| `worldbank_error.json` | Reproduces the documented World Bank error envelope. |

Synthetic data lives here and nowhere else. It is never seeded, never ingested
and never reaches a production database.
