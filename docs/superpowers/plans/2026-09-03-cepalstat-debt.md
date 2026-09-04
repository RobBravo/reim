# CEPALSTAT public debt stock — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest central-government gross public debt for the seven Central
American countries, in dollars and as a share of GDP, from CEPALSTAT
indicators 1239 and 1240.

**Architecture:** One new connector subclassing `CepalstatConnector`, the base
extracted on 2026-09-03. Two requests, both `lang=en`. `transform` filters a
four-dimensional cube to one coverage and one classification member, selecting
by member id and asserting the names are unchanged. Two dataset-level checks.

**Tech Stack:** Python 3.12, httpx, respx, pytest, SQLAlchemy, Pydantic,
PostgreSQL 16 via podman.

**Spec:** `docs/superpowers/specs/2026-09-03-cepalstat-debt-design.md`

## Global Constraints

- Every string REIM stores comes from a `lang=en` response. No Spanish request
  exists in this family, and none is to be added (spec D2).
- Rows are selected by member id, never by name; the names are asserted, not
  matched (spec D3).
- Year labels come from the response's own member table, never from arithmetic
  on the member id.
- `credits[0]` is CEPAL's fetch date, moves between runs and is excluded from
  `raw_metadata`.
- The dollar series is scaled `× 10^6` to whole USD; the ratio is stored exactly
  as published (spec D4).
- Nothing reconciles the debt ratio against `gdp_current_usd_annual`. It does
  not reconcile, by design (spec D6).
- Four gates must pass before every commit: `ruff format --check .`,
  `ruff check .`, `mypy reim apps`, `pytest tests/ -m "not live and not integration"`.
- `.venv/bin/<tool>`; there is no `pip` in the venv and no Docker daemon —
  containers are podman.

## Measured facts the tests assert

All measured against the live API on 2026-09-03.

| Fact | Value |
|---|---|
| Cells stored, 1239 (USD) | 226 |
| Cells stored, 1240 (% of GDP) | 230 |
| Total observations | 456 |
| Per-country span, both series | 1990–2025, no gaps, except Belize and Nicaragua |
| Belize | 2011–2020 (USD), 2011–2025 (ratio) |
| Nicaragua | 1990–2025 (USD), 1991–2025 (ratio) |
| Empty classification members | 10610, 10611, 10614 — zero rows across all 145 countries |
| Rows for the seven before the coverage filter | 1,326 (1239) and 1,358 (1240) |
| Largest year-on-year move | Nicaragua 1996, −47.8%, from 185.3% to 96.7% of GDP |
| Ratio range | 14% to 222.1% |
| Response sizes | ~617 KB (1239), ~635 KB (1240) |

## File structure

| File | Responsibility |
|---|---|
| `reim/domain/indicators/registry.py` | The two indicator definitions |
| `sources/catalog.yml` | The `cepalstat_debt_annual` entry |
| `sources/quality_rules.yml` | Per-indicator rules for both codes |
| `reim/ingestion/connectors/regional/cepalstat_debt.py` | `extract`, `transform`, `validate` |
| `tests/fixtures/cepalstat_debt_{1239,1240}.json.gz` | The two recordings |
| `tests/conftest.py` | Two session fixtures decompressing them |
| `tests/unit/test_cepalstat_debt_connector.py` | Everything above |
| `tests/unit/test_catalog.py` | Registration assertions |
| `docs/sources.md`, `README.md`, `ROADMAP.md` | The record |

---

### Task 1: Two indicators, the catalog entry, and their quality rules

**Files:**
- Modify: `reim/domain/indicators/registry.py`, `sources/catalog.yml`, `sources/quality_rules.yml`
- Test: `tests/unit/test_catalog.py`

**Interfaces:**
- Produces: indicator codes `public_debt_usd_annual` and
  `public_debt_pct_gdp_annual`; catalog key `cepalstat_debt_annual`. Tasks 3, 4
  and 6 consume all three.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_catalog.py`:

```python
def test_the_two_debt_indicators_are_registered() -> None:
    """The first use of the fiscal category, declared since v0.1.0."""
    codes = {i.code: i for i in INDICATORS}

    for code in ("public_debt_usd_annual", "public_debt_pct_gdp_annual"):
        assert codes[code].category is IndicatorCategory.FISCAL
        assert codes[code].frequency is Frequency.ANNUAL


def test_the_debt_indicators_declare_their_own_value_types() -> None:
    """A stock in dollars is a level; a share of GDP is a percent."""
    codes = {i.code: i for i in INDICATORS}

    assert codes["public_debt_usd_annual"].value_type is ValueType.LEVEL
    assert codes["public_debt_usd_annual"].unit == "current USD"
    assert codes["public_debt_pct_gdp_annual"].value_type is ValueType.PERCENT
    assert codes["public_debt_pct_gdp_annual"].unit == "percent of GDP"


def test_the_debt_source_is_registered_and_disabled() -> None:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    entry = catalog.get("cepalstat_debt_annual")

    assert entry.organization == "CEPAL"
    assert entry.frequency is Frequency.ANNUAL
    assert entry.license == "cepal_terms_of_use"
    assert not entry.enabled
    assert set(entry.indicators) == {
        "public_debt_usd_annual",
        "public_debt_pct_gdp_annual",
    }


def test_the_debt_rules_allow_a_ratio_above_one_hundred() -> None:
    """Nicaragua reached 222.1% of GDP; a 100 cap would reject real data."""
    rules = load_quality_rules(REPO_ROOT / "sources" / "quality_rules.yml")
    rule = rules.for_indicator("public_debt_pct_gdp_annual")

    assert rule.max_value is None
    assert rule.min_value == 0
    assert rule.allow_negative is False


def test_the_debt_change_threshold_clears_the_nicaraguan_relief() -> None:
    """1996 fell 47.8% on HIPC relief. The threshold is set above it knowingly."""
    rules = load_quality_rules(REPO_ROOT / "sources" / "quality_rules.yml")

    for code in ("public_debt_usd_annual", "public_debt_pct_gdp_annual"):
        assert rules.for_indicator(code).max_period_change_pct == 60
```

Check the imports at the top of the file already cover `IndicatorCategory`,
`ValueType`, `Frequency`, `INDICATORS`, `load_catalog`, `load_quality_rules`
and `REPO_ROOT`; add whichever are missing.

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog.py -k debt -v`
Expected: FAIL — `KeyError: 'public_debt_usd_annual'` and
`KeyError: 'cepalstat_debt_annual'`.

- [ ] **Step 3: Register the two indicators**

In `reim/domain/indicators/registry.py`, append inside the `INDICATORS` tuple,
after the `money_m3_monthly` entry:

```text
    IndicatorDefinition(
        code="public_debt_usd_annual",
        name="Central government public debt stock (annual, current USD)",
        description=(
            "Gross public debt stock of the central government at the close of "
            "each year, as compiled by CEPAL. Published in millions of current "
            "dollars and stored in whole dollars. This is the central "
            "government only: CEPAL also publishes wider institutional "
            "coverages, but only this one covers all seven countries."
        ),
        category=IndicatorCategory.FISCAL,
        frequency=Frequency.ANNUAL,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=1239&lang=en",
    ),
    IndicatorDefinition(
        code="public_debt_pct_gdp_annual",
        name="Central government public debt stock (annual, percent of GDP)",
        description=(
            "The same debt stock expressed as a share of GDP, stored exactly "
            "as published. CEPAL's denominator is each country's GDP in local "
            "currency converted at the IMF's 31 December rate, which is not "
            "REIM's gdp_current_usd_annual: dividing this series into that one "
            "does not reconcile and is not intended to."
        ),
        category=IndicatorCategory.FISCAL,
        frequency=Frequency.ANNUAL,
        unit="percent of GDP",
        value_type=ValueType.PERCENT,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=1240&lang=en",
    ),
```

- [ ] **Step 4: Add the catalog entry**

In `sources/catalog.yml`, append after the `cepalstat_monetary_monthly` entry:

```yaml
  - key: cepalstat_debt_annual
    name: Central American central government public debt (annual)
    description: >-
      Gross public debt stock of the central government for the seven Central
      American countries, from CEPALSTAT, in millions of current dollars and
      as a share of GDP. Central government only: CEPAL publishes three wider
      institutional coverages, none of which covers all seven countries.
    organization: CEPAL
    category: fiscal
    access_type: http_api
    frequency: annual
    format: json
    base_url: https://api-cepalstat.cepal.org/cepalstat/api/v1
    documentation_url: https://statistics.cepal.org/portal/cepalstat/
    connector: reim.ingestion.connectors.regional.cepalstat_debt
    indicators:
      - public_debt_usd_annual
      - public_debt_pct_gdp_annual
    license: cepal_terms_of_use
    official: true
    enabled: false
    disabled_reason: >-
      Connector under construction; enabled once it has been run end to end
      against a real database.
```

- [ ] **Step 5: Add the quality rules**

In `sources/quality_rules.yml`, append to the indicator mapping:

```yaml
  public_debt_usd_annual: &public_debt
    min_value: 0
    max_value: null
    allow_negative: false
    allow_zero: false
    # Nicaragua 1996 fell 47.8% on HIPC and Paris Club relief. 60 clears that
    # real event with headroom and still reports a discontinuity.
    max_period_change_pct: 60
    monotonic_increasing: false
    # The newest period ends 2025-12-31. 600 matches the GDP rules and CEPAL's
    # annual publication cycle.
    freshness_max_age_days: 600
    min_observations: 220

  public_debt_pct_gdp_annual:
    <<: *public_debt
    # The ratio reaches 222.1% of GDP in Nicaragua's early 1990s, so max_value
    # stays null: a 100 cap would reject published figures.
    min_observations: 224
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog.py -v`
Expected: PASS, all of them.

- [ ] **Step 7: Run the four gates, each on its own line, and read every exit code**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy reim apps
.venv/bin/python -m pytest tests/ -m "not live and not integration"
```

`catalog validate` will report the connector module as missing until Task 3.
That is expected here and only here.

- [ ] **Step 8: Commit**

```bash
git add reim/domain/indicators/registry.py sources/catalog.yml \
        sources/quality_rules.yml tests/unit/test_catalog.py
git commit -m "feat(cepalstat): register the two public debt indicators

REIM's first fiscal indicators, and the first use of a category declared
since v0.1.0. Central government only: of CEPAL's four institutional
coverages it is the one that covers all seven countries across 1990-2025,
and CEPAL's own methodology note says the published figure refers to it.

The ratio's max_value stays null deliberately. Nicaragua's debt reached
222.1% of GDP in the early 1990s, so the obvious 100 cap would reject
published data.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Record the two responses

**Files:**
- Create: `tests/fixtures/cepalstat_debt_1239.json.gz`, `tests/fixtures/cepalstat_debt_1240.json.gz`
- Modify: `tests/conftest.py`, `tests/fixtures/README.md`
- Test: `tests/unit/test_cepalstat_debt_connector.py`

**Interfaces:**
- Produces: pytest fixtures `cepalstat_debt_1239_json` and
  `cepalstat_debt_1240_json`, both `str`. Tasks 3, 4 and 5 consume them.

- [ ] **Step 1: Record**

```bash
cd tests/fixtures
for id in 1239 1240; do
  curl -s -H "User-Agent: REIM/0.3 (+https://github.com/RobBravo/reim)" \
    "https://api-cepalstat.cepal.org/cepalstat/api/v1/indicator/${id}/data?lang=en" \
    | gzip -9 > "cepalstat_debt_${id}.json.gz"
done
ls -l cepalstat_debt_*.json.gz
```

Record the **complete** response — all 145 countries and every coverage and
classification member. That is what proves the filter works at all. Do not trim.

Sanity-check each one before moving on:

```bash
for id in 1239 1240; do
  gzip -dc "cepalstat_debt_${id}.json.gz" \
    | .venv/bin/python -c "import json,sys; d=json.load(sys.stdin); print(d['header']['success'], len(d['body']['data']))"
done
```

Expected: `True 4351` and `True 4494`. If the row counts have moved, the source
has changed since 2026-09-03 — record the new counts and carry them through
every measured number in Task 2 Step 3 rather than forcing the old ones.

- [ ] **Step 2: Add the conftest fixtures**

In `tests/conftest.py`, after the `cepalstat_monetary_869_json` fixture:

```python
@pytest.fixture(scope="session")
def cepalstat_debt_1239_json() -> str:
    """CEPALSTAT indicator 1239, public debt in millions of USD (gzipped)."""
    return gzip.decompress((FIXTURES / "cepalstat_debt_1239.json.gz").read_bytes()).decode("utf-8")


@pytest.fixture(scope="session")
def cepalstat_debt_1240_json() -> str:
    """CEPALSTAT indicator 1240, public debt as a percent of GDP (gzipped)."""
    return gzip.decompress((FIXTURES / "cepalstat_debt_1240.json.gz").read_bytes()).decode("utf-8")
```

- [ ] **Step 3: Write the tests that pin what the recordings hold**

Create `tests/unit/test_cepalstat_debt_connector.py`:

```python
"""Unit tests for the CEPALSTAT public debt connector.

Every payload replayed here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

COUNTRY_DIMENSION = 208
YEARS_DIMENSION = 29117
DEBT_CLASSIFICATION = 10590
INSTITUTIONAL_COVERAGE = 10690

CENTRAL_GOVERNMENT = 10692
TOTAL_BY_RESIDENCE = 10609
INTERNAL_DEBT = 10612
EXTERNAL_DEBT = 10613

#: Carry no rows anywhere in the response, for any of the 145 countries.
EMPTY_CLASSIFICATIONS = {10610, 10611, 10614}

CENTRAL_AMERICA = frozenset({"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"})

#: What the recordings hold, measured on 2026-09-03.
STORED_CELLS = {1239: 226, 1240: 230}
ROWS_TOTAL = {1239: 4351, 1240: 4494}

#: The two series do not cover exactly the same country-years.
SPANS = {
    1239: {
        "BLZ": (2011, 2020),
        "CRI": (1990, 2025),
        "GTM": (1990, 2025),
        "HND": (1990, 2025),
        "NIC": (1990, 2025),
        "PAN": (1990, 2025),
        "SLV": (1990, 2025),
    },
    1240: {
        "BLZ": (2011, 2025),
        "CRI": (1990, 2025),
        "GTM": (1990, 2025),
        "HND": (1990, 2025),
        "NIC": (1991, 2025),
        "PAN": (1990, 2025),
        "SLV": (1990, 2025),
    },
}


def body_of(text: str) -> dict:
    return json.loads(text, parse_float=Decimal)["body"]


def members_of(body: dict, dimension_id: int) -> dict[int, str]:
    dimension = next(d for d in body["dimensions"] if d["id"] == dimension_id)
    return {member["id"]: member["name"] for member in dimension["members"]}


def slice_of(text: str) -> dict[tuple[str, int], Decimal]:
    """Flatten one response to the central-government total, for the seven."""
    body = body_of(text)
    years = members_of(body, YEARS_DIMENSION)
    cells = {}
    for row in body["data"]:
        if row.get("iso3") not in CENTRAL_AMERICA:
            continue
        if row[f"dim_{INSTITUTIONAL_COVERAGE}"] != CENTRAL_GOVERNMENT:
            continue
        if row[f"dim_{DEBT_CLASSIFICATION}"] != TOTAL_BY_RESIDENCE:
            continue
        cells[(row["iso3"], int(years[row[f"dim_{YEARS_DIMENSION}"]]))] = Decimal(str(row["value"]))
    return cells


@pytest.fixture(params=[1239, 1240])
def recording(request, cepalstat_debt_1239_json, cepalstat_debt_1240_json):
    return request.param, {1239: cepalstat_debt_1239_json, 1240: cepalstat_debt_1240_json}[
        request.param
    ]


def test_each_recording_is_the_complete_response(recording) -> None:
    """Not an excerpt: 145 countries, every coverage, every classification."""
    cepal_id, text = recording
    body = body_of(text)

    assert len(body["data"]) == ROWS_TOTAL[cepal_id]
    assert len(members_of(body, COUNTRY_DIMENSION)) == 145
    assert len(members_of(body, INSTITUTIONAL_COVERAGE)) == 4
    assert len(members_of(body, DEBT_CLASSIFICATION)) == 6


def test_the_english_member_names_are_really_translated(recording) -> None:
    """Unlike the monetary family, so no Spanish request is needed here."""
    _, text = recording
    coverage = members_of(body_of(text), INSTITUTIONAL_COVERAGE)
    classification = members_of(body_of(text), DEBT_CLASSIFICATION)

    assert coverage[CENTRAL_GOVERNMENT] == "Central government"
    assert classification[TOTAL_BY_RESIDENCE] == ("Total public debt (classification by residence)")
    assert "descripcion_ingles" not in set(coverage.values()) | set(classification.values())


def test_three_classification_members_carry_no_rows_at_all(recording) -> None:
    """Currency, rate and maturity are grouping nodes, not data."""
    _, text = recording
    used = {row[f"dim_{DEBT_CLASSIFICATION}"] for row in body_of(text)["data"]}

    assert used & EMPTY_CLASSIFICATIONS == set()
    assert used == {TOTAL_BY_RESIDENCE, INTERNAL_DEBT, EXTERNAL_DEBT}


def test_the_stored_slice_has_its_measured_size(recording) -> None:
    cepal_id, text = recording

    assert len(slice_of(text)) == STORED_CELLS[cepal_id]


def test_every_country_span_is_gapless(recording) -> None:
    """Belize and Nicaragua are shorter; none of the seven has a hole."""
    cepal_id, text = recording
    cells = slice_of(text)

    for iso3, (first, last) in SPANS[cepal_id].items():
        years = sorted(year for country, year in cells if country == iso3)
        assert years == list(range(first, last + 1)), iso3


def test_the_two_series_differ_by_exactly_six_cells(
    cepalstat_debt_1239_json: str, cepalstat_debt_1240_json: str
) -> None:
    """NIC 1990 has a dollar figure and no ratio; BLZ 2021-2025 the reverse."""
    usd = set(slice_of(cepalstat_debt_1239_json))
    pct = set(slice_of(cepalstat_debt_1240_json))

    assert usd - pct == {("NIC", 1990)}
    assert pct - usd == {("BLZ", year) for year in range(2021, 2026)}


def test_the_internal_and_external_split_does_not_sum_to_the_total(
    cepalstat_debt_1239_json: str,
) -> None:
    """The measured reason the split is not stored as REIM indicators."""
    body = body_of(cepalstat_debt_1239_json)
    years = members_of(body, YEARS_DIMENSION)
    triples: dict[tuple[str, int], dict[int, Decimal]] = {}
    for row in body["data"]:
        if row.get("iso3") not in CENTRAL_AMERICA:
            continue
        key = (row["iso3"], int(years[row[f"dim_{YEARS_DIMENSION}"]]))
        triples.setdefault((key, row[f"dim_{INSTITUTIONAL_COVERAGE}"]), {})[
            row[f"dim_{DEBT_CLASSIFICATION}"]
        ] = Decimal(str(row["value"]))

    complete = [
        v for v in triples.values() if {TOTAL_BY_RESIDENCE, INTERNAL_DEBT, EXTERNAL_DEBT} <= set(v)
    ]
    exact = [v for v in complete if v[TOTAL_BY_RESIDENCE] == v[INTERNAL_DEBT] + v[EXTERNAL_DEBT]]

    assert len(complete) == 415
    assert len(exact) == 303


def test_nicaragua_1996_is_the_largest_real_move(cepalstat_debt_1240_json: str) -> None:
    """HIPC and Paris Club relief. Every threshold is set to clear it."""
    cells = slice_of(cepalstat_debt_1240_json)

    assert cells[("NIC", 1995)] == Decimal("185.3")
    assert cells[("NIC", 1996)] == Decimal("96.7")


def test_the_ratio_exceeds_one_hundred_percent(cepalstat_debt_1240_json: str) -> None:
    """Why max_value stays null in the quality rules."""
    values = list(slice_of(cepalstat_debt_1240_json).values())

    assert max(values) == Decimal("222.1")
    assert min(values) == Decimal("14")
```

- [ ] **Step 4: Run them**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_debt_connector.py -v`
Expected: PASS, all of them. They read the recordings directly and do not import
the connector, which does not exist yet.

If a count differs, the recording differs from 2026-09-03. Update the constant
to what you actually recorded and note it in the commit message — never edit the
recording to match the number.

- [ ] **Step 5: Document the fixtures**

Add to the recorded-sources table in `tests/fixtures/README.md`:

```markdown
| `cepalstat_debt_1239.json.gz` | `GET https://api-cepalstat.cepal.org/cepalstat/api/v1/indicator/1239/data?lang=en`, byte-for-byte, gzipped only to keep the repo small (617 KB → ~60 KB). Tests decompress it before parsing. The **complete** response — 145 countries, all four institutional coverages and all six classification members — because that is what proves the filter to central government and to Total-public-debt-by-residence works at all. | 2026-09-03 |
| `cepalstat_debt_1240.json.gz` | Same endpoint, indicator `1240` — the same stock as a percentage of GDP (635 KB → ~62 KB). Recorded so the six cells where the two units disagree on coverage are asserted against both published series rather than one. | 2026-09-03 |
```

Replace the `~60 KB` and `~62 KB` figures with the real ones from
`ls -l tests/fixtures/cepalstat_debt_*.json.gz`.

- [ ] **Step 6: Run the four gates, each on its own line, and read every exit code**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy reim apps
.venv/bin/python -m pytest tests/ -m "not live and not integration"
```

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/cepalstat_debt_1239.json.gz \
        tests/fixtures/cepalstat_debt_1240.json.gz \
        tests/fixtures/README.md tests/conftest.py \
        tests/unit/test_cepalstat_debt_connector.py
git commit -m "test(cepalstat): record the two responses a debt run makes

Complete responses, not excerpts: 145 countries and all 24 coverage-by-
classification combinations, which is what proves the filter down to the
one stored slice does anything.

The tests pin the findings the design argues from, so a re-record that
moves them fails loudly rather than quietly: three classification members
carry no rows anywhere, the internal and external series sum to the total
in only 303 of 415 cells, and the two units differ by exactly six cells in
opposite directions.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: The connector — `extract` and `transform`

**Files:**
- Create: `reim/ingestion/connectors/regional/cepalstat_debt.py`
- Test: `tests/unit/test_cepalstat_debt_connector.py`

**Interfaces:**
- Consumes: `CepalstatConnector` from
  `reim.ingestion.connectors.regional.cepalstat`, supplying
  `_ensure_envelope_ok(text, cepal_id, url)`, `_decode(text, cepal_id)`,
  `_members_of(body, dimension_id, name, cepal_id)`,
  `_label_of(row, labels, dimension_id, name, cepal_id)`,
  `_value_of(row, cepal_id)`, `COUNTRY_DIMENSION` and `YEARS_DIMENSION`.
- Produces: `CepalstatDebtConnector`, `SERIES: tuple[SeriesSpec, ...]`,
  `CENTRAL_AMERICA`, `CENTRAL_GOVERNMENT`, `TOTAL_BY_RESIDENCE`. Tasks 4 and 5
  consume all of them.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cepalstat_debt_connector.py`:

```python
from datetime import UTC, datetime

from reim.core.constants import Frequency
from reim.core.exceptions import TransformationError
from reim.domain.pipelines.models import NormalizedObservation, RawDataset
from reim.domain.sources.catalog import load_catalog
from reim.ingestion.connectors.regional.cepalstat_debt import CepalstatDebtConnector
from tests.conftest import REPO_ROOT

MILLIONS = Decimal("1000000")


def build_connector() -> CepalstatDebtConnector:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    return CepalstatDebtConnector(catalog.get("cepalstat_debt_annual"))


def build_raw(payload: dict[int, str]) -> RawDataset:
    return RawDataset(
        source_key="cepalstat_debt_annual",
        retrieved_at=datetime(2026, 9, 3, 12, 0, tzinfo=UTC),
        source_url="https://api-cepalstat.cepal.org/cepalstat/api/v1",
        payload=payload,
        content_type="application/json",
        http_status=200,
    )


@pytest.fixture
def raw(cepalstat_debt_1239_json: str, cepalstat_debt_1240_json: str) -> RawDataset:
    return build_raw({1239: cepalstat_debt_1239_json, 1240: cepalstat_debt_1240_json})


def by_code(observations: list[NormalizedObservation]) -> dict[str, list[NormalizedObservation]]:
    out: dict[str, list[NormalizedObservation]] = {}
    for obs in observations:
        out.setdefault(obs.indicator_code, []).append(obs)
    return out


def test_transform_produces_every_stored_cell(raw: RawDataset) -> None:
    grouped = by_code(build_connector().transform(raw))

    assert len(grouped["public_debt_usd_annual"]) == 226
    assert len(grouped["public_debt_pct_gdp_annual"]) == 230


def test_only_central_government_totals_survive(raw: RawDataset) -> None:
    """The other eleven non-empty combinations are discarded."""
    observations = build_connector().transform(raw)
    usd = {
        (obs.country_iso3, obs.period.label)
        for obs in observations
        if obs.indicator_code == "public_debt_usd_annual"
    }

    assert ("NIC", "1990") in usd
    assert ("BLZ", "2020") in usd
    assert ("BLZ", "2021") not in usd
    assert len(usd) == 226


def test_only_the_seven_countries_survive(raw: RawDataset) -> None:
    """Mexico and the regional aggregates with iso3 null both fall out."""
    observations = build_connector().transform(raw)

    assert {obs.country_iso3 for obs in observations} == CENTRAL_AMERICA


def test_the_published_millions_are_scaled_to_whole_usd(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)
    costa_rica = next(
        obs
        for obs in observations
        if obs.indicator_code == "public_debt_usd_annual"
        and obs.country_iso3 == "CRI"
        and obs.period.label == "2025"
    )

    assert costa_rica.value_numeric == Decimal("62777") * MILLIONS
    assert costa_rica.unit == "current USD"
    assert costa_rica.currency_code == "USD"
    assert costa_rica.raw_metadata["cepalstat_scale_applied"] == "1e6"


def test_the_ratio_is_stored_exactly_as_published(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)
    costa_rica = next(
        obs
        for obs in observations
        if obs.indicator_code == "public_debt_pct_gdp_annual"
        and obs.country_iso3 == "CRI"
        and obs.period.label == "2025"
    )

    assert costa_rica.value_numeric == Decimal("60.4")
    assert costa_rica.unit == "percent of GDP"
    assert costa_rica.currency_code is None
    assert costa_rica.raw_metadata["cepalstat_scale_applied"] == "1"


def test_periods_are_calendar_years(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)
    sample = next(obs for obs in observations if obs.period.label == "2024")

    assert sample.period.frequency is Frequency.ANNUAL
    assert sample.period.start.isoformat() == "2024-01-01"
    assert sample.period.end.isoformat() == "2024-12-31"


def test_source_record_ids_are_unique_and_readable(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)
    ids = [obs.source_record_id for obs in observations]

    assert len(set(ids)) == len(ids) == 456
    assert "cepalstat:1239:CRI:2025" in ids


def test_the_fetch_date_never_reaches_stored_metadata(raw: RawDataset) -> None:
    """credits[0] moves between runs; only the citation is kept."""
    observations = build_connector().transform(raw)
    credits = observations[0].raw_metadata["cepalstat_credits"]

    assert "CEPALSTAT" in credits
    assert not any(credit.startswith("202") for credit in credits)


def test_a_renamed_coverage_member_raises(raw: RawDataset) -> None:
    """Selecting by id is silent on a relabel; the assertion is not."""
    document = json.loads(raw.payload[1239])
    for dimension in document["body"]["dimensions"]:
        if dimension["id"] == INSTITUTIONAL_COVERAGE:
            for member in dimension["members"]:
                if member["id"] == CENTRAL_GOVERNMENT:
                    member["name"] = "General government"

    doctored = build_raw({1239: json.dumps(document), 1240: raw.payload[1240]})

    with pytest.raises(TransformationError, match="General government"):
        build_connector().transform(doctored)


def test_a_renamed_classification_member_raises(raw: RawDataset) -> None:
    document = json.loads(raw.payload[1239])
    for dimension in document["body"]["dimensions"]:
        if dimension["id"] == DEBT_CLASSIFICATION:
            for member in dimension["members"]:
                if member["id"] == TOTAL_BY_RESIDENCE:
                    member["name"] = "Total public debt"

    doctored = build_raw({1239: json.dumps(document), 1240: raw.payload[1240]})

    with pytest.raises(TransformationError, match="Total public debt"):
        build_connector().transform(doctored)


def test_a_missing_coverage_dimension_raises(raw: RawDataset) -> None:
    document = json.loads(raw.payload[1239])
    document["body"]["dimensions"] = [
        d for d in document["body"]["dimensions"] if d["id"] != INSTITUTIONAL_COVERAGE
    ]

    doctored = build_raw({1239: json.dumps(document), 1240: raw.payload[1240]})

    with pytest.raises(TransformationError, match="institutional coverage dimension"):
        build_connector().transform(doctored)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_debt_connector.py -v`
Expected: FAIL — `ModuleNotFoundError: reim.ingestion.connectors.regional.cepalstat_debt`.

- [ ] **Step 3: Write the connector**

Create `reim/ingestion/connectors/regional/cepalstat_debt.py`:

```python
"""Central America — central government public debt, published by CEPAL.

The API, its lack of documentation and the way its routes were recovered are
documented in ``cepalstat.py``, which this connector's base class comes from;
only what differs is recorded here.

What differs is the shape of the cube. These two indicators carry four
dimensions rather than two: country and year as usual, plus a debt
classification with six members and an institutional coverage with four. A
country-year cell is not identified until both are pinned, so this connector
pins them and stores one slice.

1. **Only three of the six classification members carry rows** — Total public
   debt by residence, Internal debt and External debt. Currency, rate and
   maturity classification are grouping nodes in CEPAL's tree, published as
   members with nothing behind them, empty for all 145 countries.
2. **Only central government covers all seven countries.** Nonfinancial public
   sector omits Guatemala and Honduras, public sector mostly stops in 2011, and
   state and local governments exists for Honduras alone. CEPAL's own
   methodology note says the published figure "is refered to the central
   government gross public debt stock".
3. **The internal and external series do not sum to the total** — in 1239 only
   303 of 415 complete triples are exact, and three are off by more than 1%.
   That is why only the total is stored: publishing the split would invite a
   subtraction the source does not support.

The ratio in 1240 is *not* this dollar figure divided by REIM's
``gdp_current_usd_annual``. CEPAL divides by each country's GDP in local
currency converted at the IMF's 31 December rate; across the 225 shared
country-years the two disagree by 5% or more in 52 of them, worst 23.7%. Both
series are stored as published and nothing reconciles them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from reim.core.constants import Frequency
from reim.core.exceptions import TransformationError
from reim.domain.observations.periods import parse_period
from reim.domain.pipelines.models import NormalizedObservation, RawDataset
from reim.ingestion.connectors.regional.cepalstat import (
    YEARS_DIMENSION,
    CepalstatConnector,
)
from reim.ingestion.http import ensure_ok, fetch, http_client

#: This family's own dimensions; country and years come from the base module.
DEBT_CLASSIFICATION = 10590
INSTITUTIONAL_COVERAGE = 10690

#: The one slice REIM stores, selected by id and asserted by name.
CENTRAL_GOVERNMENT = 10692
CENTRAL_GOVERNMENT_NAME = "Central government"
TOTAL_BY_RESIDENCE = 10609
TOTAL_BY_RESIDENCE_NAME = "Total public debt (classification by residence)"

#: Published in millions of dollars, stored in whole dollars, matching the GDP
#: totals so the two line up.
MILLIONS = Decimal("1000000")

CENTRAL_AMERICA = frozenset({"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"})


@dataclass(frozen=True, slots=True)
class SeriesSpec:
    """One CEPAL indicator id, the REIM code it feeds, and how it is stored."""

    cepal_id: int
    indicator_code: str
    unit: str
    scale: Decimal


SERIES: tuple[SeriesSpec, ...] = (
    SeriesSpec(1239, "public_debt_usd_annual", "current USD", MILLIONS),
    SeriesSpec(1240, "public_debt_pct_gdp_annual", "percent of GDP", Decimal(1)),
)


class CepalstatDebtConnector(CepalstatConnector):
    """Central government gross public debt, in dollars and as a share of GDP."""

    connector_key = "cepalstat_debt_annual"
    version = "1.0.0"
    expected_frequency = Frequency.ANNUAL

    async def extract(self) -> RawDataset:
        """Fetch both indicators in English.

        Two requests. No Spanish request: this family's English member names
        are real translations, unlike the monetary family's.

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
                "institutional_coverage": CENTRAL_GOVERNMENT_NAME,
                "debt_classification": TOTAL_BY_RESIDENCE_NAME,
            },
        )

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Filter the four-dimensional cube down to one series per indicator.

        Pure function of ``raw``.

        Raises:
            TransformationError: The payload is not the expected mapping, a
                dimension is missing, a selected member has been renamed, or a
                row names a year member that does not exist.
        """
        payload = raw.payload
        if not isinstance(payload, dict):
            msg = "CEPALSTAT payload must be a mapping of indicator id to response text"
            raise TransformationError(msg, source_key=self.source.key)

        observations: list[NormalizedObservation] = []
        for spec in SERIES:
            text = payload.get(spec.cepal_id) or payload.get(str(spec.cepal_id))
            if text is None:
                msg = f"CEPALSTAT payload is missing indicator {spec.cepal_id}"
                raise TransformationError(msg, source_key=self.source.key)
            observations.extend(self._read_series(spec, str(text), raw))

        observations.sort(key=lambda obs: (obs.indicator_code, obs.country_iso3, obs.period.start))
        return observations

    def _read_series(
        self, spec: SeriesSpec, text: str, raw: RawDataset
    ) -> list[NormalizedObservation]:
        """Turn one indicator's payload into its Central American observations."""
        body = self._decode(text, spec.cepal_id)["body"]
        self._assert_selected_members(body, spec.cepal_id)
        years = self._members_of(body, YEARS_DIMENSION, "years", spec.cepal_id)
        published_unit = str(body["metadata"]["unit"])
        sources = {source["id"]: source["description"] for source in body["sources"]}
        credits = [entry["description"] for entry in body["credits"] if entry["id"] != 0]
        scale = "1e6" if spec.scale == MILLIONS else "1"

        observations: list[NormalizedObservation] = []
        for row in body["data"]:
            iso3 = row.get("iso3")
            if iso3 not in CENTRAL_AMERICA:
                continue
            if row.get(f"dim_{INSTITUTIONAL_COVERAGE}") != CENTRAL_GOVERNMENT:
                continue
            if row.get(f"dim_{DEBT_CLASSIFICATION}") != TOTAL_BY_RESIDENCE:
                continue
            year = self._label_of(row, years, YEARS_DIMENSION, "year", spec.cepal_id)
            value = self._value_of(row, spec.cepal_id)
            observations.append(
                NormalizedObservation(
                    country_iso3=str(iso3),
                    indicator_code=spec.indicator_code,
                    source_key=self.source.key,
                    period=parse_period(year, Frequency.ANNUAL),
                    unit=spec.unit,
                    currency_code="USD" if spec.scale == MILLIONS else None,
                    value_numeric=value * spec.scale,
                    retrieved_at=raw.retrieved_at,
                    source_url=f"{raw.source_url}/indicator/{spec.cepal_id}/data",
                    source_record_id=f"cepalstat:{spec.cepal_id}:{iso3}:{year}",
                    raw_metadata={
                        "cepalstat_indicator_id": spec.cepal_id,
                        "cepalstat_published_value": format(value.normalize(), "f"),
                        "cepalstat_published_unit": published_unit,
                        "cepalstat_scale_applied": scale,
                        "cepalstat_institutional_coverage": CENTRAL_GOVERNMENT_NAME,
                        "cepalstat_debt_classification": TOTAL_BY_RESIDENCE_NAME,
                        "cepalstat_source": sources.get(row.get("source_id"), ""),
                        # credits[0] is CEPAL's own fetch date and changes
                        # between runs; only the citation is kept.
                        "cepalstat_credits": credits,
                        "contract_status": "verified",
                    },
                )
            )
        return observations

    def _assert_selected_members(self, body: Any, cepal_id: int) -> None:
        """Confirm the two ids REIM selects still mean what they meant.

        Rows are filtered by member id, which is silent when CEPAL relabels a
        member: the filter would keep matching and REIM would store a different
        series under the same indicator code. Reading the names back turns that
        into a message that says what changed.

        Raises:
            TransformationError: A dimension is absent or a selected member has
                been renamed.
        """
        for dimension_id, name, member_id, expected in (
            (
                INSTITUTIONAL_COVERAGE,
                "institutional coverage",
                CENTRAL_GOVERNMENT,
                CENTRAL_GOVERNMENT_NAME,
            ),
            (
                DEBT_CLASSIFICATION,
                "debt classification",
                TOTAL_BY_RESIDENCE,
                TOTAL_BY_RESIDENCE_NAME,
            ),
        ):
            members = self._members_of(body, dimension_id, name, cepal_id)
            actual = members.get(member_id)
            if actual != expected:
                msg = (
                    f"CEPALSTAT {name} member {member_id} for indicator {cepal_id} "
                    f"is now {actual!r}, not {expected!r}; the stored series would "
                    f"change meaning silently"
                )
                raise TransformationError(msg, source_key=self.source.key)
```

`connector_key` must equal the catalog key exactly: `BaseConnector.__init__`
raises `ValueError` if they differ, so a typo here fails at construction rather
than at run time.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_debt_connector.py -v`
Expected: PASS, all of them.

`validate` is not implemented yet, so `BaseConnector`'s default is in force. It
is written in Task 4.

- [ ] **Step 5: Run the four gates, each on its own line, and read every exit code**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy reim apps
.venv/bin/python -m pytest tests/ -m "not live and not integration"
```

- [ ] **Step 6: Commit**

```bash
git add reim/ingestion/connectors/regional/cepalstat_debt.py \
        tests/unit/test_cepalstat_debt_connector.py
git commit -m "feat(cepalstat): parse the central government debt slice

A four-dimensional cube filtered to one coverage and one classification,
selected by member id because the row keys carry ids and not names.

Selecting by id is silent when CEPAL relabels a member: the filter keeps
matching and the same indicator code quietly starts carrying a different
series. So the names are read back and asserted, which turns that into a
message naming the old and the new string.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: `validate` — the two checks

**Files:**
- Modify: `reim/ingestion/connectors/regional/cepalstat_debt.py`
- Test: `tests/unit/test_cepalstat_debt_connector.py`

**Interfaces:**
- Consumes: `CepalstatDebtConnector.transform` from Task 3.
- Produces: `validate(observations) -> list[QualityResult]` returning exactly
  two results, named `cepalstat_debt_seven_countries` and
  `cepalstat_debt_annual_continuity`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cepalstat_debt_connector.py`:

```python
from reim.core.constants import CheckSeverity, CheckStatus
from reim.domain.pipelines.models import QualityResult


def results_of(observations: list[NormalizedObservation]) -> dict[str, QualityResult]:
    return {r.check_name: r for r in build_connector().validate(observations)}


def test_both_checks_pass_on_the_real_recordings(raw: RawDataset) -> None:
    results = build_connector().validate(build_connector().transform(raw))

    assert len(results) == 2
    assert all(result.status is CheckStatus.PASSED for result in results)


def test_a_missing_country_fails_critically(raw: RawDataset) -> None:
    observations = [obs for obs in build_connector().transform(raw) if obs.country_iso3 != "BLZ"]

    result = results_of(observations)["cepalstat_debt_seven_countries"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.CRITICAL
    assert "BLZ" in result.message


def test_a_hole_in_one_country_is_reported_as_a_warning(raw: RawDataset) -> None:
    """Pooling the seven would hide it: the others published that year."""
    observations = [
        obs
        for obs in build_connector().transform(raw)
        if not (
            obs.indicator_code == "public_debt_usd_annual"
            and obs.country_iso3 == "GTM"
            and obs.period.label == "2010"
        )
    ]

    result = results_of(observations)["cepalstat_debt_annual_continuity"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.WARNING
    assert "GTM 2010" in result.message


def test_a_shorter_span_is_not_itself_a_gap(raw: RawDataset) -> None:
    """Belize starts in 2011 and ends in 2020; neither is a hole."""
    result = results_of(build_connector().transform(raw))["cepalstat_debt_annual_continuity"]

    assert result.status is CheckStatus.PASSED


def test_every_check_is_dataset_level(raw: RawDataset) -> None:
    results = build_connector().validate(build_connector().transform(raw))

    assert all(result.observation_index is None for result in results)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_debt_connector.py -k "check or pass or gap or level" -v`
Expected: FAIL — `validate` returns the base class's empty list, so
`len(results) == 2` and the `KeyError` on the check names both fire.

- [ ] **Step 3: Implement the two checks**

First extend the imports at the top of
`reim/ingestion/connectors/regional/cepalstat_debt.py` — Task 3 deliberately
left these out, because an import used by nothing fails `ruff check`:

```python
from reim.core.constants import CheckSeverity, CheckType, Frequency
from reim.domain.pipelines.models import (
    NormalizedObservation,
    QualityResult,
    RawDataset,
)
```

Then append to `CepalstatDebtConnector` in the same file:

```text
    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert CEPALSTAT-specific expectations beyond the standard battery.

        Deliberately absent: any reconciliation of the ratio against REIM's
        own GDP series. CEPAL's denominator is a local-currency GDP converted
        at the IMF's 31 December rate, and across the 225 shared country-years
        the two disagree by 5% or more in 52 of them. A check would fail
        permanently by design, so the mismatch is documented instead.
        """
        return [
            self._check_seven_countries(observations),
            self._check_annual_continuity(observations),
        ]

    def _check_seven_countries(self, observations: list[NormalizedObservation]) -> QualityResult:
        """All seven must appear in both series."""
        seen = {obs.country_iso3 for obs in observations}
        missing = sorted(CENTRAL_AMERICA - seen)

        if not missing:
            return QualityResult.passed(
                "cepalstat_debt_seven_countries",
                CheckType.COMPLETENESS,
                f"All {len(CENTRAL_AMERICA)} countries returned figures",
                expected_value=str(len(CENTRAL_AMERICA)),
                actual_value=str(len(seen & CENTRAL_AMERICA)),
            )
        return QualityResult.failure(
            "cepalstat_debt_seven_countries",
            CheckType.COMPLETENESS,
            CheckSeverity.CRITICAL,
            f"{len(missing)} country/countries returned nothing: {', '.join(missing)}",
            expected_value=str(len(CENTRAL_AMERICA)),
            actual_value=str(len(seen & CENTRAL_AMERICA)),
        )

    def _check_annual_continuity(self, observations: list[NormalizedObservation]) -> QualityResult:
        """Holes inside each country's own span, per indicator.

        Walked per country and per series: pooling them would hide a hole
        whenever another country published that year, and six of the seven
        usually did. Belize's shorter span is not a hole — the walk starts at
        each country's own first year.
        """
        spans: dict[tuple[str, str], set[int]] = {}
        for obs in observations:
            spans.setdefault((obs.indicator_code, obs.country_iso3), set()).add(
                int(obs.period.label)
            )

        missing: list[str] = []
        expected = present = 0
        for (code, iso3), years in sorted(spans.items()):
            if len(years) < 2:
                continue
            first, last = min(years), max(years)
            expected += last - first + 1
            present += len(years)
            missing.extend(
                f"{iso3} {year} ({code})" for year in range(first, last + 1) if year not in years
            )

        if not missing:
            return QualityResult.passed(
                "cepalstat_debt_annual_continuity",
                CheckType.COMPLETENESS,
                f"No gaps in any of the {len(spans)} country-series",
                expected_value=str(expected),
                actual_value=str(present),
            )

        shown = ", ".join(missing[:5])
        suffix = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
        return QualityResult.failure(
            "cepalstat_debt_annual_continuity",
            CheckType.COMPLETENESS,
            CheckSeverity.WARNING,
            f"{len(missing)} missing year(s) inside a country's own span: {shown}{suffix}",
            expected_value=str(expected),
            actual_value=str(present),
        )
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_debt_connector.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the four gates, each on its own line, and read every exit code**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy reim apps
.venv/bin/python -m pytest tests/ -m "not live and not integration"
```

- [ ] **Step 6: Commit**

```bash
git add reim/ingestion/connectors/regional/cepalstat_debt.py \
        tests/unit/test_cepalstat_debt_connector.py
git commit -m "test(cepalstat): cover the two debt quality checks

Continuity is measured inside each country's own span, so Belize starting
in 2011 and ending in 2020 is not a finding while a hole in the middle of
Guatemala's run is one.

No check reconciles the ratio against REIM's GDP series. The docstring
records why: they disagree by 5% or more in 52 of 225 country-years because
CEPAL divides by a local-currency GDP at the IMF's 31 December rate, so a
check would fail permanently by design.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: `extract` coverage

**Files:**
- Modify: `tests/unit/test_cepalstat_debt_connector.py`

**Interfaces:**
- Consumes: `CepalstatDebtConnector.extract` written in Task 3.

`extract` was written in Task 3 so the module was importable. This task pins its
behaviour.

- [ ] **Step 1: Write the tests**

Append to `tests/unit/test_cepalstat_debt_connector.py`:

```python
import httpx
import respx

from reim.core.exceptions import ExtractionError

BASE_URL = "https://api-cepalstat.cepal.org/cepalstat/api/v1"


def data_url(cepal_id: int) -> str:
    return f"{BASE_URL}/indicator/{cepal_id}/data"


def json_response(text: str) -> httpx.Response:
    return httpx.Response(200, text=text, headers={"content-type": "application/json"})


@respx.mock
async def test_a_run_makes_one_request_per_indicator(
    cepalstat_debt_1239_json: str, cepalstat_debt_1240_json: str
) -> None:
    routes = [
        respx.get(data_url(1239)).mock(return_value=json_response(cepalstat_debt_1239_json)),
        respx.get(data_url(1240)).mock(return_value=json_response(cepalstat_debt_1240_json)),
    ]

    raw = await build_connector().extract()

    assert all(route.call_count == 1 for route in routes)
    assert set(raw.payload) == {1239, 1240}


@respx.mock
async def test_both_requests_are_english(
    cepalstat_debt_1239_json: str, cepalstat_debt_1240_json: str
) -> None:
    """No Spanish request exists in this family, and none should appear."""
    respx.get(data_url(1239)).mock(return_value=json_response(cepalstat_debt_1239_json))
    respx.get(data_url(1240)).mock(return_value=json_response(cepalstat_debt_1240_json))

    await build_connector().extract()

    assert len(respx.calls) == 2
    assert all(call.request.url.params["lang"] == "en" for call in respx.calls)


@respx.mock
async def test_the_selected_slice_is_recorded_in_metadata(
    cepalstat_debt_1239_json: str, cepalstat_debt_1240_json: str
) -> None:
    """A reader of raw_metadata should not have to guess which cube slice this is."""
    respx.get(data_url(1239)).mock(return_value=json_response(cepalstat_debt_1239_json))
    respx.get(data_url(1240)).mock(return_value=json_response(cepalstat_debt_1240_json))

    raw = await build_connector().extract()

    assert raw.metadata["institutional_coverage"] == "Central government"
    assert raw.metadata["debt_classification"] == (
        "Total public debt (classification by residence)"
    )


@respx.mock
async def test_a_failing_envelope_raises_even_on_http_200() -> None:
    """CEPAL answers an unknown id with 500 and success:false, never 404."""
    envelope = json.dumps(
        {
            "header": {"success": False, "code": 404, "message": "Not found"},
            "body": {"data": []},
        }
    )
    respx.get(data_url(1239)).mock(return_value=json_response(envelope))

    with pytest.raises(ExtractionError, match="reported failure 404"):
        await build_connector().extract()


@respx.mock
async def test_an_empty_data_array_raises(cepalstat_debt_1239_json: str) -> None:
    body = json.loads(cepalstat_debt_1239_json)
    body["body"]["data"] = []
    respx.get(data_url(1239)).mock(return_value=json_response(json.dumps(body)))

    with pytest.raises(ExtractionError, match="no rows"):
        await build_connector().extract()


@pytest.mark.live
async def test_the_real_api_still_answers_as_recorded() -> None:
    """Opt-in. Proves the contract, not the data: shape, not values."""
    connector = build_connector()
    observations = connector.transform(await connector.extract())

    assert len(observations) >= 400
    assert {obs.country_iso3 for obs in observations} == CENTRAL_AMERICA
    assert all(result.status is CheckStatus.PASSED for result in connector.validate(observations))
```

- [ ] **Step 2: Run them**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_debt_connector.py -m "not live" -v`
Expected: PASS.

**If any of them fails, the failure is real — fix `extract`, never the test.**
Do not relax the `match="reported failure 404"` or `match="no rows"` patterns;
those two strings are the whole point of the envelope check.

- [ ] **Step 3: Run the live test once, deliberately**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_debt_connector.py -m live -v`
Expected: PASS, two real requests taking about 6 seconds. If it fails, the API
changed since 2026-09-03 — record what changed in `docs/sources.md` before
adapting the connector.

- [ ] **Step 4: Run the four gates, each on its own line, and read every exit code**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy reim apps
.venv/bin/python -m pytest tests/ -m "not live and not integration"
```

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_cepalstat_debt_connector.py
git commit -m "test(cepalstat): cover the two-request debt extract

Pins that both requests are English. The monetary connector next door
fetches its dimensions in Spanish for a specific reason, and the risk here
is someone copying that pattern into a family that does not need it.

Also pins the selected cube slice into raw_metadata, so a reader of a
stored observation can tell which of the 24 coverage-by-classification
combinations it came from without reading the connector.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Enable, run for real, and record the source

**Files:**
- Modify: `sources/catalog.yml`, `tests/unit/test_catalog.py`, `docs/sources.md`, `ROADMAP.md`, `README.md`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Enable the source**

In `sources/catalog.yml`, replace the `cepalstat_debt_annual` entry's

```text
    enabled: false
    disabled_reason: >-
      Connector under construction; enabled once it has been run end to end
      against a real database.
```

with `    enabled: true`.

Then update the assertion written in Task 1: rename
`test_the_debt_source_is_registered_and_disabled` to
`test_the_debt_source_is_registered_and_enabled` and change `assert not
entry.enabled` to `assert entry.enabled`. This is the one test edit the plan
sanctions; every other failing test is a real failure.

- [ ] **Step 2: Validate the catalog**

Run: `.venv/bin/python -m reim.cli catalog validate`
Expected: `19 source(s), 19 enabled`, `33 indicator rule(s)`, all 19 connectors
importing cleanly.

- [ ] **Step 3: Run it end to end against a real database**

```bash
make db-up CONTAINER_ENGINE=podman
export REIM_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim
.venv/bin/alembic upgrade head
.venv/bin/python -m reim.cli db seed
.venv/bin/python -m reim.cli pipeline run cepalstat_debt_annual
```

`alembic upgrade head` is required on a fresh container; `db seed` fails with
`relation "countries" does not exist` without it.

Expected: `success extracted=456 inserted=456 ... rejected=0`, and **no failed
quality checks**. Confirm:

```bash
podman exec reim-test-postgres psql -U reim -d reim -c "
select check_name, status, severity, indicator_code, actual_value
from data_quality_checks where status = 'failed';"
```

Expected: zero rows. **Any failed check is a real defect — stop and investigate
rather than proceeding.** Unlike the monetary increment, nothing here is
expected to warn: the newest period is 2025 and the freshness threshold is 600
days.

- [ ] **Step 4: Prove idempotency**

Run the pipeline a second time.
Expected: `inserted=0 unchanged=456 rejected=0`. If `unchanged` is not 456,
something in `raw_metadata` or the value is unstable between runs — check that
`credits[0]` did not creep back in.

- [ ] **Step 5: Check what landed**

```bash
podman exec reim-test-postgres psql -U reim -d reim -c "
select i.code, count(*), min(o.period_start), max(o.period_start)
from observations o join indicators i on i.id = o.indicator_id
where i.code like 'public_debt%' group by i.code order by i.code;"
```

Expected: 230 for `public_debt_pct_gdp_annual` and 226 for
`public_debt_usd_annual`, both starting 1990-01-01 and ending 2025-01-01.

Then confirm the units and that the ratio carries no currency:

```bash
podman exec reim-test-postgres psql -U reim -d reim -c "
select i.code, o.unit, o.currency_code, count(*)
from observations o join indicators i on i.id = o.indicator_id
where i.code like 'public_debt%' group by 1,2,3 order by 1;"
```

Expected: exactly two rows — `current USD` with `USD`, and `percent of GDP`
with a null currency.

- [ ] **Step 6: Record the source**

Add a `### CEPAL — central government public debt` section to the "Enabled"
part of `docs/sources.md`, following the shape of the two CEPAL sections above
it. It must cover, at minimum:

- The two indicator ids, the per-country coverage table and the volume.
- **Which slice of the cube is stored and why**: central government of four
  coverages, Total-by-residence of six classifications, with the measured
  evidence — three classification members empty across all 145 countries, and
  only central government covering all seven countries across 1990–2025.
- **That the internal and external series are not stored**, with the measured
  reason: 303 of 415 complete triples sum exactly, three are off by more than
  1%.
- **That the ratio does not reconcile with REIM's own GDP series**, with the
  measured spread — 52 of 225 country-years off by 5% or more, worst Honduras
  1990 at 23.7% — and CEPAL's stated denominator.
- **That the two units differ by six cells**, naming NIC 1990 and BLZ 2021–2025.
- **That the ratio exceeds 100%**, reaching 222.1%, and that `max_value` is
  therefore null by choice.
- **That the English member names are real translations here**, unlike the
  monetary family, so this connector makes no Spanish request.
- The licence, which is CEPAL's and already quoted in the GDP section — link to
  it rather than repeating it.

Then delete the "Reachable, not ingested" subsection from the GDP section
entirely: public debt was its last row, and an empty subsection is worse than
no subsection. Check whether anything else in the file links to it.

- [ ] **Step 7: Close the roadmap line**

In `ROADMAP.md`, add the fiscal increment to the v0.3.0 section: central
government public debt for all seven countries, 456 observations, 1990–2025,
in dollars and as a share of GDP, REIM's first fiscal data. Note that the wider
institutional coverages and the internal/external split were deliberately not
ingested, with the reason in one clause each.

Check the v0.3.0 preamble — it currently reads "This release is five
independent pieces, not one increment. Three are done, and a fourth has its
first country." Update the count to match reality after this lands.

- [ ] **Step 8: Update the README**

- Add CEPAL's debt row to the source table: all seven, annual, "central
  government public debt stock, in dollars and as a share of GDP", 1990 onward.
- Update the counts: **19 pipelines, 33 indicators**, roughly **48,900**
  observations for a complete rebuild, and the `run-all` figure from ~43,400 to
  ~43,900.
- The "Three sources are rescaled" limitation becomes four, and the new clause
  must say the debt stock is rescaled from millions of USD to whole USD while
  its companion ratio is stored untouched.
- Add a limitation stating that the debt ratio's GDP denominator is **not**
  REIM's `gdp_current_usd_annual`, that dividing one series into the other does
  not reconcile, and that REIM stores both as published rather than choosing
  between them.

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
git add sources/catalog.yml tests/unit/test_catalog.py docs/sources.md \
        ROADMAP.md README.md
git commit -m "feat: CEPALSTAT public debt — REIM's first fiscal series

456 observations from two requests: central government gross public debt
for all seven countries, 1990-2025, in dollars and as a share of GDP.

The cube offers 24 coverage-by-classification combinations and this stores
one. Three classification members carry no rows anywhere; of the four
institutional coverages only central government covers all seven countries,
which is also what CEPAL's methodology note says the published figure means.

Two things measured and deliberately not built on. The internal and
external series sum to the total in only 303 of 415 cells, so they are not
stored. The ratio's implied GDP disagrees with REIM's own GDP series by 5%
or more in 52 of 225 country-years, because CEPAL divides by a
local-currency GDP at the IMF's 31 December rate; both series are stored as
published and nothing reconciles them.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage.** Every section of
`docs/superpowers/specs/2026-09-03-cepalstat-debt-design.md` maps to a task:
§1 the roadmap line → Task 6 steps 6 and 7; §2 the source → Task 1 step 4 and
Task 2; §3 the slice decision → Task 3 step 3 and Task 6 step 6; §4 the measured
findings → Task 2's fixture tests; §5 decisions D1-D7 → D1 Tasks 1 and 3, D2
Task 5's language test, D3 Task 3's `_assert_selected_members`, D4 Task 3's
scale, D5 Task 2's summation test, D6 Task 4's `validate` docstring and Task 6
step 8, D7 Task 3's new module; §6 components → Tasks 1 and 3; §7 quality →
Tasks 1 and 4; §8 testing → Tasks 2, 3, 4 and 5; §9 volume → Task 6; §10 out of
scope → nothing to build.

**Placeholders.** None. Every code step carries the code; every documentation
step lists what the prose must state rather than saying "document it". Two
figures are deliberately left to be filled from measurement — the gzipped
fixture sizes in Task 2 step 5 — and the step says where to read them.

**Type consistency.** `SeriesSpec` here has four fields (`cepal_id`,
`indicator_code`, `unit`, `scale`), matching the GDP connector's rather than the
monetary connector's two, because these two series differ in both unit and
scale. The name is reused deliberately and the dataclass is not shared; Task 7
of the monetary plan already established that merging them is not worth a
parameter for every caller. `_assert_selected_members(body, cepal_id)` is
defined in Task 3 and called once, from `_read_series`. `_members_of` and
`_label_of` are used with the base class's signatures,
`(body, dimension_id, name, cepal_id)` and
`(row, labels, dimension_id, name, cepal_id)`. `CENTRAL_AMERICA` is defined in
Task 3 and consumed by Task 4's checks and Task 5's live test.

**One thing the executor should know.** Task 6 step 3 expects **zero** failed
checks. The monetary increment expected three, and that exception was specific
to Honduras being years behind on a monthly series. Here the newest period is
2025 and the freshness threshold is 600 days, so any failure is a defect.
