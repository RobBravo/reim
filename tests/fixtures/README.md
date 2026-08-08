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
| `bcn_tc_mes_2012_01.xml` | `POST https://servicios.bcn.gob.ni/Tc_Servicio/ServicioTC.asmx`, `RecuperaTC_Mes(2012, 1)` — the first month of coverage | 2026-08-08 |
| `bcn_tc_mes_2020_03.xml` | Same endpoint, `RecuperaTC_Mes(2020, 3)` — the crawling peg, rows in the source's own arbitrary order | 2026-08-08 |
| `bcn_tc_mes_2011_12.xml` | Same endpoint, `RecuperaTC_Mes(2011, 12)` — one month before coverage; the service answers with an empty result and no SOAP fault | 2026-08-08 |
| `bcn_tc_mes_2026_12.xml` | Same endpoint, `RecuperaTC_Mes(2026, 12)` — a month that has not happened. The service projects the frozen rate forward to the end of the current calendar year; the connector discards these rows | 2026-08-08 |

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
