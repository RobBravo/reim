# CEPALSTAT regional consumer price index — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest CEPALSTAT indicator 365 as `cpi_index_monthly` — 3,451
observations, seven countries, 1980 onward — so `/compare` can answer what
inflation looks like across Central America.

**Architecture:** A `CepalstatConnector` subclass on the exchange-rate
connector's shape: one request, month names read from the data response's own
dimension table, values stored exactly as published. Its own quality battery,
because this series' hazards are nothing like the exchange rate's.

**Tech Stack:** Python 3.13, httpx + respx, SQLAlchemy 2, pytest, ruff, mypy.
Run tools as `.venv/bin/<tool>` — there is no `pip` in the venv. Integration
work needs `make db-up CONTAINER_ENGINE=podman`.

**Spec:** `docs/superpowers/specs/2026-09-06-cepalstat-regional-cpi-design.md`

## Global Constraints

* **Values are stored exactly as published** — no scaling, no rounding to the
  declared two decimals. The series publishes up to eight (spec §3.6) and
  Nicaragua publishes down to `2E-9` in scientific notation (§3.4).
* **No base year is stored and none goes in the unit.** CEPAL's declared bases
  are wrong for three of the five it declares (§3.1). The unit is `index`.
* **Nothing is derived.** The index only; no month-on-month or year-on-year
  (D2).
* **Only the seven Central American countries**, filtered from 40.
* **Tests never call an official source.** The payload is replayed from a
  recording through `respx`.
* Measured facts this plan asserts, all from 2026-09-06: 3,451 rows for the
  seven of 16,913; four countries 1980-01…2026-07 (559 months), Costa Rica
  1980-01…2026-06 (558), Honduras 1994-01 (391), Belize 1990-11…2026-06 (266
  in a 428-month span); Guatemala
  2009-12 = `94.882` and 2010-01 = `54.4831537`; El Salvador 1985-07 =
  `11.473`, 1985-08 = `7.157`, 1985-09 = `11.928`.

---

### Task 1: Record the response

**Files:**
- Create: `tests/fixtures/cepalstat_cpi_365.json.gz`
- Modify: `tests/fixtures/README.md`
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: session-scoped fixture `cepalstat_cpi_365_json() -> str`.

- [ ] **Step 1: Record it**

```bash
cd "$(git rev-parse --show-toplevel)"
curl -s -H 'User-Agent: REIM/0.1.0 (Regional Economic Intelligence Monitor; +https://github.com/RobBravo/reim)' \
  'https://api-cepalstat.cepal.org/cepalstat/api/v1/indicator/365/data?lang=en' \
  | gzip -9 > tests/fixtures/cepalstat_cpi_365.json.gz
ls -l tests/fixtures/cepalstat_cpi_365.json.gz
```

The uncompressed response is 2.02 MB and takes 11–19 s.

- [ ] **Step 2: Verify the recording holds what the plan claims**

```bash
.venv/bin/python - <<'PY'
import gzip, json, collections
body = json.loads(gzip.decompress(open("tests/fixtures/cepalstat_cpi_365.json.gz","rb").read()))["body"]
dims = {d["id"]: {m["id"]: m["name"] for m in d["members"]} for d in body["dimensions"]}
EN = {n: i for i, n in enumerate(
    ["January","February","March","April","May","June",
     "July","August","September","October","November","December"], 1)}
print("rows:", len(body["data"]), " countries:", len({r["iso3"] for r in body["data"]}))
print("unit:", body["metadata"]["unit"], "| features:", body["metadata"]["data_features"])
print("month members translated:", sorted({m for m in dims[515].values()}) == sorted(EN))
seven = {"NIC","GTM","SLV","HND","CRI","PAN","BLZ"}
cells = collections.defaultdict(dict)
for r in body["data"]:
    if r["iso3"] in seven:
        cells[r["iso3"]][(int(dims[29117][r["dim_29117"]]), EN[dims[515][r["dim_515"]]])] = r["value"]
print("rows for the seven:", sum(len(v) for v in cells.values()))
print("GTM 2009-12 / 2010-01:", cells["GTM"][(2009,12)], "/", cells["GTM"][(2010,1)])
print("SLV 1985-07/08/09:", cells["SLV"][(1985,7)], cells["SLV"][(1985,8)], cells["SLV"][(1985,9)])
print("NIC smallest:", min(cells["NIC"].values(), key=lambda v: float(v)))
print("null source_id rows:", sum(1 for r in body["data"]
                                  if r["iso3"] in seven and r["source_id"] is None))
PY
```

Expected, exactly:

```text
rows: 16913  countries: 40
unit: Index | features: Official country figures 
month members translated: True
rows for the seven: 3451
GTM 2009-12 / 2010-01: 94.882 / 54.4831537
SLV 1985-07/08/09: 11.473 7.157 11.928
NIC smallest: 2E-9
null source_id rows: 363
```

Note the trailing space after `Official country figures` — it is CEPAL's, and
the connector stores the string as published.

If any figure differs, CEPAL has republished. Stop and update the spec's
measured figures first; every assertion below is downstream of these.

- [ ] **Step 3: Add the conftest fixture**

Append to `tests/conftest.py`, beside the other CEPALSTAT fixtures:

```python
@pytest.fixture(scope="session")
def cepalstat_cpi_365_json() -> str:
    """CEPALSTAT indicator 365, consumer price index (stored gzipped)."""
    return gzip.decompress((FIXTURES / "cepalstat_cpi_365.json.gz").read_bytes()).decode("utf-8")
```

- [ ] **Step 4: Document the recording**

Add one row to `tests/fixtures/README.md`, after the `cepalstat_fx_2179` row,
and change the "these fourteen were recorded with REIM's own identifier"
sentence to "fifteen":

```text
| `cepalstat_cpi_365.json.gz` | `GET https://api-cepalstat.cepal.org/cepalstat/api/v1/indicator/365/data?lang=en`, byte-for-byte, gzipped only to keep the repo small (2.02 MB → 147 KB). Tests decompress it before parsing. The **complete** response — 40 countries and every month back to 1980 — because that is what proves the filter to the seven, and it is the only place Guatemala's 2010-01 splice and El Salvador's corrupt 1985-08 cell can be asserted. | 2026-09-06 |
```

- [ ] **Step 5: Verify the suite still collects**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_fx_connector.py -q`
Expected: PASS, 15 tests — this only proves `conftest.py` still imports.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/cepalstat_cpi_365.json.gz tests/fixtures/README.md tests/conftest.py
git commit -m "test(cepalstat): record the consumer price index response"
```

---

### Task 2: Register the indicator, the source and its rules

**Files:**
- Modify: `reim/domain/indicators/registry.py`
- Modify: `sources/catalog.yml`
- Modify: `sources/quality_rules.yml`
- Test: `tests/unit/test_catalog.py`

**Interfaces:**
- Consumes: nothing.
- Produces: indicator `cpi_index_monthly`; catalog key `cepalstat_cpi_monthly`
  naming connector module `reim.ingestion.connectors.regional.cepalstat_cpi`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_regional_cpi_is_registered() -> None:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    source = next(s for s in catalog.sources if s.key == "cepalstat_cpi_monthly")

    assert source.enabled is True
    assert source.frequency is Frequency.MONTHLY
    assert source.indicators == ["cpi_index_monthly"]
    assert source.connector == "reim.ingestion.connectors.regional.cepalstat_cpi"


def test_the_regional_cpi_declares_no_base_year() -> None:
    """CEPAL's declared bases are wrong for three of five; REIM asserts none.

    Contrast `ni_cpi_index_monthly`, which does state one, because INIDE
    publishes its base and it holds.
    """
    regional = INDICATORS_BY_CODE["cpi_index_monthly"]
    national = INDICATORS_BY_CODE["ni_cpi_index_monthly"]

    assert regional.unit == "index"
    assert regional.value_type is ValueType.INDEX
    assert regional.category is IndicatorCategory.PRICES
    assert "=100" not in regional.unit
    assert national.unit == "index (2006=100)"


def test_the_cpi_rules_set_no_change_ceiling() -> None:
    """No threshold separates Guatemala's 42.6% splice from Nicaragua's +261%."""
    rules = load_quality_rules(REPO_ROOT / "sources" / "quality_rules.yml")
    rule = rules.for_indicator("cpi_index_monthly")

    assert rule.max_period_change_pct is None
    assert rule.max_value is None
    assert rule.min_value == 0
    assert rule.allow_zero is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog.py -k "regional_cpi or cpi_rules" -v`
Expected: FAIL — `StopIteration` and `KeyError: 'cpi_index_monthly'`.

- [ ] **Step 3: Add the indicator**

Append to `INDICATORS` in `reim/domain/indicators/registry.py`:

```text
    IndicatorDefinition(
        code="cpi_index_monthly",
        name="Consumer price index (monthly)",
        description=(
            "Monthly consumer price index for the seven Central American "
            "countries, compiled by ECLAC from each country's own national "
            "publisher. Every country is on its own base period and CEPAL's "
            "declared base years do not hold for three of the five it "
            "declares, so REIM states none: levels are not comparable across "
            "countries, only their movements. Guatemala's series is spliced "
            "at 2010-01 without normalisation — December 2009 reads 94.882 "
            "and January 2010 reads 54.48 — so inflation computed across that "
            "month is meaningless. Nicaragua also has ni_cpi_index_monthly "
            "from INIDE, which differs from this series by about 4% in level."
        ),
        category=IndicatorCategory.PRICES,
        frequency=Frequency.MONTHLY,
        unit="index",
        value_type=ValueType.INDEX,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=365&lang=en",
    ),
```

- [ ] **Step 4: Add the catalog entry**

```yaml
  - key: cepalstat_cpi_monthly
    name: Central American consumer price index (monthly)
    description: >-
      Monthly consumer price index for the seven Central American countries,
      from CEPALSTAT, compiled from each country's own national publisher.
      Each country is on its own base period, so levels are not comparable
      across countries — only their movements are. Guatemala's series carries
      an unnormalised splice at 2010-01.
    organization: CEPAL
    category: prices
    access_type: http_api
    frequency: monthly
    format: json
    base_url: https://api-cepalstat.cepal.org/cepalstat/api/v1
    documentation_url: https://statistics.cepal.org/portal/cepalstat/
    connector: reim.ingestion.connectors.regional.cepalstat_cpi
    indicators:
      - cpi_index_monthly
    license: cepal_terms_of_use
    official: true
    enabled: true
```

- [ ] **Step 5: Add the quality rule**

```yaml
  cpi_index_monthly:
    min_value: 0
    max_value: null
    allow_negative: false
    allow_zero: false
    # Deliberately null. Guatemala's 2010-01 splice is -42.6% and Nicaragua's
    # 1991-03 hyperinflation is +261%, both real and published. Any threshold
    # that tolerates the second detects nothing; any that catches the first
    # rejects real Nicaraguan history. `cepalstat_cpi_known_splices` does this
    # work instead, with the measured exceptions encoded rather than guessed.
    max_period_change_pct: null
    monotonic_increasing: false
    # The series ends 2026-07 and CEPAL updates it monthly; Belize, the
    # stalest, ends 2026-06. REIM's tightest freshness threshold, and it
    # should be — this is its freshest series.
    freshness_max_age_days: 120
    min_observations: 3400
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add reim/domain/indicators/registry.py sources/catalog.yml \
        sources/quality_rules.yml tests/unit/test_catalog.py
git commit -m "feat(cepalstat): register the regional consumer price index"
```

---

### Task 3: Read the index

**Files:**
- Create: `reim/ingestion/connectors/regional/cepalstat_cpi.py`
- Test: `tests/unit/test_cepalstat_cpi_connector.py`

**Interfaces:**
- Consumes: Task 1's fixture, Task 2's registrations.
- Produces: `CepalstatCpiConnector` with `connector_key = "cepalstat_cpi_monthly"`;
  module constants `CEPAL_ID = 365`, `PERIOD_DIMENSION = 515`,
  `INDICATOR_CODE = "cpi_index_monthly"`, `CENTRAL_AMERICA`, `MONTHS_BY_NAME`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_cepalstat_cpi_connector.py`:

```python
"""Unit tests for the CEPALSTAT regional consumer price index connector.

Every payload replayed here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from reim.core.constants import Frequency
from reim.core.exceptions import ExtractionError
from reim.domain.pipelines.models import RawDataset
from reim.domain.sources.catalog import load_catalog
from reim.ingestion.connectors.regional.cepalstat_cpi import (
    CENTRAL_AMERICA,
    CepalstatCpiConnector,
)
from tests.conftest import REPO_ROOT

BASE_URL = "https://api-cepalstat.cepal.org/cepalstat/api/v1"

#: What the recording holds, measured on 2026-09-06.
ROWS_FOR_THE_SEVEN = 3451
SPANS = {
    "BLZ": ("1990-11", "2026-06", 266),
    "CRI": ("1980-01", "2026-06", 558),
    "GTM": ("1980-01", "2026-07", 559),
    "HND": ("1994-01", "2026-07", 391),
    "NIC": ("1980-01", "2026-07", 559),
    "PAN": ("1980-01", "2026-07", 559),
    "SLV": ("1980-01", "2026-07", 559),
}


@pytest.fixture
def connector() -> CepalstatCpiConnector:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    source = next(s for s in catalog.sources if s.key == "cepalstat_cpi_monthly")
    return CepalstatCpiConnector(source)


@pytest.fixture
def raw(cepalstat_cpi_365_json: str) -> RawDataset:
    return RawDataset(
        source_key="cepalstat_cpi_monthly",
        retrieved_at=datetime(2026, 9, 6, tzinfo=UTC),
        source_url=BASE_URL,
        payload={"data": cepalstat_cpi_365_json},
        content_type="application/json",
        http_status=200,
        metadata={"indicator_id": 365, "lang": "en"},
    )


def by_key(observations: list) -> dict[tuple[str, str], Decimal | None]:  # type: ignore[type-arg]
    return {(o.country_iso3, o.period.label): o.value_numeric for o in observations}


def test_stores_only_the_seven_countries(connector: CepalstatCpiConnector, raw: RawDataset) -> None:
    """The matrix carries 40 countries; REIM keeps seven."""
    observations = connector.transform(raw)

    assert len(observations) == ROWS_FOR_THE_SEVEN
    assert {o.country_iso3 for o in observations} == set(CENTRAL_AMERICA)


def test_each_country_span_matches_the_recording(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    observations = connector.transform(raw)

    for iso3, (first, last, count) in SPANS.items():
        labels = sorted(o.period.label for o in observations if o.country_iso3 == iso3)
        assert (labels[0], labels[-1], len(labels)) == (first, last, count)


def test_guatemalas_splice_is_stored_as_published(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    """A 42.6% fall that is a change of base, not deflation.

    Stored exactly as CEPAL published it. This test is the fact; the connector
    check is what stops a *new* one going unnoticed.
    """
    values = by_key(connector.transform(raw))

    assert values[("GTM", "2009-12")] == Decimal("94.882")
    assert values[("GTM", "2010-01")] == Decimal("54.4831537")


def test_el_salvadors_corrupt_cell_is_stored_as_published(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    """One bad value the series steps around — September over July is 1.0397."""
    values = by_key(connector.transform(raw))

    assert values[("SLV", "1985-07")] == Decimal("11.473")
    assert values[("SLV", "1985-08")] == Decimal("7.157")
    assert values[("SLV", "1985-09")] == Decimal("11.928")


def test_nicaraguas_redenominated_history_parses_exactly(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    """Scientific notation, down to 2E-9, held exactly by Decimal."""
    values = by_key(connector.transform(raw))
    nicaraguan = [v for (iso3, _), v in values.items() if iso3 == "NIC" and v is not None]

    assert min(nicaraguan) == Decimal("2E-9")
    assert max(nicaraguan) > Decimal("300")


def test_full_published_precision_is_kept(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    """CEPAL declares two decimals and publishes up to eight. Neither is rounded."""
    observations = connector.transform(raw)
    published = [o.raw_metadata["cepalstat_published_value"] for o in observations]
    decimals = {len(p.split(".")[1]) for p in published if "." in p}

    assert max(decimals) == 8


def test_the_unit_carries_no_base_year(connector: CepalstatCpiConnector, raw: RawDataset) -> None:
    """CEPAL's declared bases are wrong for three of five, so REIM states none."""
    observations = connector.transform(raw)

    assert {o.unit for o in observations} == {"index"}
    assert all(o.currency_code is None for o in observations)


def test_a_row_without_a_cited_source_stores_an_empty_string(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    """The freshest rows carry no source_id; REIM does not invent one."""
    observations = connector.transform(raw)
    recent = [o for o in observations if o.period.label >= "2024-01"]

    assert recent
    assert any(o.raw_metadata["cepalstat_source"] == "" for o in recent)
    assert all(o.raw_metadata["cepalstat_source"] != "None" for o in observations)


@respx.mock
async def test_extract_makes_one_request(
    connector: CepalstatCpiConnector, cepalstat_cpi_365_json: str
) -> None:
    route = respx.get(f"{BASE_URL}/indicator/365/data").mock(
        return_value=httpx.Response(
            200, text=cepalstat_cpi_365_json, headers={"content-type": "application/json"}
        )
    )
    dims = respx.get(f"{BASE_URL}/indicator/365/dimensions").mock(
        return_value=httpx.Response(200, json={})
    )

    result = await connector.extract()

    assert route.call_count == 1
    assert dims.call_count == 0
    assert route.calls[0].request.url.params["lang"] == "en"
    assert len(connector.transform(result)) == ROWS_FOR_THE_SEVEN


@respx.mock
async def test_a_failing_envelope_raises(connector: CepalstatCpiConnector) -> None:
    respx.get(f"{BASE_URL}/indicator/365/data").mock(
        return_value=httpx.Response(
            200,
            text=(
                '{"header": {"success": false, "code": 500, "message": "no data"}, '
                '"body": {"data": []}}'
            ),
            headers={"content-type": "application/json"},
        )
    )

    with pytest.raises(ExtractionError, match="500"):
        await connector.extract()


def test_periods_are_monthly(connector: CepalstatCpiConnector, raw: RawDataset) -> None:
    observations = connector.transform(raw)

    assert {o.period.frequency for o in observations} == {Frequency.MONTHLY}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_cpi_connector.py -q`
Expected: FAIL at collection — `ModuleNotFoundError`.

- [ ] **Step 3: Write the connector**

Create `reim/ingestion/connectors/regional/cepalstat_cpi.py`. Its `extract`,
`_months_of` and `_month_of` are the exchange-rate connector's, with
`CEPAL_ID = 365` — **read `cepalstat_exchange_rate.py` and mirror them** rather
than writing new ones, since the protocol is identical.

Module header and constants:

```python
"""Central America — the monthly consumer price index published through CEPALSTAT.

The API and the way its routes were recovered are documented in
``cepalstat.py``; only what differs is recorded here. The request shape is the
exchange rate's exactly: one call, with the month names read from the data
response's own dimension table.

What differs is the data, and it is unusually treacherous:

1. **Every country is on its own base period, and CEPAL's declared bases are
   wrong.** ``body.metadata.comments`` names a base year per country; checked
   against the data, three of the five it declares do not read 100 at that
   period — Guatemala's declared December 2010 reads 56.69. So REIM stores no
   base and puts none in the unit. **Levels are not comparable across
   countries**; only movements are.
2. **Guatemala's series is spliced at 2010-01 without normalisation.**
   December 2009 reads 94.882 and January 2010 reads 54.4831537, a 42.58%
   fall that is a change of base rather than deflation. It is Guatemala's only
   move beyond 15% in forty-six years, and anything computing inflation across
   it gets a meaningless answer.
3. **El Salvador has one corrupt cell**, 1985-08, reading 7.157 between
   11.473 and 11.928. That is a different defect from Guatemala's: a single
   bad value the series steps around, not a permanent level shift. Both are
   stored as published and both are pinned by ``_check_known_splices``.
4. **Nicaragua's 1980s are real and enormous** — 58 moves beyond 15% and
   values down to ``2E-9``, from hyperinflation and two córdoba
   redenominations seen through an index rebased twenty years later.

Together those make ``max_period_change_pct`` unsettable: any threshold that
tolerates Nicaragua's +261% detects nothing, and any that catches Guatemala's
splice rejects real history. The rule is null and this module checks instead.

Nicaragua also has ``ni_cpi_index_monthly`` from INIDE. The two disagree by a
median 4.2% in level while their year-on-year rates differ by more than 0.5
points in only 15 of 198 shared months — a rebasing difference between two
official compilers. REIM stores both and chooses between neither.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from reim.core.constants import CheckSeverity, CheckType, Frequency
from reim.core.exceptions import TransformationError
from reim.domain.observations.periods import parse_period
from reim.domain.pipelines.models import (
    NormalizedObservation,
    QualityResult,
    RawDataset,
)
from reim.ingestion.connectors.regional.cepalstat import (
    YEARS_DIMENSION,
    CepalstatConnector,
)
from reim.ingestion.http import ensure_ok, fetch, http_client

PERIOD_DIMENSION = 515
CEPAL_ID = 365
INDICATOR_CODE = "cpi_index_monthly"

CENTRAL_AMERICA = frozenset({"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"})

MONTHS_BY_NAME = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}

#: A month-on-month move beyond this is a series break rather than inflation,
#: everywhere except the exceptions below.
SPLICE_THRESHOLD = Decimal("15")

#: The breaks measured on 2026-09-06, keyed on the month moved **into**.
#: El Salvador needs two entries because one corrupt cell produces two moves:
#: the fall into August and the recovery into September.
KNOWN_SPLICES = frozenset({("GTM", "2010-01"), ("SLV", "1985-08"), ("SLV", "1985-09")})

#: Nicaragua's hyperinflation is excluded by date rather than enumerated: it
#: contains 58 legitimate moves beyond the threshold, and its worst from 1992
#: onward is 9.28%, so the cut is clean.
HYPERINFLATION_BEFORE = {"NIC": "1992-01"}
```

Then the class, whose `transform` mirrors the exchange rate's but stores
`unit="index"`, no `currency_code`, and no scaling:

```text
class CepalstatCpiConnector(CepalstatConnector):
    """Monthly consumer price indices for the seven Central American countries."""

    connector_key = "cepalstat_cpi_monthly"
    version = "1.0.0"
    expected_frequency = Frequency.MONTHLY
```

In `transform`, per row:

```text
                NormalizedObservation(
                    country_iso3=str(iso3),
                    indicator_code=INDICATOR_CODE,
                    source_key=self.source.key,
                    period=parse_period(label, Frequency.MONTHLY),
                    unit="index",
                    currency_code=None,
                    value_numeric=value,
                    retrieved_at=raw.retrieved_at,
                    source_url=f"{raw.source_url}/indicator/{CEPAL_ID}/data",
                    source_record_id=f"cepalstat:{CEPAL_ID}:{iso3}:{label}",
                    raw_metadata={
                        "cepalstat_indicator_id": CEPAL_ID,
                        "cepalstat_published_value": format(value.normalize(), "f"),
                        "cepalstat_published_unit": published_unit,
                        "cepalstat_data_features": data_features,
                        # Null on the freshest rows; stored empty rather than
                        # given an attribution REIM would be inventing.
                        "cepalstat_source": sources.get(row.get("source_id"), ""),
                        "cepalstat_credits": credits,
                        "contract_status": "verified",
                    },
                )
```

**Watch `format(value.normalize(), "f")` on Nicaragua's `2E-9`.** `normalize()`
turns it into `2E-9` and `format(..., "f")` renders `0.000000002`; the test in
step 1 asserts the *parsed* minimum is `Decimal("2E-9")`, which compares equal
either way. If `test_full_published_precision_is_kept` fails because
`normalize()` strips trailing zeros from an eight-decimal value, store
`str(value)` instead and say so in a comment — the point is to keep what CEPAL
published, not what `Decimal` prefers.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_cpi_connector.py -q`
Expected: PASS, 11 tests.

- [ ] **Step 5: Run the whole gate**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/python -m pytest tests/unit -q`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add reim/ingestion/connectors/regional/cepalstat_cpi.py \
        tests/unit/test_cepalstat_cpi_connector.py
git commit -m "feat(cepalstat): read the regional consumer price index"
```

---

### Task 4: The quality checks

**Files:**
- Modify: `reim/ingestion/connectors/regional/cepalstat_cpi.py`
- Test: `tests/unit/test_cepalstat_cpi_connector.py`

**Interfaces:**
- Consumes: Task 3's connector and the inherited
  `_check_monthly_continuity`.
- Produces: `validate()` returning `cepalstat_cpi_expected_countries`,
  `cepalstat_cpi_known_splices` and `cepalstat_monthly_continuity`, in that
  order.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_expected_countries_and_splice_checks_pass_on_the_recording(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    results = {r.check_name: r for r in connector.validate(connector.transform(raw))}

    assert list(results) == [
        "cepalstat_cpi_expected_countries",
        "cepalstat_cpi_known_splices",
        "cepalstat_monthly_continuity",
    ]
    assert results["cepalstat_cpi_expected_countries"].status is CheckStatus.PASSED
    assert results["cepalstat_cpi_known_splices"].status is CheckStatus.PASSED


def test_continuity_warns_about_belize_on_every_run(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    """Belize published quarterly until 2011. The warning is the correct output.

    Asserted as an expected warning rather than glossed over, so that if it
    ever stops firing someone notices the coverage changed.
    """
    results = {r.check_name: r for r in connector.validate(connector.transform(raw))}
    continuity = results["cepalstat_monthly_continuity"]

    assert continuity.status is CheckStatus.FAILED
    assert continuity.severity is CheckSeverity.WARNING
    assert "BLZ" in continuity.message


def test_a_missing_country_is_critical(connector: CepalstatCpiConnector, raw: RawDataset) -> None:
    observations = [o for o in connector.transform(raw) if o.country_iso3 != "CRI"]

    result = next(
        r
        for r in connector.validate(observations)
        if r.check_name == "cepalstat_cpi_expected_countries"
    )

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.CRITICAL
    assert "CRI" in result.message


def test_a_new_splice_fails(connector: CepalstatCpiConnector, raw: RawDataset) -> None:
    """Halving one Panamanian month is the shape of an unannounced rebase."""
    observations = connector.transform(raw)
    index = next(
        i
        for i, o in enumerate(observations)
        if o.country_iso3 == "PAN" and o.period.label == "2015-06"
    )
    observations[index] = replace(
        observations[index], value_numeric=observations[index].value_numeric / 2
    )

    result = next(
        r for r in connector.validate(observations) if r.check_name == "cepalstat_cpi_known_splices"
    )

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.ERROR
    assert "PAN 2015-06" in result.message


def test_the_measured_splices_do_not_fail_the_check(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    """Guatemala 2010-01 and El Salvador's 1985 pair are on the allow-list.

    Without all three entries this check would fail on real data every run —
    El Salvador's one corrupt cell produces two moves, not one.
    """
    result = next(
        r
        for r in connector.validate(connector.transform(raw))
        if r.check_name == "cepalstat_cpi_known_splices"
    )

    assert result.status is CheckStatus.PASSED
    assert "3" in result.message or "three" in result.message


def test_nicaraguan_hyperinflation_does_not_fail_the_check(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    """58 real moves beyond 15%, excluded by date rather than enumerated."""
    observations = [
        o
        for o in connector.transform(raw)
        if o.country_iso3 == "NIC" and o.period.label < "1992-01"
    ]

    result = next(
        r for r in connector.validate(observations) if r.check_name == "cepalstat_cpi_known_splices"
    )

    assert result.status is CheckStatus.PASSED
```

Add `from dataclasses import replace` and
`from reim.core.constants import CheckSeverity, CheckStatus` to the imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_cpi_connector.py -k "check or splice or continuity or country" -q`
Expected: FAIL — the base class's `validate` returns an empty list.

- [ ] **Step 3: Implement the checks**

```text
    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert CEPALSTAT-specific expectations beyond the standard battery."""
        return [
            self._check_expected_countries(observations),
            self._check_known_splices(observations),
            self._check_monthly_continuity(observations),
        ]
```

`_check_expected_countries` is `cepalstat_fx_expected_countries` with the name
changed — read it from `cepalstat_exchange_rate.py` and mirror it.

`_check_known_splices` walks each country's own series in period order,
compares consecutive **calendar-adjacent** months only, and skips three things
before judging a move: a period inside `HYPERINFLATION_BEFORE`, a pair on
`KNOWN_SPLICES`, and any pair whose earlier value is zero or absent. It counts
how many allow-listed breaks it saw so the passing message can say `3`, which
is what makes the allow-list visible in a run log rather than buried in code.

Skipping non-adjacent pairs matters for Belize: it published quarterly for
twenty-one years, and comparing March against the following December would
manufacture breaks that are really just gaps.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_cpi_connector.py -q`
Expected: PASS, 17 tests.

- [ ] **Step 5: Commit**

```bash
git add reim/ingestion/connectors/regional/cepalstat_cpi.py \
        tests/unit/test_cepalstat_cpi_connector.py
git commit -m "test(cepalstat): cover the CPI country and splice checks"
```

---

### Task 5: Pin the disagreement with INIDE

**Files:**
- Test: `tests/unit/test_cepalstat_cpi_connector.py`

**Interfaces:**
- Consumes: Task 3's connector and the existing `inide_workbook_bytes` fixture.
- Produces: no code. A regression test for spec §3.5.

- [ ] **Step 1: Write the test**

```python
def test_the_two_nicaraguan_indices_differ_by_a_stable_ratio(
    connector: CepalstatCpiConnector, raw: RawDataset, inide_workbook_bytes: bytes
) -> None:
    """REIM holds two official Nicaraguan CPIs and they disagree.

    CEPAL cites the Banco Central de Nicaragua; REIM reads INIDE directly.
    Both declare base 2006. Across the 198 months they share, not one agrees to
    the digit, but the ratio stays inside a narrow band — the signature of a
    rebasing difference between two compilers rather than a data disagreement.

    This is the regression test for that explanation. If a future CEPAL
    revision makes the two converge or diverge, the explanation has stopped
    being true and someone must look rather than assume.
    """
    from reim.ingestion.connectors.nicaragua.inide_cpi_monthly import InideCpiMonthly

    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    inide_source = next(s for s in catalog.sources if s.key == "inide_cpi_monthly")
    inide_raw = RawDataset(
        source_key="inide_cpi_monthly",
        retrieved_at=datetime(2026, 9, 6, tzinfo=UTC),
        source_url="https://www.inide.gob.ni",
        payload=inide_workbook_bytes,
        content_type="application/vnd.ms-excel",
        http_status=200,
        metadata={},
    )
    inide = {
        o.period.label: o.value_numeric
        for o in InideCpiMonthly(inide_source).transform(inide_raw)
        if o.indicator_code == "ni_cpi_index_monthly"
    }
    cepal = {
        o.period.label: o.value_numeric for o in connector.transform(raw) if o.country_iso3 == "NIC"
    }

    shared = sorted(set(inide) & set(cepal))
    assert len(shared) == 198

    ratios = [cepal[label] / inide[label] for label in shared]
    assert not any(cepal[label] == inide[label] for label in shared)
    assert Decimal("1.02") < min(ratios) < max(ratios) < Decimal("1.05")
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_cpi_connector.py -k nicaraguan_indices -v`
Expected: PASS without touching production code.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_cepalstat_cpi_connector.py
git commit -m "test(cepalstat): pin the two Nicaraguan CPIs against each other"
```

---

### Task 6: Run it live, then write down what happened

**Files:**
- Modify: `docs/sources.md`
- Modify: `ROADMAP.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above. No code.

- [ ] **Step 1: Run the pipeline**

```bash
make db-up CONTAINER_ENGINE=podman
export REIM_DATABASE_URL="postgresql+psycopg://reim:reim@localhost:55432/reim"
.venv/bin/alembic upgrade head
.venv/bin/reim db seed
.venv/bin/reim pipeline run cepalstat_cpi_monthly
.venv/bin/reim quality report
```

Expect 3,451 inserted, 0 rejected, and **one failing check**: continuity
warning on Belize. `reim quality report` exits 1 only on errors or worse, so a
warning still exits 0.

- [ ] **Step 2: Record what the run produced**

Query the spans and the recorded checks the way the exchange-rate increment
did — `data_quality_checks` joins `pipeline_runs` on `pipeline_run_id`, not
`run_id`. Write down the observation count, every check's status and message,
and each country's span.

**If a check fails unexpectedly, that is a finding, not a failure to hide.**

- [ ] **Step 3: Add the source section to `docs/sources.md`**

Follow the monetary and exchange-rate sections: a properties table, an
indicator table, a per-country coverage table, then subsections. Write these
five, with `####` headings, from spec §3:

1. **"The declared base years are wrong for three of five"** — including the
   measured table of when each series actually passes 100, described as
   measured rather than published.
2. **"Guatemala's series is spliced at 2010-01"** — with the four values.
3. **"El Salvador has one corrupt cell, which is a different thing"** — with
   the ratio that proves it.
4. **"Nicaragua now has two consumer price indices"** — the 4.2% median, the
   1.024–1.048 ratio, the 15-of-198 year-on-year figure, and that REIM stores
   both and chooses between neither.
5. **"Belize warns on continuity from the first run"** — quarterly until 2011,
   162 absent months, and why that is the correct output.

- [ ] **Step 4: Update `ROADMAP.md`**

The v0.2.0 frequency tally says the catalog holds "8 monthly"; it is now 9.
Add the CPI to v0.3.0's list of what CEPALSTAT delivered, in the style of the
entries already there.

- [ ] **Step 5: Update `README.md`**

Add a row to the source table. Update the two observation totals — grep for
`46,600` and `51,600`, both of which move by 3,451. Add the new indicator
wherever indicators are listed, and note in the comparability section that
levels are not comparable across countries because each is on its own base.

- [ ] **Step 6: Verify every figure you wrote**

```bash
grep -rn "3,451\|cpi_index_monthly" docs/sources.md ROADMAP.md README.md
```

Every figure in prose must match step 2's output.

- [ ] **Step 7: Run the whole gate**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && REIM_TEST_DATABASE_URL="postgresql+psycopg://reim:reim@localhost:55432/reim" .venv/bin/python -m pytest -q`
Expected: all clean.

`ruff format` rewrites any ` ```python ` block in Markdown that is not a valid
standalone module. If it reports changes to a `.md` file, fence that block as
` ```text ` rather than accepting the rewrite.

- [ ] **Step 8: Commit**

```bash
git add docs/sources.md ROADMAP.md README.md
git commit -m "feat: CEPALSTAT regional CPI — inflation for all seven countries"
```

---

## Done when

* `.venv/bin/reim pipeline run cepalstat_cpi_monthly` stores 3,451 observations
  for seven countries, with the expected-countries and splice checks passing
  and continuity warning on Belize.
* Guatemala's 2010-01 value is stored as `54.4831537`, unspliced and unrounded.
* Nicaragua's smallest value is `2E-9` and its two CPIs are pinned against each
  other.
* No indicator unit claims a base year.
* The full gate is clean and `docs/sources.md` records all five findings.
