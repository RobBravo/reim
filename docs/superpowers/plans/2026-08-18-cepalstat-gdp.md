# CEPALSTAT annual GDP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest four annual GDP series from CEPALSTAT for the seven Central American countries — 1,008 observations from four requests — giving REIM its first GDP data and Belize its first data of any kind.

**Architecture:** One country-agnostic catalog entry drives one connector in the existing `connectors/regional/` package, next to SIECA. A run issues four `GET` requests, one per CEPAL indicator id; each returns that indicator's entire matrix — 33 countries and 3 aggregates × 36 years — in a single response. `transform` keeps only rows whose `iso3` is one of the seven, maps year member ids to labels through the response's own dimension members, scales the two totals from millions to whole USD, and records the published figure alongside. `validate` adds four source-specific checks, one of which — the implied-population identity across the current and constant pairs — is only expressible because all four series pass through one connector.

**Tech Stack:** Python 3.12, httpx, Pydantic 2, pytest + respx, structlog.

## Global Constraints

- **Verify with the commands CI runs, over the whole repo, each as its own command that reports its own exit code.** Do not chain them with `&&`, `set -e`, or a pipe into `tail` — all three have masked a failure in this repository and let a broken gate reach a commit. Run: `.venv/bin/ruff format --check .`, `.venv/bin/ruff check .`, `.venv/bin/mypy reim apps`, `.venv/bin/python -m pytest tests/ -m "not live and not integration"`, then read each printed exit code before committing.
- **Tools run from the uv-managed venv:** `.venv/bin/<tool>`. There is no `pip` inside it.
- **The test database is podman, not Docker:** `make db-up CONTAINER_ENGINE=podman`, then `REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim`. Integration tests must be run over the whole `tests/integration` directory — schema setup is session-scoped and a lone file fails on `TRUNCATE`.
- **Parse every CEPALSTAT payload with `json.loads(text, parse_float=Decimal)`.** `body.data[].value` is a quoted string today, so `Decimal` is already exact — but the parser is pinned so that a future switch to bare JSON numbers on CEPAL's side cannot silently corrupt every figure in its last places, where no count or total would reveal it.
- **Read dimensions by numeric id, never by name.** The row keys literally embed the id (`dim_208`, `dim_29117`), and the names are language-dependent (`Years__ESTANDAR` in English, `Años__ESTANDAR` in Spanish). Country dimension is `208`, years dimension is `29117`, identical across all four indicators.
- **Never derive the year from the member id by arithmetic.** Today `year = member_id − 27170` holds for every member, but CEPAL documents no such contract. Build the `member_id → label` map from `dimensions[].members[]` on every run.
- **Never impute.** A country outside the seven is filtered deliberately and the completeness check guards that. A malformed row raises.
- **Code blocks holding only methods must be fenced as ```text, not ```python.** `ruff format` reads this repository's Markdown and dedents a `def foo(self)` that has no `class` header above it, silently moving every method in the block to module level. It has damaged three earlier plans this way. After editing this plan, run `.venv/bin/ruff format .` and confirm it reports no change.
- Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## Measured facts the tests assert

Recorded from the live API on 2026-08-18. Any of these changing means the fixture was re-recorded, not that the code broke.

| Fact | Value |
|---|---|
| Base URL | `https://api-cepalstat.cepal.org/cepalstat/api/v1` |
| Endpoint | `GET /indicator/{id}/data?lang=en` |
| API version reported | `1.9.13` |
| Indicator ids | 2203 current total · 2204 constant total · 2205 current per capita · 2206 constant per capita |
| Dimensions | `208` country, `29117` years — the same two for all four indicators |
| Year member ids | 1990 → `29160`, 2025 → `29195` |
| Country member ids | Nicaragua `240`, Belize `220` |
| Rows per response | 2203 → 1,289 · 2204 → 1,296 · 2205 → 1,289 · 2206 → 1,296 |
| Central American cells | **252 per indicator** (7 countries × 36 years), for all four |
| Observations | **1,008** = 4 × 252 |
| Source id | `1753` on every Central American row, all four indicators |
| `notes_ids` | `""` on 2203 and 2205; `"12080"` on 2204 and 2206 |
| Footnote 12080 | `At prices 2018` |
| Units published | 2203/2204 `Millions of dollars` · 2205 `Dollars per inhabitant at current prices` · 2206 `Dollars per inhabitant` |
| Nicaragua 2024 | 2203 `19696.31184918235` · 2204 `15301.62516515467` · 2205 `2757.621539962527` · 2206 `2142.334639853647` |
| Belize 1990 → 2025 | 2203 `546.75091228848` → `3291.31247838729` |
| Smallest total | `546.75091228848` million USD (Belize 1990, current prices) |
| Smallest per-capita | `704.39` USD |
| Worst year-on-year change | 23.0 % (Guatemala 1991, current-price total) |
| Implied-population disagreement | worst 8.1 × 10⁻¹⁶ relative, across all 252 cells |
| Unknown indicator id | HTTP **500** with `success: false` — not a 404 |
| Fixture bytes gzipped | 2203 24,038 · 2204 25,074 · 2205 25,029 · 2206 26,067 = 100,208 |
| Catalog after this work | 17 sources, 17 enabled, 28 indicator rules |

**One trap recorded up front:** `body.credits[0].description` is CEPAL's own fetch date, and it changes between runs — two downloads twelve hours apart returned `2026-08-18` and `2026-08-19`. It must **not** be stored or asserted. `raw_metadata` keeps only credits 1–3 (the citation), and `retrieved_at` already records when REIM fetched. This does not threaten idempotency — `compute_content_hash` does not hash `raw_metadata` — but it would make every fixture comparison and every stored payload churn for no reason.

## File structure

| File | Responsibility |
|---|---|
| `reim/domain/indicators/registry.py` | Four new `IndicatorDefinition` entries (modify) |
| `reim/domain/countries/registry.py` | Belize becomes active (modify, `:84-94`) |
| `sources/quality_rules.yml` | Two rule sets: one for the totals, one for the per-capita pair (modify) |
| `sources/catalog.yml` | One `cepalstat_gdp_annual` entry (modify) |
| `reim/ingestion/connectors/regional/cepalstat_gdp.py` | The connector: `extract`, `transform`, `validate` (create) |
| `tests/fixtures/cepalstat_gdp_220{3,4,5,6}.json.gz` | Four verbatim recordings (create) |
| `tests/conftest.py` | Four session fixtures (modify) |
| `tests/fixtures/README.md` | Four provenance rows (modify) |
| `tests/unit/test_cepalstat_connector.py` | Every connector test (create) |
| `docs/sources.md`, `ROADMAP.md`, `docs/implementation-plan.md`, `README.md` | The record, including the 404 correction and the licence exception (modify) |

---

### Task 1: The four indicators, Belize, and their quality rules

**Files:**
- Modify: `reim/domain/indicators/registry.py`, `reim/domain/countries/registry.py`, `sources/quality_rules.yml`
- Test: `tests/unit/test_catalog.py`

**Interfaces:**
- Produces: indicator codes `gdp_current_usd_annual`, `gdp_constant_usd_annual`, `gdp_per_capita_current_usd_annual`, `gdp_per_capita_constant_usd_annual`; `COUNTRIES_BY_ISO3["BLZ"].is_active is True`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_catalog.py`:

```python
def test_the_four_gdp_indicators_are_registered() -> None:
    codes = {
        "gdp_current_usd_annual",
        "gdp_constant_usd_annual",
        "gdp_per_capita_current_usd_annual",
        "gdp_per_capita_constant_usd_annual",
    }
    assert codes <= set(INDICATORS_BY_CODE)
    for code in codes:
        definition = INDICATORS_BY_CODE[code]
        assert definition.category is IndicatorCategory.REAL_SECTOR
        assert definition.frequency is Frequency.ANNUAL
        assert definition.value_type is ValueType.LEVEL


def test_the_constant_price_indicators_name_their_base_year() -> None:
    """The base year lives in a CEPAL footnote, so REIM puts it in the unit."""
    assert INDICATORS_BY_CODE["gdp_constant_usd_annual"].unit == "constant 2018 USD"
    assert (
        INDICATORS_BY_CODE["gdp_per_capita_constant_usd_annual"].unit
        == "constant 2018 USD per person"
    )
    assert INDICATORS_BY_CODE["gdp_current_usd_annual"].unit == "current USD"
    assert INDICATORS_BY_CODE["gdp_per_capita_current_usd_annual"].unit == "current USD per person"


def test_belize_is_active() -> None:
    """CEPALSTAT gives Belize its first data; the IMF dataflow held none."""
    assert COUNTRIES_BY_ISO3["BLZ"].is_active is True
    assert all(country.is_active for country in COUNTRIES)


def test_every_gdp_indicator_has_a_quality_rule() -> None:
    rules = load_quality_rules(REPO_ROOT / "sources" / "quality_rules.yml")
    for code in (
        "gdp_current_usd_annual",
        "gdp_constant_usd_annual",
        "gdp_per_capita_current_usd_annual",
        "gdp_per_capita_constant_usd_annual",
    ):
        rule = rules.for_indicator(code)
        assert rule.min_observations == 240
        assert rule.max_period_change_pct == 40
        assert rule.allow_negative is False
        assert rule.allow_zero is False
```

Add the imports these need at the top of the file:

```python
from reim.core.constants import Frequency, IndicatorCategory, ValueType
from reim.domain.countries.registry import COUNTRIES, COUNTRIES_BY_ISO3
from reim.domain.indicators.registry import INDICATORS_BY_CODE
from reim.domain.quality.rules import QualityRuleSet
```

`tests/conftest.py:146` already provides a session `quality_rules` fixture
holding the repository's real rules, so the last test takes it as an argument
rather than loading the file again:

```python
def test_every_gdp_indicator_has_a_quality_rule(quality_rules: QualityRuleSet) -> None:
    for code in (
        "gdp_current_usd_annual",
        "gdp_constant_usd_annual",
        "gdp_per_capita_current_usd_annual",
        "gdp_per_capita_constant_usd_annual",
    ):
        rule = quality_rules.for_indicator(code)
        assert rule is not quality_rules.defaults, f"{code} fell through to the defaults"
        assert rule.min_observations == 240
        assert rule.max_period_change_pct == 40
        assert rule.allow_negative is False
        assert rule.allow_zero is False
```

Use this version and drop the `load_quality_rules` one written above. The
`is not quality_rules.defaults` assertion matters: `for_indicator` falls back
to the defaults for an unknown code rather than raising, so a typo in the YAML
key would otherwise pass silently.

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog.py -k "gdp or belize" -v`
Expected: FAIL — `KeyError` on the indicator codes, and `assert False is True` for Belize.

- [ ] **Step 3: Register the four indicators**

In `reim/domain/indicators/registry.py`, add a module-level reference next to
the existing `_SIECA_REPORT` constant:

```python
#: CEPAL publishes no separate methodology page per indicator; the dashboard
#: for the indicator is the closest stable reference, and it carries the
#: definition, the unit and the source note the API also returns.
_CEPALSTAT_DASHBOARD = "https://statistics.cepal.org/portal/cepalstat/dashboard.html"
```

Then append four definitions to the `INDICATORS` tuple, before its closing
parenthesis:

```python
(
    IndicatorDefinition(
        code="gdp_current_usd_annual",
        name="Gross domestic product (annual, current USD)",
        description=(
            "Total annual GDP at current prices in US dollars, from CEPAL's "
            "harmonised national-accounts compilation. These are CEPAL's own "
            "estimates based on national sources, not the figure each national "
            "statistics office publishes: the series is built for "
            "cross-country comparability and need not match any country's "
            "official GDP."
        ),
        category=IndicatorCategory.REAL_SECTOR,
        frequency=Frequency.ANNUAL,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=2203&lang=en",
    ),
)
(
    IndicatorDefinition(
        code="gdp_constant_usd_annual",
        name="Gross domestic product (annual, constant 2018 USD)",
        description=(
            "Total annual GDP in volume terms, valued at 2018 prices and "
            "converted with CEPAL's base-year reference exchange rate, so "
            "movements reflect output rather than prices or the exchange rate. "
            "CEPAL's own estimates; see gdp_current_usd_annual."
        ),
        category=IndicatorCategory.REAL_SECTOR,
        frequency=Frequency.ANNUAL,
        unit="constant 2018 USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=2204&lang=en",
    ),
)
(
    IndicatorDefinition(
        code="gdp_per_capita_current_usd_annual",
        name="GDP per inhabitant (annual, current USD)",
        description=(
            "Total annual GDP at current prices divided by total population. "
            "The population is CELADE's official estimate and projection, "
            "harmonised across countries, not each country's own census "
            "figure. REIM stores no population series, so this cannot be "
            "derived from the GDP totals it holds."
        ),
        category=IndicatorCategory.REAL_SECTOR,
        frequency=Frequency.ANNUAL,
        unit="current USD per person",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=2205&lang=en",
    ),
)
(
    IndicatorDefinition(
        code="gdp_per_capita_constant_usd_annual",
        name="GDP per inhabitant (annual, constant 2018 USD)",
        description=(
            "Total annual GDP at 2018 prices divided by CELADE's population "
            "estimate; see gdp_per_capita_current_usd_annual."
        ),
        category=IndicatorCategory.REAL_SECTOR,
        frequency=Frequency.ANNUAL,
        unit="constant 2018 USD per person",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=2206&lang=en",
    ),
)
```

- [ ] **Step 4: Activate Belize**

In `reim/domain/countries/registry.py`, replace lines 91-93:

```text
        # Belize reports nothing to the IMF's IMTS dataflow at any
        # frequency, so REIM holds no data for it yet. See docs/sources.md.
        is_active=False,
```

with:

```text
        # Belize still reports nothing to the IMF's IMTS dataflow at any
        # frequency, so REIM holds no trade data for it. CEPALSTAT publishes
        # its national accounts in full — 1990 onwards, no gaps — which is
        # where Belize's data comes from. See docs/sources.md.
        is_active=True,
```

Then update the module docstring at lines 1-6, which currently states that six
countries are active because REIM holds IMF trade data for each:

```text
"""Canonical country definitions for the Central American region.

All seven countries are active. Six carry IMF merchandise-trade data; Belize
carries none, because it reports nothing to that dataflow, and is active on
the strength of CEPALSTAT's national accounts instead. Enabling a country is
a data change, not a code change.
"""
```

- [ ] **Step 5: Add the quality rules**

Append to the `indicators:` block of `sources/quality_rules.yml`:

```yaml
  # Gross domestic product ------------------------------------------------
  # CEPALSTAT returns each indicator's whole matrix on every run: 7 countries
  # x 36 years = 252 cells per indicator. 240 leaves room for a year of
  # genuine gap while still catching a run truncated to a handful of rows,
  # which would otherwise pass every other check here.
  #
  # The change ceiling is the tripwire for a scale mistake. The worst real
  # year-on-year move in these four series is 23.0% (Guatemala, 1991); a
  # forgotten or doubled 10^6 would show up as a jump of eight figures.
  gdp_current_usd_annual: &gdp_total
    min_value: 0
    max_value: null
    allow_negative: false
    allow_zero: false
    max_period_change_pct: 40
    monotonic_increasing: false
    # The newest period ends 2025-12-31, 230 days before this was written.
    # 600 tolerates CEPAL's annual publication cycle and still reports a
    # source that has frozen.
    freshness_max_age_days: 600
    min_observations: 240

  gdp_constant_usd_annual: *gdp_total

  # Same shape and same thresholds; the smallest real per-capita figure is
  # 704.39 USD, so the floor of zero is as far from the data as it is for the
  # totals.
  gdp_per_capita_current_usd_annual: &gdp_per_capita
    min_value: 0
    max_value: null
    allow_negative: false
    allow_zero: false
    max_period_change_pct: 40
    monotonic_increasing: false
    freshness_max_age_days: 600
    min_observations: 240

  gdp_per_capita_constant_usd_annual: *gdp_per_capita
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog.py -v`
Expected: PASS, including the four new tests.

Then run the whole unit suite, because activating Belize changes a value other
tests may assert:

Run: `.venv/bin/python -m pytest tests/ -m "not live and not integration" -q`
Expected: PASS. If a test asserts six active countries, update it to seven and
state why in the assertion message — do not weaken the assertion to a range.

- [ ] **Step 7: Run the four gates, each on its own line, and read every exit code**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy reim apps
.venv/bin/python -m pytest tests/ -m "not live and not integration"
```

- [ ] **Step 8: Commit**

```bash
git add reim/domain/indicators/registry.py reim/domain/countries/registry.py \
        sources/quality_rules.yml tests/unit/test_catalog.py
git commit -m "feat(cepalstat): register four GDP indicators and activate Belize

REIM has held no GDP from any source. These four are CEPAL's harmonised
national-accounts estimates, and their descriptions say so: they are built
for cross-country comparability and need not match any country's official
figure.

Belize becomes active. It reports nothing to the IMF's IMTS dataflow, which
is why it was registered inactive, but CEPALSTAT publishes its national
accounts complete from 1990.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Record the four responses

**Files:**
- Create: `tests/fixtures/cepalstat_gdp_2203.json.gz`, `..._2204.json.gz`, `..._2205.json.gz`, `..._2206.json.gz`
- Modify: `tests/conftest.py`, `tests/fixtures/README.md`

**Interfaces:**
- Produces: pytest fixtures `cepalstat_gdp_2203_json`, `cepalstat_gdp_2204_json`, `cepalstat_gdp_2205_json`, `cepalstat_gdp_2206_json`, each a `str` of the decompressed response body.

- [ ] **Step 1: Record them**

Fetch all four in one pass so their `credits[0]` dates agree, and gzip them:

```bash
cd tests/fixtures
for id in 2203 2204 2205 2206; do
  curl -s --fail --max-time 90 \
    "https://api-cepalstat.cepal.org/cepalstat/api/v1/indicator/${id}/data?lang=en" \
    -o "cepalstat_gdp_${id}.json"
  gzip -9 "cepalstat_gdp_${id}.json"
done
ls -l cepalstat_gdp_*.json.gz
```

Expected: four files, roughly 24–26 KB each.

Record them **complete**, with all 33 countries and the 3 aggregates. Do not
trim them to the seven: the full response is the only thing that proves the
filter works, and a pre-trimmed fixture would pass a connector that filters
nothing.

- [ ] **Step 2: Verify what was recorded**

```bash
cd tests/fixtures
python3 - <<'PY'
import gzip, json
from decimal import Decimal
CA = {"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"}
for i in (2203, 2204, 2205, 2206):
    d = json.loads(gzip.decompress(open(f"cepalstat_gdp_{i}.json.gz", "rb").read()),
                   parse_float=Decimal)
    b = d["body"]
    assert d["header"]["success"] is True, i
    years = next(x for x in b["dimensions"] if x["id"] == 29117)
    labels = {m["id"]: m["name"] for m in years["members"]}
    cells = {(r["iso3"], labels[r["dim_29117"]]) for r in b["data"] if r.get("iso3") in CA}
    print(i, "rows", len(b["data"]), "CA cells", len(cells),
          "unit", repr(b["metadata"]["unit"]), "footnotes", b["footnotes"])
    assert len(cells) == 252, (i, len(cells))
PY
```

Expected: four lines, each reporting `CA cells 252`, and no assertion error.

- [ ] **Step 3: Add the conftest fixtures**

Append to `tests/conftest.py`, next to the other gzipped recordings:

```python
@pytest.fixture(scope="session")
def cepalstat_gdp_2203_json() -> str:
    """CEPALSTAT indicator 2203, total GDP at current prices (stored gzipped)."""
    return gzip.decompress((FIXTURES / "cepalstat_gdp_2203.json.gz").read_bytes()).decode("utf-8")


@pytest.fixture(scope="session")
def cepalstat_gdp_2204_json() -> str:
    """CEPALSTAT indicator 2204, total GDP at constant 2018 prices (gzipped)."""
    return gzip.decompress((FIXTURES / "cepalstat_gdp_2204.json.gz").read_bytes()).decode("utf-8")


@pytest.fixture(scope="session")
def cepalstat_gdp_2205_json() -> str:
    """CEPALSTAT indicator 2205, GDP per inhabitant at current prices (gzipped)."""
    return gzip.decompress((FIXTURES / "cepalstat_gdp_2205.json.gz").read_bytes()).decode("utf-8")


@pytest.fixture(scope="session")
def cepalstat_gdp_2206_json() -> str:
    """CEPALSTAT indicator 2206, GDP per inhabitant at 2018 prices (gzipped)."""
    return gzip.decompress((FIXTURES / "cepalstat_gdp_2206.json.gz").read_bytes()).decode("utf-8")
```

- [ ] **Step 4: Document their provenance**

Add four rows to the "Recorded from live official sources" table in
`tests/fixtures/README.md`:

```markdown
| `cepalstat_gdp_2203.json.gz` | `GET https://api-cepalstat.cepal.org/cepalstat/api/v1/indicator/2203/data?lang=en`, byte-for-byte, gzipped only to keep the repo small (163 KB → 23 KB). Tests decompress it before parsing. The **complete** response — all 33 countries and the 3 regional aggregates — because that is what proves the connector's filter to the seven Central American countries works at all. | 2026-08-18 |
| `cepalstat_gdp_2204.json.gz` | Same endpoint, indicator `2204` — total GDP at constant 2018 prices. Recorded so the implied-population identity is checked against two published series rather than one computed one. | 2026-08-18 |
| `cepalstat_gdp_2205.json.gz` | Same endpoint, indicator `2205` — GDP per inhabitant at current prices. | 2026-08-18 |
| `cepalstat_gdp_2206.json.gz` | Same endpoint, indicator `2206` — GDP per inhabitant at constant 2018 prices. | 2026-08-18 |
```

Then add a paragraph under that table:

```markdown
The CEPALSTAT API needs no User-Agent override and no TLS accommodation; these
four were recorded with REIM's own identifier. `body.credits[0].description` is
CEPAL's own fetch date and differs between recordings — nothing asserts it, and
`raw_metadata` stores only the citation elements that follow it.
```

- [ ] **Step 5: Write a test that the fixtures are complete**

Create `tests/unit/test_cepalstat_connector.py` with only the fixture tests for
now — the connector arrives in Task 3:

```python
"""Unit tests for the CEPALSTAT annual GDP connector.

Every payload replayed here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

import json
from decimal import Decimal

#: What the recorded responses hold, measured on 2026-08-18.
YEARS_DIMENSION = 29117
COUNTRY_DIMENSION = 208
CENTRAL_AMERICA = frozenset({"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"})
CELLS_PER_INDICATOR = 252


def cells_of(payload: str) -> dict[tuple[str, str], Decimal]:
    """Flatten one response into ``(iso3, year label) -> value`` for the seven."""
    body = json.loads(payload, parse_float=Decimal)["body"]
    years = next(d for d in body["dimensions"] if d["id"] == YEARS_DIMENSION)
    labels = {member["id"]: member["name"] for member in years["members"]}
    return {
        (row["iso3"], labels[row[f"dim_{YEARS_DIMENSION}"]]): Decimal(str(row["value"]))
        for row in body["data"]
        if row.get("iso3") in CENTRAL_AMERICA
    }


def test_each_fixture_covers_the_seven_countries_completely(
    cepalstat_gdp_2203_json: str,
    cepalstat_gdp_2204_json: str,
    cepalstat_gdp_2205_json: str,
    cepalstat_gdp_2206_json: str,
) -> None:
    """252 cells, 36 years each, no holes. A re-recording with gaps fails here."""
    for payload in (
        cepalstat_gdp_2203_json,
        cepalstat_gdp_2204_json,
        cepalstat_gdp_2205_json,
        cepalstat_gdp_2206_json,
    ):
        cells = cells_of(payload)
        assert len(cells) == CELLS_PER_INDICATOR
        assert {iso3 for iso3, _ in cells} == CENTRAL_AMERICA
        for iso3 in CENTRAL_AMERICA:
            assert sum(1 for c, _ in cells if c == iso3) == 36


def test_the_fixtures_hold_the_other_countries_and_the_aggregates(
    cepalstat_gdp_2203_json: str,
) -> None:
    """Not trimmed to seven: the filter has to have something to filter."""
    body = json.loads(cepalstat_gdp_2203_json)["body"]
    countries = next(d for d in body["dimensions"] if d["id"] == COUNTRY_DIMENSION)
    included = [m["name"] for m in countries["members"] if m["in"] == 1]

    assert "Mexico" in included
    assert "Brazil" in included
    assert "Latin America" in included
    assert any(row.get("iso3") is None for row in body["data"])


def test_the_fixtures_keep_their_exact_published_digits(
    cepalstat_gdp_2203_json: str, cepalstat_gdp_2206_json: str
) -> None:
    """parse_float=Decimal, not float, all the way through."""
    assert cells_of(cepalstat_gdp_2203_json)[("NIC", "2024")] == Decimal("19696.31184918235")
    assert cells_of(cepalstat_gdp_2206_json)[("NIC", "2024")] == Decimal("2142.334639853647")
    assert cells_of(cepalstat_gdp_2203_json)[("BLZ", "1990")] == Decimal("546.75091228848")


def test_the_constant_price_fixtures_carry_the_base_year_footnote(
    cepalstat_gdp_2204_json: str, cepalstat_gdp_2206_json: str, cepalstat_gdp_2203_json: str
) -> None:
    """The base year is in a footnote, not the unit. That is why it is checked."""
    for payload in (cepalstat_gdp_2204_json, cepalstat_gdp_2206_json):
        footnotes = json.loads(payload)["body"]["footnotes"]
        assert [f["description"] for f in footnotes] == ["At prices 2018"]

    assert json.loads(cepalstat_gdp_2203_json)["body"]["footnotes"] == []
```

- [ ] **Step 6: Run them**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_connector.py -v`
Expected: PASS, four tests.

- [ ] **Step 7: Run the four gates, each on its own line, and read every exit code**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy reim apps
.venv/bin/python -m pytest tests/ -m "not live and not integration"
```

- [ ] **Step 8: Commit**

```bash
git add tests/fixtures/cepalstat_gdp_220*.json.gz tests/conftest.py \
        tests/fixtures/README.md tests/unit/test_cepalstat_connector.py
git commit -m "test(cepalstat): record the four responses a run makes

Recorded complete, with all 33 countries and the 3 regional aggregates
inside. Trimming them to the seven Central American countries would have
made the fixtures smaller and the tests worthless: a pre-filtered recording
passes a connector that filters nothing.

100 KB for the four gzipped, comparable to the Banguat recording.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: The catalog entry, the connector, and `transform`

**Files:**
- Create: `reim/ingestion/connectors/regional/cepalstat_gdp.py`
- Modify: `sources/catalog.yml` (add the entry **disabled**; Task 6 enables it), `reim/ingestion/connectors/regional/__init__.py`
- Test: `tests/unit/test_cepalstat_connector.py`

**Interfaces:**
- Consumes: the indicator codes from Task 1; the fixtures from Task 2.
- Produces: `CepalstatGdpConnector`, `SERIES: tuple[SeriesSpec, ...]`, `SeriesSpec` (a frozen dataclass with fields `cepal_id: int`, `indicator_code: str`, `unit: str`, `scale: Decimal`), `CENTRAL_AMERICA: frozenset[str]`, `YEARS_DIMENSION: int = 29117`, `MILLIONS = Decimal("1000000")`.

- [ ] **Step 1: Add the catalog entry, disabled**

Append to `sources/catalog.yml`:

```yaml
  # ------------------------------------------------------------------------
  # Regional — Comisión Económica para América Latina y el Caribe
  #
  # REIM's first GDP data and Belize's first data of any kind. One request
  # returns an indicator's whole matrix: every country, every year.
  #
  # The licence is the hard part and it is stated, not hidden: CEPAL's terms
  # expressly forbid redistribution and derivative works, which is stricter
  # than the IMF's terms or SIECA's absence of any grant. REIM ingests, carries
  # CEPAL's required citation on every observation, and documents the
  # exception. See docs/sources.md.
  #
  # These figures are CEPAL's own harmonised estimates, not the numbers each
  # national statistics office publishes.
  # ------------------------------------------------------------------------
  - key: cepalstat_gdp_annual
    name: Central American gross domestic product (annual)
    description: >-
      Annual GDP for the seven Central American countries from CEPALSTAT:
      totals at current and constant 2018 prices in US dollars, and the same
      pair per inhabitant, covering 1990 onwards. CEPAL's own harmonised
      estimates, built for cross-country comparability rather than to match
      each country's official national accounts.
    organization: CEPAL
    category: real_sector
    access_type: http_api
    frequency: annual
    format: json
    base_url: https://api-cepalstat.cepal.org/cepalstat/api/v1
    documentation_url: https://statistics.cepal.org/portal/cepalstat/
    connector: reim.ingestion.connectors.regional.cepalstat_gdp
    indicators:
      - gdp_current_usd_annual
      - gdp_constant_usd_annual
      - gdp_per_capita_current_usd_annual
      - gdp_per_capita_constant_usd_annual
    license: cepal_terms_of_use
    official: true
    enabled: false
    disabled_reason: >-
      Connector under construction; enabled once it has been run end to end
      against a real database.
```

- [ ] **Step 2: Write the failing transform tests**

Append to `tests/unit/test_cepalstat_connector.py`:

```python
OBSERVATIONS = 1008


def build_connector() -> CepalstatGdpConnector:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    return CepalstatGdpConnector(catalog.get("cepalstat_gdp_annual"))


def build_raw(payloads: dict[int, str]) -> RawDataset:
    return RawDataset(
        source_key="cepalstat_gdp_annual",
        retrieved_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
        source_url="https://api-cepalstat.cepal.org/cepalstat/api/v1",
        payload=payloads,
        content_type="application/json",
        http_status=200,
        metadata={"indicator_ids": sorted(payloads)},
    )


@pytest.fixture
def raw(
    cepalstat_gdp_2203_json: str,
    cepalstat_gdp_2204_json: str,
    cepalstat_gdp_2205_json: str,
    cepalstat_gdp_2206_json: str,
) -> RawDataset:
    return build_raw(
        {
            2203: cepalstat_gdp_2203_json,
            2204: cepalstat_gdp_2204_json,
            2205: cepalstat_gdp_2205_json,
            2206: cepalstat_gdp_2206_json,
        }
    )


def test_transform_produces_every_cell(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)

    assert len(observations) == OBSERVATIONS
    per_indicator = Counter(obs.indicator_code for obs in observations)
    assert set(per_indicator) == {
        "gdp_current_usd_annual",
        "gdp_constant_usd_annual",
        "gdp_per_capita_current_usd_annual",
        "gdp_per_capita_constant_usd_annual",
    }
    assert set(per_indicator.values()) == {CELLS_PER_INDICATOR}


def test_only_the_seven_countries_survive(raw: RawDataset) -> None:
    """26 other countries and 3 aggregates are in the payload and must not land."""
    observations = build_connector().transform(raw)

    assert {obs.country_iso3 for obs in observations} == CENTRAL_AMERICA


def test_belize_gets_its_first_data(raw: RawDataset) -> None:
    belize = [obs for obs in build_connector().transform(raw) if obs.country_iso3 == "BLZ"]

    assert len(belize) == 144
    assert {obs.period.label for obs in belize} == {str(y) for y in range(1990, 2026)}


def test_the_totals_are_scaled_and_the_per_capita_series_are_not(raw: RawDataset) -> None:
    """Nicaragua 2024, verified by hand against the source."""
    by_key = {
        (obs.indicator_code, obs.country_iso3, obs.period.label): obs
        for obs in build_connector().transform(raw)
    }

    total = by_key[("gdp_current_usd_annual", "NIC", "2024")]
    assert total.value_numeric == Decimal("19696311849.18235")
    assert total.unit == "current USD"
    assert total.currency_code == "USD"

    per_capita = by_key[("gdp_per_capita_current_usd_annual", "NIC", "2024")]
    assert per_capita.value_numeric == Decimal("2757.621539962527")
    assert per_capita.unit == "current USD per person"


def test_the_published_figure_is_kept_alongside(raw: RawDataset) -> None:
    by_key = {
        (obs.indicator_code, obs.country_iso3, obs.period.label): obs
        for obs in build_connector().transform(raw)
    }
    metadata = by_key[("gdp_constant_usd_annual", "NIC", "2024")].raw_metadata

    assert metadata["cepalstat_indicator_id"] == 2204
    assert metadata["cepalstat_published_value"] == "15301.62516515467"
    assert metadata["cepalstat_published_unit"] == "Millions of dollars"
    assert metadata["cepalstat_scale_applied"] == "1e6"
    assert metadata["cepalstat_source"] == "Own estimates based on national sources"
    assert metadata["cepalstat_footnotes"] == ["At prices 2018"]


def test_the_fetch_date_is_not_stored(raw: RawDataset) -> None:
    """credits[0] is CEPAL's own fetch date and changes between runs."""
    metadata = build_connector().transform(raw)[0].raw_metadata

    assert metadata["cepalstat_credits"] == [
        "CEPALSTAT",
        "Economic Commission for Latin America and the Caribbean – ECLAC",
        "United Nations",
    ]


def test_periods_are_annual_and_span_the_calendar_year(raw: RawDataset) -> None:
    observation = next(
        obs for obs in build_connector().transform(raw) if obs.period.label == "1990"
    )

    assert observation.period.frequency is Frequency.ANNUAL
    assert observation.period.start == date(1990, 1, 1)
    assert observation.period.end == date(1990, 12, 31)


def test_source_record_ids_are_unique_and_readable(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)
    ids = [obs.source_record_id for obs in observations]

    assert len(set(ids)) == OBSERVATIONS
    assert "cepalstat:2203:NIC:2024" in ids


def test_a_missing_years_dimension_raises(raw: RawDataset) -> None:
    broken = json.loads(raw.payload[2203])
    broken["body"]["dimensions"] = [
        d for d in broken["body"]["dimensions"] if d["id"] != YEARS_DIMENSION
    ]
    payloads = dict(raw.payload) | {2203: json.dumps(broken)}

    with pytest.raises(TransformationError, match="years dimension"):
        build_connector().transform(build_raw(payloads))


def test_an_unmapped_year_member_raises(raw: RawDataset) -> None:
    """A year id with no member is a contract change, not a row to skip."""
    broken = json.loads(raw.payload[2203])
    broken["body"]["data"][0][f"dim_{YEARS_DIMENSION}"] = 999999
    payloads = dict(raw.payload) | {2203: json.dumps(broken)}

    with pytest.raises(TransformationError, match="unknown year member"):
        build_connector().transform(build_raw(payloads))
```

Extend the imports at the top of the test file:

```python
from collections import Counter
from datetime import UTC, date, datetime

import pytest

from reim.core.constants import Frequency
from reim.core.exceptions import TransformationError
from reim.domain.pipelines.models import RawDataset
from reim.domain.sources.catalog import load_catalog
from reim.ingestion.connectors.regional.cepalstat_gdp import (
    CENTRAL_AMERICA,
    CepalstatGdpConnector,
)
from tests.conftest import REPO_ROOT
```

Delete the local `CENTRAL_AMERICA` constant added in Task 2 — it now comes from
the connector, so the tests and the code cannot drift apart.

- [ ] **Step 3: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_connector.py -v`
Expected: FAIL at collection — `ModuleNotFoundError: reim.ingestion.connectors.regional.cepalstat_gdp`.

- [ ] **Step 4: Write the connector module**

Create `reim/ingestion/connectors/regional/cepalstat_gdp.py`:

```python
"""Central America — annual GDP published by CEPAL through CEPALSTAT.

``api-cepalstat.cepal.org`` serves an undocumented REST API. There is no
published documentation and no interactive schema: the base URL and the route
names were recovered from the portal's own JavaScript —
``statistics.cepal.org/portal/databank/config.js`` declares ``API_BASE_URL``
and ``ENDPOINT_THEMATIC_TREE``, and ``.../cepalstat/dash/scripts/config.js``
declares the per-indicator data, dimensions, sources and notes routes. That
search is recorded here so nobody repeats it.

Four properties of the source shape this connector:

1. **One request returns an indicator's whole matrix** — 33 countries and 3
   regional aggregates by 36 years, no pagination and no window to compute. A
   rebuild is therefore complete by default, as with Banguat and SIECA.
2. **Dimensions are addressed by numeric id, never by name.** Row keys embed
   the id (``dim_208``, ``dim_29117``) and the names are language-dependent:
   ``Years__ESTANDAR`` in English is ``Años__ESTANDAR`` in Spanish.
3. **The envelope carries its own status, and it can disagree with the HTTP
   code.** An unknown indicator id answers ``500`` with ``success: false``, not
   ``404``, so ``extract`` reads ``header.success`` rather than trusting the
   status line alone.
4. **The constant-price base year lives in a footnote, not the unit.** 2204 and
   2206 declare ``Millions of dollars`` and ``Dollars per inhabitant``; only
   ``footnotes`` names 2018. A rebasing would change every value while the unit
   stood still, which is why ``validate`` checks the footnote.

CEPAL's English translation of indicator 2204 spells "dolllars" with three
l's. REIM stores its own names, so it does not propagate; it is noted here so
it does not read as a transcription error.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar

from reim.core.constants import CheckSeverity, CheckType, Frequency
from reim.core.exceptions import ExtractionError, TransformationError
from reim.domain.observations.periods import parse_period
from reim.domain.pipelines.models import (
    NormalizedObservation,
    QualityResult,
    RawDataset,
)
from reim.ingestion.base import BaseConnector
from reim.ingestion.http import ensure_ok, fetch, http_client

#: Dimension ids, identical across all four indicators. Addressed by id
#: because the row keys embed it and the names change with ``lang``.
COUNTRY_DIMENSION = 208
YEARS_DIMENSION = 29117

#: Figures for the totals are published in millions of USD and stored in whole
#: USD, matching the IMF and SIECA series so ``/compare`` can align them.
MILLIONS = Decimal("1000000")

#: The seven countries REIM covers. Everything else in the response — 26 other
#: countries and 3 regional aggregates, the latter arriving with ``iso3: null``
#: — falls out of this membership test. REIM has no code for a region.
CENTRAL_AMERICA = frozenset({"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"})


@dataclass(frozen=True, slots=True)
class SeriesSpec:
    """One CEPAL indicator id and how REIM stores it."""

    cepal_id: int
    indicator_code: str
    unit: str
    scale: Decimal


#: The four series this connector ingests. CEPAL also publishes the growth
#: rate (id 2207); it is deliberately absent because it reproduces exactly
#: from 2204 — verified to the last digit over 36 years — and REIM stores
#: levels rather than what derives from them.
SERIES: tuple[SeriesSpec, ...] = (
    SeriesSpec(2203, "gdp_current_usd_annual", "current USD", MILLIONS),
    SeriesSpec(2204, "gdp_constant_usd_annual", "constant 2018 USD", MILLIONS),
    SeriesSpec(
        2205,
        "gdp_per_capita_current_usd_annual",
        "current USD per person",
        Decimal(1),
    ),
    SeriesSpec(
        2206,
        "gdp_per_capita_constant_usd_annual",
        "constant 2018 USD per person",
        Decimal(1),
    ),
)

SERIES_BY_ID: dict[int, SeriesSpec] = {spec.cepal_id: spec for spec in SERIES}

#: The base year the two constant-price series are expressed in. A CEPAL
#: rebasing changes every constant value without touching the published unit,
#: so this is asserted rather than assumed.
CONSTANT_PRICE_BASE_YEAR = "2018"

#: Relative tolerance for the implied-population identity. The worst real
#: disagreement measured across all 252 cells is 8.1e-16; this sits six orders
#: of magnitude above it, so the check cannot fire on arithmetic noise.
POPULATION_TOLERANCE = Decimal("1e-9")


class CepalstatGdpConnector(BaseConnector):
    """Four annual GDP series for the seven Central American countries."""

    connector_key = "cepalstat_gdp_annual"
    version = "1.0.0"
    expected_frequency = Frequency.ANNUAL
    currency_code: ClassVar[str] = "USD"

    async def extract(self) -> RawDataset:
        """Fetch one payload per indicator. Four requests, whole history each.

        Raises:
            ExtractionError: The API was unreachable, answered with something
                other than JSON, reported ``success: false`` in its envelope,
                or returned an empty data array.
        """
        base = str(self.source.base_url).rstrip("/")
        retrieved_at = datetime.now(UTC)
        payload: dict[int, str] = {}
        status: int | None = None
        content_type: str | None = None

        async with http_client() as client:
            for spec in SERIES:
                url = f"{base}/indicator/{spec.cepal_id}/data"
                response = await fetch(client, url, params={"lang": "en"})
                ensure_ok(response, expected_content_type="json")
                self._ensure_envelope_ok(response.text, spec.cepal_id, url)
                payload[spec.cepal_id] = response.text
                status = response.status_code
                content_type = response.headers.get("content-type")

        return RawDataset(
            source_key=self.source.key,
            retrieved_at=retrieved_at,
            source_url=base,
            payload=payload,
            content_type=content_type,
            http_status=status,
            metadata={
                "indicator_ids": [spec.cepal_id for spec in SERIES],
                "lang": "en",
            },
        )

    def _ensure_envelope_ok(self, text: str, cepal_id: int, url: str) -> None:
        """Read CEPAL's own status, which can disagree with the HTTP code.

        An unknown indicator id answers ``500`` with ``success: false``, so the
        envelope is the authority on whether a response is usable.

        Raises:
            ExtractionError: The envelope reports failure or carries no rows.
        """
        try:
            document = json.loads(text)
            header = document["header"]
            rows = document["body"]["data"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            msg = f"CEPALSTAT returned an unreadable envelope for indicator {cepal_id}: {exc}"
            raise ExtractionError(msg, source_key=self.source.key, url=url) from exc

        if not header.get("success", False):
            detail = str(header.get("message") or "no message").strip()
            code = header.get("code", "?")
            msg = f"CEPALSTAT reported failure {code} for indicator {cepal_id}: {detail}"
            raise ExtractionError(msg, source_key=self.source.key, url=url)

        if not rows:
            msg = f"CEPALSTAT returned no rows for indicator {cepal_id}"
            raise ExtractionError(msg, source_key=self.source.key, url=url)

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Normalize the four payloads into one observation per country-year.

        Pure function of ``raw``.

        Raises:
            TransformationError: A payload is not the expected shape, its years
                dimension is missing, or a row names a year member that does
                not exist.
        """
        payload = raw.payload
        if not isinstance(payload, dict):
            msg = "CEPALSTAT payload must be a mapping of indicator id to response text"
            raise TransformationError(msg, source_key=self.source.key)

        observations: list[NormalizedObservation] = []
        for spec in SERIES:
            observations.extend(self._read_series(spec, str(payload[spec.cepal_id]), raw))
        observations.sort(key=lambda obs: (obs.indicator_code, obs.country_iso3, obs.period.start))
        return observations

    def _read_series(
        self, spec: SeriesSpec, text: str, raw: RawDataset
    ) -> list[NormalizedObservation]:
        """Turn one indicator's payload into its Central American observations."""
        body = self._decode(text, spec.cepal_id)["body"]
        years = self._years_of(body, spec.cepal_id)
        published_unit = str(body["metadata"]["unit"])
        sources = {source["id"]: source["description"] for source in body["sources"]}
        footnotes = {str(note["id"]): note["description"] for note in body["footnotes"]}
        credits = [entry["description"] for entry in body["credits"] if entry["id"] != 0]
        scale = "1e6" if spec.scale == MILLIONS else "1"

        observations: list[NormalizedObservation] = []
        for row in body["data"]:
            iso3 = row.get("iso3")
            if iso3 not in CENTRAL_AMERICA:
                continue
            year = self._year_of(row, years, spec.cepal_id)
            value = self._value_of(row, spec.cepal_id)
            note_ids = [part for part in str(row.get("notes_ids") or "").split(",") if part]
            observations.append(
                NormalizedObservation(
                    country_iso3=str(iso3),
                    indicator_code=spec.indicator_code,
                    source_key=self.source.key,
                    period=parse_period(year, Frequency.ANNUAL),
                    unit=spec.unit,
                    currency_code=self.currency_code,
                    value_numeric=value * spec.scale,
                    retrieved_at=raw.retrieved_at,
                    source_url=f"{raw.source_url}/indicator/{spec.cepal_id}/data",
                    source_record_id=f"cepalstat:{spec.cepal_id}:{iso3}:{year}",
                    raw_metadata={
                        "cepalstat_indicator_id": spec.cepal_id,
                        "cepalstat_published_value": format(value.normalize(), "f"),
                        "cepalstat_published_unit": published_unit,
                        "cepalstat_scale_applied": scale,
                        "cepalstat_source": sources.get(row.get("source_id"), ""),
                        "cepalstat_footnotes": [
                            footnotes[note] for note in note_ids if note in footnotes
                        ],
                        # credits[0] is CEPAL's own fetch date and changes
                        # between runs; only the citation is kept.
                        "cepalstat_credits": credits,
                        "contract_status": "verified",
                    },
                )
            )
        return observations

    def _decode(self, text: str, cepal_id: int) -> Any:
        """Decode JSON, keeping published decimals exact."""
        try:
            return json.loads(text, parse_float=Decimal)
        except json.JSONDecodeError as exc:
            msg = f"CEPALSTAT returned malformed JSON for indicator {cepal_id}: {exc}"
            raise TransformationError(msg, source_key=self.source.key) from exc

    def _years_of(self, body: Any, cepal_id: int) -> dict[int, str]:
        """Build the ``member id -> year label`` map from the response itself.

        Never computed from the id arithmetically: today ``year = id - 27170``
        holds for every member, but CEPAL documents no such contract.

        Raises:
            TransformationError: The years dimension is absent.
        """
        for dimension in body.get("dimensions", []):
            if dimension.get("id") == YEARS_DIMENSION:
                return {member["id"]: str(member["name"]) for member in dimension["members"]}
        msg = f"CEPALSTAT returned no years dimension for indicator {cepal_id}"
        raise TransformationError(msg, source_key=self.source.key)

    def _year_of(self, row: Any, years: dict[int, str], cepal_id: int) -> str:
        """Resolve a row's year label.

        Raises:
            TransformationError: The row names a year member that does not exist.
        """
        member = row.get(f"dim_{YEARS_DIMENSION}")
        label = years.get(member)
        if label is None:
            msg = f"CEPALSTAT row for indicator {cepal_id} names an unknown year member {member!r}"
            raise TransformationError(msg, source_key=self.source.key)
        return label

    def _value_of(self, row: Any, cepal_id: int) -> Decimal:
        """Read a published figure exactly.

        Raises:
            TransformationError: The value is absent or not a number.
        """
        try:
            return Decimal(str(row["value"]))
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            msg = f"CEPALSTAT returned an unreadable value for indicator {cepal_id}: {exc}"
            raise TransformationError(msg, source_key=self.source.key) from exc

    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert CEPALSTAT-specific expectations. Filled in by Task 4."""
        return []
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_connector.py -v`
Expected: PASS, all transform tests.

- [ ] **Step 6: Run the four gates, each on its own line, and read every exit code**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy reim apps
.venv/bin/python -m pytest tests/ -m "not live and not integration"
```

- [ ] **Step 7: Commit**

```bash
git add sources/catalog.yml reim/ingestion/connectors/regional/cepalstat_gdp.py \
        tests/unit/test_cepalstat_connector.py
git commit -m "feat(cepalstat): parse four GDP series for seven countries

transform keeps only rows whose iso3 is one of the seven; the 26 other
countries and the 3 regional aggregates fall out of the same membership
test, the aggregates because they arrive with a null iso3 and REIM has no
code for a region.

Dimensions are read by numeric id rather than name: the row keys embed the
id, and the names change with the lang parameter. The year map is built from
the response's own members on every run, never from the id arithmetically —
the offset holds today but CEPAL documents no such contract.

credits[0] is CEPAL's own fetch date and changes between runs, so only the
citation elements are stored.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: `validate` — the four checks

**Files:**
- Modify: `reim/ingestion/connectors/regional/cepalstat_gdp.py`
- Test: `tests/unit/test_cepalstat_connector.py`

**Interfaces:**
- Consumes: `CepalstatGdpConnector.transform` from Task 3.
- Produces: `validate` returning four `QualityResult`s named `cepalstat_seven_countries_present`, `cepalstat_population_identity`, `cepalstat_constant_price_base_year`, `cepalstat_annual_continuity`.

The base-year check needs the footnotes, which live in `raw_metadata`, not in
the payload `validate` receives. That is why Task 3 stored
`cepalstat_footnotes` on every observation: the check reads it from there.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cepalstat_connector.py`:

```python
def results_of(observations: list[NormalizedObservation]) -> dict[str, QualityResult]:
    return {result.check_name: result for result in build_connector().validate(observations)}


def test_all_four_checks_pass_on_the_real_recordings(raw: RawDataset) -> None:
    results = results_of(build_connector().transform(raw))

    assert set(results) == {
        "cepalstat_seven_countries_present",
        "cepalstat_population_identity",
        "cepalstat_constant_price_base_year",
        "cepalstat_annual_continuity",
    }
    assert all(result.status is CheckStatus.PASSED for result in results.values())


def test_a_missing_country_fails_critically(raw: RawDataset) -> None:
    """Belize vanishing is the failure this connector exists not to commit."""
    observations = [obs for obs in build_connector().transform(raw) if obs.country_iso3 != "BLZ"]

    result = results_of(observations)["cepalstat_seven_countries_present"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.CRITICAL
    assert "BLZ" in result.message


def test_the_population_identity_holds_on_the_real_data(raw: RawDataset) -> None:
    result = results_of(build_connector().transform(raw))["cepalstat_population_identity"]

    assert result.status is CheckStatus.PASSED
    assert "252" in result.message


def test_a_broken_population_identity_fails(raw: RawDataset) -> None:
    """Move one per-capita figure by 1%: far above noise, far below a typo."""
    observations = build_connector().transform(raw)
    for index, obs in enumerate(observations):
        if (
            obs.indicator_code == "gdp_per_capita_constant_usd_annual"
            and obs.country_iso3 == "NIC"
            and obs.period.label == "2024"
        ):
            assert obs.value_numeric is not None
            observations[index] = replace(obs, value_numeric=obs.value_numeric * Decimal("1.01"))

    result = results_of(observations)["cepalstat_population_identity"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.ERROR
    assert "NIC 2024" in result.message


def test_a_rebasing_fails_the_base_year_check(raw: RawDataset) -> None:
    """A CEPAL rebasing changes every constant value and no unit string."""
    observations = build_connector().transform(raw)
    for index, obs in enumerate(observations):
        if obs.indicator_code == "gdp_constant_usd_annual":
            observations[index] = replace(
                obs, raw_metadata={**obs.raw_metadata, "cepalstat_footnotes": ["At prices 2020"]}
            )

    result = results_of(observations)["cepalstat_constant_price_base_year"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.ERROR
    assert "2018" in result.message


def test_a_missing_year_is_reported_as_a_warning(raw: RawDataset) -> None:
    observations = [obs for obs in build_connector().transform(raw) if obs.period.label != "2008"]

    result = results_of(observations)["cepalstat_annual_continuity"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.WARNING
    assert "2008" in result.message


def test_every_check_is_dataset_level(raw: RawDataset) -> None:
    """No check names a row: a broken identity has no single guilty cell."""
    results = build_connector().validate(build_connector().transform(raw))

    assert all(result.observation_index is None for result in results)
```

Extend the test imports:

```python
from dataclasses import replace

from reim.core.constants import CheckSeverity, CheckStatus, Frequency
from reim.domain.pipelines.models import NormalizedObservation, QualityResult, RawDataset
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_connector.py -k "check or identity or year or countr" -v`
Expected: FAIL — `validate` returns `[]`, so `set(results)` is empty and the
`KeyError`s follow.

- [ ] **Step 3: Implement the four checks**

Replace the placeholder `validate` in
`reim/ingestion/connectors/regional/cepalstat_gdp.py` with the following
methods. **Fence this as ```text if you copy it into a plan** — see the global
constraints.

```text
    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert CEPALSTAT-specific expectations beyond the standard battery."""
        by_key: dict[str, dict[tuple[str, str], Decimal]] = {
            spec.indicator_code: {
                (obs.country_iso3, obs.period.label): obs.value_numeric
                for obs in observations
                if obs.indicator_code == spec.indicator_code and obs.value_numeric is not None
            }
            for spec in SERIES
        }

        return [
            self._check_seven_countries(observations),
            self._check_population_identity(by_key),
            self._check_base_year(observations),
            self._check_annual_continuity(observations),
        ]

    def _check_seven_countries(
        self, observations: list[NormalizedObservation]
    ) -> QualityResult:
        """All seven must appear. Belize's absence is the failure that matters."""
        seen = {obs.country_iso3 for obs in observations}
        missing = sorted(CENTRAL_AMERICA - seen)

        if not missing:
            return QualityResult.passed(
                "cepalstat_seven_countries_present",
                CheckType.COMPLETENESS,
                f"All {len(CENTRAL_AMERICA)} countries returned figures",
                expected_value=str(len(CENTRAL_AMERICA)),
                actual_value=str(len(seen & CENTRAL_AMERICA)),
            )
        return QualityResult.failure(
            "cepalstat_seven_countries_present",
            CheckType.COMPLETENESS,
            CheckSeverity.CRITICAL,
            f"{len(missing)} country/countries returned nothing: {', '.join(missing)}",
            expected_value=str(len(CENTRAL_AMERICA)),
            actual_value=str(len(seen & CENTRAL_AMERICA)),
        )

    def _check_population_identity(
        self, by_key: dict[str, dict[tuple[str, str], Decimal]]
    ) -> QualityResult:
        """Total over per capita must recover the same population both ways.

        The current-price pair and the constant-price pair each imply a
        population. CEPAL divides by one CELADE series, so the two must agree;
        a disagreement means two of the four series stopped describing the
        same country-year.
        """
        current_total = by_key["gdp_current_usd_annual"]
        constant_total = by_key["gdp_constant_usd_annual"]
        current_pc = by_key["gdp_per_capita_current_usd_annual"]
        constant_pc = by_key["gdp_per_capita_constant_usd_annual"]

        shared = sorted(
            set(current_total) & set(constant_total) & set(current_pc) & set(constant_pc)
        )
        broken = []
        for key in shared:
            if not current_pc[key] or not constant_pc[key]:
                broken.append(key)
                continue
            from_current = current_total[key] / current_pc[key]
            from_constant = constant_total[key] / constant_pc[key]
            if abs(from_current - from_constant) / from_current > POPULATION_TOLERANCE:
                broken.append(key)

        if not broken:
            return QualityResult.passed(
                "cepalstat_population_identity",
                CheckType.CONSISTENCY,
                f"The implied population agrees between the current and constant "
                f"pairs on all {len(shared)} cell(s), within {POPULATION_TOLERANCE}",
                expected_value="0 beyond tolerance",
                actual_value="0",
            )

        shown = ", ".join(f"{country} {year}" for country, year in broken[:5])
        suffix = f" (+{len(broken) - 5} more)" if len(broken) > 5 else ""
        return QualityResult.failure(
            "cepalstat_population_identity",
            CheckType.CONSISTENCY,
            CheckSeverity.ERROR,
            f"{len(broken)} cell(s) imply two different populations: {shown}{suffix}",
            expected_value="0 beyond tolerance",
            actual_value=str(len(broken)),
        )

    def _check_base_year(self, observations: list[NormalizedObservation]) -> QualityResult:
        """The constant-price series must still be expressed at 2018 prices.

        CEPAL states the base year only in a footnote; the published unit is
        just "Millions of dollars". A rebasing would therefore change every
        constant value while REIM went on storing it as constant 2018 USD.
        """
        constant_codes = {
            "gdp_constant_usd_annual",
            "gdp_per_capita_constant_usd_annual",
        }
        footnotes = {
            note
            for obs in observations
            if obs.indicator_code in constant_codes
            for note in obs.raw_metadata.get("cepalstat_footnotes", [])
        }
        wrong = sorted(note for note in footnotes if CONSTANT_PRICE_BASE_YEAR not in note)

        if footnotes and not wrong:
            return QualityResult.passed(
                "cepalstat_constant_price_base_year",
                CheckType.VALIDITY,
                f"The constant-price series still state base year "
                f"{CONSTANT_PRICE_BASE_YEAR}: {', '.join(sorted(footnotes))}",
                expected_value=CONSTANT_PRICE_BASE_YEAR,
                actual_value=CONSTANT_PRICE_BASE_YEAR,
            )

        detail = ", ".join(wrong) if wrong else "no base-year footnote at all"
        return QualityResult.failure(
            "cepalstat_constant_price_base_year",
            CheckType.VALIDITY,
            CheckSeverity.ERROR,
            f"The constant-price series no longer state base year "
            f"{CONSTANT_PRICE_BASE_YEAR}: {detail}. A rebasing changes every "
            f"constant value and leaves the published unit untouched.",
            expected_value=CONSTANT_PRICE_BASE_YEAR,
            actual_value=detail,
        )

    def _check_annual_continuity(
        self, observations: list[NormalizedObservation]
    ) -> QualityResult:
        """CEPAL publishes every year; a hole is worth a human look."""
        years = {int(obs.period.label) for obs in observations}
        if len(years) < 2:
            return QualityResult.passed(
                "cepalstat_annual_continuity",
                CheckType.COMPLETENESS,
                "Too few years ingested to assess continuity",
                actual_value=str(len(years)),
            )

        first, last = min(years), max(years)
        expected = last - first + 1
        missing = [str(year) for year in range(first, last + 1) if year not in years]

        if not missing:
            return QualityResult.passed(
                "cepalstat_annual_continuity",
                CheckType.COMPLETENESS,
                f"{expected} consecutive years from {first} to {last}",
                expected_value=str(expected),
                actual_value=str(len(years)),
            )

        shown = ", ".join(missing[:5])
        suffix = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
        return QualityResult.failure(
            "cepalstat_annual_continuity",
            CheckType.COMPLETENESS,
            CheckSeverity.WARNING,
            f"{len(missing)} year(s) missing: {shown}{suffix}",
            expected_value=str(expected),
            actual_value=str(len(years)),
        )
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_connector.py -v`
Expected: PASS, every test.

- [ ] **Step 5: Run the four gates, each on its own line, and read every exit code**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy reim apps
.venv/bin/python -m pytest tests/ -m "not live and not integration"
```

- [ ] **Step 6: Commit**

```bash
git add reim/ingestion/connectors/regional/cepalstat_gdp.py \
        tests/unit/test_cepalstat_connector.py
git commit -m "test(cepalstat): cover the four quality checks

The strongest of them is new to REIM: total over per capita recovers the
implied population, and the current-price and constant-price pairs must
agree. They do, to 8.1e-16 across all 252 cells. The check exists only
because one connector sees all four series.

The base-year check guards a quieter failure. CEPAL states 2018 only in a
footnote — the published unit is just 'Millions of dollars' — so a rebasing
would change every constant value while REIM went on labelling it constant
2018 USD.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: `extract`

**Files:**
- Modify: `tests/unit/test_cepalstat_connector.py`
- Test: same file

**Interfaces:**
- Consumes: `CepalstatGdpConnector.extract` written in Task 3.

`extract` was written in Task 3 so the module was complete and importable. This
task covers it, which is where its behaviour is actually pinned.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cepalstat_connector.py`:

```python
BASE_URL = "https://api-cepalstat.cepal.org/cepalstat/api/v1"


def data_url(cepal_id: int) -> str:
    return f"{BASE_URL}/indicator/{cepal_id}/data"


def json_response(text: str) -> httpx.Response:
    return httpx.Response(200, text=text, headers={"content-type": "application/json"})


@respx.mock
async def test_a_run_makes_one_request_per_indicator(
    cepalstat_gdp_2203_json: str,
    cepalstat_gdp_2204_json: str,
    cepalstat_gdp_2205_json: str,
    cepalstat_gdp_2206_json: str,
) -> None:
    routes = {
        2203: respx.get(data_url(2203)).mock(return_value=json_response(cepalstat_gdp_2203_json)),
        2204: respx.get(data_url(2204)).mock(return_value=json_response(cepalstat_gdp_2204_json)),
        2205: respx.get(data_url(2205)).mock(return_value=json_response(cepalstat_gdp_2205_json)),
        2206: respx.get(data_url(2206)).mock(return_value=json_response(cepalstat_gdp_2206_json)),
    }

    raw = await build_connector().extract()

    assert all(route.call_count == 1 for route in routes.values())
    assert set(raw.payload) == {2203, 2204, 2205, 2206}
    assert raw.payload[2203] == cepalstat_gdp_2203_json
    assert raw.metadata["lang"] == "en"


@respx.mock
async def test_the_language_is_requested_explicitly(cepalstat_gdp_2203_json: str) -> None:
    for cepal_id in (2203, 2204, 2205, 2206):
        respx.get(data_url(cepal_id)).mock(return_value=json_response(cepalstat_gdp_2203_json))

    await build_connector().extract()

    assert respx.calls[0].request.url.params["lang"] == "en"


@respx.mock
async def test_a_failing_envelope_raises_even_on_http_200(
    cepalstat_gdp_2203_json: str,
) -> None:
    """CEPAL answers an unknown id with 500 and success:false, never 404."""
    envelope = json.dumps(
        {
            "header": {"success": False, "code": 404, "message": "Not found"},
            "body": {"data": []},
        }
    )
    respx.get(data_url(2203)).mock(return_value=json_response(envelope))

    with pytest.raises(ExtractionError, match="reported failure 404"):
        await build_connector().extract()


@respx.mock
async def test_an_empty_data_array_raises(cepalstat_gdp_2203_json: str) -> None:
    """A run that returns nothing is a failure, not a quiet success."""
    body = json.loads(cepalstat_gdp_2203_json)
    body["body"]["data"] = []
    respx.get(data_url(2203)).mock(return_value=json_response(json.dumps(body)))

    with pytest.raises(ExtractionError, match="no rows"):
        await build_connector().extract()


@respx.mock
async def test_a_non_json_response_raises(cepalstat_gdp_2203_json: str) -> None:
    respx.get(data_url(2203)).mock(
        return_value=httpx.Response(200, text="<html>", headers={"content-type": "text/html"})
    )

    with pytest.raises(ExtractionError):
        await build_connector().extract()


@pytest.mark.live
async def test_the_real_api_still_answers_as_recorded() -> None:
    """Opt-in. Proves the contract, not the data: shape, not values."""
    raw = await build_connector().extract()
    observations = build_connector().transform(raw)

    assert len(observations) >= 1000
    assert {obs.country_iso3 for obs in observations} == CENTRAL_AMERICA
    assert all(
        result.status is CheckStatus.PASSED for result in build_connector().validate(observations)
    )
```

Extend the test imports:

```python
import httpx
import respx

from reim.core.exceptions import ExtractionError, TransformationError
```

- [ ] **Step 2: Run them**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_connector.py -m "not live" -v`
Expected: PASS.

These tests do not follow the write-red-first cycle the rest of the plan does,
and that is deliberate: `extract` had to exist in Task 3 for the module to
import at all, so there is no red state to observe here. They pin behaviour
rather than drive it. **If any of them fails, the failure is real — fix
`extract`, never the test.** In particular, do not relax the
`match="reported failure 404"` or `match="no rows"` patterns to make a test
pass; those two strings are the whole point of the envelope check.

- [ ] **Step 3: Run the live test once, deliberately**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_connector.py -m live -v`
Expected: PASS, four real requests to CEPAL. If it fails, the API changed
since 2026-08-18 — record what changed in `docs/sources.md` before adapting
the connector.

- [ ] **Step 4: Run the four gates, each on its own line, and read every exit code**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy reim apps
.venv/bin/python -m pytest tests/ -m "not live and not integration"
```

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_cepalstat_connector.py
git commit -m "test(cepalstat): cover the four-request extract

Pins the failure that would otherwise be silent: CEPAL answers an unknown
indicator id with HTTP 500 and success:false, so the envelope rather than the
status line decides whether a response is usable. An empty data array raises
too — a run that returns nothing is a failure, not a quiet success.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Enable, run for real, and correct the record

**Files:**
- Modify: `sources/catalog.yml` (remove `enabled: false` and `disabled_reason`)
- Modify: `docs/sources.md`, `docs/implementation-plan.md`, `ROADMAP.md`, `README.md`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Enable the source**

In `sources/catalog.yml`, replace

```text
    enabled: false
    disabled_reason: >-
      Connector under construction; enabled once it has been run end to end
      against a real database.
```

with `    enabled: true`.

- [ ] **Step 2: Validate the catalog**

Run: `.venv/bin/python -m reim.cli catalog validate`
Expected: `17 source(s), 17 enabled`, `28 indicator rule(s)`, all 17 connectors
importing cleanly.

- [ ] **Step 3: Run it end to end against a real database**

```bash
make db-up CONTAINER_ENGINE=podman
export REIM_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim
.venv/bin/python -m reim.cli db seed
.venv/bin/python -m reim.cli pipeline run cepalstat_gdp_annual
```

Expected: `success extracted=1008 inserted=1008 ... rejected=0`.

- [ ] **Step 4: Prove idempotency**

Run the pipeline a second time.
Expected: `inserted=0 unchanged=1008 rejected=0`. If `unchanged` is not 1,008,
something in `raw_metadata` or the value is unstable between runs — check that
`credits[0]` did not creep back in.

- [ ] **Step 5: Check what landed**

```bash
podman exec reim-test-postgres psql -U reim -d reim -c "
select i.code, count(*), min(o.period_start), max(o.period_start)
from observations o join indicators i on i.id = o.indicator_id
where i.code like 'gdp%' group by i.code order by i.code;"
```

Expected: four rows of 252, spanning `1990-01-01` … `2025-01-01`.

Then confirm Belize actually landed:

```bash
podman exec reim-test-postgres psql -U reim -d reim -c "
select c.iso3, count(*) from observations o
join countries c on c.id = o.country_id
group by c.iso3 order by c.iso3;"
```

Expected: `BLZ` present with 144.

- [ ] **Step 6: Record the source**

Add a `### CEPAL — annual gross domestic product` section to the "Enabled" part
of `docs/sources.md`, following the shape of the SIECA section above it. It
must cover, at minimum:

- The endpoint, the four indicator ids, the coverage, and the volume.
- **That the earlier 404 finding was wrong**, and why: every route is scoped to
  an indicator id, and a bare collection path returns 404 by design.
- **That there is no API documentation**, and that the routes were recovered
  from `statistics.cepal.org/portal/databank/config.js` and
  `.../cepalstat/dash/scripts/config.js`.
- **That indicator ids cannot be listed from an area**; `/thematic-tree?theme_id=6`
  is the closest thing, it returns 330 leaves, and 45 of them are `dummy`,
  `CLONE` or `TEST` artefacts.
- **The licence, quoted verbatim**, with a `⚠️ Not open` row in the summary
  table matching how the IMF section is marked.
- **That these are CEPAL's own harmonised estimates**, not each national
  statistics office's published figure.
- **What Belize gained**, and that it still has no IMF trade data.
- The reachable-but-not-ingested neighbours, so the next person does not
  rediscover them: monetary aggregates 862/868/869 (three dimensions, and
  Nicaragua **is** covered, which the roadmap currently gives up on) and public
  debt 1239/1240 (four dimensions).

- [ ] **Step 7: Correct the two documents that record the 404**

In `docs/implementation-plan.md:388`, replace the CEPALSTAT row's blocker text
`open; a probe of its API returned 404` with a statement that the API is live
and ingested, pointing at `docs/sources.md`.

In `docs/sources.md`, update the "Registered but not yet implemented" table:
CEPAL moves out of it, since it is now implemented.

Leave `docs/superpowers/specs/2026-08-08-regional-imf-trade-design.md:20`
untouched — a spec records what was believed when it was written, and the new
spec already states the correction.

- [ ] **Step 8: Rewrite the ROADMAP line the catalog contradicts**

In `ROADMAP.md`, mark the CEPALSTAT bullet of v0.3.0 done, with the real
numbers.

Then rewrite `ROADMAP.md:172-173`. It currently reads:

```text
- **Scraping paywalled or licence-restricted data.** Official and openly
  licensed only.
```

That line was already false before this increment — the IMF and SIECA entries
both shipped under non-open terms. Replace it with what the project actually
does:

```text
- **Defeating an active access control.** A JavaScript bot-manager challenge,
  a login, a paywall: REIM does not pass any of them. `www.bcn.gob.ni` sits
  behind a Radware bot manager and stays unread. Satisfying a static header
  check is a different thing, and `docs/sources.md` states which sources need
  one and why.
- **Hiding a licence.** REIM prefers openly licensed sources and says so, but
  three of its sources are not openly licensed — the IMF, SIECA and CEPAL.
  Each carries its real terms in the catalog, each has a section in
  `docs/sources.md` quoting them, and each ships the attribution its publisher
  asks for. The rule is that the terms are recorded, not that they are always
  permissive.
```

Also update the v0.2.0 note on monetary aggregates: it says Nicaragua's are
available only from SECMCA behind a credentialed account. CEPALSTAT indicator
862 covers Nicaragua from 1990 to 2024. Say so, and say it is not yet ingested.

- [ ] **Step 9: Update the README**

Add CEPAL to the source table and the attribution section, with its terms
stated as the IMF's are. Update any count of countries, sources or
observations the README carries — Belize's activation makes it seven countries.

- [ ] **Step 10: Run the four gates plus integration, each on its own line**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy reim apps
.venv/bin/python -m pytest tests/ -m "not live and not integration"
REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim \
  .venv/bin/python -m pytest tests/integration
```

- [ ] **Step 11: Commit**

```bash
git add sources/catalog.yml docs/sources.md docs/implementation-plan.md \
        ROADMAP.md README.md
git commit -m "feat: CEPALSTAT annual GDP — REIM's first GDP, and Belize's first data

1,008 observations from four requests: four GDP series for seven countries,
1990-2025. Belize is active for the first time; it reports nothing to the
IMF dataflow REIM's trade data comes from, and CEPALSTAT publishes its
national accounts complete.

Corrects a finding this repository recorded twice: CEPALSTAT's API does not
return 404. Every route is scoped to an indicator id, and the earlier probe
used collection paths that do not exist.

Rewrites the 'official and openly licensed only' line in the roadmap. It was
already contradicted by the IMF and SIECA entries that shipped after it, and
CEPAL's terms — which expressly forbid redistribution — make the gap
impossible to leave standing. The rule the project actually follows is that
licences are recorded honestly and active access controls are never
defeated.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage.** Every numbered section of
`docs/superpowers/specs/2026-08-18-cepalstat-gdp-design.md` maps to a task:
§1 and the 404 correction → Task 6 steps 6-7; §2 the source → Task 3 step 4;
§3 the licence → Task 3 step 1 and Task 6 steps 6, 8, 9; §4 the measured
findings → the facts table and Tasks 2 and 4; §5 decisions C1-C9 → C1/C2 the
single-connector shape in Task 3, C3 the filter in Task 3 step 2, C4 Belize in
Task 1 step 4, C5 the absent 2207 documented in `SERIES`, C6 the scale in
Task 3, C7 `lang=en` in Task 5 step 1, C8 the unprefixed codes in Task 1, C9
the estimate wording in Task 1 step 3 and Task 6 step 6; §6.1-6.5 components →
Tasks 1, 3, 4; §7 testing → Tasks 2, 3, 4, 5; §8 the expected result → Task 6
step 3; §9 out of scope → Task 6 step 6's list of neighbours.

**Placeholder scan.** No `TBD`, no "add error handling", no "similar to Task
N". Task 6 steps 6, 8 and 9 describe prose to write rather than code to paste,
and each enumerates exactly what the prose must contain — that is a
documentation step, not a deferred decision.

**Type consistency.** `SeriesSpec` fields (`cepal_id`, `indicator_code`,
`unit`, `scale`) are used identically in Tasks 3 and 4. `CENTRAL_AMERICA` is
defined once in the connector and imported by the tests; Task 3 step 2 says
explicitly to delete the duplicate the tests carried in Task 2. The check names
in Task 4's tests match the strings the implementation passes to
`QualityResult`. `YEARS_DIMENSION` is `29117` in both the connector and the
tests.

**One thing this plan changes from the spec.** The spec said `raw_metadata`
carries "the `credits` block". Recording the fixtures showed `credits[0]` is
CEPAL's own fetch date, which moves between runs. The plan stores credits 1-3
only. This does not affect idempotency — `compute_content_hash` does not hash
`raw_metadata` — but storing a per-run timestamp REIM already records as
`retrieved_at` would churn every stored payload for nothing.
