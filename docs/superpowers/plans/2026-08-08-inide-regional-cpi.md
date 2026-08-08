# INIDE Regional CPI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest INIDE's Managua and rest-of-country CPI breakdowns, which sit in columns of a worksheet the connector already parses.

**Architecture:** Sheet `2-1-06` is three symmetric four-column blocks. The connector's hand-written column map is replaced by a description of those blocks, from which the column-to-indicator map and the header assertions are derived. Turning the regional series on then means adding two entries to one tuple.

**Tech Stack:** Python 3.12, xlrd (legacy BIFF `.xls`), Pydantic 2, pytest.

## Global Constraints

- Region is modelled as **new indicator codes**, never a new column on `observations`.
- The three existing national codes — `ni_cpi_index_monthly`, `ni_cpi_inflation_monthly`, `ni_cpi_inflation_yoy` — are **not renamed**. The national block carries an empty indicator suffix.
- The **"Acumulada"** column (offset 2 in every block) is **asserted but never ingested**, for all three regions.
- Regional indicators reuse their national counterpart's quality thresholds **verbatim**.
- A mismatch in **any** asserted header aborts the whole run, national included.
- `VALUE_DECIMALS = 6`; values are `Decimal`, quantised to six places. Never `float`.
- Connector `version` goes from `1.0.0` to `1.1.0`.
- Every task ends with `ruff check`, `ruff format --check` and `mypy --strict reim apps` passing.

---

### Task 1: Register the six regional indicators

**Files:**
- Modify: `reim/domain/indicators/registry.py`
- Modify: `sources/quality_rules.yml`
- Modify: `sources/catalog.yml` (the `inide_cpi_monthly` entry's `indicators` list)
- Test: `tests/unit/test_catalog.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: indicator codes `ni_cpi_index_monthly_managua`, `ni_cpi_inflation_monthly_managua`, `ni_cpi_inflation_yoy_managua`, `ni_cpi_index_monthly_rest_of_country`, `ni_cpi_inflation_monthly_rest_of_country`, `ni_cpi_inflation_yoy_rest_of_country`. Tasks 2-4 emit exactly these strings.

This task registers the codes only. The connector still emits three series after it, which is fine: `_check_all_indicators_present` derives its expectation from the connector's own column map, not from the catalog.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_catalog.py`:

```python
def test_inide_source_declares_all_nine_cpi_indicators(catalog: SourceCatalog) -> None:
    """One source, one download, nine series: national plus two regions."""
    entry = catalog.get("inide_cpi_monthly")

    assert set(entry.indicators) == {
        "ni_cpi_index_monthly",
        "ni_cpi_inflation_monthly",
        "ni_cpi_inflation_yoy",
        "ni_cpi_index_monthly_managua",
        "ni_cpi_inflation_monthly_managua",
        "ni_cpi_inflation_yoy_managua",
        "ni_cpi_index_monthly_rest_of_country",
        "ni_cpi_inflation_monthly_rest_of_country",
        "ni_cpi_inflation_yoy_rest_of_country",
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog.py -k nine_cpi -v`
Expected: FAIL — the catalog lists three indicators, and `SourceEntry` would reject the six unknown codes anyway.

- [ ] **Step 3: Add the six indicator definitions**

In `reim/domain/indicators/registry.py`, immediately after the `ni_cpi_inflation_yoy` entry:

```text
    IndicatorDefinition(
        code="ni_cpi_index_monthly_managua",
        name="Nicaragua — consumer price index, Managua (monthly, 2006=100)",
        description=(
            "Consumer price index for Managua published monthly by INIDE, base "
            "year 2006 = 100. Published by INIDE in the same table as the "
            "national aggregate; not derived by REIM."
        ),
        category=IndicatorCategory.PRICES,
        frequency=Frequency.MONTHLY,
        unit="index (2006=100)",
        value_type=ValueType.INDEX,
        methodology_url="https://www.inide.gob.ni/Home/ipc",
    ),
    IndicatorDefinition(
        code="ni_cpi_inflation_monthly_managua",
        name="Nicaragua — consumer price inflation, Managua (month-on-month)",
        description=(
            "Percentage change of the Managua consumer price index versus the "
            "previous month, as published by INIDE."
        ),
        category=IndicatorCategory.PRICES,
        frequency=Frequency.MONTHLY,
        unit="percent",
        value_type=ValueType.PERCENT_CHANGE,
        methodology_url="https://www.inide.gob.ni/Home/ipc",
    ),
    IndicatorDefinition(
        code="ni_cpi_inflation_yoy_managua",
        name="Nicaragua — consumer price inflation, Managua (year-on-year)",
        description=(
            "Percentage change of the Managua consumer price index versus the "
            "same month of the previous year, as published by INIDE."
        ),
        category=IndicatorCategory.PRICES,
        frequency=Frequency.MONTHLY,
        unit="percent",
        value_type=ValueType.PERCENT_CHANGE,
        methodology_url="https://www.inide.gob.ni/Home/ipc",
    ),
    IndicatorDefinition(
        code="ni_cpi_index_monthly_rest_of_country",
        name="Nicaragua — consumer price index, rest of the country (monthly, 2006=100)",
        description=(
            "Consumer price index for Nicaragua excluding Managua ('resto del "
            "país'), published monthly by INIDE, base year 2006 = 100. "
            "Published by INIDE in the same table as the national aggregate; "
            "not derived by REIM."
        ),
        category=IndicatorCategory.PRICES,
        frequency=Frequency.MONTHLY,
        unit="index (2006=100)",
        value_type=ValueType.INDEX,
        methodology_url="https://www.inide.gob.ni/Home/ipc",
    ),
    IndicatorDefinition(
        code="ni_cpi_inflation_monthly_rest_of_country",
        name="Nicaragua — consumer price inflation, rest of the country (month-on-month)",
        description=(
            "Percentage change of the rest-of-country consumer price index "
            "versus the previous month, as published by INIDE."
        ),
        category=IndicatorCategory.PRICES,
        frequency=Frequency.MONTHLY,
        unit="percent",
        value_type=ValueType.PERCENT_CHANGE,
        methodology_url="https://www.inide.gob.ni/Home/ipc",
    ),
    IndicatorDefinition(
        code="ni_cpi_inflation_yoy_rest_of_country",
        name="Nicaragua — consumer price inflation, rest of the country (year-on-year)",
        description=(
            "Percentage change of the rest-of-country consumer price index "
            "versus the same month of the previous year, as published by INIDE."
        ),
        category=IndicatorCategory.PRICES,
        frequency=Frequency.MONTHLY,
        unit="percent",
        value_type=ValueType.PERCENT_CHANGE,
        methodology_url="https://www.inide.gob.ni/Home/ipc",
    ),
```

Then update the existing `ni_cpi_index_monthly` description, which currently ends "INIDE also publishes Managua and rest-of-country breakdowns." Replace that sentence with:

```
            "This is the national aggregate; the Managua and rest-of-country "
            "breakdowns are ni_cpi_index_monthly_managua and "
            "ni_cpi_index_monthly_rest_of_country."
```

- [ ] **Step 4: Add the six quality rule sets**

In `sources/quality_rules.yml`, after the `ni_cpi_inflation_yoy` block. Each duplicates its national counterpart's thresholds exactly — a regional CPI has the same plausible range as the national one:

```yaml
  # Regional CPI. Thresholds are deliberately identical to the national
  # series above: a Managua index has the same plausible range as the
  # national one, and inventing tighter bounds "because it is a region"
  # is exactly how v0.1.0 rejected 31 legitimate exchange-rate figures.
  ni_cpi_index_monthly_managua:
    min_value: 0
    allow_negative: false
    allow_zero: false
    max_period_change_pct: 15
    freshness_max_age_days: 90
    min_observations: 100

  ni_cpi_inflation_monthly_managua:
    min_value: -20
    max_value: 50
    allow_negative: true
    allow_zero: true
    freshness_max_age_days: 90
    min_observations: 100

  ni_cpi_inflation_yoy_managua:
    min_value: -30
    max_value: 500
    allow_negative: true
    allow_zero: true
    freshness_max_age_days: 90
    min_observations: 100

  ni_cpi_index_monthly_rest_of_country:
    min_value: 0
    allow_negative: false
    allow_zero: false
    max_period_change_pct: 15
    freshness_max_age_days: 90
    min_observations: 100

  ni_cpi_inflation_monthly_rest_of_country:
    min_value: -20
    max_value: 50
    allow_negative: true
    allow_zero: true
    freshness_max_age_days: 90
    min_observations: 100

  ni_cpi_inflation_yoy_rest_of_country:
    min_value: -30
    max_value: 500
    allow_negative: true
    allow_zero: true
    freshness_max_age_days: 90
    min_observations: 100
```

- [ ] **Step 5: Extend the catalog entry**

In `sources/catalog.yml`, the `inide_cpi_monthly` entry's `indicators` list becomes:

```yaml
    indicators:
      - ni_cpi_index_monthly
      - ni_cpi_inflation_monthly
      - ni_cpi_inflation_yoy
      - ni_cpi_index_monthly_managua
      - ni_cpi_inflation_monthly_managua
      - ni_cpi_inflation_yoy_managua
      - ni_cpi_index_monthly_rest_of_country
      - ni_cpi_inflation_monthly_rest_of_country
      - ni_cpi_inflation_yoy_rest_of_country
```

Also update the entry's `description`, which says "National consumer price index (base 2006=100) with month-on-month and year-on-year variation". Replace "National consumer price index" with "National, Managua and rest-of-country consumer price indices".

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit -q`
Expected: PASS. The connector still emits three series; nothing else changes yet.

Run: `.venv/bin/reim catalog validate`
Expected: 8 sources, 8 enabled, and the rule-set count rises from 10 to 16.

- [ ] **Step 7: Lint, type-check and commit**

```bash
.venv/bin/ruff check reim tests && .venv/bin/ruff format --check reim tests
.venv/bin/mypy --strict reim apps
git add reim/domain/indicators/registry.py sources/quality_rules.yml sources/catalog.yml tests/unit/test_catalog.py
git commit -m "feat(indicators): register the six INIDE regional CPI series

Managua and rest-of-country index, month-on-month and year-on-year.
Thresholds are copied verbatim from the national series: a regional CPI
has the same plausible range, and tighter bounds invented per region are
how legitimate figures get rejected.

The connector still emits three series; the next commits wire these up."
```

---

### Task 2: Express the sheet as region blocks

**Files:**
- Modify: `reim/ingestion/connectors/nicaragua/inide_cpi_monthly.py:96-140` and `:337-345`
- Test: `tests/unit/test_inide_connector.py`

**Interfaces:**
- Consumes: the indicator codes from Task 1 (not yet emitted).
- Produces: `RegionBlock` NamedTuple with fields `key: str`, `header: str`, `index_column: int`, `indicator_suffix: str`; module constants `REGION_BLOCKS: tuple[RegionBlock, ...]`, `BLOCK_COLUMNS: tuple[tuple[int, str, str], ...]`, `BLOCK_HEADERS: dict[int, str]`; derived maps `COLUMN_INDICATORS: dict[int, tuple[str, str]]`, `COLUMN_REGIONS: dict[int, str]`, `EXPECTED_HEADERS: dict[int, str]`.

**This task must not change what the connector produces.** `REGION_BLOCKS` holds the national block only; Task 3 adds the other two. The existing test asserting 582 observations is the proof, and it stays untouched.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_inide_connector.py`:

```python
def test_column_maps_are_derived_from_the_national_block() -> None:
    """The derived maps must reproduce the hand-written ones exactly."""
    assert COLUMN_INDICATORS == {
        2: ("ni_cpi_index_monthly", "index (2006=100)"),
        3: ("ni_cpi_inflation_monthly", "percent"),
        5: ("ni_cpi_inflation_yoy", "percent"),
    }
    assert EXPECTED_HEADERS == {
        2: "nacional",
        3: "mensual",
        4: "acumulada",
        5: "interanual",
    }


def test_the_year_to_date_column_is_asserted_but_not_ingested() -> None:
    """Column 4 guards the layout; its values are deliberately not read."""
    assert 4 in EXPECTED_HEADERS
    assert 4 not in COLUMN_INDICATORS


def test_every_ingested_column_knows_its_region() -> None:
    assert set(COLUMN_REGIONS) >= set(COLUMN_INDICATORS)
    assert COLUMN_REGIONS[2] == "national"
```

Extend the import at the top of the file:

```python
from reim.ingestion.connectors.nicaragua.inide_cpi_monthly import (
    COLUMN_INDICATORS,
    COLUMN_REGIONS,
    EXPECTED_HEADERS,
    SHEET_NAME,
    InideCpiMonthly,
    Release,
)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_inide_connector.py -k "column_maps or year_to_date or knows_its_region" -v`
Expected: FAIL — `ImportError: cannot import name 'COLUMN_REGIONS'`.

- [ ] **Step 3: Replace the hand-written maps with derived ones**

In `reim/ingestion/connectors/nicaragua/inide_cpi_monthly.py`, delete the existing `EXPECTED_HEADERS` block and the existing `COLUMN_INDICATORS` block, and put this in place of `EXPECTED_HEADERS` (keeping `EXPECTED_BASE_NOTE` and `VALUE_DECIMALS` where they are):

```python
class RegionBlock(NamedTuple):
    """One of sheet 2-1-06's four-column regional blocks.

    The sheet repeats the same four columns — index, month-on-month,
    year-to-date, year-on-year — once per geographic breakdown, at a fixed
    offset. Describing the blocks rather than flattening them into a column
    map keeps the reason the columns fall where they do visible, and makes
    adding a breakdown a one-line change.
    """

    #: Region slug, recorded on every observation for provenance.
    key: str
    #: Header asserted in row 3 above the index column, lowercased.
    header: str
    #: Column of this block's index series.
    index_column: int
    #: Appended to the base indicator codes. Empty for the national block, so
    #: the national series keeps the codes it has always had.
    indicator_suffix: str


REGION_BLOCKS: tuple[RegionBlock, ...] = (RegionBlock("national", "nacional", 2, ""),)

#: Offsets within a block that REIM ingests, and the base indicator each
#: feeds. Offset 2 ("Acumulada", year-to-date) is deliberately absent: it is a
#: within-year cumulative that restates every month, and REIM does not publish
#: it for any region.
BLOCK_COLUMNS: tuple[tuple[int, str, str], ...] = (
    (0, "ni_cpi_index_monthly", "index (2006=100)"),
    (1, "ni_cpi_inflation_monthly", "percent"),
    (3, "ni_cpi_inflation_yoy", "percent"),
)

#: Headers of a block's non-index columns, identical in every block. Offset 2
#: appears here although it is never ingested: asserting it still guards
#: against an inserted or reordered column.
BLOCK_HEADERS: dict[int, str] = {1: "mensual", 2: "acumulada", 3: "interanual"}


def _derive_column_maps() -> tuple[dict[int, tuple[str, str]], dict[int, str], dict[int, str]]:
    """Expand :data:`REGION_BLOCKS` into the flat maps the parser walks."""
    indicators: dict[int, tuple[str, str]] = {}
    regions: dict[int, str] = {}
    headers: dict[int, str] = {}

    for block in REGION_BLOCKS:
        headers[block.index_column] = block.header
        for offset, header in BLOCK_HEADERS.items():
            headers[block.index_column + offset] = header
        for offset, base_code, unit in BLOCK_COLUMNS:
            column = block.index_column + offset
            indicators[column] = (f"{base_code}{block.indicator_suffix}", unit)
            regions[column] = block.key

    return indicators, regions, headers


#: Columns mapped to the REIM indicator they feed.
COLUMN_INDICATORS, COLUMN_REGIONS, EXPECTED_HEADERS = _derive_column_maps()
```

Add `NamedTuple` to the `typing` import if it is not already there — the module already defines `class Release(NamedTuple)`, so it is.

- [ ] **Step 4: Record the region on every observation**

In `transform`, in the `raw_metadata` dict, replace the hard-coded line:

```text
                            "inide_series": "nacional",
```

with:

```text
                            "inide_region": COLUMN_REGIONS[column],
```

Note for the implementer: `raw_metadata` is **not** part of `compute_content_hash`, so this does not mark any stored observation as revised. The 582 rows already in a database keep their old `inide_series` key until their value changes; re-running from an empty database gives every row the new key.

- [ ] **Step 5: Run the full connector suite to verify nothing changed**

Run: `.venv/bin/python -m pytest tests/unit/test_inide_connector.py -v`
Expected: PASS, including the untouched `test_transform_parses_the_real_workbook`, which still asserts exactly 582 observations across the three national indicators. That test passing unchanged is the point of this task.

- [ ] **Step 6: Lint, type-check and commit**

```bash
.venv/bin/ruff check reim tests && .venv/bin/ruff format --check reim tests
.venv/bin/mypy --strict reim apps
git add reim/ingestion/connectors/nicaragua/inide_cpi_monthly.py tests/unit/test_inide_connector.py
git commit -m "refactor(inide): describe the sheet's blocks instead of its columns

Sheet 2-1-06 repeats the same four columns once per geographic
breakdown. The column map is now derived from a description of those
blocks rather than written out by hand, which is what makes the regional
series a one-line addition.

No behaviour change: still the national block, still 582 observations."
```

---

### Task 3: Turn on Managua and rest-of-country

**Files:**
- Modify: `reim/ingestion/connectors/nicaragua/inide_cpi_monthly.py` (`REGION_BLOCKS`, `version`)
- Test: `tests/unit/test_inide_connector.py`

**Interfaces:**
- Consumes: `RegionBlock`, `REGION_BLOCKS`, `COLUMN_INDICATORS`, `COLUMN_REGIONS` from Task 2; the indicator codes from Task 1.
- Produces: nine series, 1,746 observations from the recorded workbook.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_inide_connector.py`:

```python
def test_all_three_regions_are_parsed(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    observations = connector.transform(_raw(inide_workbook_bytes))

    by_indicator: dict[str, int] = {}
    for obs in observations:
        by_indicator[obs.indicator_code] = by_indicator.get(obs.indicator_code, 0) + 1

    # The three blocks have identical coverage in the source, so each region
    # yields the same counts as the national one.
    assert by_indicator == {
        "ni_cpi_index_monthly": 198,
        "ni_cpi_inflation_yoy": 198,
        "ni_cpi_inflation_monthly": 186,
        "ni_cpi_index_monthly_managua": 198,
        "ni_cpi_inflation_yoy_managua": 198,
        "ni_cpi_inflation_monthly_managua": 186,
        "ni_cpi_index_monthly_rest_of_country": 198,
        "ni_cpi_inflation_yoy_rest_of_country": 198,
        "ni_cpi_inflation_monthly_rest_of_country": 186,
    }
    assert len(observations) == 1746


def test_the_three_regions_are_not_the_same_series(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    """The failure this catches would otherwise look exactly like success.

    If the block offsets were wrong, all nine indicators would be filled from
    the national columns: every count would match, every value would be a
    valid CPI, and every other test would pass.
    """
    observations = connector.transform(_raw(inide_workbook_bytes))

    def index_series(code: str) -> dict[str, Decimal]:
        return {
            obs.period.label: obs.value_numeric
            for obs in observations
            if obs.indicator_code == code and obs.value_numeric is not None
        }

    national = index_series("ni_cpi_index_monthly")
    managua = index_series("ni_cpi_index_monthly_managua")
    rest = index_series("ni_cpi_index_monthly_rest_of_country")

    assert national.keys() == managua.keys() == rest.keys()
    assert national != managua
    assert national != rest
    assert managua != rest


def test_regional_observations_record_their_region(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    observations = connector.transform(_raw(inide_workbook_bytes))
    regions = {
        obs.indicator_code: obs.raw_metadata["inide_region"]
        for obs in observations
        if obs.indicator_code.startswith("ni_cpi_index_monthly")
    }

    assert regions == {
        "ni_cpi_index_monthly": "national",
        "ni_cpi_index_monthly_managua": "managua",
        "ni_cpi_index_monthly_rest_of_country": "rest_of_country",
    }


def test_record_ids_stay_unique_across_regions(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    """source_record_id is column-scoped, so nine series cannot collide."""
    observations = connector.transform(_raw(inide_workbook_bytes))
    record_ids = [obs.source_record_id for obs in observations]

    assert len(record_ids) == len(set(record_ids))


def test_regional_values_are_quantised_like_national(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    observations = connector.transform(_raw(inide_workbook_bytes))
    regional = [
        obs
        for obs in observations
        if obs.indicator_code == "ni_cpi_index_monthly_managua" and obs.value_numeric is not None
    ]

    assert regional
    for obs in regional:
        assert isinstance(obs.value_numeric, Decimal)
        assert -obs.value_numeric.as_tuple().exponent <= 6


def test_a_changed_regional_header_aborts_the_whole_run(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes, monkeypatch
) -> None:
    """A restructured sheet stops everything, national included."""
    import xlrd

    real_open = xlrd.open_workbook

    def fake_open(**kwargs: object):  # type: ignore[no-untyped-def]
        book = real_open(**kwargs)
        # Column 6 is Managua's index header.
        book.sheet_by_name(SHEET_NAME)._cell_values[3][6] = "Chinandega"
        return book

    monkeypatch.setattr(
        "reim.ingestion.connectors.nicaragua.inide_cpi_monthly.xlrd.open_workbook", fake_open
    )
    with pytest.raises(TransformationError, match="column 6"):
        connector.transform(_raw(inide_workbook_bytes))
```

- [ ] **Step 2: Update the two existing tests this changes**

`test_transform_parses_the_real_workbook` asserted the national-only totals; `test_all_three_regions_are_parsed` now covers that ground and more. **Delete** `test_transform_parses_the_real_workbook` — keeping both would assert contradictory totals.

`test_column_maps_are_derived_from_the_national_block` from Task 2 asserts the maps hold exactly the national columns. Rename it to `test_column_maps_cover_all_three_blocks` and replace its body:

```python
def test_column_maps_cover_all_three_blocks() -> None:
    assert COLUMN_INDICATORS[2] == ("ni_cpi_index_monthly", "index (2006=100)")
    assert COLUMN_INDICATORS[6] == ("ni_cpi_index_monthly_managua", "index (2006=100)")
    assert COLUMN_INDICATORS[10] == (
        "ni_cpi_index_monthly_rest_of_country",
        "index (2006=100)",
    )
    assert len(COLUMN_INDICATORS) == 9
    assert EXPECTED_HEADERS == {
        2: "nacional",
        3: "mensual",
        4: "acumulada",
        5: "interanual",
        6: "managua",
        7: "mensual",
        8: "acumulada",
        9: "interanual",
        10: "resto del país",
        11: "mensual",
        12: "acumulada",
        13: "interanual",
    }
```

`test_the_year_to_date_column_is_asserted_but_not_ingested` still holds; extend it to the other two blocks:

```python
def test_the_year_to_date_column_is_asserted_but_not_ingested() -> None:
    """Columns 4, 8 and 12 guard the layout; their values are not read."""
    for column in (4, 8, 12):
        assert column in EXPECTED_HEADERS
        assert column not in COLUMN_INDICATORS
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_inide_connector.py -v`
Expected: FAIL — the new tests find three series where they expect nine.

- [ ] **Step 4: Add the two blocks**

In the connector, replace the one-entry tuple:

```python
REGION_BLOCKS: tuple[RegionBlock, ...] = (RegionBlock("national", "nacional", 2, ""),)
```

with:

```python
REGION_BLOCKS: tuple[RegionBlock, ...] = (
    RegionBlock("national", "nacional", 2, ""),
    RegionBlock("managua", "managua", 6, "_managua"),
    RegionBlock("rest_of_country", "resto del país", 10, "_rest_of_country"),
)
```

The header `"resto del país"` carries an accent. `_assert_layout` lowercases and strips the cell value; it must **not** strip accents, and the literal here must match the workbook byte for byte.

Bump the connector version:

```text
    version = "1.1.0"
```

Update the module docstring's layout section to describe three blocks rather than the national columns alone, and say that "Acumulada" is asserted but not ingested.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_inide_connector.py -v`
Expected: PASS. Every pre-existing national assertion — periods, published values, quantisation, the 2008-2010 gap, provenance, purity — must still pass untouched.

- [ ] **Step 6: Lint, type-check and commit**

```bash
.venv/bin/ruff check reim tests && .venv/bin/ruff format --check reim tests
.venv/bin/mypy --strict reim apps
git add reim/ingestion/connectors/nicaragua/inide_cpi_monthly.py tests/unit/test_inide_connector.py
git commit -m "feat(inide): ingest the Managua and rest-of-country CPI

Two more entries in REGION_BLOCKS. 582 observations become 1,746, from
the same single download of the same workbook — the regional series were
always in the sheet the connector already parsed.

The test that matters most asserts the three regions differ from each
other: wrong block offsets would fill all nine series from the national
columns and every other test would still pass."
```

---

### Task 4: Continuity per region

**Files:**
- Modify: `reim/ingestion/connectors/nicaragua/inide_cpi_monthly.py` (`validate`, `_check_index_series_complete`)
- Test: `tests/unit/test_inide_connector.py`

**Interfaces:**
- Consumes: `REGION_BLOCKS`, `BLOCK_COLUMNS` from Tasks 2-3.
- Produces: `validate` returns four results — `inide_all_indicators_present` plus `inide_index_continuity_national`, `inide_index_continuity_managua`, `inide_index_continuity_rest_of_country`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_inide_connector.py`:

```python
def test_validate_checks_continuity_once_per_region(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    observations = connector.transform(_raw(inide_workbook_bytes))
    names = {r.check_name for r in connector.validate(observations)}

    assert names == {
        "inide_all_indicators_present",
        "inide_index_continuity_national",
        "inide_index_continuity_managua",
        "inide_index_continuity_rest_of_country",
    }


def test_a_hole_in_one_region_does_not_implicate_the_others(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    observations = [
        obs
        for obs in connector.transform(_raw(inide_workbook_bytes))
        if not (
            obs.indicator_code == "ni_cpi_index_monthly_managua" and obs.period.label == "2015-05"
        )
    ]
    results = {r.check_name: r for r in connector.validate(observations)}

    assert results["inide_index_continuity_managua"].failed
    assert results["inide_index_continuity_managua"].severity is CheckSeverity.ERROR
    assert results["inide_index_continuity_managua"].actual_value == "1"
    assert not results["inide_index_continuity_national"].failed
    assert not results["inide_index_continuity_rest_of_country"].failed
```

- [ ] **Step 2: Update the two existing continuity tests**

`test_validate_reports_the_documented_sparse_history` and
`test_validate_flags_a_hole_in_the_modern_series` both look up
`check_name == "inide_index_continuity"`, which no longer exists. In both,
change the lookup to `"inide_index_continuity_national"`. Nothing else in
either test changes.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_inide_connector.py -k "continuity or sparse_history or hole" -v`
Expected: FAIL — `StopIteration` looking up the per-region names.

- [ ] **Step 4: Make the continuity check region-aware**

In the connector, replace `validate` with:

```text
    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert INIDE-specific expectations beyond the standard battery."""
        results: list[QualityResult] = [self._check_all_indicators_present(observations)]
        results.extend(
            self._check_index_series_complete(observations, block) for block in REGION_BLOCKS
        )
        return results
```

Change `_check_index_series_complete` to take the block and use its index
indicator code and a per-region check name. Its signature and first lines
become:

```text
    def _check_index_series_complete(
        self, observations: list[NormalizedObservation], block: RegionBlock
    ) -> QualityResult:
        """The index must be unbroken from :data:`CONTIGUOUS_FROM_YEAR` onward.

        INIDE's own table is sparse before that: sheet ``2-1-06`` carries annual
        rows only for 2001-2006 and 2008-2010, with monthly detail for 2007 and
        then continuously from 2011. That history is a property of the source,
        not a parsing fault, so it is not treated as a failure. The modern
        stretch, however, must never develop a hole — one there would mean the
        workbook was truncated or the row scan broke.

        Run once per region; all three blocks share the same coverage, so the
        same threshold applies to each.
        """
        check_name = f"inide_index_continuity_{block.key}"
        index_code = f"{BLOCK_COLUMNS[0][1]}{block.indicator_suffix}"
        months = sorted(obs.period.start for obs in observations if obs.indicator_code == index_code)
```

Then replace every remaining literal `"inide_index_continuity"` inside the
method body with `check_name`. There are four occurrences: the `skipped`
result, the "no monthly index" failure, the `passed` result and the gap
failure.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_inide_connector.py -v`
Expected: PASS, all of them.

- [ ] **Step 6: Lint, type-check and commit**

```bash
.venv/bin/ruff check reim tests && .venv/bin/ruff format --check reim tests
.venv/bin/mypy --strict reim apps
git add reim/ingestion/connectors/nicaragua/inide_cpi_monthly.py tests/unit/test_inide_connector.py
git commit -m "feat(inide): check index continuity per region

A hole in the Managua series is a Managua problem. Reporting one result
per region says which series broke instead of collapsing three findings
into one."
```

---

### Task 5: Verify end to end and document

**Files:**
- Modify: `docs/sources.md`, `docs/implementation-plan.md`, `ROADMAP.md`, `README.md`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Run the full suite**

```bash
make db-up CONTAINER_ENGINE=podman
export REIM_TEST_DATABASE_URL="postgresql+psycopg://reim:reim@localhost:55432/reim"
.venv/bin/python -m pytest -q
```

Expected: PASS, with no skipped integration tests. Note this machine has no
Docker daemon; `CONTAINER_ENGINE=podman` is required.

- [ ] **Step 2: Migrate, seed and run against a real database**

```bash
export REIM_DATABASE_URL="postgresql+psycopg://reim:reim@localhost:55432/reim"
.venv/bin/alembic upgrade head
.venv/bin/reim db seed
.venv/bin/reim pipeline run inide_cpi_monthly
```

Expected: status `success`, **1,746 observations**, 0 rejected. If the database
already holds the 582 national rows from an earlier run, expect 1,164 inserted
and 582 unchanged — **`updated` must be 0**. A non-zero `updated` means the
refactor changed a national value and must be investigated before going on.

- [ ] **Step 3: Prove idempotency**

Run: `.venv/bin/reim pipeline run inide_cpi_monthly`
Expected: 0 inserted, 0 updated, 1,746 unchanged.

- [ ] **Step 4: Confirm the regions are distinct in the stored data**

```bash
podman exec reim-test-postgres psql -U reim -d reim -t -A -F' | ' -c \
"SELECT i.code, count(*), min(o.period_label), max(o.period_label), round(avg(o.value_numeric), 3)
   FROM observations o JOIN indicators i ON i.id = o.indicator_id
  WHERE i.code LIKE 'ni_cpi_index_monthly%'
  GROUP BY i.code ORDER BY i.code;"
```

Expected: three rows, each with 198 observations over the same period range,
and **three different averages**. Identical averages would mean the blocks are
reading the same columns.

- [ ] **Step 5: Check the quality checks**

```bash
podman exec reim-test-postgres psql -U reim -d reim -t -A -F' | ' -c \
"SELECT check_name, status, severity FROM data_quality_checks
  WHERE check_name LIKE 'inide%' ORDER BY created_at DESC LIMIT 8;"
podman exec reim-test-postgres psql -U reim -d reim -t -A -c \
"SELECT count(*) FROM data_quality_checks WHERE status='failed' AND severity IN ('error','critical');"
```

Expected: the four INIDE checks present and passing, and a count of 0 failures
at `error` or `critical`.

- [ ] **Step 6: Update the documentation**

`docs/sources.md` — in the INIDE section, add the three-block table from the
spec (§1), state that all three blocks share identical coverage (224 index, 186
month-on-month, 224 year-on-year rows), that "Acumulada" is asserted but not
ingested, and that sheets `2-2-06`, `2-3-06`, `2-4-06` (by division) and
`2-5-06` (core inflation) remain unread and are separate future increments.

`docs/implementation-plan.md` — add `## 13. Post-MVP increment — INIDE regional
CPI (2026-08-08)` with a verification table recording Steps 1-5.

`ROADMAP.md` — under v0.2.0, change the "INIDE regional CPI" bullet to the
struck-through done form used by the other completed entries, noting 1,746
observations from one download.

`README.md` — update the test count and the indicator count if stated.

- [ ] **Step 7: Final gate and commit**

```bash
export REIM_TEST_DATABASE_URL="postgresql+psycopg://reim:reim@localhost:55432/reim"
.venv/bin/python -m pytest -q
.venv/bin/ruff check reim apps tests && .venv/bin/ruff format --check reim apps tests
.venv/bin/mypy --strict reim apps
.venv/bin/reim catalog validate
git add docs/ ROADMAP.md README.md
git commit -m "docs(inide): record the regional CPI increment

1,746 observations across nine series from one download, with the
Managua and rest-of-country breakdowns verified distinct from the
national aggregate in the stored data."
podman stop reim-test-postgres
```

---

## Self-review notes

**Spec coverage.** Spec §3.1 → Tasks 2-4; §3.2 → Task 1 Step 3; §3.3 → Task 1 Step 4; §3.4 → Task 1 Step 5; §4 → Tasks 2-4 tests; §5 → Task 5 Step 6; §6 → Task 5 Step 2; §7 risks → Task 2 Step 5 (national unchanged), Task 3 Step 1 (`test_the_three_regions_are_not_the_same_series`), Task 3 Step 1 (header abort); §8 → Task 5 Step 6. Decisions R1-R7 all land: R1 in Task 1, R2 in Task 3 (one connector), R3 in the empty national suffix, R4 in `BLOCK_COLUMNS`, R5 in `BLOCK_HEADERS` plus the abort test, R6 in Task 1 Step 4, R7 in Task 3 Step 4.

**One correction to the spec.** The spec says nine headers are asserted. That would be a **regression**: the current connector asserts the "Acumulada" header at column 4, and deriving assertions only from ingested columns would silently drop it. The plan asserts **twelve** — three index headers plus three non-index headers per block — so the existing guard survives and each region gets the same protection. `BLOCK_HEADERS` therefore carries offset 2 while `BLOCK_COLUMNS` does not.

**Existing tests this plan changes**, all identified by reading the file rather than assumed:
- `test_transform_parses_the_real_workbook` — deleted in Task 3, superseded by `test_all_three_regions_are_parsed`.
- `test_validate_reports_the_documented_sparse_history` and `test_validate_flags_a_hole_in_the_modern_series` — the `check_name` lookup becomes `inide_index_continuity_national` in Task 4.
- `test_transform_records_provenance` and `test_missing_published_at_is_tolerated` use `observations[0]`. They keep working: observations sort by `(indicator_code, period.start)`, and `ni_cpi_index_monthly` still sorts first among the nine codes.
- `test_reordered_columns_are_refused` mutates row 3 column 3 and still passes.

**Metadata key change.** `inide_series: "nacional"` becomes `inide_region: "<block key>"`. `raw_metadata` is not part of `compute_content_hash`, so no stored observation is marked revised; rows written before this change keep the old key until their value changes.
