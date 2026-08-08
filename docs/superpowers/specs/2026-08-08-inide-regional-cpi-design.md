# INIDE regional CPI — design

Status: **approved, not yet implemented**
Date: 2026-08-08
Roadmap item: v0.2.0, "INIDE regional CPI"

---

## 1. What this adds

INIDE publishes the consumer price index for **Managua** and the **rest of the
country** alongside the national aggregate. REIM ingests only the national
series today. This adds the two regional breakdowns.

The roadmap describes them as sitting "in the same workbook alongside the
national series already ingested". They sit closer than that: in the **same
worksheet**, in the **same rows**, in columns the connector already walks past.

Sheet `2-1-06` is titled *"Índice de precios al consumidor nacional, Managua y
resto del país"* and holds three symmetric four-column blocks:

| Block | Index | Mensual | Acumulada | Interanual |
|---|---|---|---|---|
| nacional | 2 | 3 | 4 | 5 |
| Managua | 6 | 7 | 8 | 9 |
| resto del país | 10 | 11 | 12 | 13 |

Verified against the recorded workbook (`tests/fixtures/inide_ipc_junio_2026.xls.gz`),
the three blocks have **identical coverage**: 224 index rows, 186
month-on-month rows and 224 year-on-year rows each. Regional data starts and
stops exactly where national does, including the 2008-2010 gap.

So this increment needs **no new download, no new sheet parser, and no new
network call**. It maps six more columns of a workbook already in hand.

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| R1 | Region is expressed as **new indicator codes**, not a new dimension on `observations`. | The table's natural key is `(indicator, country, source, period)`. Adding a region column means a migration touching every observation, the repositories and the API, for one source that needs it today. Same pattern already distinguishes `ni_exchange_rate_official_daily` from `ni_exchange_rate_official_annual_avg`. |
| R2 | **Extend `inide_cpi_monthly`** rather than add a connector. | The data is in the same sheet of the same workbook. A second connector would download the same ~400 KB twice and hit INIDE twice for bytes already retrieved. |
| R3 | The three existing national indicator codes are **not renamed**. | Renaming would orphan the 582 stored national observations and break series continuity for no gain. The national block simply carries an empty indicator suffix. |
| R4 | The **"Acumulada" (year-to-date) column stays unread**, for all three regions. | The national connector already skips it deliberately. Ingesting it only for regions would be an asymmetry with no reason behind it. |
| R5 | A mismatch in **any** of the nine asserted headers aborts the whole run, national included. | Consistent with the existing rule that a rebased or reordered sheet must fail loudly. Headers are asserted by position, so a restructured sheet casts doubt on the national columns too. |
| R6 | Regional indicators get the **same quality thresholds** as their national counterparts. | A Managua CPI has the same plausible range as the national one. v0.1.0 already showed what inventing tighter bounds costs: a `min_value: 1` on the exchange rate rejected 31 legitimate observations. Thresholds are tripwires for a broken feed, not economic priors. |
| R7 | Connector version goes to **`1.1.0`**. | `BaseConnector` requires a bump whenever `transform` changes its output for the same input. It does: more observations from the same workbook. |

## 3. Components

### 3.1 `reim/ingestion/connectors/nicaragua/inide_cpi_monthly.py`

Today the sheet's structure is flattened into a hand-written column map:

```python
COLUMN_INDICATORS: dict[int, tuple[str, str]] = {
    2: ("ni_cpi_index_monthly", "index (2006=100)"),
    3: ("ni_cpi_inflation_monthly", "percent"),
    5: ("ni_cpi_inflation_yoy", "percent"),
}
```

Writing that out nine times would work and would obscure why the columns fall
where they do. The blocks are described instead, and both the column map and
the header assertions are derived from them:

```python
class RegionBlock(NamedTuple):
    """One of the sheet's three four-column regional blocks."""

    key: str               # "national" | "managua" | "rest_of_country"
    header: str            # index-column header asserted in row 3, lowercased
    index_column: int      # 2, 6, 10
    indicator_suffix: str  # "", "_managua", "_rest_of_country"


REGION_BLOCKS: tuple[RegionBlock, ...] = (
    RegionBlock("national", "nacional", 2, ""),
    RegionBlock("managua", "managua", 6, "_managua"),
    RegionBlock("rest_of_country", "resto del país", 10, "_rest_of_country"),
)

#: Offsets within a block, and the base indicator each one feeds. The
#: "Acumulada" column at offset 2 is deliberately not ingested.
BLOCK_COLUMNS: tuple[tuple[int, str, str], ...] = (
    (0, "ni_cpi_index_monthly", "index (2006=100)"),
    (1, "ni_cpi_inflation_monthly", "percent"),
    (3, "ni_cpi_inflation_yoy", "percent"),
)

#: Headers of the variation columns, identical in all three blocks. The index
#: column at offset 0 is not here: its header names the region and comes from
#: :attr:`RegionBlock.header`.
VARIATION_HEADERS: dict[int, str] = {1: "mensual", 3: "interanual"}
```

From these, two module-level maps are built once:

* `COLUMN_INDICATORS: dict[int, tuple[str, str]]` — nine entries, column index
  to `(indicator_code, unit)`, where the code is the base name plus the block's
  suffix. The national block's empty suffix reproduces today's three codes
  exactly.
* `COLUMN_REGIONS: dict[int, str]` — column index to region key, used for
  provenance.
* `EXPECTED_HEADERS: dict[int, str]` — nine entries: `block.index_column` maps
  to `block.header`, and `block.index_column + offset` maps to
  `VARIATION_HEADERS[offset]` for each offset in `VARIATION_HEADERS`.

`transform` is otherwise unchanged: it already iterates `COLUMN_INDICATORS`. It
gains one line of provenance, `"inide_region": COLUMN_REGIONS[column]`, in
`raw_metadata`. `source_record_id` is already `f"{SHEET_NAME}:{label}:c{column}"`
— column-scoped, so the six new series need no change to stay unique.

`_assert_layout` keeps its shape and simply iterates the nine-entry
`EXPECTED_HEADERS`. Note that `"resto del país"` carries an accent; the
comparison lowercases and collapses whitespace, and must not strip accents.

`_check_index_series_complete` currently hard-codes `ni_cpi_index_monthly`. It
becomes one check **per region**, named `inide_index_continuity_<region_key>`,
returning three results. `CONTIGUOUS_FROM_YEAR = 2011` is unchanged and correct
for all three, since their coverage is identical.

`_check_all_indicators_present` already derives its expectation from
`COLUMN_INDICATORS` and needs no change; it will cover all nine automatically.

### 3.2 `reim/domain/indicators/registry.py`

Six new `IndicatorDefinition` entries, mirroring the national three in category
(`PRICES`), frequency (`MONTHLY`), unit and value type. Descriptions state the
geographic coverage and that the figure is published by INIDE, not derived by
REIM.

The existing `ni_cpi_index_monthly` description says INIDE "also publishes
Managua and rest-of-country breakdowns" — it is updated to point at the codes
that now carry them.

### 3.3 `sources/quality_rules.yml`

Six new rule sets. Each regional entry duplicates its national counterpart's
thresholds verbatim: `ni_cpi_index_monthly` bounds for the two regional index
series, `ni_cpi_inflation_monthly` bounds for the two regional month-on-month
series, `ni_cpi_inflation_yoy` bounds for the two regional year-on-year series.

### 3.4 `sources/catalog.yml`

The `inide_cpi_monthly` entry's `indicators` list grows from three to nine. It
remains **one source, one pipeline, one download**.

## 4. Testing

All tests replay the recorded workbook; none touches the network.

New unit tests in `tests/unit/test_inide_connector.py`:

* all nine indicators receive observations
* Managua and rest-of-country index series each have the same observation count
  as the national one
* **the three regions are not identical to each other** — a region whose values
  equal the national aggregate exactly would mean the block offsets are wrong
  and every series is reading the same columns
* regional observations carry `raw_metadata["inide_region"]`
* regional values are exact `Decimal`s quantised to six places, like national
* `source_record_id` is unique across all nine series for a given month
* continuity returns one result per region, named per region
* mutating a **regional** header in a copy of the workbook aborts the run
  (decision R5), and the error message names the offending column

The existing national assertions stay as they are: they are the regression test
that this refactor did not change national output.

## 5. Documentation

* `docs/sources.md` — the INIDE section gains the block table, the coverage
  symmetry finding, and the note that the by-division and core-inflation sheets
  remain unread.
* `docs/implementation-plan.md` — a post-MVP increment section with the
  verification record.
* `ROADMAP.md` — mark the regional CPI item done under v0.2.0.
* `README.md` — update the test count and any indicator or observation counts.

## 6. Expected result

582 observations become **1,746** (three regions × 198 index + 186 m/m + 198
y/y), from the same single download.

## 7. Risks

| Risk | Mitigation |
|---|---|
| The refactor silently changes national output. | The existing national tests are unchanged and must keep passing; a full re-run must report the 582 national observations as `unchanged`, not `updated`. |
| Block offsets are wrong and all three regions read the same columns. | The "regions differ from each other" test exists precisely for this, and it is the one failure mode that would otherwise look like success. |
| INIDE restructures the sheet. | Nine positional header assertions abort before any value is read. |

## 8. Out of scope

The workbook's other four sheets, each of which deserves its own increment:

* `2-2-06` — national CPI by division
* `2-3-06` — Managua CPI by division
* `2-4-06` — rest-of-country CPI by division
* `2-5-06` — national **core** inflation (*subyacente*)
