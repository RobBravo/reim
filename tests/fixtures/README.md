# Test fixtures

## Recorded from live official sources

These are **real** responses. Tests replay them through `respx` so the suite
never calls an official source.

| File | Origin | Recorded |
|------|--------|----------|
| `worldbank_ni_cpi_inflation.json` | `GET https://api.worldbank.org/v2/country/NIC/indicator/FP.CPI.TOTL.ZG?format=json&per_page=500`, trimmed to 2015–2024 with the metadata block adjusted to match | 2026-08-04 |
| `inide_ipc_junio_2026.xls.gz` | `GET https://www.inide.gob.ni/docs/ipc/ipc_2026/ipc_jun26/Cuadros_Estadisticas_IPC_junio_2026.xls`, byte-for-byte, gzipped only to keep the repo small (402 KB → 157 KB). Tests decompress it before parsing. | 2026-08-04 |

## Excerpted from a live source

| File | What was changed |
|------|------------------|
| `inide_ipc_index.html` | Excerpt of `https://www.inide.gob.ni/Home/ipc`. All 74 `<a href>` workbook links are **verbatim** from the live page; only the surrounding site chrome was removed, because the real page is ~220 KB of navigation markup. The link set — which is what the connector parses — is unmodified. |

## Synthetic

| File | Why it is synthetic |
|------|---------------------|
| `bcn_exchange_rate_soap.xml` | The BCN SOAP endpoint could not be reached during development (legacy TLS), so no real response was ever observed. This envelope follows the published service description; it is a **plausible shape, not a recording**, and exists only to exercise the parser. It must be replaced with a genuine recording before `bcn_exchange_rate` is enabled. See `docs/sources.md`. |
| `worldbank_error.json` | Reproduces the documented World Bank error envelope. |

Synthetic data lives here and nowhere else. It is never seeded, never ingested
and never reaches a production database.
