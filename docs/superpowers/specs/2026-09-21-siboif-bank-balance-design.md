# SIBOIF banking-system balance sheet — design

REIM's first data from Nicaragua's banking supervisor: three system-wide
balance-sheet totals, monthly, verified to satisfy their own accounting
identity. Closes one line of `docs/sources.md`'s "Registered but not yet
implemented" table — SIBOIF, "Banking system aggregates."

Everything measured below was checked against the live site on 2026-09-21,
each request fetched at least twice and confirmed identical or reproducibly
progressing (the one multi-step mechanism this design deliberately avoids
using — see §2).

## 1. What exists, and what this adds

`reim/domain/sources/organizations.py` already registers `SIBOIF`
(`website_url="https://www.siboif.gob.ni"`, confirmed live and correct — unlike
MHCP's registered `www.mhcp.gob.ni`, which does not resolve, a dead end this
spike ruled out separately). No catalog entry, no indicators, and no connector
exist yet.

This increment adds:

- Three new indicators: total assets, total liabilities, total equity of
  Nicaragua's banking system, monthly.
- One connector reading one static file.
- One new dependency, to read it.

**Not in this increment:** `SISTEMA_FINANCIERO` (the broader, non-bank-inclusive
aggregate the same file also carries), any per-institution figure (14 named
banks are in the same file and are not read), and the income statement — a
confirmed, live, same-shape companion file, excluded on scope grounds only
(see §10).

## 2. The source, and the path not taken

SIBOIF publishes banking statistics two ways. Both were measured; only one is
used.

**The interactive filtered browser** (`/consultas/estadisticas`) holds the
same data through the current month, but export requires driving Drupal's
batch-export protocol: submit a filtered `GET`, follow a `302` to
`/batch?op=start`, poll `/batch?...&op=do_nojs` repeatedly (confirmed: ~25
polls, each advancing a few percent, several seconds of server-side work per
request) until `100%`, follow a second redirect through `op=finished` to a
token-authorized download URL, and only then fetch the file — which turns out
to be an HTML `<table>` mislabelled `Content-Type: application/vnd.ms-excel`,
36 MB for one broad query. Reproduced end-to-end once, successfully, to
confirm the mechanism works. **Rejected** as this connector's source: multi-
step, session-cookied, server-expensive for every run, and the payload needs
HTML-table parsing rather than a real spreadsheet reader.

**The pre-generated report series** (`/consultas/informes`) lists static
files, refreshed in place, no session or batch step:

```text
GET https://www.siboif.gob.ni/sites/default/files/documentos/serie-informes-excel/bancos/ib_balance_general_0.xlsx
→ 200, 1,018,079 bytes, genuine OOXML ("Microsoft Excel 2007+")
```

Fetched twice, byte-identical (`sha256sum` match). This is the connector's
source: one `GET`, no state.

## 3. The file's shape

16 worksheets: 14 named banks (`BANPRO`, `BAC`, `BDF`, …), plus
`SISTEMA_FINANCIERO` and `SISTEMA_BANCARIO`. Per this design's own scoping
question, only `SISTEMA_BANCARIO` is read.

That sheet is a full hierarchical balance sheet — title "Balances de
Situación", subtitle "Al 31 de Agosto del 2026", unit note "(Expresado en
miles de Córdobas)" — 95 rows, column A holding each line item's description,
columns B onward one per month-end date (`31/01/2019`, `28/02/2019`, …,
`31/08/2026`: 92 consecutive months, no gaps found in the range checked).

Three rows are the whole of what this connector reads, verified by their own
arithmetic rather than assumed from their labels:

| Row | Label (column A, verbatim) | 2026-08 value (thousands NIO) |
|---|---|---|
| 11 | `Activo` | 222,581,300.2105 |
| 46 | `Pasivo` | 184,992,392.2015 |
| 71 | `PATRIMONIO` | 37,588,908.0090 |

`184,992,392.2015 + 37,588,908.0090 = 222,581,300.2105` — Assets = Liabilities
+ Equity, exact to four decimal places, for the one month spot-checked. This
is the guard this design's testing section pins across every month the
connector reads, the same accounting-identity discipline SIECA's balance
check and CEPALSTAT's BOP identity checks already use elsewhere in this
codebase.

Two disclosures the file makes about its own history, worth carrying into
`docs/sources.md` rather than silently dropping:

> A partir de enero 2019 Banco Produzcamos Consolida en el Sistema Bancario y
> en el Sistema Financiero Nacional.

> El Banco Corporativo, S.A (BANCORP) solicitó la autorización a la
> Superintendencia de Bancos, para proceder a la disolución voluntaria
> anticipada … a partir de julio del 2019 se suspendió la publicación …

Neither affects the three system-wide rows this connector reads (they are
already-consolidated totals), but both explain why a naive per-bank cross-
check would not reconcile perfectly across 2019, if anyone ever builds one.

## 4. Data model — none

No schema change. Three indicators, one country (Nicaragua, already
seeded), no new dimension — unlike the INEC Panama increment, this fits
REIM's existing `Country` × `Indicator` × `Period` shape exactly, because
"system aggregate" is precisely the shape REIM already knows how to store.

## 5. The new dependency

`xlrd>=2.0` (already a dependency, used by the INIDE connector) cannot read
this file: `xlrd` 2.0 deliberately dropped `.xlsx`/OOXML support and reads
only the legacy binary `.xls` format. This file is genuine OOXML
(`file` reports "Microsoft Excel 2007+"). A new dependency is required —
**`openpyxl`**, the standard maintained reader for `.xlsx`. Add to
`pyproject.toml`'s `dependencies` list, next to `xlrd`'s own entry, with a
comment following that entry's convention (why this connector needs it, since
`xlrd` already exists and doesn't cover this format). Confirm during
implementation whether `openpyxl` ships its own type stubs (recent versions
do) before adding an `xlrd`-style `[[tool.mypy.overrides]]` block — only add
one if `mypy --strict` actually complains without it.

## 6. Transformation

Values arrive as thousands of córdobas. Multiply by 1,000 to store whole
córdobas, and keep the original thousands-value in `raw_metadata` — the same
declared, reversible, audit-preserving transformation SIECA already applies
to its millions-to-whole-USD conversion (`docs/sources.md`'s SIECA section:
"REIM's first declared transformation").

Row selection is by the exact literal text in column A (`"Activo"`,
`"Pasivo"`, `"PATRIMONIO"`) rather than by hardcoded row number — the
row-number table in §3 is what was measured on 2026-09-21, not a guarantee
SIBOIF keeps it stable across a future republication that adds or removes a
line item above these three. Matching on text is what survives that.

Period: each column header (`"31/01/2019"`, day-first) becomes a monthly
`Period` via `parse_period("2019-01", Frequency.MONTHLY)` — REIM's period
model already supports the `"YYYY-MM"` monthly form; the connector's own job
is only the day-first-string-to-`"YYYY-MM"` conversion, not new period logic.

Currency: `NIO`, `currency_convertible=False` for this first cut. REIM has a
Nicaragua NIO/USD rate series (BCN daily) that could in principle support
`/compare?convert_to=USD` for these indicators later, but that is a separate
decision this design does not make — flip the flag in a later increment if
wanted, once the conversion basis (which rate, what period-alignment) is
argued the way the currency-conversion design already argues it for the
indicators that use it today.

## 7. Connector

`reim/ingestion/connectors/nicaragua/siboif_bank_balance.py`, one
`BaseConnector`, `connector_key` matching a new catalog entry.

`extract()`: one request via this codebase's shared `reim/ingestion/http.py`
helpers (`http_client`/`fetch`/`ensure_ok`) — same convention every other
connector in this codebase follows, confirmed against
`sieca_services_trade.py` and (for this same plan's most recent precedent)
`inec_provincial.py`. `ensure_ok(..., expected_content_type=...)` should check
`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` — the
exact header this host sends, confirmed via `curl -I` on 2026-09-21, not
guessed.

`transform()`: open the workbook with `openpyxl` (read-only mode —
`openpyxl.load_workbook(..., read_only=True, data_only=True)` — this file has
no formulas to preserve and read-only mode is materially cheaper for a
95-row-by-~95-column sheet), select the `SISTEMA_BANCARIO` worksheet by name,
locate the three rows by column-A text match, and for each of the 92 (and
growing) month columns emit one `NormalizedObservation` per row, using that
column's header string as the period.

`validate()`: assert the accounting identity — for every period this run
produced all three rows for, `Activo == Pasivo + Patrimonio` (within a small
tolerance for the file's own four-decimal-place figures) — `QualityResult`
via `.passed()`/`.failure()`, following the `sieca_services_trade.py`
`_check_balance_identity` pattern this codebase already has for exactly this
shape of check.

## 8. Testing

Real fixture: the actual `.xlsx`, gzipped to keep the repository small — the
same "record the complete file, compress it" pattern already used for
Banguat's, the IMF's and CEPALSTAT's larger recordings (see
`tests/fixtures/README.md`). Un-trimmed: 1 MB gzips small, and per-bank sheets
being present but unread costs nothing at rest.

Guard tests beyond the ordinary transform tests:

- The accounting identity holds for every period the fixture carries (the
  load-bearing test — the connector's whole justification is that these
  three numbers are genuine, reconciled totals, not an assumption from their
  row labels).
- Exactly the 92 months the fixture actually has become exactly 3×92
  observations, no more, no fewer — a duplicate or a dropped month is a real
  transform defect worth failing loudly on, the same completeness-check
  instinct `inec_provincial.py`'s eleven-rows check and
  `sieca_services_trade.py`'s six-countries check already apply.
- Row selection is genuinely by text, not position: a fixture-mutation test
  that moves the `Activo`/`Pasivo`/`PATRIMONIO` rows to different row numbers
  (inserting a synthetic row above them) still finds the right three values —
  pins that a future SIBOIF republication with an extra line item does not
  silently start reading the wrong row.

## 9. Decisions

| | Decision | Rationale |
|---|---|---|
| **D1** | Read `/consultas/informes`'s static `.xlsx`, not the interactive `/consultas/estadisticas` batch-export | The static file needs one stateless `GET`; the batch path needs a multi-step session protocol, is server-expensive per run, and returns an HTML table mislabelled as Excel rather than a real spreadsheet (§2) |
| **D2** | `SISTEMA_BANCARIO` only, not `SISTEMA_FINANCIERO`, not any of the 14 named banks | Matches the roadmap's own wording ("banking system aggregates") exactly; per-institution or the broader financial-system mix are both separate, larger scope questions this increment doesn't answer |
| **D3** | Three top-level totals (Activo/Pasivo/Patrimonio) only, not the full 95-row hierarchy | Self-contained and independently verifiable (§3's identity check); the other ~92 line items are real but not "aggregates" in the roadmap's sense, and can be added later without restructuring anything this design builds |
| **D4** | New dependency `openpyxl`, not an extension of `xlrd`'s existing use | `xlrd>=2.0` cannot read OOXML `.xlsx` at all — this is not a preference between two working options (§5) |
| **D5** | Row selection by column-A text match, not hardcoded row number | The measured row numbers (11/46/71) are this month's layout, not a contract SIBOIF has made; text matching survives a future republication adding or reordering line items (§6) |
| **D6** | `currency_convertible=False` for this first cut | REIM has the NIO/USD rate this would need, but which rate and what period-alignment is a real decision this design doesn't make — deferred rather than guessed (§6) |

## 10. Out of scope

- **`SISTEMA_FINANCIERO`** and any **per-institution** figures. Same file,
  read differently; a later increment's own scope.
- **The income statement.** `ib_estado_resultados_0.xlsx` sits in the exact
  same listing as the balance sheet — confirmed live, `200`, same
  `Content-Type`. This spec's first draft claimed it hadn't been found; that
  was wrong, caught during this spec's own self-review, not by a later
  reviewer. It's excluded here on scope grounds (D3: this increment is
  balance-sheet totals only), not because it's unreachable — a real,
  same-shape follow-up increment, not a research gap.
- **The other 92 line items** of the balance sheet (cash, loan portfolio,
  deposits, etc.). Real, available in the same file, not "aggregates."
- **Currency conversion** (`/compare?convert_to=USD`). Flag exists
  (`currency_convertible`), decision deferred (D6).
- **Any other SIBOIF-regulated sector** (Seguros, Valores, Almacenes) — same
  site, same file-listing pattern, separate files, not investigated here.
