# CEPALSTAT quarterly balance of payments — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest CEPALSTAT indicator 547 as 25 quarterly balance-of-payments
indicators — **19,582 observations**, seven countries, from one request — giving
REIM its first balance-of-payments data and its second quarterly source.

**Architecture:** One `CepalstatConnector` subclass on `cepalstat_debt.py`'s
four-dimension shape. One request, no Spanish dimensions fetch (this family's
item names *are* translated). Rows are selected by country and by item id, with
the selected ids' names asserted so a CEPAL relabelling fails loudly instead of
silently changing what a series means.

**Tech Stack:** Python 3.13, httpx + respx, SQLAlchemy 2, pytest, ruff, mypy.
Run tools as `.venv/bin/<tool>` — there is no `pip` in the venv. Integration
work needs `make db-up CONTAINER_ENGINE=podman`.

**Spec:** `docs/superpowers/specs/2026-09-09-cepalstat-bop-design.md`

## Global Constraints

* **Values are stored exactly as published**, then scaled by 1e6 — the published
  figures are millions of dollars and REIM stores whole units, matching
  `cepalstat_debt.py` and the GDP totals. **No rounding**, in either direction:
  this family declares `decimals: 0` and publishes up to **22** (spec §3.2).
* **Negatives and zeros are ordinary.** 9,924 of 19,582 values are negative and
  594 are zero. Both are normal in a balance of payments (spec §3.5).
* **Only the seven Central American countries**, and only the **25 item members**
  in `ITEMS`. 41 of the 66 item members are discarded.
* **`methodology_varies_by_country` is deliberately NOT declared** on these
  indicators. The metadata contradicts itself about the IMF manual, but
  measurement shows the figures are consistent — spec §3.1, decision D5.
* **Tests never call an official source.** The payload is replayed from a
  recording through `respx`.
* **The verification gate is CI's, over the whole repository:**
  `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest`.
  `ruff format` also formats Python fenced in Markdown, so `docs/` is in scope.
* Measured facts this plan asserts, all from 2026-09-09: 19,582 stored
  observations of 43,078 rows for the seven and 153,295 in the response; spans
  complete with **no interior gaps** in any country; the identity residuals
  781/781, 784/784, 784/784 and 782/784; Panama 2004-Q3 (−9.1) and 2021-Q4
  (+14.1) as the only global-balance exceptions; `V + VI = 0` holding in only
  2 of 784.

---

### Task 1: Record and trim the response

The full response is 20.3 MB and gzips to 1.74 MB — more than `tests/fixtures/`
weighs in total today. The recording is **trimmed** to the seven Central
American countries plus **Mexico**, keeping all 66 item members: 0.53 MB.

Mexico exists so the country filter is still genuinely tested — trimming to the
seven alone would leave nothing for the filter to exclude. All 66 items are kept
so the item filter is genuinely tested: 41 must be discarded.

**Files:**
- Create: `tests/fixtures/cepalstat_bop_547.json.gz`
- Modify: `tests/fixtures/README.md`
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: session-scoped fixture `cepalstat_bop_547_json() -> str`.

- [ ] **Step 1: Record and trim in one pass**

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/bin/python - <<'PY'
import gzip, json, urllib.request

URL = "https://api-cepalstat.cepal.org/cepalstat/api/v1/indicator/547/data?lang=en"
UA = "REIM/0.1.0 (Regional Economic Intelligence Monitor; +https://github.com/RobBravo/reim)"
KEEP = {"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ", "MEX"}

request = urllib.request.Request(URL, headers={"User-Agent": UA})
with urllib.request.urlopen(request, timeout=300) as response:
    document = json.loads(response.read())

body = document["body"]
before = len(body["data"])
body["data"] = [row for row in body["data"] if row["iso3"] in KEEP]
print(f"rows {before:,} -> {len(body['data']):,}")

payload = json.dumps(document).encode()
with open("tests/fixtures/cepalstat_bop_547.json.gz", "wb") as handle:
    handle.write(gzip.compress(payload, 9))
PY
ls -l tests/fixtures/cepalstat_bop_547.json.gz
```

The download takes about 50 s. Expect `rows 153,295 -> 53,253` and a file of
roughly 0.53 MB.

**Only the `data` array is filtered.** The `dimensions`, `metadata`, `sources`
and `footnotes` blocks are kept whole, so every member table the connector reads
is the real one — including the 145 country members and all 66 item members.

- [ ] **Step 2: Verify the recording holds what the plan claims**

```bash
.venv/bin/python - <<'PY'
import gzip, json, collections
from decimal import Decimal

body = json.loads(
    gzip.decompress(open("tests/fixtures/cepalstat_bop_547.json.gz", "rb").read())
)["body"]
SEVEN = {"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"}
items = {m["id"]: m["name"] for d in body["dimensions"] if d["id"] == 1272 for m in d["members"]}
years = {m["id"]: m["name"] for d in body["dimensions"] if d["id"] == 29117 for m in d["members"]}
quarters = {511: 1, 512: 2, 513: 3, 514: 4}

assert len(items) == 66, f"item members: {len(items)}"
assert len([d for d in body["dimensions"] if d["id"] == 208][0]["members"]) == 145
assert "MEX" in {r["iso3"] for r in body["data"]}, "Mexico must survive for the filter test"
print("dimensions intact: 145 countries, 66 items")

STORED = {
    1274: "current account", 1275: "capital account", 1276: "financial account",
    1273: "errors and omissions", 1277: "global balance", 1278: "reserves and related",
    1282: "balance goods", 1286: "balance goods+services", 1290: "balance income",
    1285: "balance current transfers", 1279: "exports fob", 1281: "imports fob",
    1291: "services credit", 1284: "services debit", 1287: "income credit",
    1289: "income debit", 1280: "transfers credit", 1283: "transfers debit",
    1308: "DI abroad", 1309: "DI inward", 1310: "PI assets", 1311: "PI liabilities",
    1312: "OI assets", 1313: "OI liabilities", 1326: "reserve assets",
}
assert len(STORED) == 25
rows = [r for r in body["data"] if r["iso3"] in SEVEN and r["dim_1272"] in STORED]
assert len(rows) == 19582, f"stored rows: {len(rows)}"
print("stored rows for the seven:", len(rows))

cells = collections.defaultdict(dict)
for row in rows:
    key = (row["iso3"], int(years[row["dim_29117"]]), quarters[row["dim_510"]])
    cells[key][items[row["dim_1272"]]] = Decimal(row["value"])

spans = collections.defaultdict(set)
for iso3, year, quarter in cells:
    spans[iso3].add((year, quarter))
for iso3 in sorted(spans):
    ordered = sorted(spans[iso3])
    width = (ordered[-1][0] - ordered[0][0]) * 4 + (ordered[-1][1] - ordered[0][1]) + 1
    gaps = width - len(ordered)
    print(f"   {iso3}: {len(ordered):3d} quarters {ordered[0][0]}-Q{ordered[0][1]}"
          f" .. {ordered[-1][0]}-Q{ordered[-1][1]}  gaps {gaps}")
    assert gaps == 0, f"{iso3} has {gaps} interior gaps"

def identity(target, parts, tolerance=Decimal("0.5")):
    ok = total = 0
    worst = Decimal(0)
    broken = []
    for key, value in cells.items():
        if target in value and all(p in value for p in parts):
            total += 1
            diff = abs(value[target] - sum(value[p] for p in parts))
            worst = max(worst, diff)
            if diff <= tolerance:
                ok += 1
            else:
                broken.append((key, diff))
    return ok, total, worst, broken

for name, target, parts in (
    ("I = goods+services + income + transfers", "I.  BALANCE ON CURRENT ACCOUNT",
     ["Balance on goods and services", "Balance on income", "Balance on current transfers"]),
    ("goods = exports + imports", "Balance on goods",
     ["Exports of goods, f.o.b.", "Imports of goods, f.o.b."]),
    ("goods+services", "Balance on goods and services",
     ["Balance on goods", "Services (credit)", "Services (debit)"]),
):
    ok, total, worst, broken = identity(target, parts)
    print(f"   {name}: {ok}/{total}  worst {worst}")
    assert ok == total, f"{name} broken on {broken[:3]}"

ok, total, worst, broken = identity(
    "V.  GLOBAL BALANCE",
    ["I.  BALANCE ON CURRENT ACCOUNT", "II.  BALANCE ON CAPITAL ACCOUNT",
     "III.  BALANCE ON FINANCIAL ACCOUNT", "IV.  ERRORS AND OMISSIONS"])
print(f"   V = I+II+III+IV: {ok}/{total}  worst {worst}")
assert total - ok == 2, f"expected exactly 2 exceptions, got {total - ok}"
assert {(k[0], f"{k[1]}-Q{k[2]}") for k, _ in broken} == {("PAN", "2004-Q3"), ("PAN", "2021-Q4")}

ok, total, _, _ = identity("V.  GLOBAL BALANCE", ["VI.  RESERVES AND RELATED ITEMS"])
print(f"   V + VI = 0: {ok}/{total}  (expected to NOT hold)")
assert ok < 10, "V + VI = 0 unexpectedly holds; the spec says it does not"

values = [Decimal(r["value"]) for r in rows]
print("negatives:", sum(1 for v in values if v < 0), "zeros:", sum(1 for v in values if v == 0))
print("max decimals:", max(-v.as_tuple().exponent for v in values))
print("ALL RECORDING ASSERTIONS PASSED")
PY
```

Expected: 19,582 stored rows, zero interior gaps in all seven, the three exact
identities, exactly two Panama exceptions, `V + VI = 0` failing, 9,924
negatives, 594 zeros and 22 maximum decimals.

If a count differs, CEPAL has revised the table since 2026-09-09. **Stop and
report** — every threshold in the spec derives from these.

- [ ] **Step 3: Add the conftest fixture**

Append to `tests/conftest.py`, after the last CEPALSTAT fixture:

```python
@pytest.fixture(scope="session")
def cepalstat_bop_547_json() -> str:
    """CEPALSTAT indicator 547, quarterly balance of payments (stored gzipped)."""
    return gzip.decompress((FIXTURES / "cepalstat_bop_547.json.gz").read_bytes()).decode("utf-8")
```

- [ ] **Step 4: Document the recording and its trim**

Add one row to the table in `tests/fixtures/README.md`, using the byte size
`ls -l` reported:

```text
| `cepalstat_bop_547.json.gz` | `GET https://api-cepalstat.cepal.org/cepalstat/api/v1/indicator/547/data?lang=en`, **trimmed** to the seven Central American countries plus Mexico and then gzipped (20.3 MB → 0.53 MB; the untrimmed response gzips to 1.74 MB, more than this whole directory weighs). Only the `data` array is filtered — the `dimensions`, `metadata`, `sources` and `footnotes` blocks are byte-for-byte, so all 145 country members and all 66 item members are the real ones. **Mexico is kept on purpose**: without a country that must be discarded, the connector's country filter would have nothing to prove. The 41 item members REIM does not store do the same job for the item filter. | 2026-09-09 |
```

The sentence below the table counting the CEPALSTAT recordings must go from
"eighteen" to "nineteen".

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q 2>&1 | tail -2
git add tests/fixtures/cepalstat_bop_547.json.gz tests/fixtures/README.md tests/conftest.py
git commit -m "test(cepalstat): record the quarterly balance of payments, trimmed"
```

---

### Task 2: Register the 25 indicators

**Files:**
- Modify: `reim/domain/indicators/registry.py`
- Test: `tests/unit/test_catalog.py`

**Interfaces:**
- Consumes: nothing.
- Produces: 25 indicator codes, all prefixed `bop_` and suffixed `_quarterly`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_catalog.py`, after the interest-rate tests. That
module already imports `INDICATORS`, `INDICATORS_BY_CODE`, `IndicatorCategory`,
`Frequency` and `ValueType`:

```python
BOP_CODES = (
    "bop_current_account_quarterly",
    "bop_capital_account_quarterly",
    "bop_financial_account_quarterly",
    "bop_errors_omissions_quarterly",
    "bop_global_balance_quarterly",
    "bop_reserves_related_quarterly",
    "bop_balance_goods_quarterly",
    "bop_balance_goods_services_quarterly",
    "bop_balance_income_quarterly",
    "bop_balance_current_transfers_quarterly",
    "bop_exports_goods_fob_quarterly",
    "bop_imports_goods_fob_quarterly",
    "bop_services_credit_quarterly",
    "bop_services_debit_quarterly",
    "bop_income_credit_quarterly",
    "bop_income_debit_quarterly",
    "bop_current_transfers_credit_quarterly",
    "bop_current_transfers_debit_quarterly",
    "bop_direct_investment_abroad_quarterly",
    "bop_direct_investment_inward_quarterly",
    "bop_portfolio_investment_assets_quarterly",
    "bop_portfolio_investment_liabilities_quarterly",
    "bop_other_investment_assets_quarterly",
    "bop_other_investment_liabilities_quarterly",
    "bop_reserve_assets_quarterly",
)


def test_the_balance_of_payments_indicators_are_registered() -> None:
    """Twenty-five quarterly series, one cube, one unit."""
    assert len(BOP_CODES) == 25
    for code in BOP_CODES:
        definition = INDICATORS_BY_CODE[code]
        assert definition.category is IndicatorCategory.EXTERNAL_SECTOR
        assert definition.frequency is Frequency.QUARTERLY
        assert definition.unit == "current USD"
        assert definition.value_type is ValueType.LEVEL
        assert definition.currency_convertible is False


def test_the_balance_of_payments_does_not_declare_varying_methodology() -> None:
    """Its metadata disagrees about the IMF manual; its figures do not.

    CEPAL declares BPM5 while six of the seven countries carry a BPM6 footnote,
    but the sign convention is consistent across all seven and the accounting
    identities hold everywhere. Declaring the flag would put a caveat on
    /compare that the measurement contradicts — see decision D5.
    """
    for code in BOP_CODES:
        assert INDICATORS_BY_CODE[code].methodology_varies_by_country is False


def test_the_two_balance_of_payments_traps_are_stated_in_their_descriptions() -> None:
    """Neither closes the roadmap gap its name suggests.

    Reserve assets here is the quarterly *flow*, not the stock the roadmap
    wants; current transfers is the whole account, official transfers included,
    and is not remittances.
    """
    reserves = INDICATORS_BY_CODE["bop_reserve_assets_quarterly"].description
    assert "flow" in reserves.lower()
    assert "not the stock" in reserves.lower()

    transfers = INDICATORS_BY_CODE["bop_current_transfers_credit_quarterly"].description
    assert "not remittances" in transfers.lower()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/pytest tests/unit/test_catalog.py -q -k balance_of_payments 2>&1 | tail -5
```

Expected: FAIL — `KeyError: 'bop_current_account_quarterly'`.

- [ ] **Step 3: Add the 25 definitions**

Before the closing `)` of `INDICATORS`. Every entry shares
`category=IndicatorCategory.EXTERNAL_SECTOR`, `frequency=Frequency.QUARTERLY`,
`unit="current USD"`, `value_type=ValueType.LEVEL`, and
`methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en"`.

Write each description in the registry's established voice — what the series is,
and what a reader needs to know before using it. A shared sentence belongs in
each: *"Quarterly balance of payments compiled by ECLAC; CEPAL declares the
IMF's fifth Balance of Payments Manual while six of the seven countries carry a
footnote citing the sixth."*

**Two descriptions carry a mandatory warning** and their tests above assert it:

```text
bop_reserve_assets_quarterly
    ... This is the balance-of-payments **flow** in reserve assets over the
    quarter — the change — and not the stock of reserves. It is not the
    reserves level ROADMAP.md asks for, which is what FI.RES.TOTL.CD and the
    IMF's IRFCL hold.

bop_current_transfers_credit_quarterly
    ... This is the whole current-transfers account, official transfers
    included; it is not remittances, and CEPAL's item dimension does not break
    personal remittances out of it. The World Bank series REIM stores annually,
    BX.TRF.PWKR.CD.DT, is a third definition again.
```

Note `bop_exports_goods_fob_quarterly` and `bop_imports_goods_fob_quarterly`
should each name the monthly IMF series REIM already holds, so the overlap is
visible from either side.

- [ ] **Step 4: Verify and commit**

```bash
.venv/bin/pytest tests/unit/test_catalog.py -q 2>&1 | tail -2
.venv/bin/mypy reim apps
git add reim/domain/indicators/registry.py tests/unit/test_catalog.py
git commit -m "feat(cepalstat): register the 25 balance-of-payments indicators"
```

---

### Task 3: Catalog entry and quality rules

**Files:**
- Modify: `sources/catalog.yml`
- Modify: `sources/quality_rules.yml`
- Test: `tests/unit/test_catalog.py`

**Interfaces:**
- Consumes: the 25 codes from Task 2.
- Produces: catalog key `cepalstat_bop_quarterly`, resolving to
  `reim.ingestion.connectors.regional.cepalstat_bop` (created in Task 4).

- [ ] **Step 1: Write the failing rules test**

Append to `tests/unit/test_catalog.py`:

```python
def test_every_balance_of_payments_indicator_has_a_quality_rule(
    quality_rules: QualityRuleSet,
) -> None:
    """One cube, one set of thresholds, each derived from a measurement."""
    for code in BOP_CODES:
        rule = quality_rules.for_indicator(code)
        assert rule is not quality_rules.defaults, f"{code} fell through to the defaults"
        # 9,924 of 19,582 values are negative and 594 are zero. A deficit is a
        # negative number and an absent flow is a real zero.
        assert rule.allow_negative is True
        assert rule.allow_zero is True
        assert rule.min_value is None
        assert rule.max_value is None
        # These series cross zero, so a percentage change of them is unbounded
        # and meaningless as a tripwire.
        assert rule.max_period_change_pct is None
        assert rule.monotonic_increasing is False
        # Four countries end 2026-Q1 (162 days old on 2026-09-09); the rest end
        # 2025-Q4 at 252. 550 clears CEPAL's quarterly cycle with headroom.
        assert rule.freshness_max_age_days == 550
        assert rule.min_observations == 19000
```

- [ ] **Step 2: Run it and watch it fail**

```bash
.venv/bin/pytest tests/unit/test_catalog.py -q -k balance_of_payments_indicator_has 2>&1 | tail -4
```

Expected: FAIL — every code falls through to `quality_rules.defaults`.

- [ ] **Step 3: Add the quality rules**

In `sources/quality_rules.yml`, after the interest-rate block. Use a YAML anchor
so the 25 entries do not repeat 25 times — `money_m1_monthly` establishes that
pattern with `&monetary_aggregate`:

```yaml
  bop_current_account_quarterly: &balance_of_payments
    min_value: null
    max_value: null
    # A balance of payments has no natural bound in either direction, and
    # 9,924 of 19,582 measured values are negative with 594 exactly zero:
    # a deficit is a negative number and an absent flow is a real zero.
    allow_negative: true
    allow_zero: true
    # Deliberately null on all twenty-five. These series cross zero, where a
    # percentage change is unbounded and meaningless as a tripwire — the same
    # call ni_cpi_inflation_monthly already makes.
    max_period_change_pct: null
    monotonic_increasing: false
    # Costa Rica, El Salvador, Honduras and Panama end 2026-Q1, 162 days old on
    # 2026-09-09; Belize, Guatemala and Nicaragua end 2025-Q4 at 252. 550
    # clears CEPAL's quarterly cycle with headroom and still catches a family
    # that has stopped being extended.
    freshness_max_age_days: 550
    # 19,582 measured across the twenty-five series.
    min_observations: 19000
```

then the remaining 24 as `<<: *balance_of_payments`.

- [ ] **Step 4: Add the catalog entry**

After `cepalstat_rates_monthly` in `sources/catalog.yml`, listing all 25 codes:

```yaml
  - key: cepalstat_bop_quarterly
    name: Central American quarterly balance of payments
    description: >-
      Quarterly balance of payments for the seven Central American countries,
      from CEPALSTAT: the six headline balances, four sub-balances and fifteen
      components, in current dollars. CEPAL declares the IMF's fifth Balance of
      Payments Manual while six of the seven countries carry a footnote citing
      the sixth; the figures are consistent across both. Reserve assets here is
      the quarterly flow, not the stock, and current transfers is not
      remittances.
    organization: CEPAL
    category: external_sector
    access_type: http_api
    frequency: quarterly
    format: json
    base_url: https://api-cepalstat.cepal.org/cepalstat/api/v1
    documentation_url: https://statistics.cepal.org/portal/cepalstat/
    connector: reim.ingestion.connectors.regional.cepalstat_bop
    indicators:
      - bop_current_account_quarterly
      # ... all 25, in the order of BOP_CODES
    license: cepal_terms_of_use
    official: true
    enabled: true
```

- [ ] **Step 5: Verify**

```bash
.venv/bin/pytest tests/unit/test_catalog.py -q 2>&1 | tail -2
.venv/bin/python -m reim.cli catalog validate 2>&1 | tail -5
```

The rules test must now PASS. `catalog validate` must FAIL with a
`ConnectorLoadError` for `reim.ingestion.connectors.regional.cepalstat_bop` —
that module is Task 4's job, and this failure proves the entry resolves its
connector path. **Do not create a stub to silence it.**

CI runs `catalog validate` as its own step, so the branch is red between this
commit and Task 4's. That is expected and must not be merged in between.

- [ ] **Step 6: Commit**

```bash
git add sources/catalog.yml sources/quality_rules.yml tests/unit/test_catalog.py
git commit -m "feat(cepalstat): catalog entry and quality rules for the balance of payments"
```

---

### Task 4: The connector — extraction and transformation

**Files:**
- Create: `reim/ingestion/connectors/regional/cepalstat_bop.py`
- Create: `tests/unit/test_cepalstat_bop_connector.py`

**Interfaces:**
- Consumes: `CepalstatConnector`, `COUNTRY_DIMENSION`, `YEARS_DIMENSION` from
  the base module; the catalog entry from Task 3.
- Produces:
  - `CEPAL_ID: int` — `547`
  - `QUARTERS_DIMENSION: int` — `510`, `ITEM_DIMENSION: int` — `1272`
  - `QUARTERS: dict[int, int]` — member id to quarter number
  - `ITEMS: dict[int, str]` — item member id to REIM indicator code
  - `CENTRAL_AMERICA: frozenset[str]`, `MILLIONS: Decimal`
  - `CepalstatBopConnector` with `connector_key = "cepalstat_bop_quarterly"`,
    `version = "1.0.0"`, `expected_frequency = Frequency.QUARTERLY`
  - `async extract(self) -> RawDataset` with `payload` the response text
  - `transform(self, raw) -> list[NormalizedObservation]`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_cepalstat_bop_connector.py`. **Follow
`tests/unit/test_cepalstat_debt_connector.py`'s conventions** — it is the direct
precedent for a four-dimension family. In particular: no `@pytest.mark.anyio`
(`pyproject.toml` sets `asyncio_mode = "auto"`), use the `@respx.mock`
decorator with module-level `respx.get(...)` and assert on route `call_count`,
and build a `RawDataset` synchronously for `transform` tests rather than
performing HTTP in a fixture.

```python
"""Unit tests for the CEPALSTAT quarterly balance-of-payments connector.

Every payload replayed here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from reim.core.constants import CheckSeverity, CheckStatus, Frequency
from reim.core.exceptions import TransformationError
from reim.domain.pipelines.models import NormalizedObservation, RawDataset
from reim.domain.sources.catalog import load_catalog
from reim.ingestion.connectors.regional.cepalstat_bop import (
    CENTRAL_AMERICA,
    ITEMS,
    CepalstatBopConnector,
)
from tests.conftest import REPO_ROOT

BASE_URL = "https://api-cepalstat.cepal.org/cepalstat/api/v1"
DATA_URL = f"{BASE_URL}/indicator/547/data"

#: What the recording holds, measured on 2026-09-09.
STORED_OBSERVATIONS = 19582


def build_connector() -> CepalstatBopConnector:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    return CepalstatBopConnector(catalog.get("cepalstat_bop_quarterly"))


def json_response(text: str) -> httpx.Response:
    return httpx.Response(200, text=text, headers={"content-type": "application/json"})


def build_raw(text: str) -> RawDataset:
    return RawDataset(
        source_key="cepalstat_bop_quarterly",
        retrieved_at=datetime(2026, 9, 9, 12, 0, tzinfo=UTC),
        source_url=BASE_URL,
        payload={"data": text},
        content_type="application/json",
        http_status=200,
    )


@pytest.fixture
def raw(cepalstat_bop_547_json: str) -> RawDataset:
    return build_raw(cepalstat_bop_547_json)


@respx.mock
async def test_extract_makes_one_request_and_asks_for_english(
    cepalstat_bop_547_json: str,
) -> None:
    """No Spanish dimensions fetch: this family's item names are translated."""
    data_route = respx.get(DATA_URL).mock(return_value=json_response(cepalstat_bop_547_json))
    dimensions_route = respx.get(f"{BASE_URL}/indicator/547/dimensions").mock(
        return_value=json_response(cepalstat_bop_547_json)
    )

    await build_connector().extract()

    assert data_route.call_count == 1
    assert dimensions_route.call_count == 0
    assert data_route.calls[0].request.url.params["lang"] == "en"


def test_stores_twenty_five_series_for_the_seven(raw: RawDataset) -> None:
    """41 of the 66 item members are discarded, and so is Mexico."""
    observations = build_connector().transform(raw)

    assert len(observations) == STORED_OBSERVATIONS
    assert {obs.country_iso3 for obs in observations} == CENTRAL_AMERICA
    assert {obs.indicator_code for obs in observations} == set(ITEMS.values())
    assert len(ITEMS) == 25
    assert {obs.period.frequency for obs in observations} == {Frequency.QUARTERLY}


def test_mexico_is_discarded_although_it_is_in_the_recording(
    raw: RawDataset, cepalstat_bop_547_json: str
) -> None:
    """The recording keeps Mexico so this filter has something to prove."""
    assert '"MEX"' in cepalstat_bop_547_json
    observations = build_connector().transform(raw)
    assert "MEX" not in {obs.country_iso3 for obs in observations}


def test_values_are_scaled_to_whole_dollars_and_never_rounded(raw: RawDataset) -> None:
    """Published in millions; stored in units, matching the debt and GDP totals.

    CEPAL declares zero decimals and publishes up to 22, so the scale must be
    applied without rounding the noise away.
    """
    observations = build_connector().transform(raw)

    published = {
        (obs.country_iso3, obs.indicator_code, obs.period.label): obs for obs in observations
    }
    sample = published[("PAN", "bop_current_account_quarterly", "2004-Q3")]
    assert sample.unit == "current USD"
    assert sample.currency_code == "USD"
    assert sample.value_numeric == Decimal(
        sample.raw_metadata["cepalstat_published_value"]
    ) * Decimal("1000000")

    # At least one stored value keeps more than two decimals of published noise.
    noisy = [
        obs
        for obs in observations
        if -Decimal(obs.raw_metadata["cepalstat_published_value"]).as_tuple().exponent > 8
    ]
    assert noisy, "the recording holds cells with more than eight decimals"


def test_negatives_and_zeros_are_stored(raw: RawDataset) -> None:
    """9,924 negatives and 594 zeros: both ordinary in a balance of payments."""
    values = [obs.value_numeric for obs in build_connector().transform(raw)]
    assert sum(1 for v in values if v is not None and v < 0) == 9924
    assert sum(1 for v in values if v == 0) == 594


def test_a_renamed_item_member_raises_rather_than_changing_a_series(
    cepalstat_bop_547_json: str,
) -> None:
    """Rows are filtered by member id, which is silent when CEPAL relabels one.

    The filter would keep matching and REIM would store a different series under
    the same indicator code, which is exactly the failure `cepalstat_debt.py`'s
    `_assert_selected_members` exists to prevent.
    """
    document = json.loads(cepalstat_bop_547_json)
    for dimension in document["body"]["dimensions"]:
        if dimension["id"] == 1272:
            for member in dimension["members"]:
                if member["id"] == 1274:
                    member["name"] = "I.  SOMETHING ELSE ENTIRELY"

    with pytest.raises(TransformationError, match="1274"):
        build_connector().transform(build_raw(json.dumps(document)))
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_cepalstat_bop_connector.py -q 2>&1 | tail -5
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the module**

Create `reim/ingestion/connectors/regional/cepalstat_bop.py`. Its docstring
records what differs from the sibling families — the module docstrings in
`cepalstat_rates.py` and `cepalstat_debt.py` are the models for length and
voice. It must cover: one request and no Spanish fetch; the BPM5/BPM6
contradiction and why the flag is not declared; the 20.3 MB with no server-side
filtering; and that 41 of 66 items are discarded.

The item map, copied verbatim — these ids were read from the recording:

```python
CEPAL_ID = 547

#: This family's own dimensions; country and years come from the base module.
QUARTERS_DIMENSION = 510
ITEM_DIMENSION = 1272

#: Quarter member ids are contiguous and in calendar order, unlike the
#: monthly families' period dimension.
QUARTERS: dict[int, int] = {511: 1, 512: 2, 513: 3, 514: 4}

#: Published in millions of dollars, stored in whole dollars, matching the debt
#: and GDP totals so every dollar figure in the database means the same thing.
MILLIONS = Decimal("1000000")

CENTRAL_AMERICA = frozenset({"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"})

#: The 25 item members REIM stores, of 66. Selected by id and asserted by name
#: in ``_assert_selected_items``: filtering by id is silent when CEPAL relabels
#: a member, and the series would change meaning under an unchanged code.
ITEMS: dict[int, str] = {
    1274: "bop_current_account_quarterly",
    1275: "bop_capital_account_quarterly",
    1276: "bop_financial_account_quarterly",
    1273: "bop_errors_omissions_quarterly",
    1277: "bop_global_balance_quarterly",
    1278: "bop_reserves_related_quarterly",
    1282: "bop_balance_goods_quarterly",
    1286: "bop_balance_goods_services_quarterly",
    1290: "bop_balance_income_quarterly",
    1285: "bop_balance_current_transfers_quarterly",
    1279: "bop_exports_goods_fob_quarterly",
    1281: "bop_imports_goods_fob_quarterly",
    1291: "bop_services_credit_quarterly",
    1284: "bop_services_debit_quarterly",
    1287: "bop_income_credit_quarterly",
    1289: "bop_income_debit_quarterly",
    1280: "bop_current_transfers_credit_quarterly",
    1283: "bop_current_transfers_debit_quarterly",
    1308: "bop_direct_investment_abroad_quarterly",
    1309: "bop_direct_investment_inward_quarterly",
    1310: "bop_portfolio_investment_assets_quarterly",
    1311: "bop_portfolio_investment_liabilities_quarterly",
    1312: "bop_other_investment_assets_quarterly",
    1313: "bop_other_investment_liabilities_quarterly",
    1326: "bop_reserve_assets_quarterly",
}

#: The published name each stored id must still carry. Read back on every run.
ITEM_NAMES: dict[int, str] = {
    1274: "I.  BALANCE ON CURRENT ACCOUNT",
    1275: "II.  BALANCE ON CAPITAL ACCOUNT",
    1276: "III.  BALANCE ON FINANCIAL ACCOUNT",
    1273: "IV.  ERRORS AND OMISSIONS",
    1277: "V.  GLOBAL BALANCE",
    1278: "VI.  RESERVES AND RELATED ITEMS",
    1282: "Balance on goods",
    1286: "Balance on goods and services",
    1290: "Balance on income",
    1285: "Balance on current transfers",
    1279: "Exports of goods, f.o.b.",
    1281: "Imports of goods, f.o.b.",
    1291: "Services (credit)",
    1284: "Services (debit)",
    1287: "Income (credit)",
    1289: "Income (debit)",
    1280: "Current transfers (credit)",
    1283: "Current transfers (debit)",
    1308: "Direct investment abroad",
    1309: "Direct investment in reporting economy",
    1310: "Portfolio investment assets",
    1311: "Portfolio investment liabilities",
    1312: "Other investment assets",
    1313: "Other investment liabilities",
    1326: "Reserve assets",
}
```

`extract` is one request — model it on `cepalstat_cpi.py`'s, which also fetches a
single indicator and stores `payload={"data": response.text}`. Use that exact
shape: it is the sibling precedent for a one-request CEPALSTAT family, and the
test helper below builds the same dict. `transform` decodes once, calls `_assert_selected_items`, then walks
`body["data"]` keeping rows whose `iso3` is in `CENTRAL_AMERICA` and whose
`dim_1272` is in `ITEMS`, building the period from
`f"{year}-Q{QUARTERS[row['dim_510']]}"` and scaling the value by `MILLIONS`.

`_assert_selected_items` is `cepalstat_debt.py`'s `_assert_selected_members`
generalised over `ITEM_NAMES` — read the member table once and raise
`TransformationError` naming the id whose name changed.

`raw_metadata` carries `cepalstat_indicator_id`, `cepalstat_item_id`,
`cepalstat_published_value`, `cepalstat_published_unit`,
`cepalstat_scale_applied` (`"1e6"`), `cepalstat_source`, `cepalstat_notes_ids`
and `contract_status`. **`cepalstat_source` reads `organization_name`**, not
`description` — the rates connector established that and the monetary one is the
outlier.

- [ ] **Step 4: Verify and commit**

```bash
.venv/bin/pytest tests/unit/test_cepalstat_bop_connector.py -q 2>&1 | tail -3
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps
.venv/bin/python -m reim.cli catalog validate 2>&1 | tail -3
git add reim/ingestion/connectors/regional/cepalstat_bop.py tests/unit/test_cepalstat_bop_connector.py
git commit -m "feat(cepalstat): read the quarterly balance of payments"
```

`catalog validate` must now pass, closing the red window Task 3 opened.

---

### Task 5: The quality battery

**Files:**
- Modify: `reim/ingestion/connectors/regional/cepalstat_bop.py`
- Modify: `tests/unit/test_cepalstat_bop_connector.py`

**Interfaces:**
- Consumes: `transform` from Task 4; `_check_country_coverage` from the base
  class (signature: `(observations, expected: Mapping[str, frozenset[str]], check_name: str)`).
- Produces: `validate` returning five results, and
  `IDENTITY_TOLERANCE`, `GLOBAL_BALANCE_EXCEPTIONS`.

- [ ] **Step 1: Write the failing tests**

The four identity checks share a shape, so test them through one helper. Each
needs a constructed break as well as the fixture passing — a check that only
ever sees good data proves nothing.

```python
def results_of(observations: list[NormalizedObservation]) -> dict[str, QualityResult]:
    return {result.check_name: result for result in build_connector().validate(observations)}


def test_all_five_checks_pass_on_the_recording(raw: RawDataset) -> None:
    """The expected first-run state, from spec section 6.3."""
    results = results_of(build_connector().transform(raw))
    assert set(results) == {
        "cepalstat_bop_current_account",
        "cepalstat_bop_goods",
        "cepalstat_bop_goods_services",
        "cepalstat_bop_global_balance",
        "cepalstat_bop_expected_countries",
    }
    for name, result in results.items():
        assert result.status is CheckStatus.PASSED, f"{name}: {result.message}"


def test_the_global_balance_check_allows_only_panamas_two_known_exceptions(
    raw: RawDataset,
) -> None:
    """Panama 2004-Q3 and 2021-Q4 are real and encoded; a third would fire."""
    observations = build_connector().transform(raw)
    assert results_of(observations)["cepalstat_bop_global_balance"].status is CheckStatus.PASSED

    broken = [
        obs
        for obs in observations
        if obs.indicator_code == "bop_global_balance_quarterly"
        and (obs.country_iso3, obs.period.label) == ("CRI", "2010-Q1")
    ]
    assert broken, "fixture must hold CRI 2010-Q1 for this test to mean anything"
    broken[0].value_numeric += Decimal("5000000")

    result = results_of(observations)["cepalstat_bop_global_balance"]
    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.WARNING
    assert "CRI 2010-Q1" in result.message
    assert "PAN 2004-Q3" not in result.message
```

Write one such pair for each of the other three identities, breaking a different
country-quarter in each so a copy-paste error is visible.

- [ ] **Step 2: Run them and watch them fail**

```bash
.venv/bin/pytest tests/unit/test_cepalstat_bop_connector.py -q -k "checks or identity or balance" 2>&1 | tail -5
```

- [ ] **Step 3: Implement `validate`**

```text
IDENTITY_TOLERANCE = Decimal("0.5") * MILLIONS

#: Measured 2026-09-09: the only two country-quarters where the global balance
#: does not equal I + II + III + IV, by -9.1 and +14.1 million. Encoded rather
#: than guessed, so a third break is reported.
GLOBAL_BALANCE_EXCEPTIONS = frozenset({("PAN", "2004-Q3"), ("PAN", "2021-Q4")})
```

`validate` returns, in order: `_check_identity` for the current account, goods,
and goods-and-services at `CheckSeverity.ERROR`; `_check_identity` for the global
balance at `CheckSeverity.WARNING` with `GLOBAL_BALANCE_EXCEPTIONS`; and
`self._check_country_coverage(observations, EXPECTED_COUNTRIES, "cepalstat_bop_expected_countries")`
where `EXPECTED_COUNTRIES` maps every one of the 25 codes to `CENTRAL_AMERICA`.

`_check_identity(observations, name, target_code, part_codes, severity, exceptions=frozenset())`
indexes observations by `(country, period, indicator_code)`, compares
`target - sum(parts)` against `IDENTITY_TOLERANCE` for every country-quarter
where all the codes are present, skips pairs in `exceptions`, and reports the
first five breaks with their residuals.

**Note the tolerance is scaled.** Values are stored in whole dollars, so the
0.5-million tolerance from the spec is `Decimal("0.5") * MILLIONS`. Comparing a
whole-dollar residual against `0.5` would make every check fail.

**There is no continuity check.** The base class's `_check_monthly_continuity`
splits `period.label` on `-`, which raises on `2024-Q1`; and every country's span
is complete, so there is nothing for a quarterly equivalent to find.
`min_observations` covers a collapse.

- [ ] **Step 4: Verify and commit**

```bash
.venv/bin/pytest tests/unit/test_cepalstat_bop_connector.py -q 2>&1 | tail -3
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q 2>&1 | tail -2
git add reim/ingestion/connectors/regional/cepalstat_bop.py tests/unit/test_cepalstat_bop_connector.py
git commit -m "feat(cepalstat): the balance of payments' accounting identities as checks"
```

---

### Task 6: Run it live and record what happened

**Files:**
- Modify: `docs/sources.md`, `ROADMAP.md`, `README.md`

- [ ] **Step 1: Bring the database up, migrate and seed**

```bash
make db-up CONTAINER_ENGINE=podman
.venv/bin/alembic upgrade head
.venv/bin/python -m reim.cli db seed
```

**The seed is not optional** — it writes indicators and catalog sources into the
database. Expect it to report 25 indicators and 1 source created.

- [ ] **Step 2: Run the pipeline**

```bash
.venv/bin/python -m reim.cli pipeline run cepalstat_bop_quarterly 2>&1 | tail -40
```

Expected: **19,582 observations** stored, five checks passing. Record the exact
count, the duration and **every** check result with its severity. The download is
20.3 MB, so expect a noticeably longer run than any other pipeline.

**Anything other than the predicted state is a finding to record, not a
threshold to adjust.** If a check fails, stop and report.

- [ ] **Step 3: Verify through the CLI and the API**

```bash
.venv/bin/python -m reim.cli pipeline status --limit 5
.venv/bin/python -m reim.cli quality report --days 1
.venv/bin/uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!
sleep 3
curl -s 'http://localhost:8000/api/v1/compare?indicator=bop_current_account_quarterly&country=NIC&country=GTM&country=CRI&limit=3' \
  | .venv/bin/python -m json.tool | head -40
kill $API_PID
```

Neither CLI command takes a pipeline argument; both list the most recent runs.
The comparison should report `comparable: true` with **no** methodology note —
this family deliberately does not declare the flag.

- [ ] **Step 4: Write the `docs/sources.md` section**

Under "Enabled", after the interest rates, in the house pattern: a header table,
the per-country coverage table, then one `####` subsection per finding whose
heading *states* the finding. Cover, at minimum:

- **the BPM5/BPM6 contradiction**, the by-country split, and the measurement
  that shows it does not break comparability — including why
  `methodology_varies_by_country` is deliberately not declared (spec §3.1, D5);
- **three identities hold, a fourth has two Panama exceptions, and `V + VI = 0`
  does not hold at all** (spec §3.4) — the last is the one a reader would assume;
- **no interior gaps in any country**, unique among REIM's families (spec §2.1);
- **declared decimals are wrong by up to twenty-two places** (spec §3.2);
- **there is no server-side filtering**, and two parameter forms silently return
  the whole cube (spec §2.2);
- **attribution is multiple per country** and the footnotes block is populated
  (spec §3.3);
- **25 of 55 items are stored**, with the 30 unstored ones named so a later
  increment starts from this measurement;
- **the two traps** — reserve assets is a flow, current transfers is not
  remittances (spec §4.1);
- **the first run's exact result** from Step 2.

Then update "Reachable, not ingested": 547 leaves the table, and the prose
saying "two families beyond the eight REIM reads" becomes one beyond nine.
Check the surrounding counts.

- [ ] **Step 5: Update `ROADMAP.md` and `README.md`**

`ROADMAP.md`: v0.3.0 gains a line in the established voice — REIM's first
balance-of-payments data and second quarterly source, 19,582 observations, and
the BPM5/BPM6 finding. Also update the catalog census (`8 annual, 11 monthly,
2 daily and 1 quarterly` becomes `… and 2 quarterly`) and, in v0.2.0, the
reserves and remittances bullets should note that 547 is now read and still does
**not** close either gap.

`README.md`: add the source and the 25 indicators to their tables, and check the
pipeline and indicator counts, which move from 22 and 38.

- [ ] **Step 6: Run the gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . \
  && .venv/bin/mypy reim apps && .venv/bin/pytest -q 2>&1 | tail -2
git add docs/sources.md ROADMAP.md README.md
git commit -m "docs(cepalstat): the balance of payments, and what the first run showed"
make db-down CONTAINER_ENGINE=podman
```

`ruff format` reaches Python fenced in Markdown. If it rewrites a block in
`docs/sources.md`, that block is not a valid standalone module — fence it as
```text and re-run until clean.

---

## Self-review

**Spec coverage.** §2 source and volume → Tasks 1, 4. §2.1 coverage → Tasks 1, 6.
§2.2 no filtering → Tasks 4, 6. §3.1 BPM contradiction → Tasks 2, 6. §3.2
decimals → Tasks 1, 4, 6. §3.3 attribution → Tasks 4, 6. §3.4 identities →
Tasks 1, 5, 6. §3.5 negatives and zeros → Tasks 3, 4. §3.6 translated names →
Task 4. §4 scope → Tasks 2, 4. §4.1 traps → Task 2. §4.2 goods overlap → Task 2.
§5 architecture → Task 4. §6.1 rules → Task 3. §6.2 checks → Task 5. §6.3 first
run → Task 6. §7 testing → Tasks 1, 4, 5. §8 D1–D9 all land in a task. No gaps.

**Type consistency.** `ITEMS` maps `int` to `str` and `ITEM_NAMES` maps the same
keys to published names — Task 4 defines both and Task 5 uses neither directly.
`_check_country_coverage` takes `(observations, Mapping[str, frozenset[str]],
str)`, verified against `cepalstat.py`. `IDENTITY_TOLERANCE` is scaled by
`MILLIONS`, which Task 5's step calls out explicitly because forgetting it makes
every identity check fail.

**Known soft spots.** Task 5's test breaks `CRI 2010-Q1` — confirm that
country-quarter exists in the recording before relying on it; the test asserts
this itself. Task 2's descriptions are prose the plan does not spell out
verbatim, deliberately: 25 of them would be unreadable here, and the tests pin
the two that carry mandatory warnings.
