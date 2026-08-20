# CEPALSTAT monetary aggregates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest CEPALSTAT's monthly M1, M2 and M3 for the seven Central American countries — 5,383 observations — closing the v0.2.0 roadmap line that named SECMCA and a credentialed account as the only route to Nicaragua's monetary aggregates.

**Architecture:** One connector, one catalog entry, three indicators. `extract` makes six requests: three for data in `lang=en` and three for `/dimensions` in `lang=es`, the latter solely to learn which period member id is which month. `transform` keeps the twelve monthly members, discards the annual and quarterly restatements, filters to the seven countries, resolves each country's currency from the country registry and scales by `10^6`. The shared CEPALSTAT protocol is extracted into a base class **last**, once both connectors exist.

**Tech Stack:** Python 3.12, httpx, respx, pytest, SQLAlchemy, Pydantic, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-19-cepalstat-monetary-design.md`

## Global Constraints

- **Run every gate over the whole repository**, not just the files you touched: `.venv/bin/ruff format --check .`, `.venv/bin/ruff check .`, `.venv/bin/mypy reim apps`, `.venv/bin/python -m pytest tests/ -m "not live and not integration"`. Read every exit code.
- **`ruff format` rewrites Python code blocks inside Markdown.** A block containing only methods gets dedented to module level and the file changes under you. When a plan or doc quotes method-level Python, fence it as ` ```text `, not ` ```python `.
- **No pip in the venv.** Use `.venv/bin/<tool>` directly.
- **Podman, not Docker:** `make db-up CONTAINER_ENGINE=podman`. Note that `make db-down` runs `podman rm -f` and destroys the container's data.
- **TDD throughout.** Write the failing test, watch it fail for the right reason, then implement.
- **Never widen a test to make it pass.** If an assertion fails, the connector is wrong until proven otherwise.
- Values are parsed with `parse_float=Decimal`. Never `float`.
- The seven countries are `NIC, GTM, SLV, HND, CRI, PAN, BLZ`.

## Measured facts the tests assert

All measured 2026-08-19 against complete responses. These are the numbers the tests pin; if a re-recording changes them, the recording changed, not the test.

| Fact | Value |
|---|---|
| Monthly observations | **5,383** = 2,026 (M1) + 1,611 (M2) + 1,746 (M3) |
| Gaps inside any country's span | **0**, in all 21 country-indicator series |
| `Anual` == `Diciembre` | 453 cells, **0** exceptions |
| `Trimestre N` == its closing month | 1,800 cells, **0** exceptions |
| M1 ≤ M2 | 1,611 shared cells, 116 rounding violations, worst 0.014040 % |
| M2 ≤ M3 | 1,331 shared cells, 113 rounding violations, worst 0.005047 % |
| M1 ≤ M3 | 1,746 shared cells, **0** violations |
| Worst month-on-month move | 45.93 % (PAN 2006-11, M1) |
| Belize | present in M1 and M3 from 1990-01; **absent from M2** |
| El Salvador | present in M1 and M2; **absent from M3** |
| Honduras | M1/M2 end 2023-10; **M3 ends 2023-03** |
| Period dimension | id `3981`, 17 members, ids **not** in calendar order |

## File structure

| File | Responsibility |
|---|---|
| `reim/domain/indicators/registry.py` | Three new `IndicatorDefinition`s (modify) |
| `sources/catalog.yml` | One new source entry (modify) |
| `sources/quality_rules.yml` | Three new indicator rules (modify) |
| `tests/fixtures/cepalstat_monetary_{862,868,869}.json.gz` | Recorded data responses (create) |
| `tests/fixtures/cepalstat_dimensions_{862,868,869}.json.gz` | Recorded Spanish dimension tables (create) |
| `tests/conftest.py` | Six session fixtures (modify) |
| `reim/ingestion/connectors/regional/cepalstat_monetary.py` | The connector (create) |
| `tests/unit/test_cepalstat_monetary_connector.py` | Its tests (create) |
| `reim/ingestion/connectors/regional/cepalstat.py` | Shared protocol base, Task 7 (create) |

---

### Task 1: Three indicators, the catalog entry, and their quality rules

**Files:**
- Modify: `reim/domain/indicators/registry.py`
- Modify: `sources/catalog.yml`
- Modify: `sources/quality_rules.yml`
- Test: `tests/unit/test_catalog.py`, `tests/unit/test_quality.py`

**Interfaces:**
- Produces: indicator codes `money_m1_monthly`, `money_m2_monthly`, `money_m3_monthly`; catalog key `cepalstat_monetary_monthly`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_catalog.py`:

```python
def test_the_three_monetary_indicators_are_registered() -> None:
    """The first use of the monetary category, declared since v0.1.0."""
    codes = {i.code: i for i in INDICATORS}

    for code in ("money_m1_monthly", "money_m2_monthly", "money_m3_monthly"):
        assert codes[code].category is IndicatorCategory.MONETARY
        assert codes[code].frequency is Frequency.MONTHLY
        assert codes[code].value_type is ValueType.LEVEL


def test_the_monetary_indicators_carry_no_country_prefix() -> None:
    """Decision C8: regional sources drop the prefix, as SIECA and GDP did."""
    codes = {i.code for i in INDICATORS}

    assert {"money_m1_monthly", "money_m2_monthly", "money_m3_monthly"} <= codes
    assert not any(code.startswith(("ni_money", "gt_money")) for code in codes)


def test_the_monetary_indicator_unit_names_no_single_currency() -> None:
    """Seven countries, six currencies: the code cannot claim one of them."""
    codes = {i.code: i for i in INDICATORS}

    for code in ("money_m1_monthly", "money_m2_monthly", "money_m3_monthly"):
        assert codes[code].unit == "units of local currency"


def test_the_monetary_source_is_registered_and_disabled() -> None:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    entry = catalog.get("cepalstat_monetary_monthly")

    assert entry.organization == "CEPAL"
    assert entry.frequency is Frequency.MONTHLY
    assert entry.license == "cepal_terms_of_use"
    assert not entry.enabled
    assert set(entry.indicators) == {
        "money_m1_monthly",
        "money_m2_monthly",
        "money_m3_monthly",
    }
```

Append to `tests/unit/test_quality.py`:

```python
def test_monetary_indicators_have_their_own_rules() -> None:
    rules = load_quality_rules(REPO_ROOT / "sources" / "quality_rules.yml")

    for code, floor in (
        ("money_m1_monthly", 1950),
        ("money_m2_monthly", 1550),
        ("money_m3_monthly", 1680),
    ):
        rule = rules.for_indicator(code)
        assert rule.min_observations == floor
        assert rule.max_period_change_pct == Decimal("60")
        assert rule.freshness_max_age_days == 900


def test_the_monetary_change_ceiling_clears_the_worst_real_move() -> None:
    """Panama's M1 moved 45.93% in November 2006; the source published it."""
    rules = load_quality_rules(REPO_ROOT / "sources" / "quality_rules.yml")

    assert rules.for_indicator("money_m1_monthly").max_period_change_pct > Decimal("45.93")


def test_monetary_aggregates_may_not_be_negative() -> None:
    """A money stock is a stock: negative is a broken feed, not a deficit."""
    rules = load_quality_rules(REPO_ROOT / "sources" / "quality_rules.yml")

    assert not rules.for_indicator("money_m1_monthly").allow_negative
```

Check the imports already present at the top of each test file and add only
what is missing — `INDICATORS`, `IndicatorCategory`, `ValueType`, `Frequency`,
`load_catalog`, `load_quality_rules`, `REPO_ROOT`, `Decimal`.

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog.py tests/unit/test_quality.py -k "monetary or money" -v`
Expected: FAIL — `KeyError: 'money_m1_monthly'` from the registry lookups and
`ConfigurationError`/lookup failure for the catalog key.

- [ ] **Step 3: Register the three indicators**

In `reim/domain/indicators/registry.py`, append inside the `INDICATORS` tuple,
after the four GDP definitions:

```text
    IndicatorDefinition(
        code="money_m1_monthly",
        name="Money (M1, end of period)",
        description=(
            "Narrow money at the close of each month: currency held by the "
            "public plus demand deposits, as compiled by CEPAL from central "
            "bank figures. Stored in whole units of each country's own "
            "currency, so values are not comparable across countries without "
            "a conversion REIM does not perform."
        ),
        category=IndicatorCategory.MONETARY,
        frequency=Frequency.MONTHLY,
        unit="units of local currency",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=862&lang=en",
    ),
    IndicatorDefinition(
        code="money_m2_monthly",
        name="Liquidity (M2, end of period)",
        description=(
            "M1 plus savings and time deposits in local currency, at the close "
            "of each month. CEPAL's own definition; see money_m1_monthly for "
            "the currency caveat. Belize is not covered by this series."
        ),
        category=IndicatorCategory.MONETARY,
        frequency=Frequency.MONTHLY,
        unit="units of local currency",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=868&lang=en",
    ),
    IndicatorDefinition(
        code="money_m3_monthly",
        name="Broad liquidity (M3, end of period)",
        description=(
            "M2 plus foreign-currency deposits, at the close of each month. "
            "CEPAL's own definition; see money_m1_monthly for the currency "
            "caveat. El Salvador is not covered by this series."
        ),
        category=IndicatorCategory.MONETARY,
        frequency=Frequency.MONTHLY,
        unit="units of local currency",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=869&lang=en",
    ),
```

- [ ] **Step 4: Add the catalog entry**

In `sources/catalog.yml`, after the `cepalstat_gdp_annual` entry:

```yaml
  - key: cepalstat_monetary_monthly
    name: Central American monetary aggregates (monthly)
    description: >-
      Monthly M1, M2 and M3 at the close of each month for the seven Central
      American countries, from CEPALSTAT. Published in millions of each
      country's own currency and stored in whole units of it, so the series
      are not comparable across countries without a conversion REIM does not
      perform. CEPAL's compilation from central bank figures.
    organization: CEPAL
    category: monetary
    access_type: http_api
    frequency: monthly
    format: json
    base_url: https://api-cepalstat.cepal.org/cepalstat/api/v1
    documentation_url: https://statistics.cepal.org/portal/cepalstat/
    connector: reim.ingestion.connectors.regional.cepalstat_monetary
    indicators:
      - money_m1_monthly
      - money_m2_monthly
      - money_m3_monthly
    license: cepal_terms_of_use
    official: true
    enabled: false
    disabled_reason: >-
      Connector under construction; enabled once it has been run end to end
      against a real database.
```

- [ ] **Step 5: Add the quality rules**

In `sources/quality_rules.yml`, after the GDP block:

```yaml
  # Monetary aggregates -----------------------------------------------------
  # CEPALSTAT returns each indicator's whole matrix on every run. The real
  # monthly counts on 2026-08-19 are 2,026 / 1,611 / 1,746; the floors below
  # sit just under them, leaving room for a month of genuine gap while still
  # catching a run truncated to a handful of rows.
  #
  # The 60% ceiling is the tripwire for a scale mistake. The worst real
  # month-on-month move across the three series is 45.93% (Panama, November
  # 2006, M1 moving 1,984.6 -> 2,896.2 -> 2,610.3), which the source
  # publishes. A forgotten or doubled 10^6 would show up as eight figures.
  #
  # freshness_max_age_days is deliberately a threshold Honduras fails. On
  # 2026-08-19 the freshest country was 718 days behind and Honduras was
  # 1,023 (M1, M2) and 1,237 (M3). At 900 Honduras warns on all three from
  # the first run and the other six pass. Setting it at 1,300 would turn
  # every light green, which is tuning a threshold until it stops speaking:
  # Honduras really is three and a half years behind. This is `warning`
  # severity, so nothing is blocked.
  money_m1_monthly: &monetary_aggregate
    min_value: 0
    max_value: null
    allow_negative: false
    allow_zero: false
    max_period_change_pct: 60
    monotonic_increasing: false
    freshness_max_age_days: 900
    min_observations: 1950

  money_m2_monthly:
    <<: *monetary_aggregate
    min_observations: 1550

  money_m3_monthly:
    <<: *monetary_aggregate
    min_observations: 1680
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog.py tests/unit/test_quality.py -v`
Expected: PASS.

Also run: `.venv/bin/python -m reim.cli catalog validate`
Expected: `18 source(s), 17 enabled` and `31 indicator rule(s)`. The connector
module does not exist yet, so the import check will report
`cepalstat_monetary_monthly` as failing to import — that is expected at this
task and resolved in Task 3. If it aborts the command rather than reporting,
skip this check until Task 3.

- [ ] **Step 7: Run the four gates, each on its own line, and read every exit code**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy reim apps
.venv/bin/python -m pytest tests/ -m "not live and not integration"
```

- [ ] **Step 8: Commit**

```bash
git add reim/domain/indicators/registry.py sources/catalog.yml \
        sources/quality_rules.yml tests/unit/test_catalog.py \
        tests/unit/test_quality.py
git commit -m "feat(cepalstat): register the three monetary aggregates

First use of the monetary category, declared in IndicatorCategory since
v0.1.0 and unused until now. The unit reads 'units of local currency'
because seven countries share six currencies and no code can claim one of
them; each observation carries the concrete pair.

The freshness threshold is deliberately one Honduras fails. It is three and
a half years behind on M3 and the check should say so.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Record the six responses

**Files:**
- Create: `tests/fixtures/cepalstat_monetary_862.json.gz`, `_868`, `_869`
- Create: `tests/fixtures/cepalstat_dimensions_862.json.gz`, `_868`, `_869`
- Modify: `tests/conftest.py`, `tests/fixtures/README.md`
- Test: `tests/unit/test_cepalstat_monetary_connector.py`

**Interfaces:**
- Produces: pytest fixtures `cepalstat_monetary_862_json`, `_868_`, `_869_`, and `cepalstat_dimensions_862_json`, `_868_`, `_869_`, each returning decompressed response text.

- [ ] **Step 1: Record**

Run this script. It writes six gzipped files and prints their sizes.

```python
import gzip
import httpx
from pathlib import Path

BASE = "https://api-cepalstat.cepal.org/cepalstat/api/v1"
OUT = Path("tests/fixtures")
UA = "REIM/0.1.0 (research; +https://github.com/RobBravo/reim)"

with httpx.Client(timeout=120.0, headers={"User-Agent": UA}) as client:
    for cepal_id in (862, 868, 869):
        data = client.get(f"{BASE}/indicator/{cepal_id}/data", params={"lang": "en"})
        data.raise_for_status()
        target = OUT / f"cepalstat_monetary_{cepal_id}.json.gz"
        target.write_bytes(gzip.compress(data.content, 9))
        print(
            f"{target.name}: {len(data.content) // 1024} KB -> {target.stat().st_size // 1024} KB"
        )

        dims = client.get(f"{BASE}/indicator/{cepal_id}/dimensions", params={"lang": "es"})
        dims.raise_for_status()
        target = OUT / f"cepalstat_dimensions_{cepal_id}.json.gz"
        target.write_bytes(gzip.compress(dims.content, 9))
        print(
            f"{target.name}: {len(dims.content) // 1024} KB -> {target.stat().st_size // 1024} KB"
        )
```

Expected: roughly 107, 85 and 105 KB for the data files and about 4 KB each
for the dimensions files — around 310 KB in total.

- [ ] **Step 2: Add the conftest fixtures**

In `tests/conftest.py`, after the four `cepalstat_gdp_*` fixtures:

```python
@pytest.fixture(scope="session")
def cepalstat_monetary_862_json() -> str:
    """CEPALSTAT indicator 862, money M1, monthly (stored gzipped)."""
    return gzip.decompress((FIXTURES / "cepalstat_monetary_862.json.gz").read_bytes()).decode(
        "utf-8"
    )


@pytest.fixture(scope="session")
def cepalstat_monetary_868_json() -> str:
    """CEPALSTAT indicator 868, liquidity M2, monthly (stored gzipped)."""
    return gzip.decompress((FIXTURES / "cepalstat_monetary_868.json.gz").read_bytes()).decode(
        "utf-8"
    )


@pytest.fixture(scope="session")
def cepalstat_monetary_869_json() -> str:
    """CEPALSTAT indicator 869, broad liquidity M3, monthly (stored gzipped)."""
    return gzip.decompress((FIXTURES / "cepalstat_monetary_869.json.gz").read_bytes()).decode(
        "utf-8"
    )


@pytest.fixture(scope="session")
def cepalstat_dimensions_862_json() -> str:
    """Indicator 862's dimensions in Spanish; the only place months are named."""
    return gzip.decompress((FIXTURES / "cepalstat_dimensions_862.json.gz").read_bytes()).decode(
        "utf-8"
    )


@pytest.fixture(scope="session")
def cepalstat_dimensions_868_json() -> str:
    """Indicator 868's dimensions in Spanish."""
    return gzip.decompress((FIXTURES / "cepalstat_dimensions_868.json.gz").read_bytes()).decode(
        "utf-8"
    )


@pytest.fixture(scope="session")
def cepalstat_dimensions_869_json() -> str:
    """Indicator 869's dimensions in Spanish."""
    return gzip.decompress((FIXTURES / "cepalstat_dimensions_869.json.gz").read_bytes()).decode(
        "utf-8"
    )
```

- [ ] **Step 3: Write the tests that pin what the recordings hold**

Create `tests/unit/test_cepalstat_monetary_connector.py`:

```python
"""Unit tests for the CEPALSTAT monthly monetary-aggregates connector.

Every payload replayed here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

PERIOD_DIMENSION = 3981
COUNTRY_DIMENSION = 208
YEARS_DIMENSION = 29117
CENTRAL_AMERICA = frozenset({"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"})

#: What the recordings hold, measured on 2026-08-19.
MONTHLY_CELLS = {862: 2026, 868: 1611, 869: 1746}
ABSENT = {862: set(), 868: {"BLZ"}, 869: {"SLV"}}

SPANISH_MONTHS = {
    "Enero": 1,
    "Febrero": 2,
    "Marzo": 3,
    "Abril": 4,
    "Mayo": 5,
    "Junio": 6,
    "Julio": 7,
    "Agosto": 8,
    "Septiembre": 9,
    "Octubre": 10,
    "Noviembre": 11,
    "Diciembre": 12,
}


def period_members(dimensions_text: str) -> dict[int, str]:
    body = json.loads(dimensions_text)["body"]
    dimension = next(d for d in body["dimensions"] if d["id"] == PERIOD_DIMENSION)
    return {member["id"]: member["name"] for member in dimension["members"]}


def monthly_cells(data_text: str, members: dict[int, str]) -> dict[tuple[str, int, int], Decimal]:
    """Flatten one response to ``(iso3, year, month) -> value`` for the seven."""
    body = json.loads(data_text, parse_float=Decimal)["body"]
    years = next(d for d in body["dimensions"] if d["id"] == YEARS_DIMENSION)
    labels = {member["id"]: member["name"] for member in years["members"]}
    cells = {}
    for row in body["data"]:
        if row.get("iso3") not in CENTRAL_AMERICA:
            continue
        name = members[row[f"dim_{PERIOD_DIMENSION}"]]
        if name not in SPANISH_MONTHS:
            continue
        key = (row["iso3"], int(labels[row[f"dim_{YEARS_DIMENSION}"]]), SPANISH_MONTHS[name])
        cells[key] = Decimal(str(row["value"]))
    return cells


def test_the_english_period_members_are_all_untranslated(
    cepalstat_monetary_862_json: str,
) -> None:
    """The whole reason a second request is made in Spanish."""
    body = json.loads(cepalstat_monetary_862_json)["body"]
    dimension = next(d for d in body["dimensions"] if d["id"] == PERIOD_DIMENSION)

    names = {member["name"] for member in dimension["members"]}

    assert names == {"descripcion_ingles"}
    assert len(dimension["members"]) == 17


def test_the_spanish_dimensions_name_every_month(
    cepalstat_dimensions_862_json: str,
) -> None:
    members = period_members(cepalstat_dimensions_862_json)

    assert len(members) == 17
    assert set(members.values()) == set(SPANISH_MONTHS) | {
        "Anual",
        "Trimestre 1",
        "Trimestre 2",
        "Trimestre 3",
        "Trimestre 4",
    }


def test_the_member_ids_are_not_in_calendar_order(
    cepalstat_dimensions_862_json: str,
) -> None:
    """Pinning or inferring the ids was never an option: 3993 is September."""
    members = period_members(cepalstat_dimensions_862_json)
    by_name = {name: member_id for member_id, name in members.items()}

    assert by_name["Septiembre"] < by_name["Julio"] < by_name["Agosto"]
    assert by_name["Diciembre"] < by_name["Octubre"] < by_name["Noviembre"]


@pytest.mark.parametrize("cepal_id", [862, 868, 869])
def test_each_recording_holds_its_measured_monthly_count(
    cepal_id: int, request: pytest.FixtureRequest
) -> None:
    data = request.getfixturevalue(f"cepalstat_monetary_{cepal_id}_json")
    members = period_members(request.getfixturevalue(f"cepalstat_dimensions_{cepal_id}_json"))

    cells = monthly_cells(data, members)

    assert len(cells) == MONTHLY_CELLS[cepal_id]
    assert {iso3 for iso3, _, _ in cells} == CENTRAL_AMERICA - ABSENT[cepal_id]


@pytest.mark.parametrize("cepal_id", [862, 868, 869])
def test_no_country_has_a_gap_inside_its_own_span(
    cepal_id: int, request: pytest.FixtureRequest
) -> None:
    """Zero gaps in all 21 country-indicator series, measured 2026-08-19."""
    data = request.getfixturevalue(f"cepalstat_monetary_{cepal_id}_json")
    members = period_members(request.getfixturevalue(f"cepalstat_dimensions_{cepal_id}_json"))
    cells = monthly_cells(data, members)

    for iso3 in sorted({country for country, _, _ in cells}):
        months = sorted((y, m) for country, y, m in cells if country == iso3)
        first, last = months[0], months[-1]
        span = (last[0] - first[0]) * 12 + (last[1] - first[1]) + 1
        assert len(months) == span, f"{iso3} has {span - len(months)} gap(s)"


@pytest.mark.parametrize("cepal_id", [862, 868, 869])
def test_the_annual_member_only_restates_december(
    cepal_id: int, request: pytest.FixtureRequest
) -> None:
    """453 cells, zero exceptions. This is why only the month is stored."""
    data = request.getfixturevalue(f"cepalstat_monetary_{cepal_id}_json")
    dims = request.getfixturevalue(f"cepalstat_dimensions_{cepal_id}_json")
    members = period_members(dims)
    body = json.loads(data, parse_float=Decimal)["body"]
    years = next(d for d in body["dimensions"] if d["id"] == YEARS_DIMENSION)
    labels = {member["id"]: member["name"] for member in years["members"]}

    by_kind: dict[tuple[str, str, str], Decimal] = {}
    for row in body["data"]:
        if row.get("iso3") not in CENTRAL_AMERICA:
            continue
        key = (
            row["iso3"],
            labels[row[f"dim_{YEARS_DIMENSION}"]],
            members[row[f"dim_{PERIOD_DIMENSION}"]],
        )
        by_kind[key] = Decimal(str(row["value"]))

    compared = 0
    for (iso3, year, kind), value in by_kind.items():
        if kind != "Anual":
            continue
        december = by_kind.get((iso3, year, "Diciembre"))
        assert december == value, f"{iso3} {year}: annual {value} != December {december}"
        compared += 1
    assert compared > 0
```

- [ ] **Step 4: Run them**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_monetary_connector.py -v`
Expected: PASS. These tests read the recordings directly and need no connector.
If the counts differ from `MONTHLY_CELLS`, the recording is newer than this
plan — record the new numbers here and in the spec rather than loosening the
assertions.

- [ ] **Step 5: Document the fixtures**

Add six rows to the table in `tests/fixtures/README.md`:

```text
| `cepalstat_monetary_862.json.gz` | `GET https://api-cepalstat.cepal.org/cepalstat/api/v1/indicator/862/data?lang=en`, byte-for-byte, gzipped only to keep the repo small (1.60 MB → 107 KB). Tests decompress it before parsing. The **complete** response — 145 countries and every period member — because that is what proves both the filter to the seven Central American countries and the discarding of the annual and quarterly members. | 2026-08-19 |
| `cepalstat_monetary_868.json.gz` | Same endpoint, indicator `868` — liquidity M2 (1.40 MB → 85 KB). Belize is absent from this series, which the expected-countries check encodes. | 2026-08-19 |
| `cepalstat_monetary_869.json.gz` | Same endpoint, indicator `869` — broad liquidity M3 (1.44 MB → 105 KB). El Salvador is absent from this series. | 2026-08-19 |
| `cepalstat_dimensions_862.json.gz` | `GET .../indicator/862/dimensions?lang=es`, byte-for-byte, gzipped (28 KB → 4 KB). Recorded in Spanish because `lang=en` returns all seventeen period members as the untranslated string `descripcion_ingles`; this is the only place a month can be told from a quarter. | 2026-08-19 |
| `cepalstat_dimensions_868.json.gz` | Same endpoint, indicator `868`. | 2026-08-19 |
| `cepalstat_dimensions_869.json.gz` | Same endpoint, indicator `869`. | 2026-08-19 |
```

- [ ] **Step 6: Run the four gates, each on its own line, and read every exit code**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy reim apps
.venv/bin/python -m pytest tests/ -m "not live and not integration"
```

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/cepalstat_monetary_*.json.gz \
        tests/fixtures/cepalstat_dimensions_*.json.gz \
        tests/fixtures/README.md tests/conftest.py \
        tests/unit/test_cepalstat_monetary_connector.py
git commit -m "test(cepalstat): record the six responses a monetary run makes

Three data responses in English and three dimension tables in Spanish. The
split is not a preference: in lang=en all seventeen members of the period
dimension come back as the untranslated string 'descripcion_ingles', so the
English response cannot tell a month from a quarter from the annual figure.
The ids cannot be pinned either — 3993 is September and 3994 is July.

The recordings are complete rather than trimmed, at 310 KB gzipped, because
the 145 countries they carry are what proves the filter works at all.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: The connector — `extract` and `transform`

**Files:**
- Create: `reim/ingestion/connectors/regional/cepalstat_monetary.py`
- Test: `tests/unit/test_cepalstat_monetary_connector.py`

**Interfaces:**
- Consumes: the catalog entry and indicator codes from Task 1; the fixtures from Task 2.
- Produces: `CepalstatMonetaryConnector` with `connector_key = "cepalstat_monetary_monthly"`, `extract() -> RawDataset`, `transform(raw) -> list[NormalizedObservation]`, and module constants `SERIES`, `CENTRAL_AMERICA`, `PERIOD_DIMENSION`, `MONTHS_BY_SPANISH_NAME`.
- `RawDataset.payload` is `{"data": {862: text, ...}, "dimensions": {862: text, ...}}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cepalstat_monetary_connector.py`:

```python
def build_connector() -> CepalstatMonetaryConnector:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    return CepalstatMonetaryConnector(catalog.get("cepalstat_monetary_monthly"))


def build_raw(data: dict[int, str], dimensions: dict[int, str]) -> RawDataset:
    return RawDataset(
        source_key="cepalstat_monetary_monthly",
        retrieved_at=datetime(2026, 8, 19, 12, 0, tzinfo=UTC),
        source_url="https://api-cepalstat.cepal.org/cepalstat/api/v1",
        payload={"data": data, "dimensions": dimensions},
        content_type="application/json",
        http_status=200,
    )


@pytest.fixture
def raw(
    cepalstat_monetary_862_json: str,
    cepalstat_monetary_868_json: str,
    cepalstat_monetary_869_json: str,
    cepalstat_dimensions_862_json: str,
    cepalstat_dimensions_868_json: str,
    cepalstat_dimensions_869_json: str,
) -> RawDataset:
    return build_raw(
        {
            862: cepalstat_monetary_862_json,
            868: cepalstat_monetary_868_json,
            869: cepalstat_monetary_869_json,
        },
        {
            862: cepalstat_dimensions_862_json,
            868: cepalstat_dimensions_868_json,
            869: cepalstat_dimensions_869_json,
        },
    )


def test_transform_produces_every_monthly_cell(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)

    assert len(observations) == 5383
    counts = Counter(obs.indicator_code for obs in observations)
    assert counts["money_m1_monthly"] == 2026
    assert counts["money_m2_monthly"] == 1611
    assert counts["money_m3_monthly"] == 1746


def test_the_annual_and_quarterly_members_are_discarded(raw: RawDataset) -> None:
    """Exact restatements of a month; storing them would triple-count."""
    observations = build_connector().transform(raw)

    assert all(obs.period.frequency is Frequency.MONTHLY for obs in observations)
    assert all(obs.period.days <= 31 for obs in observations)


def test_only_the_seven_countries_survive(raw: RawDataset) -> None:
    """145 countries and the regional aggregates come back; seven are kept."""
    observations = build_connector().transform(raw)

    assert {obs.country_iso3 for obs in observations} == CENTRAL_AMERICA


def test_belize_is_absent_from_m2_and_el_salvador_from_m3(raw: RawDataset) -> None:
    """The source's own asymmetry, carried through rather than papered over."""
    by_indicator: dict[str, set[str]] = {}
    for obs in build_connector().transform(raw):
        by_indicator.setdefault(obs.indicator_code, set()).add(obs.country_iso3)

    assert by_indicator["money_m1_monthly"] == CENTRAL_AMERICA
    assert by_indicator["money_m2_monthly"] == CENTRAL_AMERICA - {"BLZ"}
    assert by_indicator["money_m3_monthly"] == CENTRAL_AMERICA - {"SLV"}


def test_each_country_carries_its_own_currency(raw: RawDataset) -> None:
    """REIM's first indicator whose unit changes with the country."""
    expected = {
        "NIC": "NIO",
        "GTM": "GTQ",
        "SLV": "USD",
        "HND": "HNL",
        "CRI": "CRC",
        "PAN": "PAB",
        "BLZ": "BZD",
    }

    for obs in build_connector().transform(raw):
        assert obs.currency_code == expected[obs.country_iso3]
        assert obs.unit == expected[obs.country_iso3]


def test_the_published_millions_are_scaled_to_whole_units(raw: RawDataset) -> None:
    """Nicaragua's M1 for December 2023: 73,214.4 millions of cordobas."""
    observations = build_connector().transform(raw)
    cell = next(
        obs
        for obs in observations
        if obs.indicator_code == "money_m1_monthly"
        and obs.country_iso3 == "NIC"
        and obs.period.label == "2023-12"
    )

    assert cell.value_numeric == Decimal("73214400000")
    assert cell.raw_metadata["cepalstat_published_value"] == "73214.4"
    assert cell.raw_metadata["cepalstat_scale_applied"] == "1e6"


def test_periods_are_calendar_months(raw: RawDataset) -> None:
    cell = next(
        obs
        for obs in build_connector().transform(raw)
        if obs.country_iso3 == "NIC" and obs.period.label == "2023-12"
    )

    assert cell.period.start == date(2023, 12, 1)
    assert cell.period.end == date(2023, 12, 31)


def test_source_record_ids_are_unique_and_readable(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)
    ids = [obs.source_record_id for obs in observations]

    assert len(set(ids)) == len(ids)
    assert "cepalstat:862:NIC:2023-12" in ids


def test_an_unknown_period_member_raises(raw: RawDataset) -> None:
    """A renamed or added member must fail loudly, not drop rows in silence."""
    dimensions = json.loads(raw.payload["dimensions"][862])
    for dimension in dimensions["body"]["dimensions"]:
        if dimension["id"] == PERIOD_DIMENSION:
            dimension["members"] = [m for m in dimension["members"] if m["name"] != "Enero"]

    broken = build_raw(
        dict(raw.payload["data"]),
        {**raw.payload["dimensions"], 862: json.dumps(dimensions)},
    )

    with pytest.raises(TransformationError, match="unknown period member"):
        build_connector().transform(broken)


def test_a_missing_period_dimension_raises(raw: RawDataset) -> None:
    dimensions = json.loads(raw.payload["dimensions"][862])
    dimensions["body"]["dimensions"] = [
        d for d in dimensions["body"]["dimensions"] if d["id"] != PERIOD_DIMENSION
    ]

    broken = build_raw(
        dict(raw.payload["data"]),
        {**raw.payload["dimensions"], 862: json.dumps(dimensions)},
    )

    with pytest.raises(TransformationError, match="no period dimension"):
        build_connector().transform(broken)
```

Extend the test imports:

```python
from collections import Counter
from datetime import UTC, date, datetime

from reim.core.constants import Frequency
from reim.core.exceptions import ExtractionError, TransformationError
from reim.domain.pipelines.models import RawDataset
from reim.domain.sources.catalog import load_catalog
from reim.ingestion.connectors.regional.cepalstat_monetary import (
    CENTRAL_AMERICA,
    CepalstatMonetaryConnector,
)
from tests.conftest import REPO_ROOT
```

Remove the module-level `CENTRAL_AMERICA` constant added in Task 2; it now
comes from the connector, which is what the tests should be checking against.

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_monetary_connector.py -v`
Expected: FAIL at collection — `ModuleNotFoundError: reim.ingestion.connectors.regional.cepalstat_monetary`.

- [ ] **Step 3: Write the connector**

Create `reim/ingestion/connectors/regional/cepalstat_monetary.py`:

```python
"""Central America — monthly monetary aggregates published through CEPALSTAT.

The API, its lack of documentation and the way its routes were recovered are
documented in ``cepalstat_gdp.py``; only what differs is recorded here.

Two things differ, and both come from one dimension:

1. **Dimension 3981 selects a period inside the year** — twelve months, four
   quarters and an annual figure. Only the twelve months are stored: the annual
   figure is exactly December's and each quarter is exactly its closing month,
   verified across 2,253 cells with no exceptions. These are end-of-period
   stocks, so the restatement is definitional.
2. **In ``lang=en`` all seventeen of its members are the string
   ``descripcion_ingles``** — the untranslated column name of CEPAL's own
   database, surfacing through the API. The ids cannot be pinned either: they
   run 3982-3998 but not in calendar order, with September at 3993 and July at
   3994. So the member table is fetched separately in Spanish, and only the
   member table: the data itself stays ``lang=en`` and every string REIM stores
   stays English.

The figures are published in millions of each country's own currency. REIM
stores whole units of that currency, and the currency comes from the country
registry rather than from the payload, which says only "local currency". Two
of the seven are dollarised, so their series alone are comparable with each
other; none of the others is comparable with anything without a conversion
REIM does not perform.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from reim.core.constants import CheckSeverity, CheckType, Frequency
from reim.core.exceptions import ExtractionError, TransformationError
from reim.domain.countries.registry import COUNTRIES_BY_ISO3
from reim.domain.observations.periods import parse_period
from reim.domain.pipelines.models import (
    NormalizedObservation,
    QualityResult,
    RawDataset,
)
from reim.ingestion.base import BaseConnector
from reim.ingestion.http import ensure_ok, fetch, http_client

#: Shared with the GDP connector; the period dimension is this family's own.
COUNTRY_DIMENSION = 208
YEARS_DIMENSION = 29117
PERIOD_DIMENSION = 3981

#: Published in millions of local currency, stored in whole units.
MILLIONS = Decimal("1000000")

CENTRAL_AMERICA = frozenset({"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"})

#: The only member names that become observations. Read from the Spanish
#: dimensions response; "Anual" and the four "Trimestre N" members are
#: restatements of a month and are dropped.
MONTHS_BY_SPANISH_NAME = {
    "Enero": 1,
    "Febrero": 2,
    "Marzo": 3,
    "Abril": 4,
    "Mayo": 5,
    "Junio": 6,
    "Julio": 7,
    "Agosto": 8,
    "Septiembre": 9,
    "Octubre": 10,
    "Noviembre": 11,
    "Diciembre": 12,
}


@dataclass(frozen=True, slots=True)
class SeriesSpec:
    """One CEPAL indicator id and the REIM code it feeds."""

    cepal_id: int
    indicator_code: str


SERIES: tuple[SeriesSpec, ...] = (
    SeriesSpec(862, "money_m1_monthly"),
    SeriesSpec(868, "money_m2_monthly"),
    SeriesSpec(869, "money_m3_monthly"),
)

#: Countries each series covers, measured 2026-08-19. Encoded so that a
#: disappearance is visible and the two known absences are stated rather
#: than discovered.
EXPECTED_COUNTRIES: dict[str, frozenset[str]] = {
    "money_m1_monthly": CENTRAL_AMERICA,
    "money_m2_monthly": CENTRAL_AMERICA - {"BLZ"},
    "money_m3_monthly": CENTRAL_AMERICA - {"SLV"},
}

#: Relative tolerance for the M1 <= M2 <= M3 nesting. CEPAL declares zero
#: decimals and publishes some series rounded to whole millions and others to
#: one decimal, which inverts the ordering by at most 0.014% in 229 of 2,942
#: shared cells. This sits seven times above that and far below any real
#: inversion, which would be percent-scale.
NESTING_TOLERANCE = Decimal("0.001")
```

Then the class. If you copy this block into a plan or doc, fence it as text
rather than as python — see the global constraints.

```text
class CepalstatMonetaryConnector(BaseConnector):
    """Monthly M1, M2 and M3 for the seven Central American countries."""

    connector_key = "cepalstat_monetary_monthly"
    version = "1.0.0"
    expected_frequency = Frequency.MONTHLY

    async def extract(self) -> RawDataset:
        """Fetch each indicator's data and its Spanish member table.

        Six requests: three for data in English, three for dimensions in
        Spanish. The Spanish request exists only because the English period
        members are untranslated; nothing from it is stored.

        Raises:
            ExtractionError: The API was unreachable, answered with something
                other than JSON, reported ``success: false`` in its envelope,
                or returned an empty data array.
        """
        base = str(self.source.base_url).rstrip("/")
        retrieved_at = datetime.now(UTC)
        data: dict[int, str] = {}
        dimensions: dict[int, str] = {}
        status: int | None = None
        content_type: str | None = None

        async with http_client() as client:
            for spec in SERIES:
                url = f"{base}/indicator/{spec.cepal_id}/data"
                response = await fetch(client, url, params={"lang": "en"})
                ensure_ok(response, expected_content_type="json")
                self._ensure_envelope_ok(response.text, spec.cepal_id, url)
                data[spec.cepal_id] = response.text
                status = response.status_code
                content_type = response.headers.get("content-type")

                url = f"{base}/indicator/{spec.cepal_id}/dimensions"
                response = await fetch(client, url, params={"lang": "es"})
                ensure_ok(response, expected_content_type="json")
                dimensions[spec.cepal_id] = response.text

        return RawDataset(
            source_key=self.source.key,
            retrieved_at=retrieved_at,
            source_url=base,
            payload={"data": data, "dimensions": dimensions},
            content_type=content_type,
            http_status=status,
            metadata={
                "indicator_ids": [spec.cepal_id for spec in SERIES],
                "lang": "en",
                "dimensions_lang": "es",
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
        """Normalize the three payloads into one observation per country-month.

        Pure function of ``raw``.

        Raises:
            TransformationError: The payload is not the expected mapping, a
                period or years dimension is missing, or a row names a member
                that does not exist.
        """
        payload = raw.payload
        if not isinstance(payload, dict) or "data" not in payload:
            msg = "CEPALSTAT payload must carry 'data' and 'dimensions' mappings"
            raise TransformationError(msg, source_key=self.source.key)

        observations: list[NormalizedObservation] = []
        for spec in SERIES:
            observations.extend(
                self._read_series(
                    spec,
                    str(payload["data"][spec.cepal_id]),
                    str(payload["dimensions"][spec.cepal_id]),
                    raw,
                )
            )
        observations.sort(key=lambda obs: (obs.indicator_code, obs.country_iso3, obs.period.start))
        return observations

    def _read_series(
        self, spec: SeriesSpec, text: str, dimensions_text: str, raw: RawDataset
    ) -> list[NormalizedObservation]:
        """Turn one indicator's payload into its Central American observations."""
        body = self._decode(text, spec.cepal_id)["body"]
        months = self._months_of(self._decode(dimensions_text, spec.cepal_id), spec.cepal_id)
        years = self._members_of(body, YEARS_DIMENSION, "years", spec.cepal_id)
        published_unit = str(body["metadata"]["unit"])
        sources = {source["id"]: source["description"] for source in body["sources"]}
        credits = [entry["description"] for entry in body["credits"] if entry["id"] != 0]

        observations: list[NormalizedObservation] = []
        for row in body["data"]:
            iso3 = row.get("iso3")
            if iso3 not in CENTRAL_AMERICA:
                continue
            month = self._month_of(row, months, spec.cepal_id)
            if month is None:
                continue
            year = self._label_of(row, years, YEARS_DIMENSION, "year", spec.cepal_id)
            value = self._value_of(row, spec.cepal_id)
            label = f"{year}-{month:02d}"
            currency = COUNTRIES_BY_ISO3[str(iso3)].currency_code
            observations.append(
                NormalizedObservation(
                    country_iso3=str(iso3),
                    indicator_code=spec.indicator_code,
                    source_key=self.source.key,
                    period=parse_period(label, Frequency.MONTHLY),
                    unit=currency,
                    currency_code=currency,
                    value_numeric=value * MILLIONS,
                    retrieved_at=raw.retrieved_at,
                    source_url=f"{raw.source_url}/indicator/{spec.cepal_id}/data",
                    source_record_id=f"cepalstat:{spec.cepal_id}:{iso3}:{label}",
                    raw_metadata={
                        "cepalstat_indicator_id": spec.cepal_id,
                        "cepalstat_published_value": format(value.normalize(), "f"),
                        "cepalstat_published_unit": published_unit,
                        "cepalstat_scale_applied": "1e6",
                        "cepalstat_source": sources.get(row.get("source_id"), ""),
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

    def _members_of(
        self, body: Any, dimension_id: int, name: str, cepal_id: int
    ) -> dict[int, str]:
        """Build the ``member id -> label`` map from the response itself.

        Raises:
            TransformationError: The dimension is absent.
        """
        for dimension in body.get("dimensions", []):
            if dimension.get("id") == dimension_id:
                return {member["id"]: str(member["name"]) for member in dimension["members"]}
        msg = f"CEPALSTAT returned no {name} dimension for indicator {cepal_id}"
        raise TransformationError(msg, source_key=self.source.key)

    def _months_of(self, dimensions_document: Any, cepal_id: int) -> dict[int, int | None]:
        """Map each period member id to a month number, or ``None`` to skip.

        ``None`` marks the annual and quarterly members, which restate a month
        exactly and are not stored.

        Raises:
            TransformationError: The period dimension is absent.
        """
        members = self._members_of(
            dimensions_document["body"], PERIOD_DIMENSION, "period", cepal_id
        )
        return {
            member_id: MONTHS_BY_SPANISH_NAME.get(label) for member_id, label in members.items()
        }

    def _month_of(self, row: Any, months: dict[int, int | None], cepal_id: int) -> int | None:
        """Resolve a row's month, or ``None`` when it is a restatement.

        Raises:
            TransformationError: The row names a period member that does not
                exist, which means CEPAL renamed or added one.
        """
        member = row.get(f"dim_{PERIOD_DIMENSION}")
        if member not in months:
            msg = (
                f"CEPALSTAT row for indicator {cepal_id} names an unknown "
                f"period member {member!r}"
            )
            raise TransformationError(msg, source_key=self.source.key)
        return months[member]

    def _label_of(
        self, row: Any, labels: dict[int, str], dimension_id: int, name: str, cepal_id: int
    ) -> str:
        """Resolve a row's label for one dimension.

        Raises:
            TransformationError: The row names a member that does not exist.
        """
        member = row.get(f"dim_{dimension_id}")
        label = labels.get(member)
        if label is None:
            msg = (
                f"CEPALSTAT row for indicator {cepal_id} names an unknown "
                f"{name} member {member!r}"
            )
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

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_monetary_connector.py -v`
Expected: PASS, every test.

If `test_an_unknown_period_member_raises` fails because removing "Enero" from
the member table makes `months` lack that id, confirm the error message says
`unknown period member` — that is the behaviour being pinned. Do not soften
the match string.

- [ ] **Step 5: Run the four gates, each on its own line, and read every exit code**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy reim apps
.venv/bin/python -m pytest tests/ -m "not live and not integration"
```

Also run `.venv/bin/python -m reim.cli catalog validate` and confirm all 18
connectors now import cleanly.

- [ ] **Step 6: Commit**

```bash
git add reim/ingestion/connectors/regional/cepalstat_monetary.py \
        tests/unit/test_cepalstat_monetary_connector.py
git commit -m "feat(cepalstat): parse three monetary series for seven countries

5,383 monthly observations. The annual and quarterly members are dropped
because they restate a month exactly — 2,253 cells checked, no exceptions —
and storing them would triple-count the same stock.

Each observation carries its own currency, resolved from the country
registry: REIM's first indicator whose unit changes with the country. The
payload says only 'local currency'.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: `validate` — the three checks

**Files:**
- Modify: `reim/ingestion/connectors/regional/cepalstat_monetary.py`
- Test: `tests/unit/test_cepalstat_monetary_connector.py`

**Interfaces:**
- Consumes: `CepalstatMonetaryConnector.transform` from Task 3.
- Produces: `validate` returning three `QualityResult`s named `cepalstat_monetary_nesting`, `cepalstat_monetary_expected_countries`, `cepalstat_monthly_continuity`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cepalstat_monetary_connector.py`:

```python
def results_of(observations: list[NormalizedObservation]) -> dict[str, QualityResult]:
    return {result.check_name: result for result in build_connector().validate(observations)}


def test_all_three_checks_pass_on_the_real_recordings(raw: RawDataset) -> None:
    results = results_of(build_connector().transform(raw))

    assert set(results) == {
        "cepalstat_monetary_nesting",
        "cepalstat_monetary_expected_countries",
        "cepalstat_monthly_continuity",
    }
    assert all(result.status is CheckStatus.PASSED for result in results.values())


def test_the_nesting_holds_on_the_real_data_despite_rounding(raw: RawDataset) -> None:
    """229 cells invert by up to 0.014% because CEPAL rounds some series."""
    result = results_of(build_connector().transform(raw))["cepalstat_monetary_nesting"]

    assert result.status is CheckStatus.PASSED


def test_a_real_inversion_fails_the_nesting_check(raw: RawDataset) -> None:
    """Move one M1 cell above its M2: a percent-scale break, not rounding."""
    observations = build_connector().transform(raw)
    for index, obs in enumerate(observations):
        if (
            obs.indicator_code == "money_m1_monthly"
            and obs.country_iso3 == "NIC"
            and obs.period.label == "2023-12"
        ):
            assert obs.value_numeric is not None
            observations[index] = replace(obs, value_numeric=obs.value_numeric * Decimal("10"))

    result = results_of(observations)["cepalstat_monetary_nesting"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.ERROR
    assert "NIC 2023-12" in result.message


def test_rounding_alone_never_fails_the_nesting_check(raw: RawDataset) -> None:
    """The tolerance must admit the source's own rounding, and no more."""
    observations = build_connector().transform(raw)
    for index, obs in enumerate(observations):
        if obs.indicator_code == "money_m2_monthly":
            assert obs.value_numeric is not None
            observations[index] = replace(obs, value_numeric=obs.value_numeric * Decimal("0.9999"))

    assert results_of(observations)["cepalstat_monetary_nesting"].status is CheckStatus.PASSED


def test_a_missing_country_fails_critically(raw: RawDataset) -> None:
    observations = [
        obs
        for obs in build_connector().transform(raw)
        if not (obs.indicator_code == "money_m1_monthly" and obs.country_iso3 == "NIC")
    ]

    result = results_of(observations)["cepalstat_monetary_expected_countries"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.CRITICAL
    assert "NIC" in result.message


def test_belize_appearing_in_m2_is_reported_too(raw: RawDataset) -> None:
    """The expectation is a set, not a floor: an arrival is news as well."""
    observations = build_connector().transform(raw)
    extra = next(obs for obs in observations if obs.indicator_code == "money_m1_monthly")
    observations.append(replace(extra, indicator_code="money_m2_monthly", country_iso3="BLZ"))

    result = results_of(observations)["cepalstat_monetary_expected_countries"]

    assert result.status is CheckStatus.FAILED
    assert "BLZ" in result.message


def test_a_hole_in_one_country_is_reported_as_a_warning(raw: RawDataset) -> None:
    """Pooling the seven would hide it: the others published that month."""
    observations = [
        obs
        for obs in build_connector().transform(raw)
        if not (
            obs.indicator_code == "money_m1_monthly"
            and obs.country_iso3 == "NIC"
            and obs.period.label == "2015-06"
        )
    ]

    result = results_of(observations)["cepalstat_monthly_continuity"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.WARNING
    assert "NIC 2015-06" in result.message


def test_every_check_is_dataset_level(raw: RawDataset) -> None:
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

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_monetary_connector.py -k "check or nesting or countr or continuity or rounding" -v`
Expected: FAIL — `validate` returns `[]`, so `set(results)` is empty and the
`KeyError`s follow.

- [ ] **Step 3: Implement the three checks**

Replace the placeholder `validate` in
`reim/ingestion/connectors/regional/cepalstat_monetary.py`. If you copy this
block into a plan or doc, fence it as text rather than as python — see the
global constraints.

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
            self._check_nesting(by_key),
            self._check_expected_countries(observations),
            self._check_monthly_continuity(observations),
        ]

    def _check_nesting(self, by_key: dict[str, dict[tuple[str, str], Decimal]]) -> QualityResult:
        """M1 <= M2 <= M3, which is how CEPAL defines the family.

        ``calculation_methodology`` states M2 = M1 + savings deposits and
        M3 = M2 + foreign currency deposits, so the ordering is definitional.
        The tolerance exists because CEPAL declares zero decimals and publishes
        some series rounded to whole millions and others to one decimal, which
        inverts 229 of 2,942 shared cells by at most 0.014%.
        """
        pairs = (
            ("money_m1_monthly", "money_m2_monthly"),
            ("money_m2_monthly", "money_m3_monthly"),
        )
        broken: list[tuple[str, str]] = []
        compared = 0
        for narrow_code, wide_code in pairs:
            narrow, wide = by_key[narrow_code], by_key[wide_code]
            for key in sorted(set(narrow) & set(wide)):
                compared += 1
                if not wide[key]:
                    continue
                excess = (narrow[key] - wide[key]) / wide[key]
                if excess > NESTING_TOLERANCE:
                    broken.append(key)

        if not broken:
            return QualityResult.passed(
                "cepalstat_monetary_nesting",
                CheckType.CONSISTENCY,
                f"M1 <= M2 <= M3 holds on all {compared} shared cell(s), "
                f"within {NESTING_TOLERANCE}",
                expected_value="0 beyond tolerance",
                actual_value="0",
            )

        shown = ", ".join(f"{country} {period}" for country, period in broken[:5])
        suffix = f" (+{len(broken) - 5} more)" if len(broken) > 5 else ""
        return QualityResult.failure(
            "cepalstat_monetary_nesting",
            CheckType.CONSISTENCY,
            CheckSeverity.ERROR,
            f"{len(broken)} cell(s) break the M1 <= M2 <= M3 ordering: {shown}{suffix}",
            expected_value="0 beyond tolerance",
            actual_value=str(len(broken)),
        )

    def _check_expected_countries(
        self, observations: list[NormalizedObservation]
    ) -> QualityResult:
        """Each series has its own country set; Belize and El Salvador differ.

        An expectation rather than a floor, so that a country arriving is
        reported as loudly as one disappearing.
        """
        seen: dict[str, set[str]] = {spec.indicator_code: set() for spec in SERIES}
        for obs in observations:
            if obs.indicator_code in seen:
                seen[obs.indicator_code].add(obs.country_iso3)

        problems: list[str] = []
        for code, expected in EXPECTED_COUNTRIES.items():
            for iso3 in sorted(expected - seen[code]):
                problems.append(f"{code} lost {iso3}")
            for iso3 in sorted(seen[code] - expected):
                problems.append(f"{code} gained {iso3}")

        if not problems:
            return QualityResult.passed(
                "cepalstat_monetary_expected_countries",
                CheckType.COMPLETENESS,
                "Every series carries exactly the countries it is expected to",
                expected_value=str(sum(len(v) for v in EXPECTED_COUNTRIES.values())),
                actual_value=str(sum(len(v) for v in seen.values())),
            )

        return QualityResult.failure(
            "cepalstat_monetary_expected_countries",
            CheckType.COMPLETENESS,
            CheckSeverity.CRITICAL,
            f"{len(problems)} change(s) in country coverage: {', '.join(problems[:5])}",
            expected_value=str(sum(len(v) for v in EXPECTED_COUNTRIES.values())),
            actual_value=str(sum(len(v) for v in seen.values())),
        )

    def _check_monthly_continuity(
        self, observations: list[NormalizedObservation]
    ) -> QualityResult:
        """Holes inside each country's own span, per indicator.

        Walked per country and per series: pooling them would hide a hole
        whenever another country published that month, and six of the seven
        usually did.
        """
        spans: dict[tuple[str, str], set[tuple[int, int]]] = {}
        for obs in observations:
            year, month = obs.period.label.split("-")
            spans.setdefault((obs.indicator_code, obs.country_iso3), set()).add(
                (int(year), int(month))
            )

        missing: list[str] = []
        expected = present = 0
        for (code, iso3), months in sorted(spans.items()):
            if len(months) < 2:
                continue
            first, last = min(months), max(months)
            width = (last[0] - first[0]) * 12 + (last[1] - first[1]) + 1
            expected += width
            present += len(months)
            cursor = first
            for _ in range(width):
                if cursor not in months:
                    missing.append(f"{iso3} {cursor[0]}-{cursor[1]:02d} ({code})")
                cursor = (cursor[0] + 1, 1) if cursor[1] == 12 else (cursor[0], cursor[1] + 1)

        if not missing:
            return QualityResult.passed(
                "cepalstat_monthly_continuity",
                CheckType.COMPLETENESS,
                f"No gaps in any of the {len(spans)} country-series",
                expected_value=str(expected),
                actual_value=str(present),
            )

        shown = ", ".join(missing[:5])
        suffix = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
        return QualityResult.failure(
            "cepalstat_monthly_continuity",
            CheckType.COMPLETENESS,
            CheckSeverity.WARNING,
            f"{len(missing)} month(s) missing: {shown}{suffix}",
            expected_value=str(expected),
            actual_value=str(present),
        )
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_monetary_connector.py -v`
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
git add reim/ingestion/connectors/regional/cepalstat_monetary.py \
        tests/unit/test_cepalstat_monetary_connector.py
git commit -m "test(cepalstat): cover the three monetary quality checks

The nesting check is the family's own definition turned into an assertion:
CEPAL states M2 = M1 + savings deposits and M3 = M2 + foreign currency
deposits, so M1 <= M2 <= M3 must hold. It does, once a 0.1% tolerance admits
the source's own rounding — 229 of 2,942 shared cells invert by at most
0.014% because some series are published rounded to whole millions.

The country check is an expectation, not a floor, so Belize arriving in M2
is reported as loudly as Nicaragua vanishing from M1.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: `extract` coverage

**Files:**
- Modify: `tests/unit/test_cepalstat_monetary_connector.py`

**Interfaces:**
- Consumes: `CepalstatMonetaryConnector.extract` written in Task 3.

`extract` was written in Task 3 so the module was importable. This task pins
its behaviour.

- [ ] **Step 1: Write the tests**

Append to `tests/unit/test_cepalstat_monetary_connector.py`:

```python
BASE_URL = "https://api-cepalstat.cepal.org/cepalstat/api/v1"


def data_url(cepal_id: int) -> str:
    return f"{BASE_URL}/indicator/{cepal_id}/data"


def dimensions_url(cepal_id: int) -> str:
    return f"{BASE_URL}/indicator/{cepal_id}/dimensions"


def json_response(text: str) -> httpx.Response:
    return httpx.Response(200, text=text, headers={"content-type": "application/json"})


@respx.mock
async def test_a_run_makes_two_requests_per_indicator(
    cepalstat_monetary_862_json: str,
    cepalstat_monetary_868_json: str,
    cepalstat_monetary_869_json: str,
    cepalstat_dimensions_862_json: str,
    cepalstat_dimensions_868_json: str,
    cepalstat_dimensions_869_json: str,
) -> None:
    data = {
        862: cepalstat_monetary_862_json,
        868: cepalstat_monetary_868_json,
        869: cepalstat_monetary_869_json,
    }
    dims = {
        862: cepalstat_dimensions_862_json,
        868: cepalstat_dimensions_868_json,
        869: cepalstat_dimensions_869_json,
    }
    routes = []
    for cepal_id in (862, 868, 869):
        routes.append(
            respx.get(data_url(cepal_id)).mock(return_value=json_response(data[cepal_id]))
        )
        routes.append(
            respx.get(dimensions_url(cepal_id)).mock(return_value=json_response(dims[cepal_id]))
        )

    raw = await build_connector().extract()

    assert all(route.call_count == 1 for route in routes)
    assert set(raw.payload["data"]) == {862, 868, 869}
    assert set(raw.payload["dimensions"]) == {862, 868, 869}


@respx.mock
async def test_the_data_is_english_and_the_dimensions_are_spanish(
    cepalstat_monetary_862_json: str, cepalstat_dimensions_862_json: str
) -> None:
    """The whole point of the split: nothing stored comes back translated."""
    for cepal_id in (862, 868, 869):
        respx.get(data_url(cepal_id)).mock(return_value=json_response(cepalstat_monetary_862_json))
        respx.get(dimensions_url(cepal_id)).mock(
            return_value=json_response(cepalstat_dimensions_862_json)
        )

    await build_connector().extract()

    by_path = {call.request.url.path: call.request.url for call in respx.calls}
    assert by_path["/cepalstat/api/v1/indicator/862/data"].params["lang"] == "en"
    assert by_path["/cepalstat/api/v1/indicator/862/dimensions"].params["lang"] == "es"


@respx.mock
async def test_a_failing_envelope_raises_even_on_http_200() -> None:
    """CEPAL answers an unknown id with 500 and success:false, never 404."""
    envelope = json.dumps(
        {
            "header": {"success": False, "code": 404, "message": "Not found"},
            "body": {"data": []},
        }
    )
    respx.get(data_url(862)).mock(return_value=json_response(envelope))

    with pytest.raises(ExtractionError, match="reported failure 404"):
        await build_connector().extract()


@respx.mock
async def test_an_empty_data_array_raises(cepalstat_monetary_862_json: str) -> None:
    body = json.loads(cepalstat_monetary_862_json)
    body["body"]["data"] = []
    respx.get(data_url(862)).mock(return_value=json_response(json.dumps(body)))

    with pytest.raises(ExtractionError, match="no rows"):
        await build_connector().extract()


@pytest.mark.live
async def test_the_real_api_still_answers_as_recorded() -> None:
    """Opt-in. Proves the contract, not the data: shape, not values."""
    connector = build_connector()
    observations = connector.transform(await connector.extract())

    assert len(observations) >= 5000
    assert {obs.country_iso3 for obs in observations} == CENTRAL_AMERICA
    assert all(result.status is CheckStatus.PASSED for result in connector.validate(observations))
```

Extend the test imports:

```python
import httpx
import respx
```

- [ ] **Step 2: Run them**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_monetary_connector.py -m "not live" -v`
Expected: PASS.

**If any of them fails, the failure is real — fix `extract`, never the test.**
In particular do not relax the `match="reported failure 404"` or
`match="no rows"` patterns; those two strings are the whole point of the
envelope check.

- [ ] **Step 3: Run the live test once, deliberately**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_monetary_connector.py -m live -v`
Expected: PASS, six real requests to CEPAL taking around 30 seconds. If it
fails, the API changed since 2026-08-19 — record what changed in
`docs/sources.md` before adapting the connector.

- [ ] **Step 4: Run the four gates, each on its own line, and read every exit code**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy reim apps
.venv/bin/python -m pytest tests/ -m "not live and not integration"
```

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_cepalstat_monetary_connector.py
git commit -m "test(cepalstat): cover the six-request monetary extract

Pins the language split, which is the design decision most likely to be
undone by someone tidying up: the data must be fetched in English and the
dimensions in Spanish. Collapsing them to one language breaks either the
month names or every stored string.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Enable, run for real, and record the source

**Files:**
- Modify: `sources/catalog.yml`, `docs/sources.md`, `ROADMAP.md`, `README.md`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Enable the source**

In `sources/catalog.yml`, replace the `cepalstat_monetary_monthly` entry's

```text
    enabled: false
    disabled_reason: >-
      Connector under construction; enabled once it has been run end to end
      against a real database.
```

with `    enabled: true`.

- [ ] **Step 2: Validate the catalog**

Run: `.venv/bin/python -m reim.cli catalog validate`
Expected: `18 source(s), 18 enabled`, `31 indicator rule(s)`, all 18 connectors
importing cleanly.

- [ ] **Step 3: Run it end to end against a real database**

```bash
make db-up CONTAINER_ENGINE=podman
export REIM_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim
.venv/bin/python -m reim.cli db seed
.venv/bin/python -m reim.cli pipeline run cepalstat_monetary_monthly
```

Expected: `success extracted=5383 inserted=5383 ... rejected=0`.

The run will log `pipeline.quality_failures` with three failed checks: the
per-country freshness check firing on Honduras for M1, M2 and M3. That is
expected and documented in `sources/quality_rules.yml`. Confirm it is exactly
those three and nothing else:

```bash
podman exec reim-test-postgres psql -U reim -d reim -c "
select check_name, severity, indicator_code, actual_value
from data_quality_checks where status = 'failed' order by indicator_code;"
```

Expected: three `freshness` rows at `warning`, with `actual_value` around
1023, 1023 and 1237. **Any other failed check is a real defect — stop and
investigate rather than proceeding.**

- [ ] **Step 4: Prove idempotency**

Run the pipeline a second time.
Expected: `inserted=0 unchanged=5383 rejected=0`. If `unchanged` is not 5,383,
something in `raw_metadata` or the value is unstable between runs — check that
`credits[0]` did not creep back in.

- [ ] **Step 5: Check what landed**

```bash
podman exec reim-test-postgres psql -U reim -d reim -c "
select i.code, count(*), min(o.period_start), max(o.period_start)
from observations o join indicators i on i.id = o.indicator_id
where i.code like 'money%' group by i.code order by i.code;"
```

Expected: 2,026 / 1,611 / 1,746, the first two starting 1990-01-01 for M1 and
M3 and 2001-12-01 for M2.

Then confirm the currencies landed per country:

```bash
podman exec reim-test-postgres psql -U reim -d reim -c "
select c.iso3, o.currency_code, count(*)
from observations o
join countries c on c.id = o.country_id
join indicators i on i.id = o.indicator_id
where i.code like 'money%' group by 1,2 order by 1;"
```

Expected: exactly one currency per country — `NIO`, `GTQ`, `USD`, `HNL`,
`CRC`, `PAB`, `BZD`.

- [ ] **Step 6: Record the source**

Add a `### CEPAL — monthly monetary aggregates` section to the "Enabled" part
of `docs/sources.md`, following the shape of the CEPAL GDP section above it. It
must cover, at minimum:

- The three indicator ids, the coverage table per country, and the volume.
- **That only the monthly member is stored**, with the measured evidence: the
  annual figure equals December in 453 cells and each quarter equals its
  closing month in 1,800, with no exceptions.
- **The language split and why**: `descripcion_ingles` in `lang=en`, ids not in
  calendar order, and that the Spanish request is 29 KB and touches nothing
  REIM stores.
- **That the figures are in local currency** and therefore not comparable
  across countries, and that El Salvador and Panama are dollarised so those two
  alone are comparable with each other.
- **The nesting identity**, and that its 229 apparent violations are the
  source's rounding.
- **That Honduras warns on freshness from the first run**, with the measured
  ages, and that the threshold was chosen rather than tuned around it.
- The licence, which is CEPAL's and already quoted in the GDP section — link to
  it rather than repeating it.

Then remove the monetary row from that section's "Reachable, not ingested"
table, leaving public debt.

- [ ] **Step 7: Close the roadmap line**

In `ROADMAP.md`, the v0.2.0 bullet currently reads that Nicaragua's monetary
aggregates are available from SECMCA behind a credentialed account, with
CEPALSTAT noted as a route that is not yet ingested. Rewrite it as done, with
the real numbers: M1, M2 and M3 monthly for all seven countries, 5,383
observations, Nicaragua from 2001-12. Note that remittances remain absent —
this increment does not touch them.

- [ ] **Step 8: Update the README**

- Add CEPAL's monetary row to the source table.
- Update the counts: 18 pipelines, 31 indicators, roughly 48,400 observations
  for a complete rebuild.
- The "Two sources are converted" limitation becomes three, and the sentence
  must say the third is in local currency rather than USD.
- Add a limitation stating plainly that the monetary series are **not
  comparable across countries** and that REIM does not convert them.

- [ ] **Step 9: Run the four gates plus integration, each on its own line**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy reim apps
.venv/bin/python -m pytest tests/ -m "not live and not integration"
REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim \
  .venv/bin/python -m pytest tests/integration
```

- [ ] **Step 10: Commit**

```bash
git add sources/catalog.yml docs/sources.md ROADMAP.md README.md
git commit -m "feat: CEPALSTAT monetary aggregates — M1, M2 and M3, monthly

5,383 observations from six requests, closing the v0.2.0 line that named
SECMCA and a credentialed account as the only route to Nicaragua's monetary
aggregates. CEPALSTAT publishes them from 2001-12, unauthenticated.

These are REIM's first figures in a currency other than the dollar, the
cordoba and the quetzal, and the first that are not comparable across
countries: each is in its own currency and REIM does not convert. El
Salvador and Panama are dollarised, so those two alone line up.

Honduras warns on freshness from the first run, on all three series. The
threshold was set at 900 days knowing that. It is three and a half years
behind on M3 and the check should say so rather than be tuned around it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Extract the shared CEPALSTAT protocol

**Files:**
- Create: `reim/ingestion/connectors/regional/cepalstat.py`
- Modify: `reim/ingestion/connectors/regional/cepalstat_gdp.py`
- Modify: `reim/ingestion/connectors/regional/cepalstat_monetary.py`
- Test: `tests/unit/test_cepalstat_connector.py`, `tests/unit/test_cepalstat_monetary_connector.py`

**Interfaces:**
- Consumes: both finished connectors.
- Produces: `CepalstatConnector(BaseConnector)` carrying `_ensure_envelope_ok`, `_decode`, `_members_of`, `_label_of` and `_value_of`, plus the shared `COUNTRY_DIMENSION` and `YEARS_DIMENSION` constants.

This task is last on purpose. Deciding what to share before the second
connector existed would have been predicting the shared surface rather than
reading it. Now both are written and the overlap is visible.

- [ ] **Step 1: Confirm what is actually identical**

Run:

```bash
diff <(sed -n '/_ensure_envelope_ok/,/^    def transform/p' \
        reim/ingestion/connectors/regional/cepalstat_gdp.py) \
     <(sed -n '/_ensure_envelope_ok/,/^    def transform/p' \
        reim/ingestion/connectors/regional/cepalstat_monetary.py)
```

Expected: no differences, or only the docstring. Do the same for `_decode` and
`_value_of`. **Extract only what this step proves identical.** If a method
differs, leave it in both connectors and say so in the commit message — a
shared base that needs a parameter for every caller is worse than duplication.

- [ ] **Step 2: Write the base class**

Create `reim/ingestion/connectors/regional/cepalstat.py` holding a
`CepalstatConnector(BaseConnector)` with the methods Step 1 proved identical,
and the two shared dimension-id constants. Its module docstring is the natural
home for the API description currently in `cepalstat_gdp.py` — move it there
and leave each connector's docstring describing only what is its own.

- [ ] **Step 3: Point both connectors at it**

Change `CepalstatGdpConnector(BaseConnector)` to
`CepalstatGdpConnector(CepalstatConnector)` and delete the methods now
inherited. Do the same for `CepalstatMonetaryConnector`. Import
`COUNTRY_DIMENSION` and `YEARS_DIMENSION` from the new module in both, and
delete the duplicate definitions.

- [ ] **Step 4: Run every test that touches either connector**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_cepalstat_connector.py \
  tests/unit/test_cepalstat_monetary_connector.py -m "not live" -v
```

Expected: PASS, all of them, with **no test changed**. This refactor is
green-to-green by construction: if a test needs editing, the extraction
changed behaviour and is wrong.

- [ ] **Step 5: Run the four gates, each on its own line, and read every exit code**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy reim apps
.venv/bin/python -m pytest tests/ -m "not live and not integration"
```

- [ ] **Step 6: Run both pipelines for real**

```bash
export REIM_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim
.venv/bin/python -m reim.cli pipeline run cepalstat_gdp_annual
.venv/bin/python -m reim.cli pipeline run cepalstat_monetary_monthly
```

Expected: both `success`, both `inserted=0 unchanged=...`, and the same three
Honduras freshness warnings as before — no more, no fewer.

- [ ] **Step 7: Commit**

```bash
git add reim/ingestion/connectors/regional/cepalstat.py \
        reim/ingestion/connectors/regional/cepalstat_gdp.py \
        reim/ingestion/connectors/regional/cepalstat_monetary.py
git commit -m "refactor(cepalstat): one home for the undocumented protocol

Two connectors now read the same API with no published documentation. The
envelope check is the part worth sharing: an unknown indicator id answers
500 with success:false rather than 404, and that trap belongs in one place
rather than two that can drift apart.

Extracted after both connectors were written rather than before, so the
shared surface was read rather than predicted. Not a generic engine: each
connector still names its own dimensions and writes its own transform, which
is what decision C2 rejected and still rejects — the monetary series carry
three dimensions and public debt carries four.

No test changed.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage.** Every section of
`docs/superpowers/specs/2026-08-19-cepalstat-monetary-design.md` maps to a task:
§1 the roadmap correction → Task 6 step 7; §2 the source → Task 1 step 4; §3 the
language split → Task 3 (connector) and Task 5 (its test); §4 the measured
findings → the facts table, Task 2's fixture tests and Task 4's checks; §5
decisions M1-M9 → M1/M2 Task 3, M3/M4 Tasks 1 and 3, M5 Task 3 step 3, M6 Task 6
step 8, M7 Tasks 3 and 5, M8 Task 3's `_month_of`, M9 Task 7; §6 components →
Tasks 1, 3 and 4; §7 quality → Tasks 1 and 4; §8 testing → Tasks 2 and 5; §9
volume → Task 6; §10 out of scope → nothing to build.

**Placeholders.** None. Every code step carries the code; every documentation
step lists what the prose must state rather than saying "document it".

**Type consistency.** `SeriesSpec` has two fields here (`cepal_id`,
`indicator_code`) against the GDP connector's four — the monetary series share
one unit rule and one scale, so `unit` and `scale` would be dead weight. The
name is reused deliberately; Task 7 does not merge the two dataclasses, and
Step 1 of that task will not find them identical. `_members_of` is defined in
Task 3 with the signature `(body, dimension_id, name, cepal_id)` and used with
that signature in `_months_of` and `_read_series`. `EXPECTED_COUNTRIES` is
defined in Task 3 and consumed in Task 4.

**One thing the executor should know.** Task 6 step 3 expects three failing
checks on the first real run. That is the only place in this plan where a
non-empty `quality_failures` log is correct. Anywhere else, it is a defect.
