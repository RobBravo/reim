# CEPALSTAT interest rates — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest CEPALSTAT indicators 856, 857 and 1206 as
`lending_rate_nominal_monthly`, `deposit_rate_nominal_monthly` and
`policy_rate_monthly` — 6,564 observations, seven countries, monthly from 1990
— giving REIM its first interest-rate data and its first use of the
`financial` indicator category.

**Architecture:** One `CepalstatConnector` subclass holding three
`SeriesSpec` entries, on `cepalstat_monetary.py`'s shape. Dimension 3981's
period handling first moves from that connector into the shared
`cepalstat.py` base, so both families use one copy. Four requests: three for
data in English, one for the Spanish member table.

**Tech Stack:** Python 3.13, httpx + respx, SQLAlchemy 2, pytest, ruff, mypy.
Run tools as `.venv/bin/<tool>` — there is no `pip` in the venv. Integration
work needs `make db-up CONTAINER_ENGINE=podman`.

**Spec:** `docs/superpowers/specs/2026-09-07-cepalstat-interest-rates-design.md`

## Global Constraints

* **Values are stored exactly as published** — no scaling and no rounding.
  Indicator 856 declares `decimals: 0` and publishes two in 2,065 of 2,490
  cells (spec §3.5).
* **Only the twelve monthly members of dimension 3981 become observations.**
  `Anual` and `Trimestre N` are *means* of their months here, not restatements
  of a period end (spec §3.2, D2).
* **Panama is excluded from `policy_rate_monthly` only** (spec §3.3, D3). It
  keeps its lending and deposit series.
* **Nicaragua's 2010-03 and 2010-04 zeros in 1206 are stored** (spec §3.4, D4).
* **CEPAL's defects are recorded, never repaired** — Costa Rica's `CBBO`
  attribution in 857 and the null `source_id` on 345 rows of 1206 (spec §2.2,
  D11).
* **Only the seven Central American countries**, filtered from 145.
* **Tests never call an official source.** Every payload is replayed from a
  recording through `respx`.
* **The verification gate is CI's, over the whole repository:**
  `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest`.
  `ruff format` also formats Python fenced in Markdown, so `docs/` is in scope.
* Measured facts this plan asserts, all from 2026-09-07: 2,490 / 2,453 / 1,621
  stored observations; lending > deposit in all 2,453 shared months, spread
  1.18 to 18.84; no calendar-adjacent move beyond 8 points in 6,523 pairs,
  the largest being Belize 1206 2010-12 at 7 (18 → 11); Nicaragua 857
  1999-12 → 2000-01 is 5.8 points; the newest cell across all 145 countries is
  2025-10 on all three.

---

### Task 1: Record the four responses

**Files:**
- Create: `tests/fixtures/cepalstat_rates_856.json.gz`
- Create: `tests/fixtures/cepalstat_rates_857.json.gz`
- Create: `tests/fixtures/cepalstat_rates_1206.json.gz`
- Create: `tests/fixtures/cepalstat_dimensions_856.json.gz`
- Modify: `tests/fixtures/README.md`
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: session-scoped fixtures `cepalstat_rates_856_json() -> str`,
  `cepalstat_rates_857_json() -> str`, `cepalstat_rates_1206_json() -> str`,
  `cepalstat_dimensions_856_json() -> str`.

- [ ] **Step 1: Record them**

```bash
cd "$(git rev-parse --show-toplevel)"
UA='REIM/0.1.0 (Regional Economic Intelligence Monitor; +https://github.com/RobBravo/reim)'
BASE='https://api-cepalstat.cepal.org/cepalstat/api/v1'
for id in 856 857 1206; do
  curl -s -H "User-Agent: $UA" "$BASE/indicator/$id/data?lang=en" \
    | gzip -9 > "tests/fixtures/cepalstat_rates_$id.json.gz"
done
curl -s -H "User-Agent: $UA" "$BASE/indicator/856/dimensions?lang=es" \
  | gzip -9 > tests/fixtures/cepalstat_dimensions_856.json.gz
ls -l tests/fixtures/cepalstat_rates_*.json.gz tests/fixtures/cepalstat_dimensions_856.json.gz
```

Uncompressed the data responses are 1.70 MB, 1.80 MB and 1.38 MB and take
7–13 s each; the dimensions response is 28 KB.

- [ ] **Step 2: Verify the recordings hold what the plan claims**

```bash
.venv/bin/python - <<'PY'
import gzip, json, collections
from decimal import Decimal

def load(name):
    return json.loads(gzip.decompress(open(f"tests/fixtures/{name}.json.gz","rb").read()))

SEVEN = {"NIC","GTM","SLV","HND","CRI","PAN","BLZ"}
MONTHS = {"Enero":1,"Febrero":2,"Marzo":3,"Abril":4,"Mayo":5,"Junio":6,
          "Julio":7,"Agosto":8,"Septiembre":9,"Octubre":10,"Noviembre":11,"Diciembre":12}

dims = load("cepalstat_dimensions_856")["body"]["dimensions"]
period = {m["id"]: m["name"] for d in dims if d["id"] == 3981 for m in d["members"]}
assert sorted(set(period.values()) & set(MONTHS)) == sorted(MONTHS), "Spanish months missing"
print("period members:", len(period), "| months found:", len(set(period.values()) & set(MONTHS)))

EXPECTED = {856: 2490, 857: 2453, 1206: 1621}
cells = {}
for cid in (856, 857, 1206):
    body = load(f"cepalstat_rates_{cid}")["body"]
    years = {m["id"]: m["name"] for d in body["dimensions"] if d["id"] == 29117 for m in d["members"]}
    english = {m["name"] for d in body["dimensions"] if d["id"] == 3981 for m in d["members"]}
    assert english == {"descripcion_ingles"}, f"{cid} period members unexpectedly translated"
    got = {}
    for row in body["data"]:
        if row["iso3"] not in SEVEN or period[row["dim_3981"]] not in MONTHS:
            continue
        if cid == 1206 and row["iso3"] == "PAN":
            continue
        got[(row["iso3"], int(years[row["dim_29117"]]), MONTHS[period[row["dim_3981"]]])] = Decimal(row["value"])
    cells[cid] = got
    assert len(got) == EXPECTED[cid], f"{cid}: {len(got)} != {EXPECTED[cid]}"
    print(cid, body["metadata"]["indicator_name"], "|", len(got), "cells | unit:", body["metadata"]["unit"])

shared = set(cells[856]) & set(cells[857])
spread = [cells[856][k] - cells[857][k] for k in shared]
assert min(spread) > 0, "lending is not always above deposit"
print("spread: n =", len(shared), "min", min(spread), "max", max(spread))

worst = Decimal(0)
for cid, got in cells.items():
    by_country = collections.defaultdict(dict)
    for (iso3, y, m), v in got.items():
        by_country[iso3][(y, m)] = v
    for iso3, series in by_country.items():
        keys = sorted(series)
        for a, b in zip(keys, keys[1:]):
            if (b[0]-a[0])*12 + (b[1]-a[1]) == 1:
                worst = max(worst, abs(series[b] - series[a]))
print("largest calendar-adjacent move:", worst, "points")
assert worst < 8, "a move reaches the 8-point threshold"

pan = [r for r in load("cepalstat_rates_1206")["body"]["data"] if r["iso3"] == "PAN"]
assert {r["value"] for r in pan} == {"0"} and {r["source_id"] for r in pan} == {None}
print("Panama in 1206:", len(pan), "rows, all zero, all unattributed")
nic = load("cepalstat_rates_1206")["body"]
years = {m["id"]: m["name"] for d in nic["dimensions"] if d["id"] == 29117 for m in d["members"]}
zeros = sorted((years[r["dim_29117"]], period[r["dim_3981"]]) for r in nic["data"]
               if r["iso3"] == "NIC" and r["value"] == "0" and period[r["dim_3981"]] in MONTHS)
print("Nicaragua zero months in 1206:", zeros)
assert set(zeros) == {("2010", "Marzo"), ("2010", "Abril")}
print("ALL RECORDING ASSERTIONS PASSED")
PY
```

Expected: every assertion passes, `2490 / 2453 / 1621` cells, spread min
`1.18` max `18.84`, largest move `7`, Panama 16 rows.

If a count differs, CEPAL has revised the table since 2026-09-07. **Stop and
report** — the spec's measured numbers, and every threshold derived from them,
would need re-deriving rather than adjusting.

- [ ] **Step 3: Add the conftest fixtures**

Append to `tests/conftest.py`, after `cepalstat_cpi_365_json`:

```python
@pytest.fixture(scope="session")
def cepalstat_rates_856_json() -> str:
    """CEPALSTAT indicator 856, nominal lending rate (stored gzipped)."""
    return gzip.decompress((FIXTURES / "cepalstat_rates_856.json.gz").read_bytes()).decode("utf-8")


@pytest.fixture(scope="session")
def cepalstat_rates_857_json() -> str:
    """CEPALSTAT indicator 857, nominal deposit rate (stored gzipped)."""
    return gzip.decompress((FIXTURES / "cepalstat_rates_857.json.gz").read_bytes()).decode("utf-8")


@pytest.fixture(scope="session")
def cepalstat_rates_1206_json() -> str:
    """CEPALSTAT indicator 1206, monetary policy rate (stored gzipped)."""
    return gzip.decompress((FIXTURES / "cepalstat_rates_1206.json.gz").read_bytes()).decode("utf-8")


@pytest.fixture(scope="session")
def cepalstat_dimensions_856_json() -> str:
    """Indicator 856's dimensions in Spanish — the only place a month is named."""
    return gzip.decompress((FIXTURES / "cepalstat_dimensions_856.json.gz").read_bytes()).decode(
        "utf-8"
    )
```

- [ ] **Step 4: Document the recordings**

Add four rows to the table in `tests/fixtures/README.md`, after the
`cepalstat_cpi_365.json.gz` row. Use the byte sizes `ls -l` reported in Step 1
in place of the `→` figures below:

```text
| `cepalstat_rates_856.json.gz` | `GET https://api-cepalstat.cepal.org/cepalstat/api/v1/indicator/856/data?lang=en`, byte-for-byte, gzipped only to keep the repo small (1.70 MB → NN KB). Tests decompress it before parsing. The **complete** response — 145 countries and every period member — because that is what proves the filter to the seven Central American countries and the discarding of the annual and quarterly members. | 2026-09-07 |
| `cepalstat_rates_857.json.gz` | Same endpoint, indicator `857` — nominal deposit rate (1.80 MB → NN KB). The only place the lending-above-deposit invariant can be asserted, and the only place CEPAL's `CBBO` misattribution of Costa Rica is visible. | 2026-09-07 |
| `cepalstat_rates_1206.json.gz` | Same endpoint, indicator `1206` — monetary policy rate (1.38 MB → NN KB). Holds Panama's sixteen uniformly zero, wholly unattributed 2022 rows, Nicaragua's two genuine 2010 zeros, and the 345 rows whose `source_id` is null. | 2026-09-07 |
| `cepalstat_dimensions_856.json.gz` | `GET .../indicator/856/dimensions?lang=es`, byte-for-byte, gzipped (28 KB → N KB). Recorded in Spanish because `lang=en` returns all seventeen period members as the untranslated string `descripcion_ingles`. Dimension 3981's member table was measured identical across 856, 857 and 1206, so the rates connector fetches it once. | 2026-09-07 |
```

Also update the sentence below the table that counts the recordings — it reads
"these fifteen were recorded with REIM's own identifier" and must become
"nineteen".

- [ ] **Step 5: Verify the fixtures load**

```bash
.venv/bin/pytest tests/unit -q -k cepalstat 2>&1 | tail -3
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: the existing CEPALSTAT tests still pass and the gate is clean. The
new fixtures have no consumer yet.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/cepalstat_rates_856.json.gz \
        tests/fixtures/cepalstat_rates_857.json.gz \
        tests/fixtures/cepalstat_rates_1206.json.gz \
        tests/fixtures/cepalstat_dimensions_856.json.gz \
        tests/fixtures/README.md tests/conftest.py
git commit -m "test(cepalstat): record the three interest-rate responses"
```

---

### Task 2: Move dimension 3981's handling into the shared base

A pure move, spec §4.3 / D9. `cepalstat_monetary.py`'s existing tests are the
regression gate: they must pass unchanged, with no edit to the test file.

**Files:**
- Modify: `reim/ingestion/connectors/regional/cepalstat.py`
- Modify: `reim/ingestion/connectors/regional/cepalstat_monetary.py`
- Test: `tests/unit/test_cepalstat_monetary_connector.py` (run, do not edit)

**Interfaces:**
- Consumes: nothing.
- Produces, from `reim.ingestion.connectors.regional.cepalstat`:
  - `PERIOD_DIMENSION: int` — `3981`
  - `MONTHS_BY_SPANISH_NAME: dict[str, int]`
  - `NON_MONTH_MEMBERS: frozenset[str]`
  - `CepalstatConnector._months_of(self, dimensions_document: Any, cepal_id: int) -> dict[int, int | None]`
  - `CepalstatConnector._month_of(self, row: Any, months: dict[int, int | None], cepal_id: int) -> int | None`

- [ ] **Step 1: Confirm the gate is green before moving anything**

```bash
.venv/bin/pytest tests/unit/test_cepalstat_monetary_connector.py -q 2>&1 | tail -3
```

Expected: PASS. Record the count — the same count must hold after the move.

- [ ] **Step 2: Add the constants to `cepalstat.py`**

Below `YEARS_DIMENSION = 29117`:

```python
#: The period-within-year dimension. Belongs to the dimension rather than to
#: any family: the monetary aggregates and the interest rates both carry it,
#: with the same seventeen members and the same ids.
PERIOD_DIMENSION = 3981

#: The only member names that become observations. Read from the Spanish
#: dimensions response, because ``lang=en`` returns all seventeen members as
#: the untranslated string ``descripcion_ingles`` and the ids run 3982-3998
#: out of calendar order, with September at 3993 and July at 3994.
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

#: The only period members that are legitimately not months. Together with
#: ``MONTHS_BY_SPANISH_NAME`` this makes the label classification total: any
#: label in neither set is a contract break (a rename or an unannounced new
#: member) and must raise rather than silently fall out as "not a month".
#:
#: What these members *mean* differs by family, and neither connector stores
#: them either way: for the monetary aggregates they restate a period-end
#: stock exactly, and for the interest rates they are means of their months.
NON_MONTH_MEMBERS = frozenset({"Anual", "Trimestre 1", "Trimestre 2", "Trimestre 3", "Trimestre 4"})
```

- [ ] **Step 3: Move the two methods into `CepalstatConnector`**

Cut `_months_of` and `_month_of` from `cepalstat_monetary.py` and paste them
into `CepalstatConnector` in `cepalstat.py`, immediately before
`_check_monthly_continuity`. The bodies are unchanged. Their docstrings gain
one line each recording that they are shared:

`_months_of` — after its existing first line, add:

```text
    Shared by every family that carries dimension 3981.
```

- [ ] **Step 4: Extend the base module's docstring**

`cepalstat.py`'s docstring currently says "Nothing about an indicator family's
dimensions belongs in this file." That is now false and must be corrected
rather than left to contradict the code. Replace that sentence and the one
after it with:

```text
Dimension 3981 is the one exception, and it earns it: the period-within-year
member table is a property of the dimension, not of a family. Two families
carry it — the monetary aggregates and the interest rates — with the same
seventeen members, the same out-of-order ids and the same untranslated
English names, so ``_months_of`` and ``_month_of`` live here rather than
being copied. Everything else about a family's dimensions still belongs to
its own connector. Each connector still names its own dimensions and writes
its own ``extract``, ``transform`` and ``validate``: GDP reads a
country-by-year matrix, public debt carries four dimensions, and the exchange
rate carries a twelve-member month dimension of its own. Merging those
transforms was rejected in design and stays rejected.
```

- [ ] **Step 5: Re-point `cepalstat_monetary.py` at the base**

Delete its local `PERIOD_DIMENSION`, `MONTHS_BY_SPANISH_NAME` and
`NON_MONTH_MEMBERS`, and import them instead:

```python
from reim.ingestion.connectors.regional.cepalstat import (
    MONTHS_BY_SPANISH_NAME,
    NON_MONTH_MEMBERS,
    PERIOD_DIMENSION,
    YEARS_DIMENSION,
    CepalstatConnector,
)
```

`MONTHS_BY_SPANISH_NAME` and `NON_MONTH_MEMBERS` are no longer referenced in
that module's body once the methods have moved, but the module docstring
discusses them and the test module imports neither. Verify with:

```bash
grep -n "MONTHS_BY_SPANISH_NAME\|NON_MONTH_MEMBERS\|PERIOD_DIMENSION" \
  reim/ingestion/connectors/regional/cepalstat_monetary.py
```

If a name is genuinely unreferenced after the move, drop it from the import
rather than leaving `ruff` to flag it.

- [ ] **Step 6: Run the regression gate**

```bash
.venv/bin/pytest tests/unit/test_cepalstat_monetary_connector.py -q 2>&1 | tail -3
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps
```

Expected: the same pass count as Step 1, with the test file unedited. Any
change in behaviour means this stopped being a pure move.

- [ ] **Step 7: Commit**

```bash
git add reim/ingestion/connectors/regional/cepalstat.py \
        reim/ingestion/connectors/regional/cepalstat_monetary.py
git commit -m "refactor(cepalstat): dimension 3981 belongs to the base, not to one family"
```

---

### Task 3: Register the three indicators and the comparability field

**Files:**
- Modify: `reim/domain/indicators/registry.py`
- Test: `tests/unit/test_catalog.py` — where the registry tests live, beside
  `test_the_three_monetary_indicators_are_registered`

**Interfaces:**
- Consumes: nothing.
- Produces: `IndicatorDefinition.methodology_varies_by_country: bool`, default
  `False`; registry codes `lending_rate_nominal_monthly`,
  `deposit_rate_nominal_monthly`, `policy_rate_monthly`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_catalog.py`, beside
`test_the_three_monetary_indicators_are_registered`. That module already
imports `INDICATORS`, `INDICATORS_BY_CODE`, `IndicatorCategory`, `Frequency`
and `ValueType`, so no import changes are needed:

```python
def test_interest_rates_are_registered_and_declare_varying_methodology() -> None:
    """The three CEPAL rates share a unit and declare CEPAL's per-country methods."""
    codes = (
        "lending_rate_nominal_monthly",
        "deposit_rate_nominal_monthly",
        "policy_rate_monthly",
    )
    for code in codes:
        definition = INDICATORS_BY_CODE[code]
        assert definition.category is IndicatorCategory.FINANCIAL
        assert definition.frequency is Frequency.MONTHLY
        assert definition.unit == "percent per annum"
        assert definition.value_type is ValueType.PERCENT
        assert definition.currency_convertible is False
        assert definition.methodology_varies_by_country is True


def test_methodology_varies_by_country_defaults_to_false() -> None:
    """Only the three CEPAL rates declare it; nothing else changed meaning."""
    declaring = {i.code for i in INDICATORS if i.methodology_varies_by_country}
    assert declaring == {
        "lending_rate_nominal_monthly",
        "deposit_rate_nominal_monthly",
        "policy_rate_monthly",
    }
```

The second test also guards the field's blast radius: it asserts that exactly
these three indicators declare it, so a later edit that sets it somewhere else
has to be deliberate.

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/pytest tests/unit/test_catalog.py -q -k "interest_rates or methodology_varies" 2>&1 | tail -5
```

Expected: FAIL — `KeyError: 'lending_rate_nominal_monthly'`.

- [ ] **Step 3: Add the field to `IndicatorDefinition`**

After `currency_convertible`:

```text
    #: Whether the publisher defines this indicator differently in each
    #: country, so that levels may not be read against each other even when
    #: the unit and the currency match. CEPAL's interest rates declare exactly
    #: this in their own ``calculation_methodology`` field: "According to the
    #: definition from each country." ``/compare`` states it as a note and
    #: still returns the series — see the interest-rates design, decision D6.
    methodology_varies_by_country: bool = False
```

- [ ] **Step 4: Add the three definitions**

Before the closing `)` of `INDICATORS`:

```text
    IndicatorDefinition(
        code="lending_rate_nominal_monthly",
        name="Nominal lending rate (monthly)",
        description=(
            "Monthly nominal lending rate for the seven Central American "
            "countries, compiled by ECLAC from each country's own central "
            "bank. CEPAL defines the rate differently in each country: a "
            "weighted average in local currency for Costa Rica, Guatemala and "
            "Honduras; the basic lending rate for up to one year in El "
            "Salvador; a weighted average of short-term rates in Nicaragua; "
            "the rate on one-year trade credit in Panama; and a weighted "
            "average over personal, business, residential and other "
            "construction loans in Belize. Levels are therefore not "
            "comparable across countries, only their movements."
        ),
        category=IndicatorCategory.FINANCIAL,
        frequency=Frequency.MONTHLY,
        unit="percent per annum",
        value_type=ValueType.PERCENT,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=856&lang=en",
        methodology_varies_by_country=True,
    ),
    IndicatorDefinition(
        code="deposit_rate_nominal_monthly",
        name="Nominal deposit rate (monthly)",
        description=(
            "Monthly nominal deposit rate for the seven Central American "
            "countries, compiled by ECLAC from each country's own central "
            "bank. CEPAL defines the rate differently in each country: the "
            "average local-currency deposit rate in Costa Rica, a 180-day "
            "saving rate in El Salvador, a weighted average of term deposit "
            "rates in Honduras, 30-day local-currency passive rates in "
            "Nicaragua, six-month deposits in Panama, and a weighted average "
            "in Belize. Levels are therefore not comparable across countries, "
            "only their movements. CEPAL's own definition text calls "
            "Guatemala's series a lending rate; the data is a deposit rate, "
            "below lending_rate_nominal_monthly in all 357 shared months."
        ),
        category=IndicatorCategory.FINANCIAL,
        frequency=Frequency.MONTHLY,
        unit="percent per annum",
        value_type=ValueType.PERCENT,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=857&lang=en",
        methodology_varies_by_country=True,
    ),
    IndicatorDefinition(
        code="policy_rate_monthly",
        name="Monetary policy rate (monthly)",
        description=(
            "Monthly monetary policy rate for six Central American countries, "
            "compiled by ECLAC. CEPAL defines the rate differently in each: "
            "the yield on 180-day central bank bonds in Nicaragua, a "
            "stock-exchange repo yield over 1-7 days in El Salvador, the rate "
            "on local-currency central bank operations in Costa Rica, and the "
            "Central Bank's own lending rate in Belize. Levels are therefore "
            "not comparable across countries, only their movements. Panama is "
            "absent: it is dollarised and has no central bank, and CEPAL's "
            "twelve zero-valued, unattributed 2022 cells for it are an "
            "artifact REIM does not store."
        ),
        category=IndicatorCategory.FINANCIAL,
        frequency=Frequency.MONTHLY,
        unit="percent per annum",
        value_type=ValueType.PERCENT,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=1206&lang=en",
        methodology_varies_by_country=True,
    ),
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_catalog.py -q 2>&1 | tail -3
.venv/bin/mypy reim apps
```

Expected: PASS, and mypy clean.

- [ ] **Step 6: Commit**

```bash
git add reim/domain/indicators/registry.py tests/unit/test_catalog.py
git commit -m "feat(cepalstat): register the three interest rates"
```

---

### Task 4: Catalog entry and quality rules

**Files:**
- Modify: `sources/catalog.yml`
- Modify: `sources/quality_rules.yml`
- Test: `tests/unit/test_catalog.py`

**Interfaces:**
- Consumes: the three indicator codes from Task 3.
- Produces: catalog key `cepalstat_rates_monthly`, resolving to
  `reim.ingestion.connectors.regional.cepalstat_rates` (created in Task 5).

- [ ] **Step 1: Add the catalog entry**

After the `cepalstat_cpi_monthly` entry in `sources/catalog.yml`:

```yaml
  - key: cepalstat_rates_monthly
    name: Central American interest rates (monthly)
    description: >-
      Monthly nominal lending rates, nominal deposit rates and monetary policy
      rates for the seven Central American countries, from CEPALSTAT, compiled
      from each country's own central bank. CEPAL defines each rate
      differently in each country, so levels are not comparable across
      countries — only their movements are. Panama is absent from the policy
      rate: it has no central bank.
    organization: CEPAL
    category: financial
    access_type: http_api
    frequency: monthly
    format: json
    base_url: https://api-cepalstat.cepal.org/cepalstat/api/v1
    documentation_url: https://statistics.cepal.org/portal/cepalstat/
    connector: reim.ingestion.connectors.regional.cepalstat_rates
    indicators:
      - lending_rate_nominal_monthly
      - deposit_rate_nominal_monthly
      - policy_rate_monthly
    license: cepal_terms_of_use
    official: true
    enabled: true
```

- [ ] **Step 2: Add the quality rules**

After the `cpi_index_monthly` block in `sources/quality_rules.yml`:

```yaml
  lending_rate_nominal_monthly:
    min_value: 0
    max_value: null
    allow_negative: false
    allow_zero: false
    # Nicaragua's largest real move is +45.1% in 2011-12 (9.09 -> 13.19).
    # 60 clears it and still reports a discontinuity. Kept only on this
    # series: see the two below for why it cannot work on them.
    max_period_change_pct: 60
    monotonic_increasing: false
    # The family ends 2025-10 worldwide while CEPAL's own last_update is
    # 2026-08: it genuinely lags about eleven months, so the stalest country
    # is 342 days old as of 2026-09-07. 450 matches the exchange-rate rule at
    # the identical lag, passes with headroom, and still catches a family that
    # has stopped being extended.
    freshness_max_age_days: 450
    min_observations: 2400

  deposit_rate_nominal_monthly:
    min_value: 0
    max_value: null
    allow_negative: false
    allow_zero: false
    # Deliberately null. This series sits near zero, where a percentage change
    # is unbounded and meaningless as a tripwire: Nicaragua moving 0.5 -> 1.7
    # is +240% and 1.2 points, and 79 moves exceed 25%, essentially all real.
    # `cepalstat_rates_step` measures percentage *points* instead. Same call
    # ni_cpi_inflation_monthly already makes.
    max_period_change_pct: null
    monotonic_increasing: false
    # Belize, Costa Rica and Honduras end 2025-08, the stalest in the family
    # at 372 days on 2026-09-07. 450 passes that with 78 days of headroom.
    freshness_max_age_days: 450
    min_observations: 2350

  policy_rate_monthly:
    min_value: 0
    max_value: null
    allow_negative: false
    # Nicaragua publishes a genuine 0 in 2010-03 and 2010-04, inside a real
    # attributed series. The other two rate series never publish a zero.
    allow_zero: true
    # Null for the same reason as the deposit rate: El Salvador moving
    # 1.47 -> 4.87 is +231% and 3.4 points, and 85 moves exceed 25%.
    max_period_change_pct: null
    monotonic_increasing: false
    freshness_max_age_days: 450
    # 1,621 measured across six countries; Nicaragua's 61 interior gaps could
    # widen, so this sits further below the measurement than its two siblings.
    min_observations: 1550
```

- [ ] **Step 3: Validate the catalog**

```bash
.venv/bin/python -m reim.cli catalog validate 2>&1 | tail -20
```

Expected: FAIL — `ConnectorLoadError`, module
`reim.ingestion.connectors.regional.cepalstat_rates` does not exist. That is
the correct state until Task 5; it proves the entry is being resolved.

- [ ] **Step 4: Commit**

```bash
git add sources/catalog.yml sources/quality_rules.yml
git commit -m "feat(cepalstat): catalog entry and quality rules for the interest rates"
```

---

### Task 5: The connector's extraction

**Files:**
- Create: `reim/ingestion/connectors/regional/cepalstat_rates.py`
- Create: `tests/unit/test_cepalstat_rates_connector.py`

**Interfaces:**
- Consumes: `CepalstatConnector`, `PERIOD_DIMENSION`,
  `MONTHS_BY_SPANISH_NAME`, `NON_MONTH_MEMBERS`, `YEARS_DIMENSION` from Task 2;
  the catalog entry from Task 4.
- Produces:
  - `SeriesSpec(cepal_id: int, indicator_code: str)` — frozen dataclass
  - `SERIES: tuple[SeriesSpec, ...]`
  - `CENTRAL_AMERICA: frozenset[str]`
  - `EXPECTED_COUNTRIES: dict[str, frozenset[str]]`
  - `DIMENSIONS_INDICATOR: int` — `856`
  - `MAX_STEP_POINTS: Decimal`
  - `CepalstatRatesConnector` with `connector_key = "cepalstat_rates_monthly"`,
    `version = "1.0.0"`, `expected_frequency = Frequency.MONTHLY`
  - `async extract(self) -> RawDataset` with
    `payload = {"data": {856: str, 857: str, 1206: str}, "dimensions": str}`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_cepalstat_rates_connector.py`:

```python
"""Unit tests for the CEPALSTAT monthly interest-rates connector.

Every payload replayed here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from reim.domain.sources.catalog import load_catalog
from reim.ingestion.connectors.regional.cepalstat_rates import (
    CepalstatRatesConnector,
)
from tests.conftest import REPO_ROOT

BASE = "https://api-cepalstat.cepal.org/cepalstat/api/v1"


@pytest.fixture
def connector() -> CepalstatRatesConnector:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    return CepalstatRatesConnector(catalog.get("cepalstat_rates_monthly"))


def mount(
    respx_mock: respx.MockRouter,
    data: dict[int, str],
    dimensions: str,
) -> None:
    """Serve the three data responses and the one Spanish dimensions response."""
    for cepal_id, text in data.items():
        respx_mock.get(f"{BASE}/indicator/{cepal_id}/data").mock(
            return_value=httpx.Response(
                200, text=text, headers={"content-type": "application/json"}
            )
        )
    respx_mock.get(f"{BASE}/indicator/856/dimensions").mock(
        return_value=httpx.Response(
            200, text=dimensions, headers={"content-type": "application/json"}
        )
    )


@pytest.mark.anyio
@respx.mock
async def test_extract_makes_four_requests_not_six(
    connector: CepalstatRatesConnector,
    cepalstat_rates_856_json: str,
    cepalstat_rates_857_json: str,
    cepalstat_rates_1206_json: str,
    cepalstat_dimensions_856_json: str,
    respx_mock: respx.MockRouter,
) -> None:
    """Dimension 3981's member table is fetched once, not once per indicator.

    It belongs to the dimension, not to an indicator, and was measured
    byte-identical across 856, 857 and 1206.
    """
    mount(
        respx_mock,
        {
            856: cepalstat_rates_856_json,
            857: cepalstat_rates_857_json,
            1206: cepalstat_rates_1206_json,
        },
        cepalstat_dimensions_856_json,
    )

    raw = await connector.extract()

    assert len(respx_mock.calls) == 4
    dimension_calls = [call for call in respx_mock.calls if "dimensions" in str(call.request.url)]
    assert len(dimension_calls) == 1
    assert "indicator/856/dimensions" in str(dimension_calls[0].request.url)
    assert dimension_calls[0].request.url.params["lang"] == "es"

    data_calls = [call for call in respx_mock.calls if "/data" in str(call.request.url)]
    assert {call.request.url.params["lang"] for call in data_calls} == {"en"}
    assert set(raw.payload["data"]) == {856, 857, 1206}
    assert isinstance(raw.payload["dimensions"], str)
```

Match the async-test decorator and `respx_mock` fixture style to
`tests/unit/test_cepalstat_monetary_connector.py`; copy its exact form rather
than assuming the ones above.

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/pytest tests/unit/test_cepalstat_rates_connector.py -q 2>&1 | tail -5
```

Expected: FAIL — `ModuleNotFoundError: reim.ingestion.connectors.regional.cepalstat_rates`.

- [ ] **Step 3: Write the module header and `extract`**

Create `reim/ingestion/connectors/regional/cepalstat_rates.py`:

```python
"""Central America — monthly interest rates published through CEPALSTAT.

The API, its lack of documentation and the way its routes were recovered are
documented in ``cepalstat.py``, which this connector's base class comes from;
only what differs is recorded here.

This family carries the same period-within-year dimension as the monetary
aggregates, handled in the base class — including that ``lang=en`` returns all
seventeen of its members as the untranslated string ``descripcion_ingles``,
which is why a Spanish member table is fetched at all.

**Four things differ from the monetary family:**

1. **One dimensions request, not three.** The member table belongs to
   dimension 3981, not to an indicator, and was measured byte-identical across
   856, 857 and 1206 on 2026-09-07.
2. **The annual and quarterly members are means of their months, not
   restatements of a period end.** For the monetary aggregates the annual
   figure *is* December's stock and each quarter *is* its closing month, which
   is why dropping them loses nothing. Here the annual figure equals the mean
   of its twelve months in 202 of 202 checkable cases on indicator 856, and
   each quarter the mean of its three in 693 of 693. They are dropped for the
   opposite reason: storing a mean beside its own inputs would publish a
   derived figure as if CEPAL had published it.
3. **Nothing is scaled.** These are percentages, stored exactly as published.
   Indicator 856 declares ``decimals: 0`` and publishes two in 2,065 of 2,490
   cells, so the declared precision is not usable as a rounding instruction.
4. **Panama has no monetary policy rate.** It is dollarised and has no central
   bank. CEPAL nonetheless publishes sixteen rows for it on indicator 1206,
   every one ``'0'`` and every one with a null ``source_id``, all inside 2022.
   That is an artifact of the table rather than a measurement, and REIM stores
   none of it. Nicaragua's two zeros in 2010-03 and 2010-04 are a different
   thing — real cells in a live attributed series — and are stored.

CEPAL states in its own ``calculation_methodology`` that each country's rate
is defined "according to the definition from each country", and the
``definition`` field spells that out: Panama's lending rate is the rate on
one-year trade credit, Belize's "policy rate" is its central bank's lending
rate. The three indicators therefore declare
``methodology_varies_by_country``, and ``/compare`` states it as a note.
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

CENTRAL_AMERICA = frozenset({"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"})

#: Whose dimensions response is fetched. Any of the three would serve; 856 is
#: named so the request is deterministic and the fixture has one origin.
DIMENSIONS_INDICATOR = 856

#: Published as "Annual percentage"; stored under REIM's own name for it.
UNIT = "percent per annum"

#: Panama is dollarised, has no central bank and therefore no policy rate.
#: CEPAL's sixteen zero-valued, unattributed 2022 rows are an artifact.
NO_POLICY_RATE = frozenset({"PAN"})


@dataclass(frozen=True, slots=True)
class SeriesSpec:
    """One CEPAL indicator id, the REIM code it feeds, and who it excludes."""

    cepal_id: int
    indicator_code: str
    excluded_countries: frozenset[str] = frozenset()


SERIES: tuple[SeriesSpec, ...] = (
    SeriesSpec(856, "lending_rate_nominal_monthly"),
    SeriesSpec(857, "deposit_rate_nominal_monthly"),
    SeriesSpec(1206, "policy_rate_monthly", NO_POLICY_RATE),
)

#: Countries each series covers, measured 2026-09-07. Encoded so that a
#: disappearance is visible and Panama's absence is stated rather than
#: discovered.
EXPECTED_COUNTRIES: dict[str, frozenset[str]] = {
    "lending_rate_nominal_monthly": CENTRAL_AMERICA,
    "deposit_rate_nominal_monthly": CENTRAL_AMERICA,
    "policy_rate_monthly": CENTRAL_AMERICA - NO_POLICY_RATE,
}

#: Largest calendar-adjacent move the family may make without comment, in
#: percentage points. The largest measured anywhere in 6,523 adjacent pairs is
#: Belize's policy rate stepping 18 -> 11 in 2010-12, which is 7. Percentage
#: change cannot do this job: these series sit near zero, where 0.5 -> 1.7 is
#: +240% and 1.2 points.
MAX_STEP_POINTS = Decimal("8")


class CepalstatRatesConnector(CepalstatConnector):
    """Monthly lending, deposit and policy rates for Central America."""

    connector_key = "cepalstat_rates_monthly"
    version = "1.0.0"
    expected_frequency = Frequency.MONTHLY

    async def extract(self) -> RawDataset:
        """Fetch the three data responses and one Spanish member table.

        Four requests. The dimensions request is made once because dimension
        3981's members belong to the dimension rather than to an indicator;
        ``_month_of`` raises on any member id the table does not hold, so a
        future divergence between the three surfaces as a failure rather than
        as a silent drop.

        Raises:
            ExtractionError: The API was unreachable, answered with something
                other than JSON, reported ``success: false`` in its envelope,
                or returned an empty data array.
        """
        base = str(self.source.base_url).rstrip("/")
        retrieved_at = datetime.now(UTC)
        data: dict[int, str] = {}
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

            url = f"{base}/indicator/{DIMENSIONS_INDICATOR}/dimensions"
            response = await fetch(client, url, params={"lang": "es"})
            ensure_ok(response, expected_content_type="json")
            dimensions = response.text

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
                "dimensions_indicator_id": DIMENSIONS_INDICATOR,
            },
        )
```

`transform` and `validate` are added in Tasks 6 and 7. Until then the class is
abstract if `BaseConnector` declares them abstract — if the test errors on
instantiation rather than on the assertion, add temporary bodies that
`raise NotImplementedError` and delete them in Task 6.

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/bin/pytest tests/unit/test_cepalstat_rates_connector.py -q 2>&1 | tail -3
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add reim/ingestion/connectors/regional/cepalstat_rates.py \
        tests/unit/test_cepalstat_rates_connector.py
git commit -m "feat(cepalstat): fetch the three interest-rate series"
```

---

### Task 6: The connector's transformation

**Files:**
- Modify: `reim/ingestion/connectors/regional/cepalstat_rates.py`
- Modify: `tests/unit/test_cepalstat_rates_connector.py`

**Interfaces:**
- Consumes: `SERIES`, `CENTRAL_AMERICA`, `UNIT`, `DIMENSIONS_INDICATOR` from
  Task 5.
- Produces: `CepalstatRatesConnector.transform(self, raw: RawDataset) -> list[NormalizedObservation]`,
  and the private `_read_series(self, spec: SeriesSpec, text: str, months: dict[int, int | None], raw: RawDataset) -> list[NormalizedObservation]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cepalstat_rates_connector.py`:

```python
#: What the recordings hold, measured on 2026-09-07.
STORED_CELLS = {
    "lending_rate_nominal_monthly": 2490,
    "deposit_rate_nominal_monthly": 2453,
    "policy_rate_monthly": 1621,
}


@pytest.fixture
async def observations(
    connector: CepalstatRatesConnector,
    cepalstat_rates_856_json: str,
    cepalstat_rates_857_json: str,
    cepalstat_rates_1206_json: str,
    cepalstat_dimensions_856_json: str,
    respx_mock: respx.MockRouter,
) -> list[NormalizedObservation]:
    mount(
        respx_mock,
        {
            856: cepalstat_rates_856_json,
            857: cepalstat_rates_857_json,
            1206: cepalstat_rates_1206_json,
        },
        cepalstat_dimensions_856_json,
    )
    return connector.transform(await connector.extract())


@pytest.mark.anyio
@respx.mock
async def test_stores_only_the_monthly_members_of_the_seven(
    observations: list[NormalizedObservation],
) -> None:
    """Annual and quarterly members are means of their months and are dropped."""
    counts = Counter(obs.indicator_code for obs in observations)
    assert dict(counts) == STORED_CELLS
    assert {obs.country_iso3 for obs in observations} <= CENTRAL_AMERICA
    assert {obs.period.frequency for obs in observations} == {Frequency.MONTHLY}


@pytest.mark.anyio
@respx.mock
async def test_panama_has_lending_and_deposit_rates_but_no_policy_rate(
    observations: list[NormalizedObservation],
) -> None:
    """CEPAL's sixteen zero, unattributed 2022 cells are an artifact, not data."""
    by_code = {
        code: {obs.country_iso3 for obs in observations if obs.indicator_code == code}
        for code in STORED_CELLS
    }
    assert "PAN" in by_code["lending_rate_nominal_monthly"]
    assert "PAN" in by_code["deposit_rate_nominal_monthly"]
    assert "PAN" not in by_code["policy_rate_monthly"]
    assert by_code["policy_rate_monthly"] == CENTRAL_AMERICA - {"PAN"}


@pytest.mark.anyio
@respx.mock
async def test_nicaragua_keeps_its_two_genuine_policy_rate_zeros(
    observations: list[NormalizedObservation],
) -> None:
    """Real cells in a live attributed series, unlike Panama's placeholder."""
    zeros = sorted(
        obs.period.label
        for obs in observations
        if obs.indicator_code == "policy_rate_monthly"
        and obs.country_iso3 == "NIC"
        and obs.value_numeric == Decimal(0)
    )
    assert zeros == ["2010-03", "2010-04"]


@pytest.mark.anyio
@respx.mock
async def test_values_are_stored_exactly_as_published(
    observations: list[NormalizedObservation],
) -> None:
    """856 declares `decimals: 0` and publishes two. Nothing is rounded."""
    lending = {
        (obs.country_iso3, obs.period.label): obs.value_numeric
        for obs in observations
        if obs.indicator_code == "lending_rate_nominal_monthly"
    }
    assert lending[("NIC", "2011-12")] == Decimal("13.19")
    assert lending[("NIC", "2011-11")] == Decimal("9.09")
    assert all(obs.unit == "percent per annum" for obs in observations)
    assert all(obs.currency_code is None for obs in observations)


@pytest.mark.anyio
@respx.mock
async def test_costa_rica_keeps_cepals_bolivian_misattribution(
    observations: list[NormalizedObservation],
) -> None:
    """CEPAL cites the Central Bank of Bolivia for Costa Rica's deposit rate.

    856 and 1206 both say CBCR. REIM does not repair a publisher's provenance,
    so this pins the defect: if CEPAL corrects it, this test fails and the
    correction is noticed rather than absorbed.
    """
    deposit = [
        obs
        for obs in observations
        if obs.indicator_code == "deposit_rate_nominal_monthly" and obs.country_iso3 == "CRI"
    ]
    assert deposit
    assert {obs.raw_metadata["cepalstat_source"] for obs in deposit} == {"Central Bank of Bolivia"}


@pytest.mark.anyio
@respx.mock
async def test_null_source_id_becomes_an_empty_attribution(
    observations: list[NormalizedObservation],
) -> None:
    """345 rows of 1206 carry no source_id; that is a gap, not an exception."""
    unattributed = [
        obs
        for obs in observations
        if obs.indicator_code == "policy_rate_monthly" and obs.country_iso3 == "HND"
    ]
    assert unattributed
    assert {obs.raw_metadata["cepalstat_source"] for obs in unattributed} == {""}


@pytest.mark.anyio
@respx.mock
async def test_english_only_run_cannot_name_a_month(
    connector: CepalstatRatesConnector,
    cepalstat_rates_856_json: str,
    cepalstat_rates_857_json: str,
    cepalstat_rates_1206_json: str,
    respx_mock: respx.MockRouter,
) -> None:
    """The Spanish fetch is load-bearing, not incidental.

    In `lang=en` all seventeen members of dimension 3981 are the string
    `descripcion_ingles`, which is neither a month nor a known non-month
    member, so the classification must raise rather than drop every row.
    """
    mount(
        respx_mock,
        {
            856: cepalstat_rates_856_json,
            857: cepalstat_rates_857_json,
            1206: cepalstat_rates_1206_json,
        },
        cepalstat_rates_856_json,
    )
    raw = await connector.extract()
    with pytest.raises(TransformationError, match="descripcion_ingles"):
        connector.transform(raw)
```

Add the imports these need: `Counter`, `Decimal`, `Frequency`,
`NormalizedObservation`, `TransformationError`, `CENTRAL_AMERICA`.

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_cepalstat_rates_connector.py -q 2>&1 | tail -5
```

Expected: FAIL — `transform` is not implemented.

- [ ] **Step 3: Implement `transform`**

Append to `CepalstatRatesConnector`, replacing any temporary
`NotImplementedError` body:

```text
    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Normalize the three payloads into one observation per country-month.

        Pure function of ``raw``.

        Raises:
            TransformationError: The payload is not the expected mapping, a
                period or years dimension is missing, or a row names a member
                that does not exist.
        """
        payload = raw.payload
        if not isinstance(payload, dict) or "data" not in payload or "dimensions" not in payload:
            msg = "CEPALSTAT payload must carry 'data' and 'dimensions'"
            raise TransformationError(msg, source_key=self.source.key)

        months = self._months_of(
            self._decode(str(payload["dimensions"]), DIMENSIONS_INDICATOR),
            DIMENSIONS_INDICATOR,
        )

        observations: list[NormalizedObservation] = []
        for spec in SERIES:
            observations.extend(
                self._read_series(spec, str(payload["data"][spec.cepal_id]), months, raw)
            )
        observations.sort(key=lambda obs: (obs.indicator_code, obs.country_iso3, obs.period.start))
        return observations

    def _read_series(
        self,
        spec: SeriesSpec,
        text: str,
        months: dict[int, int | None],
        raw: RawDataset,
    ) -> list[NormalizedObservation]:
        """Turn one indicator's payload into its Central American observations."""
        body = self._decode(text, spec.cepal_id)["body"]
        years = self._members_of(body, YEARS_DIMENSION, "years", spec.cepal_id)
        published_unit = str(body["metadata"]["unit"])
        sources = {source["id"]: source["organization_name"] for source in body["sources"]}
        credits = [entry["description"] for entry in body["credits"] if entry["id"] != 0]

        wanted = CENTRAL_AMERICA - spec.excluded_countries
        observations: list[NormalizedObservation] = []
        for row in body["data"]:
            iso3 = row.get("iso3")
            if iso3 not in wanted:
                continue
            month = self._month_of(row, months, spec.cepal_id)
            if month is None:
                continue
            year = self._label_of(row, years, YEARS_DIMENSION, "year", spec.cepal_id)
            value = self._value_of(row, spec.cepal_id)
            label = f"{year}-{month:02d}"
            observations.append(
                NormalizedObservation(
                    country_iso3=str(iso3),
                    indicator_code=spec.indicator_code,
                    source_key=self.source.key,
                    period=parse_period(label, Frequency.MONTHLY),
                    unit=UNIT,
                    currency_code=None,
                    value_numeric=value,
                    retrieved_at=raw.retrieved_at,
                    source_url=f"{raw.source_url}/indicator/{spec.cepal_id}/data",
                    source_record_id=f"cepalstat:{spec.cepal_id}:{iso3}:{label}",
                    raw_metadata={
                        "cepalstat_indicator_id": spec.cepal_id,
                        "cepalstat_published_value": format(value.normalize(), "f"),
                        "cepalstat_published_unit": published_unit,
                        # Empty when CEPAL cites nobody: 345 rows of 1206
                        # carry a null source_id, which is a gap in the
                        # publisher's provenance rather than an error here.
                        "cepalstat_source": sources.get(row.get("source_id"), ""),
                        # credits[0] is CEPAL's own fetch date and changes
                        # between runs; only the citation is kept.
                        "cepalstat_credits": credits,
                        "contract_status": "verified",
                    },
                )
            )
        return observations
```

Note the departure from `cepalstat_monetary.py`: `sources` maps to
`organization_name`, not `description`. For this family every
`description` is the untranslated `(Translation in progress ...)`, while
`organization_name` carries the real publisher — and it is what makes the
Costa Rica test meaningful. Verify against the recording before accepting:

```bash
.venv/bin/python - <<'PY'
import gzip, json
body = json.loads(gzip.decompress(
    open("tests/fixtures/cepalstat_rates_857.json.gz","rb").read()))["body"]
srcs = {s["id"]: (s["description"], s["organization_name"]) for s in body["sources"]}
cri = {r["source_id"] for r in body["data"] if r["iso3"] == "CRI"}
print([srcs[s] for s in cri])
PY
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_cepalstat_rates_connector.py -q 2>&1 | tail -3
```

Expected: PASS, all eight tests.

- [ ] **Step 5: Commit**

```bash
git add reim/ingestion/connectors/regional/cepalstat_rates.py \
        tests/unit/test_cepalstat_rates_connector.py
git commit -m "feat(cepalstat): read the three interest-rate series"
```

---

### Task 7: The connector's quality battery

**Files:**
- Modify: `reim/ingestion/connectors/regional/cepalstat_rates.py`
- Modify: `tests/unit/test_cepalstat_rates_connector.py`

**Interfaces:**
- Consumes: `transform` from Task 6, `EXPECTED_COUNTRIES` and
  `MAX_STEP_POINTS` from Task 5, `_check_monthly_continuity` from the base.
- Produces: `CepalstatRatesConnector.validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]`
  returning four results, named `cepalstat_rates_spread`,
  `cepalstat_rates_step`, `cepalstat_rates_expected_countries` and
  `cepalstat_monthly_continuity`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cepalstat_rates_connector.py`:

```python
@pytest.mark.anyio
@respx.mock
async def test_validate_reports_four_checks_and_the_known_first_run_state(
    connector: CepalstatRatesConnector,
    observations: list[NormalizedObservation],
) -> None:
    """Spread, step and coverage pass; continuity warns on two known gaps."""
    results = {r.check_name: r for r in connector.validate(observations)}
    assert set(results) == {
        "cepalstat_rates_spread",
        "cepalstat_rates_step",
        "cepalstat_rates_expected_countries",
        "cepalstat_monthly_continuity",
    }
    assert results["cepalstat_rates_spread"].status is CheckStatus.PASSED
    assert results["cepalstat_rates_step"].status is CheckStatus.PASSED
    assert results["cepalstat_rates_expected_countries"].status is CheckStatus.PASSED
    # Panama's 33 deposit gaps and Nicaragua's 61 policy gaps are real.
    continuity = results["cepalstat_monthly_continuity"]
    assert continuity.status is CheckStatus.FAILED
    assert continuity.severity is CheckSeverity.WARNING
    assert "94 month(s) missing" in continuity.message


@pytest.mark.anyio
@respx.mock
async def test_spread_holds_on_every_shared_month(
    connector: CepalstatRatesConnector,
    observations: list[NormalizedObservation],
) -> None:
    """Lending above deposit in all 2,453 shared country-months."""
    result = next(
        r for r in connector.validate(observations) if r.check_name == "cepalstat_rates_spread"
    )
    assert result.status is CheckStatus.PASSED
    assert "2453" in result.message.replace(",", "")


def test_spread_fails_on_a_constructed_inversion(
    connector: CepalstatRatesConnector,
) -> None:
    """A bank charging less than it pays is a defect, not a rounding artifact."""
    observations = [
        _observation("lending_rate_nominal_monthly", "NIC", "2020-01", Decimal("4.0")),
        _observation("deposit_rate_nominal_monthly", "NIC", "2020-01", Decimal("9.0")),
    ]
    result = next(
        r for r in connector.validate(observations) if r.check_name == "cepalstat_rates_spread"
    )
    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.CRITICAL
    assert "NIC 2020-01" in result.message


def test_step_fires_beyond_eight_points_and_not_at_seven(
    connector: CepalstatRatesConnector,
) -> None:
    """8 points is the threshold; Belize's real 18 -> 11 step is 7 and passes."""
    passing = [
        _observation("policy_rate_monthly", "BLZ", "2010-12", Decimal("18")),
        _observation("policy_rate_monthly", "BLZ", "2011-01", Decimal("11")),
    ]
    result = next(r for r in connector.validate(passing) if r.check_name == "cepalstat_rates_step")
    assert result.status is CheckStatus.PASSED

    failing = [
        _observation("policy_rate_monthly", "BLZ", "2010-12", Decimal("18")),
        _observation("policy_rate_monthly", "BLZ", "2011-01", Decimal("9.99")),
    ]
    result = next(r for r in connector.validate(failing) if r.check_name == "cepalstat_rates_step")
    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.WARNING


def test_step_ignores_a_move_across_a_gap(
    connector: CepalstatRatesConnector,
) -> None:
    """Comparing across a hole manufactures a break that is really an absence."""
    across_a_gap = [
        _observation("policy_rate_monthly", "NIC", "2010-01", Decimal("2")),
        _observation("policy_rate_monthly", "NIC", "2014-01", Decimal("18")),
    ]
    result = next(
        r for r in connector.validate(across_a_gap) if r.check_name == "cepalstat_rates_step"
    )
    assert result.status is CheckStatus.PASSED


def test_expected_countries_reports_a_gain_as_loudly_as_a_loss(
    connector: CepalstatRatesConnector,
) -> None:
    """Panama appearing in the policy rate is news, not a silent improvement."""
    with_panama = [
        _observation("policy_rate_monthly", iso3, "2020-01", Decimal("5"))
        for iso3 in CENTRAL_AMERICA
    ]
    result = next(
        r
        for r in connector.validate(with_panama)
        if r.check_name == "cepalstat_rates_expected_countries"
    )
    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.CRITICAL
    assert "policy_rate_monthly gained PAN" in result.message
```

Add a module-level helper beside the fixtures:

```python
def _observation(code: str, iso3: str, label: str, value: Decimal) -> NormalizedObservation:
    """A minimal observation for checks that need constructed data."""
    return NormalizedObservation(
        country_iso3=iso3,
        indicator_code=code,
        source_key="cepalstat_rates_monthly",
        period=parse_period(label, Frequency.MONTHLY),
        unit="percent per annum",
        currency_code=None,
        value_numeric=value,
        retrieved_at=datetime(2026, 9, 7, tzinfo=UTC),
        source_url="https://example.invalid",
        source_record_id=f"test:{code}:{iso3}:{label}",
        raw_metadata={},
    )
```

Match `NormalizedObservation`'s real required fields — copy the construction
from `tests/unit/test_cepalstat_monetary_connector.py` if it differs. Add the
imports: `CheckStatus`, `CheckSeverity`, `parse_period`, `datetime`, `UTC`.

The `94` in the first test is Panama's 33 deposit gaps plus Nicaragua's 61
policy gaps. Confirm it against the recording before implementing:

```bash
.venv/bin/python - <<'PY'
import gzip, json
MONTHS = {"Enero":1,"Febrero":2,"Marzo":3,"Abril":4,"Mayo":5,"Junio":6,
          "Julio":7,"Agosto":8,"Septiembre":9,"Octubre":10,"Noviembre":11,"Diciembre":12}
dims = json.loads(gzip.decompress(
    open("tests/fixtures/cepalstat_dimensions_856.json.gz","rb").read()))["body"]["dimensions"]
period = {m["id"]: m["name"] for d in dims if d["id"] == 3981 for m in d["members"]}
total = 0
for cid in (856, 857, 1206):
    body = json.loads(gzip.decompress(
        open(f"tests/fixtures/cepalstat_rates_{cid}.json.gz","rb").read()))["body"]
    years = {m["id"]: m["name"] for d in body["dimensions"] if d["id"] == 29117 for m in d["members"]}
    spans = {}
    for r in body["data"]:
        if r["iso3"] not in {"NIC","GTM","SLV","HND","CRI","PAN","BLZ"}: continue
        if cid == 1206 and r["iso3"] == "PAN": continue
        if period[r["dim_3981"]] not in MONTHS: continue
        spans.setdefault(r["iso3"], set()).add(
            (int(years[r["dim_29117"]]), MONTHS[period[r["dim_3981"]]]))
    for iso3, months in spans.items():
        first, last = min(months), max(months)
        width = (last[0]-first[0])*12 + (last[1]-first[1]) + 1
        if width != len(months):
            print(cid, iso3, width - len(months), "missing")
            total += width - len(months)
print("TOTAL MISSING:", total)
PY
```

Use whatever this prints; if it is not 94, correct the test rather than the
check.

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_cepalstat_rates_connector.py -q -k "validate or spread or step or expected_countries" 2>&1 | tail -5
```

Expected: FAIL — `validate` is not implemented.

- [ ] **Step 3: Implement `validate` and the three checks**

Append to `CepalstatRatesConnector`:

```text
    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert CEPALSTAT-specific expectations beyond the standard battery."""
        return [
            self._check_spread(observations),
            self._check_step(observations),
            self._check_expected_countries(observations),
            self._check_monthly_continuity(observations),
        ]

    def _check_spread(self, observations: list[NormalizedObservation]) -> QualityResult:
        """Lending above deposit, which is what a bank is for.

        Holds in all 2,453 shared country-months as measured on 2026-09-07,
        from 1.18 points (El Salvador) to 18.84 (Honduras). Unlike the
        monetary family's nesting check this needs no tolerance: the margin is
        two orders of magnitude above any rounding CEPAL applies.
        """
        sides: dict[str, dict[tuple[str, str], Decimal]] = {
            "lending_rate_nominal_monthly": {},
            "deposit_rate_nominal_monthly": {},
        }
        for obs in observations:
            if obs.indicator_code in sides and obs.value_numeric is not None:
                sides[obs.indicator_code][(obs.country_iso3, obs.period.label)] = obs.value_numeric

        lending = sides["lending_rate_nominal_monthly"]
        deposit = sides["deposit_rate_nominal_monthly"]
        shared = sorted(set(lending) & set(deposit))
        broken = [key for key in shared if lending[key] <= deposit[key]]

        if not broken:
            return QualityResult.passed(
                "cepalstat_rates_spread",
                CheckType.CONSISTENCY,
                f"Lending exceeds deposit on all {len(shared)} shared country-month(s)",
                expected_value="0 inversions",
                actual_value="0",
            )

        shown = ", ".join(f"{country} {period}" for country, period in broken[:5])
        suffix = f" (+{len(broken) - 5} more)" if len(broken) > 5 else ""
        return QualityResult.failure(
            "cepalstat_rates_spread",
            CheckType.CONSISTENCY,
            CheckSeverity.CRITICAL,
            f"{len(broken)} month(s) where the deposit rate meets or exceeds "
            f"the lending rate: {shown}{suffix}",
            expected_value="0 inversions",
            actual_value=str(len(broken)),
        )

    def _check_step(self, observations: list[NormalizedObservation]) -> QualityResult:
        """Calendar-adjacent moves beyond ``MAX_STEP_POINTS`` percentage points.

        Measured in points rather than percent because these series sit near
        zero, where a percentage change is unbounded and says nothing: 0.5 to
        1.7 is +240% and 1.2 points. Adjacent months only — comparing across a
        hole would manufacture a break that is really a gap, the rule
        ``cepalstat_cpi_known_splices`` already establishes.
        """
        series: dict[tuple[str, str], dict[tuple[int, int], Decimal]] = {}
        for obs in observations:
            if obs.value_numeric is None:
                continue
            year, month = obs.period.label.split("-")
            series.setdefault((obs.indicator_code, obs.country_iso3), {})[
                (int(year), int(month))
            ] = obs.value_numeric

        compared = 0
        breaks: list[str] = []
        for (code, iso3), months in sorted(series.items()):
            ordered = sorted(months)
            for earlier, later in zip(ordered, ordered[1:], strict=False):
                if (later[0] - earlier[0]) * 12 + (later[1] - earlier[1]) != 1:
                    continue
                compared += 1
                move = abs(months[later] - months[earlier])
                if move > MAX_STEP_POINTS:
                    breaks.append(f"{iso3} {later[0]}-{later[1]:02d} ({code}, {move} pts)")

        if not breaks:
            return QualityResult.passed(
                "cepalstat_rates_step",
                CheckType.VALIDITY,
                f"No move beyond {MAX_STEP_POINTS} point(s) in {compared} adjacent pair(s)",
                expected_value=f"<= {MAX_STEP_POINTS} points",
                actual_value="0 beyond",
            )

        shown = ", ".join(breaks[:5])
        suffix = f" (+{len(breaks) - 5} more)" if len(breaks) > 5 else ""
        return QualityResult.failure(
            "cepalstat_rates_step",
            CheckType.VALIDITY,
            CheckSeverity.WARNING,
            f"{len(breaks)} move(s) beyond {MAX_STEP_POINTS} points: {shown}{suffix}",
            expected_value=f"<= {MAX_STEP_POINTS} points",
            actual_value=str(len(breaks)),
        )

    def _check_expected_countries(self, observations: list[NormalizedObservation]) -> QualityResult:
        """Each series has its own country set; Panama is absent from one.

        An expectation rather than a floor, so that a country arriving is
        reported as loudly as one disappearing. Panama appearing in the policy
        rate would mean CEPAL had replaced its zero placeholder with something,
        which is worth a human reading it.
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
                "cepalstat_rates_expected_countries",
                CheckType.COMPLETENESS,
                "Every series carries exactly the countries it is expected to",
                expected_value=str(sum(len(v) for v in EXPECTED_COUNTRIES.values())),
                actual_value=str(sum(len(v) for v in seen.values())),
            )

        return QualityResult.failure(
            "cepalstat_rates_expected_countries",
            CheckType.COMPLETENESS,
            CheckSeverity.CRITICAL,
            f"{len(problems)} change(s) in country coverage: {', '.join(problems[:5])}",
            expected_value=str(sum(len(v) for v in EXPECTED_COUNTRIES.values())),
            actual_value=str(sum(len(v) for v in seen.values())),
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_cepalstat_rates_connector.py -q 2>&1 | tail -3
.venv/bin/python -m reim.cli catalog validate 2>&1 | tail -5
```

Expected: PASS, and the catalog now validates — `cepalstat_rates_monthly`
appears in the pipeline list, which it could not in Task 4.

- [ ] **Step 5: Run the full gate**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . \
  && .venv/bin/mypy reim apps && .venv/bin/pytest -q 2>&1 | tail -3
```

- [ ] **Step 6: Commit**

```bash
git add reim/ingestion/connectors/regional/cepalstat_rates.py \
        tests/unit/test_cepalstat_rates_connector.py
git commit -m "feat(cepalstat): the interest rates' own quality battery"
```

---

### Task 8: State the varying methodology on `/compare`

**Files:**
- Modify: `reim/schemas/comparison.py:20-68`
- Modify: `apps/api/routers/comparison.py:134`
- Test: `tests/unit/test_comparison.py`
- Test: `tests/integration/test_api.py`

**Interfaces:**
- Consumes: `IndicatorDefinition.methodology_varies_by_country` from Task 3.
- Produces: `assess_comparability(summaries: list[SeriesSummary], definition: IndicatorDefinition | None = None) -> tuple[bool, list[str]]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_comparison.py`:

```python
def test_varying_methodology_is_noted_and_does_not_flip_the_flag() -> None:
    """Comparability turns on unit and currency; this is a caveat, not a refusal.

    CEPAL's rates share a unit and carry no currency, so the flag is true and
    correct on the axes it measures. The note carries what the flag cannot:
    movements are comparable, levels are not.
    """
    summaries = [
        summary("NIC", units=("percent per annum",), currencies=(None,)),
        summary("GTM", units=("percent per annum",), currencies=(None,)),
    ]
    definition = INDICATORS_BY_CODE["lending_rate_nominal_monthly"]

    comparable, notes = assess_comparability(summaries, definition)

    assert comparable is True
    assert any("differently in each country" in note for note in notes)
    assert any("movements" in note for note in notes)


def test_no_methodology_note_for_an_ordinary_indicator() -> None:
    """The note must not appear on the 30-odd indicators that do not declare it."""
    summaries = [
        summary("NIC", units=("index",), currencies=(None,)),
        summary("GTM", units=("index",), currencies=(None,)),
    ]
    definition = INDICATORS_BY_CODE["cpi_index_monthly"]

    comparable, notes = assess_comparability(summaries, definition)

    assert comparable is True
    assert not any("differently in each country" in note for note in notes)


def test_assess_comparability_without_a_definition_is_unchanged() -> None:
    """The parameter is optional; existing callers keep their behaviour."""
    summaries = [
        summary("NIC", units=("index",), currencies=(None,)),
        summary("GTM", units=("index",), currencies=(None,)),
    ]
    assert assess_comparability(summaries) == assess_comparability(summaries, None)
```

`summary()` is that module's existing helper — do not add another. Its
keyword arguments are `units`, `currencies`, `sources`, `organizations` and
`observations`, all defaulted, so only the two that matter are passed above.

Add one import to the module: `INDICATORS_BY_CODE` from
`reim.domain.indicators.registry`.

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_comparison.py -q -k methodology 2>&1 | tail -5
```

Expected: FAIL — `assess_comparability() takes 1 positional argument but 2 were given`.

- [ ] **Step 3: Extend `assess_comparability`**

Change its signature and docstring, and append the note before the return:

```text
def assess_comparability(
    summaries: list[SeriesSummary],
    definition: IndicatorDefinition | None = None,
) -> tuple[bool, list[str]]:
```

In the docstring, after the existing paragraph, add:

```text
    An indicator whose publisher defines it differently in each country adds a
    note and **does not** flip the flag. CEPAL's interest rates are the case:
    they share a unit and carry no currency, so the flag is true and correct
    on the axes it measures, while their levels still are not readable against
    each other. Flipping it would widen what ``comparable`` means for every
    existing caller and would misreport comparing how two countries' rates
    *moved*, which is sound.

    Args:
        summaries: One per requested country, empty series included.
        definition: The registered indicator, when the caller has it. Only
            ``methodology_varies_by_country`` is read.
```

Before `comparable = ...`:

```text
    if definition is not None and definition.methodology_varies_by_country:
        notes.append(
            "The publisher defines this indicator differently in each country, "
            "so levels are not comparable; movements over time are."
        )
```

Add the import: `from reim.domain.indicators.registry import IndicatorDefinition`.
If that creates a cycle, import it under `TYPE_CHECKING` and quote the
annotation — `reim/schemas/comparison.py` already imports from
`reim.repositories.comparison`, so check the direction before assuming.

- [ ] **Step 4: Pass the definition from the router**

In `apps/api/routers/comparison.py`, the router already resolves
`INDICATORS_BY_CODE` for the conversion path. Hoist that lookup above the
`convert_to` branch so both uses share it, then pass it through:

```text
    registered = INDICATORS_BY_CODE.get(definition.code)

    if convert_to is not None:
        if registered is None:
            msg = f"Indicator {definition.code!r} is not in the registry"
            raise ResourceNotFoundError(msg, indicator=definition.code)
        ensure_convertible(registered)
```

and at line 134:

```text
    comparable, notes = assess_comparability(summaries, registered)
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_comparison.py -q 2>&1 | tail -3
.venv/bin/pytest tests/integration/test_api.py -q -k compar 2>&1 | tail -3
.venv/bin/mypy reim apps
```

Expected: PASS, with every existing comparison test unchanged — the parameter
is optional and defaults to the old behaviour.

- [ ] **Step 6: Commit**

```bash
git add reim/schemas/comparison.py apps/api/routers/comparison.py \
        tests/unit/test_comparison.py
git commit -m "feat(compare): state a publisher's per-country methodology"
```

---

### Task 9: Run it against the live source and record what happened

The first eight tasks never touch CEPAL. This one does, once, and writes down
what the run actually produced.

**Files:**
- Modify: `docs/sources.md`
- Modify: `ROADMAP.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: no code.

- [ ] **Step 1: Bring the database up and migrate**

```bash
make db-up CONTAINER_ENGINE=podman
.venv/bin/alembic upgrade head
```

- [ ] **Step 2: Run the pipeline**

```bash
.venv/bin/python -m reim.cli pipeline run cepalstat_rates_monthly 2>&1 | tail -40
```

Expected: 6,564 observations stored. Record the exact count, the run duration,
and **every** check that did not pass, with its severity.

The predicted state, from spec §6.4: `cepalstat_rates_spread`,
`cepalstat_rates_step` and `cepalstat_rates_expected_countries` pass;
`cepalstat_monthly_continuity` warns on Panama's deposit gaps and Nicaragua's
policy gaps; freshness passes on all twenty country-series. **Anything else is
a finding** — record it as one rather than adjusting a threshold to hide it.

- [ ] **Step 3: Verify what landed**

```bash
.venv/bin/python -m reim.cli observations list \
  --indicator lending_rate_nominal_monthly --limit 5
curl -s 'http://localhost:8000/api/v1/compare?indicator=lending_rate_nominal_monthly&country=NIC&country=GTM&country=CRI&limit=3' \
  | .venv/bin/python -m json.tool | head -50
```

Confirm the comparison payload carries `comparable: true` **and** the
per-country methodology note from Task 8. If the note is absent, Task 8's
router change did not take effect.

- [ ] **Step 4: Write the `docs/sources.md` section**

Add under "Enabled", after the consumer price index section, following the
house pattern: a header table (organization, endpoints, auth, volume,
coverage, licence, status), then the per-country coverage table, then a
subsection per finding. Cover, at minimum:

- the annual and quarterly members being **means, not restatements**, and how
  that differs from the monetary family (spec §3.2);
- **Panama has no policy rate**, the sixteen zero unattributed cells, and the
  decision to store none of them — with Nicaragua's two genuine zeros as the
  contrast (spec §3.3);
- **CEPAL defines each country's rate differently**, quoting the
  `calculation_methodology` line and the per-country definitions, and what
  `/compare` now says about it (spec §3.4);
- **`Belice` inside the English definition string**, and 857's description of
  Guatemala's deposit rate as a lending rate (spec §3.4);
- **Costa Rica attributed to the Central Bank of Bolivia** in 857 (spec §2.2);
- **the declared decimals are wrong for 856** (spec §3.5);
- **why `max_period_change_pct` is null on two of three**, and what
  `cepalstat_rates_step` does instead (spec §3.8);
- **the ~11-month lag against a two-week-old `last_update`**, and why the
  threshold is 450 rather than a monthly cadence (spec §3.6, §6.2);
- **the first run's exact result** from Step 2, so a later reader can tell a
  regression from a known state.

Then update the "Reachable, not ingested" section: 856, 857 and 1206 leave the
table, and the sentence introducing it is adjusted — it currently says "three
families beyond the five REIM reads", which becomes two beyond eight. Check
the surrounding prose for other counts that move.

- [ ] **Step 5: Update `ROADMAP.md`**

Add a v0.3.0 bullet in the established voice — what shipped, the observation
count, and the two or three things the work settled that a reader would not
guess. Note that this is REIM's **first interest-rate data** and its first use
of the `financial` category, and state plainly that Panama's policy rate is
absent by decision.

- [ ] **Step 6: Update `README.md`**

Find the indicator/source tables and add the three indicators and the new
source. Check for a total-observation or source count in the prose that has
now moved:

```bash
grep -n "cpi_index_monthly\|cepalstat_cpi_monthly" README.md
```

- [ ] **Step 7: Run the full gate**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . \
  && .venv/bin/mypy reim apps && .venv/bin/pytest -q 2>&1 | tail -3
```

`ruff format` reaches Python fenced in Markdown. If it rewrites a block in
`docs/sources.md`, that block is not a valid standalone module — fence it as
```` ```text ```` and re-run until the check is clean.

- [ ] **Step 8: Commit**

```bash
git add docs/sources.md ROADMAP.md README.md
git commit -m "docs(cepalstat): the interest rates, and what the first run showed"
```

- [ ] **Step 9: Tear down**

```bash
make db-down CONTAINER_ENGINE=podman
```

---

## Self-review

**Spec coverage.** §2.1 coverage → Tasks 1, 6. §2.2 attribution defects →
Task 6. §3.1 untranslated members → Tasks 2, 6. §3.2 means not restatements →
Tasks 5, 6, 9. §3.3 Panama → Tasks 5, 6, 9. §3.4 varying methodology → Tasks
3, 8, 9. §3.5 declared decimals → Tasks 6, 9. §3.6 freshness → Tasks 4, 9.
§3.7 spread → Task 7. §3.8 step check → Tasks 4, 7. §4.1–4.4 architecture →
Tasks 2, 5, 6. §5 comparability → Tasks 3, 8. §6.1 indicators → Task 3. §6.2
rules → Task 4. §6.3 checks → Task 7. §6.4 first-run expectation → Task 9. §7
catalog → Task 4. §8 testing → Tasks 5, 6, 7, 8. §9 D1–D11 all land in a task.
§10 out-of-scope introduces no work. No gaps.

**Type consistency.** `SeriesSpec` gains a third field, `excluded_countries`,
which `cepalstat_monetary.py`'s two-field version does not have — the two are
separate classes in separate modules and do not share a definition.
`assess_comparability`'s second parameter is optional throughout. Check names
are spelled identically in Task 7's tests and implementation:
`cepalstat_rates_spread`, `cepalstat_rates_step`,
`cepalstat_rates_expected_countries`.

**Known soft spots**, flagged rather than papered over: three numbers in the
tests are asserted from the recording and must be confirmed against it before
the implementation is written — the 94 missing months in Task 7, the
`organization_name` versus `description` choice in Task 6, and the exact
`NormalizedObservation` construction in both. Each has a verification command
beside it. The Task 5 note about `NotImplementedError` stubs depends on
whether `BaseConnector` declares `transform` and `validate` abstract; the step
says to check rather than assume.
