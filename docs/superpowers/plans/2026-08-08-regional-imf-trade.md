# Regional IMF Merchandise Trade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the IMF merchandise-trade connector from Nicaragua to six Central American countries, giving REIM its first data for more than one country.

**Architecture:** The connector body moves to a shared base in `connectors/common/`, following the pattern the World Bank connectors already use, and each catalog entry gets an eight-line subclass. The country stops being a class constant and comes from the catalog entry, so one module serves six sources. The three indicators drop their country prefix, because `observations` already carries a country column.

**Tech Stack:** Python 3.12, httpx, `csv` from the standard library, pytest + respx.

## Global Constraints

- Indicator codes for this multilateral series are **country-neutral**: `exports_goods_monthly`, `imports_goods_monthly`, `trade_balance_goods_monthly`.
- The other 16 `ni_*` indicator codes are **not touched**. Renaming all 19 would mark 8,388 stored observations as revised.
- **Six catalog entries**, one per country, sharing one connector base. Never one regional source: `source_key` is part of an observation's natural key.
- The Nicaragua entry keeps its key `imf_imts_nicaragua` and its module path.
- **Belize gets no entry** and stays `is_active=False`: it reports nothing to IMTS at any frequency.
- Quality-rule thresholds are **unchanged** — verified to span the region's full range, 12.7 M to 3,225 M USD.
- `SCALE` is never applied; the counterpart `G001` is filtered in the SDMX key; the CSV media type stays pinned.
- Verify with the commands CI runs, over the whole repo: `ruff check . && ruff format --check . && mypy reim apps && pytest`. Do not pipe them through `tail`, which masks the exit code.

---

### Task 1: Drop the country prefix from the three IMTS indicators

**Files:**
- Modify: `reim/domain/indicators/registry.py`
- Modify: `sources/quality_rules.yml`
- Modify: `reim/ingestion/connectors/nicaragua/imf_imts_trade.py` (the `INDICATORS` map)
- Test: `tests/unit/test_imf_imts_connector.py`, `tests/unit/test_quality.py`

**Interfaces:**
- Consumes: nothing.
- Produces: indicator codes `exports_goods_monthly`, `imports_goods_monthly`, `trade_balance_goods_monthly`. Tasks 3–5 emit exactly these.

- [ ] **Step 1: Update the tests that name the old codes**

In `tests/unit/test_quality.py`, replace the three `ni_*_goods_monthly` strings in
`test_monthly_trade_indicators_have_their_own_rules` and
`test_trade_balance_may_be_negative` with the neutral codes:

```text
    for code in (
        "exports_goods_monthly",
        "imports_goods_monthly",
        "trade_balance_goods_monthly",
    ):
        assert code in quality_rules.indicators, f"{code} has no rule set of its own"
```

and

```text
    balance = quality_rules.indicators["trade_balance_goods_monthly"]
```

In `tests/unit/test_imf_imts_connector.py`, replace every occurrence of
`ni_exports_goods_monthly` with `exports_goods_monthly`,
`ni_imports_goods_monthly` with `imports_goods_monthly`, and
`ni_trade_balance_goods_monthly` with `trade_balance_goods_monthly`. Counted
against the current file: **15 lines** carry one of the three, in
`build_connector`'s `indicators` list and throughout the test bodies. A
whole-word search-and-replace of the three strings is the safe way to do it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_imf_imts_connector.py tests/unit/test_quality.py -q`
Expected: FAIL — the registry and rules still hold the prefixed codes, and
`SourceEntry` rejects the unknown neutral ones.

- [ ] **Step 3: Rename the indicator definitions**

In `reim/domain/indicators/registry.py`, rename the three IMTS entries and
generalise their text — one definition now serves six countries, so nothing may
say "Nicaragua":

```text
    IndicatorDefinition(
        code="exports_goods_monthly",
        name="Merchandise exports FOB (monthly)",
        description=(
            "Exports of goods, free on board, compiled by the IMF from national "
            "customs data (International Merchandise Trade Statistics). Goods "
            "only: this does not replace the annual, broader goods-and-services "
            "series. The country is carried by the observation, not the code, "
            "because every country shares this methodology."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.MONTHLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=_IMF_TERMS,
    ),
    IndicatorDefinition(
        code="imports_goods_monthly",
        name="Merchandise imports CIF (monthly)",
        description=(
            "Imports of goods including cost, insurance and freight, compiled "
            "by the IMF from national customs data. Goods only: this does not "
            "replace the annual, broader goods-and-services series."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.MONTHLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=_IMF_TERMS,
    ),
    IndicatorDefinition(
        code="trade_balance_goods_monthly",
        name="Merchandise trade balance (monthly)",
        description=(
            "Merchandise exports FOB minus imports CIF, as published by the "
            "IMF. Negative in the great majority of months for every Central "
            "American country REIM covers."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.MONTHLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=_IMF_TERMS,
    ),
```

- [ ] **Step 4: Rename the quality-rule keys**

In `sources/quality_rules.yml`, rename the three keys from
`ni_exports_goods_monthly` to `exports_goods_monthly`, and likewise for imports
and the balance. **Change no thresholds.** Update the balance's comment, which
currently cites Nicaragua's 433 of 436 months:

```yaml
  trade_balance_goods_monthly:
    # NOT bounded below. A trade balance crosses zero; a sign constraint here
    # would reject the great majority of real months in every country covered.
    allow_negative: true
    allow_zero: true
    freshness_max_age_days: 120
    min_observations: 300
```

- [ ] **Step 5: Point the connector at the new codes**

In `reim/ingestion/connectors/nicaragua/imf_imts_trade.py`:

```python
INDICATORS: dict[str, tuple[str, str]] = {
    "XG_FOB_USD": ("exports_goods_monthly", "current USD"),
    "MG_CIF_USD": ("imports_goods_monthly", "current USD"),
    "TBG_USD": ("trade_balance_goods_monthly", "current USD"),
}
```

and in `_check_balance_identity`, update the three `series.get(...)` lookups to
the neutral codes.

Update `sources/catalog.yml`'s `imf_imts_nicaragua` entry to list the three
neutral indicators.

Bump the connector `version` to `"2.0.0"`: the same input now produces
different indicator codes, which is exactly what the `BaseConnector` contract
says to bump for, and it is a breaking rename rather than an addition.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit -q`
Expected: PASS.

Run: `.venv/bin/reim catalog validate`
Expected: 9 sources, 9 enabled, 19 rule sets.

- [ ] **Step 7: Gate and commit**

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy reim apps
git add reim/domain/indicators/registry.py sources/ reim/ingestion/connectors/nicaragua/imf_imts_trade.py tests/
git commit -m "refactor(imf): drop the country prefix from the trade indicators

observations already carries a country column, so six country-prefixed
variants of one concept would force every cross-country query to map a
concept onto six codes.

The rule this establishes: prefix by country when the source is national
and the methodology differs — a Guatemalan CPI is not a Nicaraguan one —
and drop the prefix when the source is multilateral and shared. The 16
ni_* codes from national and World Bank sources keep their prefix.

indicator_code is part of an observation's natural key, so any database
holding the old rows needs them deleted once. That is 1,308 rows, one
commit old, regenerated in four seconds."
```

---

### Task 2: Extract the shared base

**Files:**
- Create: `reim/ingestion/connectors/common/imf_imts.py` (moved)
- Rewrite: `reim/ingestion/connectors/nicaragua/imf_imts_trade.py` (thin subclass)
- Test: `tests/unit/test_imf_imts_connector.py`

**Interfaces:**
- Consumes: the neutral indicator codes from Task 1.
- Produces: `reim.ingestion.connectors.common.imf_imts.ImfImtsTradeConnector` — the base, with **no** `connector_key`; `reim.ingestion.connectors.nicaragua.imf_imts_trade.ImfImtsNicaragua` — the subclass, `connector_key = "imf_imts_nicaragua"`.

This task must not change what the connector produces. The existing 1,308-row
assertions are the proof, and they stay untouched.

- [ ] **Step 1: Move the module**

```bash
git mv reim/ingestion/connectors/nicaragua/imf_imts_trade.py \
       reim/ingestion/connectors/common/imf_imts.py
```

- [ ] **Step 2: Turn the moved module into a base**

In `reim/ingestion/connectors/common/imf_imts.py`, delete the line
`connector_key = "imf_imts_nicaragua"` from the class body. Leave `version`,
`expected_frequency`, `country_iso3` and `currency_code` where they are.

Update the module docstring's first line to
`"""Merchandise trade from the IMF's SDMX API — shared connector base."""`
and remove "Nicaragua —" from it; the rest of the docstring is still accurate
and must be kept, including the bot-manager explanation and the licence note.

- [ ] **Step 3: Write the Nicaragua subclass**

Create `reim/ingestion/connectors/nicaragua/imf_imts_trade.py`:

```python
"""Nicaragua — monthly merchandise trade from the IMF's IMTS dataflow."""

from __future__ import annotations

from reim.ingestion.connectors.common.imf_imts import ImfImtsTradeConnector


class ImfImtsNicaragua(ImfImtsTradeConnector):
    """IMF IMTS merchandise trade for Nicaragua.

    Everything but the catalog key comes from the base: the country is read
    from the catalog entry, so this class carries no country of its own.
    """

    connector_key = "imf_imts_nicaragua"
```

The connector registry resolves a catalog entry to "the single concrete
`BaseConnector` subclass whose `__module__` equals the dotted path", so
importing the base here does not confuse it — this is exactly how the six World
Bank connectors work.

- [ ] **Step 4: Update the test import**

In `tests/unit/test_imf_imts_connector.py`, change the import to the subclass:

```python
from reim.ingestion.connectors.nicaragua.imf_imts_trade import ImfImtsNicaragua
```

and change `build_connector` to return `ImfImtsNicaragua(entry)`. Its
annotation becomes `-> ImfImtsNicaragua`.

- [ ] **Step 5: Run the tests to verify nothing changed**

Run: `.venv/bin/python -m pytest tests/unit -q`
Expected: PASS, including the untouched assertion of 1,308 observations. That
test passing unchanged is the point of this task.

Run: `.venv/bin/reim catalog validate`
Expected: all 9 connectors still import cleanly.

- [ ] **Step 6: Gate and commit**

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy reim apps
git add reim/ingestion/connectors/ tests/unit/test_imf_imts_connector.py
git commit -m "refactor(imf): split the IMTS connector into base and subclass

Follows the pattern the six World Bank connectors already use: a shared
base in connectors/common/ and a thin per-entry subclass carrying only
the catalog key. This is what lets one module serve six countries
without weakening BaseConnector's guard that the catalog key matches.

No behaviour change: still Nicaragua, still 1,308 observations."
```

---

### Task 3: Take the country from the catalog

**Files:**
- Modify: `reim/ingestion/connectors/common/imf_imts.py`
- Create: `tests/fixtures/imf_imts_gtm_g001.csv.gz`
- Modify: `tests/conftest.py`, `tests/fixtures/README.md`
- Test: `tests/unit/test_imf_imts_connector.py`

**Interfaces:**
- Consumes: `ImfImtsTradeConnector` from Task 2.
- Produces: `ImfImtsTradeConnector.country_iso3` as a **property** reading the catalog entry; a fourth quality check `imf_imts_country_match`; pytest fixture `imf_imts_gtm_csv() -> str`.

- [ ] **Step 1: Record the Guatemala fixture**

```bash
curl -sL -H "Accept: application/vnd.sdmx.data+csv;version=2.0.0" \
  "https://api.imf.org/external/sdmx/2.1/data/IMF.STA,IMTS/GTM..G001.M?startPeriod=1990-01" \
  | gzip -9 > tests/fixtures/imf_imts_gtm_g001.csv.gz
```

Verify it:

```bash
.venv/bin/python - <<'PY'
import csv, gzip, io
text = gzip.decompress(open("tests/fixtures/imf_imts_gtm_g001.csv.gz","rb").read()).decode("utf-8")
rows = [r for r in csv.DictReader(io.StringIO(text)) if r["TIME_PERIOD"]]
print("rows:", len(rows), "countries:", {r["COUNTRY"] for r in rows})
PY
```

Expected: `rows: 1308 countries: {'GTM'}`. The raw response is ~791 KB and
gzips to ~18 KB.

Add the fixture to `tests/conftest.py`, next to `imf_imts_csv`:

```python
@pytest.fixture(scope="session")
def imf_imts_gtm_csv() -> str:
    """Real IMF IMTS response for Guatemala, world aggregate (stored gzipped)."""
    return gzip.decompress((FIXTURES / "imf_imts_gtm_g001.csv.gz").read_bytes()).decode("utf-8")
```

and a row to the "Recorded from live official sources" table in
`tests/fixtures/README.md`:

```markdown
| `imf_imts_gtm_g001.csv.gz` | `GET https://api.imf.org/external/sdmx/2.1/data/IMF.STA,IMTS/GTM..G001.M?startPeriod=1990-01` with `Accept: application/vnd.sdmx.data+csv;version=2.0.0`, byte-for-byte, gzipped (791 KB → 18 KB). Recorded so tests can prove the country comes from the catalog entry rather than a constant. | 2026-08-08 |
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/unit/test_imf_imts_connector.py`. `build_connector` currently
hard-codes Nicaragua; add a country parameter to it:

```python
def build_connector(country: str = "NI", key: str = "imf_imts_nicaragua", **options: object):
    entry = SourceEntry.model_validate(
        {
            "key": key,
            "name": "Merchandise trade (monthly)",
            "country": country,
            "organization": "IMF",
            "category": "external_sector",
            "access_type": "http_api",
            "frequency": "monthly",
            "format": "csv",
            "base_url": BASE_URL,
            "connector": "reim.ingestion.connectors.nicaragua.imf_imts_trade",
            "indicators": [
                "exports_goods_monthly",
                "imports_goods_monthly",
                "trade_balance_goods_monthly",
            ],
            "license": "imf_terms_of_use",
            "options": dict(options),
        }
    )
    return ImfImtsNicaragua(entry)
```

Then the new tests:

```python
def test_country_comes_from_the_catalog_entry() -> None:
    assert build_connector(country="NI").country_iso3 == "NIC"
    assert build_connector(country="GT").country_iso3 == "GTM"
    assert build_connector(country="CR").country_iso3 == "CRI"


def test_a_source_without_a_country_is_rejected() -> None:
    """Defaulting to Nicaragua would file another country's data under it."""
    connector = build_connector(country=None)

    with pytest.raises(ExtractionError, match="must declare a country"):
        _ = connector.country_iso3


def test_guatemala_rows_are_filed_under_guatemala(imf_imts_gtm_csv: str) -> None:
    connector = build_connector(country="GT")

    observations = connector.transform(raw_from(imf_imts_gtm_csv))

    assert len(observations) == 1308
    assert {obs.country_iso3 for obs in observations} == {"GTM"}


def test_guatemala_and_nicaragua_are_different_series(
    imf_imts_csv: str, imf_imts_gtm_csv: str
) -> None:
    """The one failure mode counts cannot catch.

    Both countries return 436 identically shaped months, so a country-mapping
    bug would produce plausible figures under the wrong flag and every count
    would still match.
    """
    nicaragua = {
        obs.period.label: obs.value_numeric
        for obs in build_connector(country="NI").transform(raw_from(imf_imts_csv))
        if obs.indicator_code == "exports_goods_monthly"
    }
    guatemala = {
        obs.period.label: obs.value_numeric
        for obs in build_connector(country="GT").transform(raw_from(imf_imts_gtm_csv))
        if obs.indicator_code == "exports_goods_monthly"
    }

    assert nicaragua.keys() == guatemala.keys()
    assert nicaragua != guatemala
    assert nicaragua["2026-04"] == Decimal("601982690")
    assert guatemala["2026-04"] == Decimal("1524586084")


def test_a_foreign_country_in_the_response_fails_the_check(imf_imts_gtm_csv: str) -> None:
    """A Guatemala entry served Nicaragua's rows must not pass silently."""
    connector = build_connector(country="GT")
    observations = connector.transform(raw_from(imf_imts_gtm_csv))
    observations[0].country_iso3 = "NIC"

    check = results_by_name(connector.validate(observations))["imf_imts_country_match"]

    assert check.status is CheckStatus.FAILED
    assert check.severity is CheckSeverity.CRITICAL
    assert "NIC" in str(check.actual_value)


def test_validate_now_returns_four_checks(imf_imts_csv: str) -> None:
    connector = build_connector()
    observations = connector.transform(raw_from(imf_imts_csv))

    assert set(results_by_name(connector.validate(observations))) == {
        "imf_imts_world_aggregate_present",
        "imf_imts_all_indicators_present",
        "imf_imts_balance_identity",
        "imf_imts_country_match",
    }
```

Delete the older `test_validate_returns_the_three_source_checks`, which asserts
a set of exactly three names and now contradicts the test above.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_imf_imts_connector.py -q`
Expected: FAIL — `country_iso3` is still a `ClassVar` fixed to `"NIC"`, and
`imf_imts_country_match` does not exist.

- [ ] **Step 4: Make the country dynamic**

In `reim/ingestion/connectors/common/imf_imts.py`, delete
`country_iso3: ClassVar[str] = COUNTRY_ISO3` and the now-unused
`COUNTRY_ISO3` constant, and add the property:

```text
    @property
    def country_iso3(self) -> str:
        """ISO-3 of the country this catalog entry covers.

        Read from the catalog rather than fixed on the class, so one module
        serves every country in the dataflow.

        Raises:
            ExtractionError: The entry declares no country, or one REIM does
                not know. Defaulting to any country would file its data under
                the wrong flag.
        """
        iso2 = self.source.country_iso2
        if iso2 is None:
            msg = f"{self.source.key} must declare a country"
            raise ExtractionError(msg, source_key=self.source.key)
        definition = COUNTRIES_BY_ISO2.get(iso2)
        if definition is None:
            msg = f"{self.source.key} names unknown country {iso2!r}"
            raise ExtractionError(msg, source_key=self.source.key)
        return definition.iso3
```

Add the imports it needs:

```python
from reim.core.exceptions import ExtractionError, TransformationError
from reim.domain.countries.registry import COUNTRIES_BY_ISO2
```

- [ ] **Step 5: Add the country-match check**

In `validate`, append the fourth check, and add the method:

```text
    def _check_country_match(self, observations: list[NormalizedObservation]) -> QualityResult:
        """Every row must belong to the country this entry declares.

        Critical: one module now serves six catalog entries, so a wrong key or
        a wrong response would file one country's trade under another's flag —
        and the counts would look perfectly healthy, because all six countries
        return the same 436 months.
        """
        expected = self.country_iso3
        foreign = sorted({obs.country_iso3 for obs in observations if obs.country_iso3 != expected})

        if not foreign:
            return QualityResult.passed(
                "imf_imts_country_match",
                CheckType.INTEGRITY,
                f"All {len(observations)} observation(s) reported for {expected}",
                expected_value=expected,
                actual_value=expected,
            )
        return QualityResult.failure(
            "imf_imts_country_match",
            CheckType.INTEGRITY,
            CheckSeverity.CRITICAL,
            f"Observations for {', '.join(foreign)} in a {expected} source",
            expected_value=expected,
            actual_value=", ".join(foreign),
        )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit -q`
Expected: PASS. Every pre-existing Nicaragua assertion must still hold.

- [ ] **Step 7: Gate and commit**

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy reim apps
git add reim/ tests/
git commit -m "feat(imf): read the country from the catalog entry

One module now serves any country in the dataflow. A source that
declares no country raises rather than defaulting, and a new critical
check asserts every row belongs to the declared country.

That check exists because counts cannot detect the failure: all six
countries return 436 identically shaped months, so a mapping bug would
produce plausible figures under the wrong flag."
```

---

### Task 4: Bring the five countries live

**Files:**
- Modify: `reim/domain/countries/registry.py`
- Create: `reim/ingestion/connectors/{guatemala,el_salvador,honduras,costa_rica,panama}/__init__.py` and `.../imf_imts_trade.py`
- Modify: `sources/catalog.yml`
- Test: `tests/unit/test_catalog.py`, `tests/integration/test_api.py`

**Interfaces:**
- Consumes: `ImfImtsTradeConnector` (Task 2), the dynamic country (Task 3).
- Produces: catalog keys `imf_imts_guatemala`, `imf_imts_el_salvador`, `imf_imts_honduras`, `imf_imts_costa_rica`, `imf_imts_panama`, with classes `ImfImtsGuatemala`, `ImfImtsElSalvador`, `ImfImtsHonduras`, `ImfImtsCostaRica`, `ImfImtsPanama`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_catalog.py`:

```python
def test_imts_covers_the_six_reporting_countries(catalog: SourceCatalog) -> None:
    """Belize is absent on purpose: it reports nothing to IMTS."""
    imts = {e.key: e.country for e in catalog.sources if e.key.startswith("imf_imts_")}

    assert imts == {
        "imf_imts_nicaragua": "NI",
        "imf_imts_guatemala": "GT",
        "imf_imts_el_salvador": "SV",
        "imf_imts_honduras": "HN",
        "imf_imts_costa_rica": "CR",
        "imf_imts_panama": "PA",
    }


def test_every_imts_entry_declares_the_imf_licence(catalog: SourceCatalog) -> None:
    for entry in catalog.sources:
        if entry.key.startswith("imf_imts_"):
            assert entry.license == "imf_terms_of_use"
```

Add to `tests/unit/test_catalog.py` a registry assertion:

```python
def test_six_countries_are_active_and_belize_is_not() -> None:
    """REIM holds data for six; Belize reports nothing to IMTS."""
    active = {c.iso2 for c in COUNTRIES if c.is_active}

    assert active == {"NI", "GT", "SV", "HN", "CR", "PA"}
    assert COUNTRIES_BY_ISO2["BZ"].is_active is False
```

importing `from reim.domain.countries.registry import COUNTRIES, COUNTRIES_BY_ISO2`.

- [ ] **Step 2: Update the integration test that assumes one active country**

`tests/integration/test_api.py::test_active_only_filter` currently asserts
`== ["NI"]`. It must become:

```python
def test_active_only_filter(client: TestClient) -> None:
    body = client.get("/api/v1/countries", params={"active_only": True}).json()
    returned = {c["iso2"] for c in body["data"]}

    assert returned == {"NI", "GT", "SV", "HN", "CR", "PA"}
    assert "BZ" not in returned
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog.py -k "imts or six_countries" -q`
Expected: FAIL — the catalog holds one IMTS entry and only Nicaragua is active.

- [ ] **Step 4: Activate the five countries**

In `reim/domain/countries/registry.py`, set `is_active=True` on Guatemala, El
Salvador, Honduras, Costa Rica and Panama. **Leave Belize `False`** and add a
comment on its entry:

```python
# Belize reports nothing to the IMF's IMTS dataflow at any frequency,
# so REIM holds no data for it yet. See docs/sources.md.
is_active = (False,)
```

Update the module docstring, which says "Only Nicaragua is active in v0.1.0".

- [ ] **Step 5: Create the five connector subclasses**

For each country, create the package `__init__.py` with a one-line docstring
matching `nicaragua/__init__.py`'s style (`"""guatemala package."""`), and the
module. Guatemala's, in full:

```python
"""Guatemala — monthly merchandise trade from the IMF's IMTS dataflow."""

from __future__ import annotations

from reim.ingestion.connectors.common.imf_imts import ImfImtsTradeConnector


class ImfImtsGuatemala(ImfImtsTradeConnector):
    """IMF IMTS merchandise trade for Guatemala.

    Everything but the catalog key comes from the base: the country is read
    from the catalog entry, so this class carries no country of its own.
    """

    connector_key = "imf_imts_guatemala"
```

The other four are identical but for the country name, class name and key:
`ImfImtsElSalvador` / `imf_imts_el_salvador` in `el_salvador/`,
`ImfImtsHonduras` / `imf_imts_honduras` in `honduras/`,
`ImfImtsCostaRica` / `imf_imts_costa_rica` in `costa_rica/`, and
`ImfImtsPanama` / `imf_imts_panama` in `panama/`.

- [ ] **Step 6: Add the five catalog entries**

Append to `sources/catalog.yml`. Guatemala's, in full; the other four differ
only in `key`, `name`, `country`, `connector` and the country named in
`description`:

```yaml
  - key: imf_imts_guatemala
    name: Guatemala merchandise trade (monthly)
    description: >-
      Monthly merchandise exports FOB, imports CIF and the balance between
      them for Guatemala, from the IMF's International Merchandise Trade
      Statistics, world aggregate, covering January 1990 onwards.
    country: GT
    organization: IMF
    category: external_sector
    access_type: http_api
    frequency: monthly
    format: csv
    base_url: https://api.imf.org/external/sdmx/2.1
    documentation_url: https://www.imf.org/external/terms.htm
    connector: reim.ingestion.connectors.guatemala.imf_imts_trade
    indicators:
      - exports_goods_monthly
      - imports_goods_monthly
      - trade_balance_goods_monthly
    license: imf_terms_of_use
    official: true
    enabled: true
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit -q`
Expected: PASS.

Run: `.venv/bin/reim catalog validate`
Expected: **14 sources, 14 enabled**, 19 rule sets, all 14 connectors import.

- [ ] **Step 8: Gate and commit**

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy reim apps
git add reim/ sources/catalog.yml tests/
git commit -m "feat(imf): bring Guatemala, El Salvador, Honduras, Costa Rica and Panama live

Five catalog entries and five eight-line subclasses, all sharing the
base. Their country registry entries flip to active, because holding
observations for a country the API reports as inactive would be
incoherent.

Belize stays inactive and gets no entry: it reports nothing to IMTS at
monthly, quarterly or annual frequency."
```

---

### Task 5: Verify end to end and document

**Files:**
- Modify: `docs/sources.md`, `docs/implementation-plan.md`, `ROADMAP.md`, `README.md`

- [ ] **Step 1: Run the full suite**

```bash
make db-up CONTAINER_ENGINE=podman
export REIM_TEST_DATABASE_URL="postgresql+psycopg://reim:reim@localhost:55432/reim"
.venv/bin/python -m pytest -q
```

Expected: PASS with no skipped integration tests. This machine has no Docker
daemon; `CONTAINER_ENGINE=podman` is required.

- [ ] **Step 2: Clear the superseded Nicaragua rows and reseed**

The three indicators were renamed in Task 1, and `indicator_code` is part of an
observation's natural key, so any rows written before this branch sit under the
old codes. Drop them rather than leaving a duplicate series:

```bash
export REIM_DATABASE_URL="postgresql+psycopg://reim:reim@localhost:55432/reim"
podman exec reim-test-postgres psql -U reim -d reim -c \
"DELETE FROM observations o USING indicators i WHERE i.id = o.indicator_id
   AND i.code IN ('ni_exports_goods_monthly','ni_imports_goods_monthly','ni_trade_balance_goods_monthly');"
podman exec reim-test-postgres psql -U reim -d reim -c \
"DELETE FROM indicators WHERE code IN ('ni_exports_goods_monthly','ni_imports_goods_monthly','ni_trade_balance_goods_monthly');"
.venv/bin/alembic upgrade head
.venv/bin/reim db seed
```

Expected: seeding creates the 3 renamed indicators and 5 sources, and updates 5
countries to active.

- [ ] **Step 3: Run all six pipelines**

```bash
for c in nicaragua guatemala el_salvador honduras costa_rica panama; do
  .venv/bin/reim pipeline run "imf_imts_$c" 2>&1 | tail -1
done
```

Expected: six successes, **1,308 observations each**, 0 rejected.

- [ ] **Step 4: Prove idempotency**

Run the same loop again.
Expected: six runs of 0 inserted, 0 updated, 1,308 unchanged.

- [ ] **Step 5: Confirm the six countries are distinct in stored data**

```bash
podman exec reim-test-postgres psql -U reim -d reim -t -A -F' | ' -c \
"SELECT c.iso3, count(*), round(avg(o.value_numeric)) AS mean_exports
   FROM observations o
   JOIN indicators i ON i.id = o.indicator_id
   JOIN countries  c ON c.id = o.country_id
  WHERE i.code = 'exports_goods_monthly'
  GROUP BY c.iso3 ORDER BY c.iso3;"
```

Expected: six rows of 436 observations each, with **six different means**.
Identical means would mean one country's data was filed under several flags.

- [ ] **Step 6: Check the quality checks**

```bash
podman exec reim-test-postgres psql -U reim -d reim -t -A -F' | ' -c \
"SELECT check_name, status, count(*) FROM data_quality_checks
  WHERE check_name LIKE 'imf%' GROUP BY check_name, status ORDER BY check_name;"
podman exec reim-test-postgres psql -U reim -d reim -t -A -c \
"SELECT count(*) FROM data_quality_checks WHERE status='failed' AND severity IN ('error','critical');"
```

Expected: four IMF check names, all `passed`, and 0 failures at `error` or
`critical`.

- [ ] **Step 7: Update the documentation**

`docs/sources.md` — generalise the IMF section from Nicaragua to the region:
the six countries and their identical coverage; that Belize reports nothing at
any frequency; that the country comes from the catalog entry; and that the
indicator codes carry no country prefix, with the rule stated (prefix for
national sources whose methodology differs, none for shared multilateral ones).
Keep the licence warning and the bot-manager explanation as they are.

`docs/implementation-plan.md` — add `## 15. Post-MVP increment — regional IMF
trade (2026-08-08)` with a verification table covering Steps 3–6, and record the
decomposition of v0.3.0 into pieces A–F with A delivered.

`ROADMAP.md` — under v0.3.0, mark the regional trade work done, note that
Belize is excluded and why, and record that the remaining pieces are the
national central banks, SIECA, CEPALSTAT, the comparison endpoints and currency
handling.

`README.md` — update the test count, and change any statement that REIM covers
only Nicaragua: it now holds data for six countries.

- [ ] **Step 8: Final gate and commit**

```bash
export REIM_TEST_DATABASE_URL="postgresql+psycopg://reim:reim@localhost:55432/reim"
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy reim apps
.venv/bin/reim catalog validate
git add docs/ ROADMAP.md README.md
git commit -m "docs: record the regional IMF trade increment

7,848 observations across six countries, REIM's first data for more than
one. Records why Belize is absent and why the indicator codes lost their
country prefix."
podman stop reim-test-postgres
```

---

## Self-review notes

**Spec coverage.** Spec §3 R1 → Task 1; R2 → Task 1 (the 16 `ni_*` are untouched); R3 → Task 4 Step 6; R4 → Task 3 Step 4; R5 → Task 4 Steps 4 and 6, Task 5 Step 7; R6 → Task 4 Step 4; R7 → Task 1 Step 4 (keys renamed, thresholds unchanged). §4.1 → Tasks 1 and 4; §4.2 → Task 1; §4.3 → Tasks 2 and 3; §4.4 → Task 4; §5 testing → Tasks 3 and 4; §6 → Task 5 Steps 3–5; §7 risks → Task 3's country-match check and the Guatemala-differs test.

**Existing tests this plan changes**, identified by reading the files rather than assumed:

- `tests/integration/test_api.py::test_active_only_filter` asserts `== ["NI"]` and **breaks** the moment five countries are activated. Task 4 Step 2 updates it.
- `tests/unit/test_quality.py`'s two trade tests name the prefixed codes. Task 1 Step 1.
- `tests/unit/test_imf_imts_connector.py` names the prefixed codes throughout and imports the class that becomes a base. Tasks 1 and 2.
- `test_validate_returns_the_three_source_checks` asserts a set of exactly three check names and is deleted in Task 3, superseded by the four-check version.
- `tests/integration/test_persistence.py::test_seed_creates_reference_data` asserts `count(Country.id) == 7`. Activating countries does not change the count, so it keeps passing.

**Why the connector registry is not confused by the base.** It selects classes whose `__module__` equals the dotted path being loaded, so a subclass module that imports its base yields exactly one candidate. This is verified behaviour — the six World Bank connectors already rely on it.

**Numbers stated here were measured, not estimated:** 1,308 observations and 436 months per country for all six; Belize returning 0 at monthly, quarterly and annual frequency and with no counterpart filter; Guatemala's 2026-04 exports of `1524586084` against Nicaragua's `601982690`; the regional range of 12.7 M to 3,225 M USD that leaves the quality thresholds untouched.
