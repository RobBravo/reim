# CEPALSTAT monthly exchange rate — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest CEPALSTAT indicator 2179, the monthly nominal exchange rate, as
`exchange_rate_nominal_monthly` — 2,749 observations for the seven Central
American countries — so that increment B can convert with it.

**Architecture:** A new `CepalstatConnector` subclass on the exact shape the
monetary connector already uses: two requests (data in English, dimensions in
Spanish for the month names), one observation per country-month, values stored
as published with no scaling. The one structural change outside the new files is
lifting `_check_monthly_continuity` from the monetary connector to the shared
base class, because two connectors now need it.

**Tech Stack:** Python 3.13, httpx + respx, SQLAlchemy 2, Pydantic v2, pytest,
ruff, mypy. Run tools as `.venv/bin/<tool>` — there is no `pip` in the venv.

**Spec:** `docs/superpowers/specs/2026-09-06-currency-conversion-design.md`

## Scope

This plan is **increment A only** (spec §4). Two items from spec §6.1 belong to
increment B and must **not** be implemented here:

* the `currency_convertible` field on `IndicatorDefinition`, and
* removing the clause "without a conversion REIM does not perform" from the
  monetary indicator descriptions and the catalog entry.

Both are meaningless until `?convert_to=USD` exists. Increment A leaves them
alone.

## Global Constraints

* **Values are stored exactly as published — no scaling.** Unlike the monetary
  family there is no `× 10^6` (spec §6.3).
* **The rate's currency comes from a connector-local table, never from the
  country registry.** The registry answers "what does this country transact in
  today" and would label El Salvador's rate `USD per USD` (spec §3.1).
* **Only the seven Central American countries are stored**, filtered from a
  145-country matrix.
* **Nothing from the Spanish dimensions response is stored.** It resolves month
  names and is then discarded; every stored string comes from the English data
  response.
* **Tests never call an official source.** Every payload is replayed from a
  recording through `respx`.
* Measured facts this plan asserts, all from 2026-09-06: 2,749 rows for the
  seven; spans 1993-06…2025-09 (Panama 1990-01, Costa Rica 1994-02); no gaps;
  no null values; every row `source_id` 424; 1,813 values with one decimal and
  936 with none.

---

### Task 1: Record the two responses a rate run makes

**Files:**
- Create: `tests/fixtures/cepalstat_fx_2179.json.gz`
- Create: `tests/fixtures/cepalstat_dimensions_2179.json.gz`
- Modify: `tests/fixtures/README.md`
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: two session-scoped pytest fixtures, `cepalstat_fx_2179_json() -> str`
  and `cepalstat_fx_dimensions_json() -> str`, each returning the decompressed
  response text.

- [ ] **Step 1: Record both responses byte-for-byte**

```bash
cd "$(git rev-parse --show-toplevel)"
curl -s -H 'User-Agent: REIM/0.1 (+https://github.com/robertobravo/REIM-Proyect)' \
  'https://api-cepalstat.cepal.org/cepalstat/api/v1/indicator/2179/data?lang=en' \
  | gzip -9 > tests/fixtures/cepalstat_fx_2179.json.gz
curl -s -H 'User-Agent: REIM/0.1 (+https://github.com/robertobravo/REIM-Proyect)' \
  'https://api-cepalstat.cepal.org/cepalstat/api/v1/indicator/2179/dimensions?lang=es' \
  | gzip -9 > tests/fixtures/cepalstat_dimensions_2179.json.gz
ls -l tests/fixtures/cepalstat_fx_2179.json.gz tests/fixtures/cepalstat_dimensions_2179.json.gz
```

Expected: about 54 KB and 4 KB. The uncompressed responses are 1.19 MB and
28 KB.

- [ ] **Step 2: Verify the recordings hold what the plan claims**

```bash
.venv/bin/python - <<'PY'
import gzip, json, collections
data = json.loads(gzip.decompress(open("tests/fixtures/cepalstat_fx_2179.json.gz","rb").read()))
dims = json.loads(gzip.decompress(open("tests/fixtures/cepalstat_dimensions_2179.json.gz","rb").read()))
body = data["body"]
print("success:", data["header"]["success"], "rows:", len(body["data"]))
print("unit:", body["metadata"]["unit"])
print("methodology:", body["metadata"]["calculation_methodology"])
print("data_features:", body["metadata"]["data_features"])
months = next(d for d in dims["body"]["dimensions"] if d["id"] == 515)
print("period dimension members:", len(months["members"]))
seven = {"NIC","GTM","SLV","HND","CRI","PAN","BLZ"}
rows = [r for r in body["data"] if r["iso3"] in seven]
print("rows for the seven:", len(rows))
print("null values:", sum(1 for r in rows if r["value"] in (None, "")))
print("source ids:", {r["source_id"] for r in rows})
dec = collections.Counter(len(r["value"].split(".")[1]) if "." in r["value"] else 0 for r in rows)
print("decimal places:", dict(sorted(dec.items())))
PY
```

Expected, exactly:

```text
success: True rows: 11496
unit: National currency by USA dolar
methodology: Daily exchange rate, monthly average
data_features: Source Bloomberg
period dimension members: 12
rows for the seven: 2749
null values: 0
source ids: {424}
decimal places: {0: 936, 1: 1813}
```

If any number differs, CEPAL has republished. Stop and update the spec's
measured figures before continuing — the plan's assertions are downstream of
these.

- [ ] **Step 3: Add the conftest fixtures**

Append to `tests/conftest.py`, next to the other CEPALSTAT fixtures:

```python
@pytest.fixture(scope="session")
def cepalstat_fx_2179_json() -> str:
    """CEPALSTAT indicator 2179, nominal exchange rate (stored gzipped)."""
    return gzip.decompress((FIXTURES / "cepalstat_fx_2179.json.gz").read_bytes()).decode("utf-8")


@pytest.fixture(scope="session")
def cepalstat_fx_dimensions_json() -> str:
    """Indicator 2179's member table in Spanish, where the months are named."""
    return gzip.decompress((FIXTURES / "cepalstat_dimensions_2179.json.gz").read_bytes()).decode(
        "utf-8"
    )
```

- [ ] **Step 4: Document both recordings**

Add two rows to the table in `tests/fixtures/README.md`, after the
`cepalstat_debt_1240.json.gz` row:

```text
| `cepalstat_fx_2179.json.gz` | `GET https://api-cepalstat.cepal.org/cepalstat/api/v1/indicator/2179/data?lang=en`, byte-for-byte, gzipped only to keep the repo small (1.19 MB → 54 KB). Tests decompress it before parsing. The **complete** response — 30 countries and every month — because that is what proves the filter to the seven Central American countries works, and it is the only place El Salvador's post-dollarisation colón rate can be asserted. | 2026-09-06 |
| `cepalstat_dimensions_2179.json.gz` | `GET .../indicator/2179/dimensions?lang=es`, byte-for-byte, gzipped (28 KB → 4 KB). Recorded in Spanish for the same reason as the monetary dimensions: `lang=en` returns the period members as the untranslated string `descripcion_ingles`. Dimension 515 carries twelve members and no annual or quarterly restatement, unlike the monetary family's seventeen. | 2026-09-06 |
```

Also update the paragraph that begins "The CEPALSTAT API needs no User-Agent
override" — it says "these four were recorded with REIM's own identifier" and
that count is now stale. Change "these four" to "these fifteen".

- [ ] **Step 5: Verify the fixtures load**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_monetary_connector.py -q`
Expected: PASS, unchanged — this step only proves `conftest.py` still imports.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/cepalstat_fx_2179.json.gz \
        tests/fixtures/cepalstat_dimensions_2179.json.gz \
        tests/fixtures/README.md tests/conftest.py
git commit -m "test(cepalstat): record the two responses a rate run makes"
```

---

### Task 2: Register the indicator, the source and its quality rule

**Files:**
- Modify: `reim/domain/indicators/registry.py`
- Modify: `sources/catalog.yml`
- Modify: `sources/quality_rules.yml`
- Test: `tests/unit/test_catalog.py`

**Interfaces:**
- Consumes: nothing.
- Produces: indicator code `exchange_rate_nominal_monthly`; catalog source key
  `cepalstat_exchange_rate_monthly` whose `connector` field names
  `reim.ingestion.connectors.regional.cepalstat_exchange_rate`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_catalog.py`:

```python
def test_exchange_rate_source_is_registered() -> None:
    """The rate source names its indicator and its connector module."""
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    source = next(s for s in catalog.sources if s.key == "cepalstat_exchange_rate_monthly")

    assert source.enabled is True
    assert source.official is True
    assert source.frequency is Frequency.MONTHLY
    assert source.license == "cepal_terms_of_use"
    assert source.indicators == ["exchange_rate_nominal_monthly"]
    assert source.connector == "reim.ingestion.connectors.regional.cepalstat_exchange_rate"
    assert str(source.base_url).startswith("https://api-cepalstat.cepal.org")


def test_exchange_rate_indicator_is_a_rate_not_an_amount() -> None:
    """Its unit says 'per USD', which is what distinguishes it from a stock."""
    definition = next(i for i in INDICATORS if i.code == "exchange_rate_nominal_monthly")

    assert definition.frequency is Frequency.MONTHLY
    assert definition.unit == "units of local currency per USD"
    assert definition.value_type is ValueType.LEVEL
    assert definition.is_active is True
```

Add whatever of `INDICATORS`, `ValueType` and `Frequency` the file does not
already import.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog.py -k exchange_rate -v`
Expected: FAIL — `StopIteration`, because neither the source nor the indicator
exists yet.

- [ ] **Step 3: Add the indicator definition**

In `reim/domain/indicators/registry.py`, append to `INDICATORS` after the debt
entries:

```text
    IndicatorDefinition(
        code="exchange_rate_nominal_monthly",
        name="Nominal exchange rate (monthly average)",
        description=(
            "Units of each country's own currency per US dollar, published by "
            "ECLAC as the average of the daily rates within the month. The "
            "payload names Bloomberg as the underlying source while its "
            "sources array claims official figures; REIM stores the series "
            "without repeating the second claim. El Salvador is quoted in "
            "colones at its fixed conversion rate throughout, twenty-four "
            "years after it adopted the dollar, so this series carries a rate "
            "for a currency no longer in circulation."
        ),
        category=IndicatorCategory.EXCHANGE_RATE,
        frequency=Frequency.MONTHLY,
        unit="units of local currency per USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=2179&lang=en",
    ),
```

Confirm `IndicatorCategory.EXCHANGE_RATE` is the member's real name first:

```bash
.venv/bin/python -c "from reim.core.constants import IndicatorCategory as C; print(list(C))"
```

Use whichever member the existing `ni_exchange_rate_official_daily` entry uses —
read it rather than guessing.

- [ ] **Step 4: Add the catalog entry**

In `sources/catalog.yml`, after the `cepalstat_debt_annual` entry:

```yaml
  - key: cepalstat_exchange_rate_monthly
    name: Central American nominal exchange rates (monthly)
    description: >-
      Units of each country's own currency per US dollar for the seven Central
      American countries, from CEPALSTAT, as the average of the daily rates
      within each month. ECLAC publishes it; the payload names Bloomberg as the
      underlying source. El Salvador is quoted in colones at its fixed
      conversion rate throughout, long after dollarisation.
    organization: CEPAL
    category: exchange_rate
    access_type: http_api
    frequency: monthly
    format: json
    base_url: https://api-cepalstat.cepal.org/cepalstat/api/v1
    documentation_url: https://statistics.cepal.org/portal/cepalstat/
    connector: reim.ingestion.connectors.regional.cepalstat_exchange_rate
    indicators:
      - exchange_rate_nominal_monthly
    license: cepal_terms_of_use
    official: true
    enabled: true
```

Match `category:` to the value the existing exchange-rate sources use — check
with `grep -n 'category:' sources/catalog.yml | sort -u`.

- [ ] **Step 5: Add the quality rule**

In `sources/quality_rules.yml`, alongside the other CEPALSTAT entries:

```yaml
  exchange_rate_nominal_monthly:
    min_value: 0
    max_value: null
    allow_negative: false
    allow_zero: false
    max_period_change_pct: 25
    monotonic_increasing: false
    # The series ends 2025-09 while CEPAL's own last_update is 2026-08: it
    # genuinely lags about a year, so the stalest country is ~341 days old on
    # the day this was written. 450 passes that with headroom and still catches
    # a series that has stopped being extended.
    freshness_max_age_days: 450
    min_observations: 2700
```

`min_value: 0` inclusive rather than `1`, per spec §7: every rate in the series
is at least 1, but `docs/sources.md` already records `min_value: 1` as a past
mistake on the Nicaraguan rate and the tighter bound buys nothing.

`max_period_change_pct: 25` — the largest month-on-month move in the recording
is well inside this; verify with:

```bash
.venv/bin/python - <<'PY'
import gzip, json
from decimal import Decimal
data = json.loads(gzip.decompress(open("tests/fixtures/cepalstat_fx_2179.json.gz","rb").read()))
dims = json.loads(gzip.decompress(open("tests/fixtures/cepalstat_dimensions_2179.json.gz","rb").read()))
order = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto",
         "Septiembre","Octubre","Noviembre","Diciembre"]
mon = {m["id"]: order.index(m["name"]) + 1
       for d in dims["body"]["dimensions"] if d["id"] == 515 for m in d["members"]}
yrs = {m["id"]: int(m["name"])
       for d in data["body"]["dimensions"] if d["id"] == 29117 for m in d["members"]}
seven = {"NIC","GTM","SLV","HND","CRI","PAN","BLZ"}
series = {}
for r in data["body"]["data"]:
    if r["iso3"] in seven:
        series.setdefault(r["iso3"], {})[(yrs[r["dim_29117"]], mon[r["dim_515"]])] = Decimal(r["value"])
worst = Decimal(0)
for iso3, cells in series.items():
    keys = sorted(cells)
    for a, b in zip(keys, keys[1:]):
        change = abs(cells[b] - cells[a]) / cells[a] * 100
        if change > worst:
            worst, where = change, (iso3, b)
print("largest month-on-month change:", round(worst, 3), "% at", where)
PY
```

Expected: comfortably below 25. If it is not, raise the threshold to sit above
the real move and say so in a comment — never trim real data to fit a rule.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog.py -q`
Expected: PASS. The catalog validator will reject the entry if the indicator
code, organization or licence key does not resolve, so this covers all three.

- [ ] **Step 7: Commit**

```bash
git add reim/domain/indicators/registry.py sources/catalog.yml \
        sources/quality_rules.yml tests/unit/test_catalog.py
git commit -m "feat(cepalstat): register the monthly exchange rate indicator"
```

---

### Task 3: Lift the monthly-continuity check to the shared base class

**Files:**
- Modify: `reim/ingestion/connectors/regional/cepalstat.py`
- Modify: `reim/ingestion/connectors/regional/cepalstat_monetary.py`
- Test: `tests/unit/test_cepalstat_monetary_connector.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CepalstatConnector._check_monthly_continuity(self, observations:
  list[NormalizedObservation]) -> QualityResult`, available to every CEPALSTAT
  connector. Its check name stays `cepalstat_monthly_continuity`.

This is a pure move: no behaviour changes, and the monetary connector's tests
are the proof. Spec §7 records why it moves rather than being copied.

- [ ] **Step 1: Confirm the existing tests cover the check before touching it**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_monetary_connector.py -k continuity -v`
Expected: PASS, at least one test. These are the regression net for the move; if
there are none, write one first that asserts a hole in one country's span is
reported while another country's complete span is not.

- [ ] **Step 2: Move the method**

Cut `_check_monthly_continuity` — the whole method, docstring included — from
`reim/ingestion/connectors/regional/cepalstat_monetary.py` and paste it into
`CepalstatConnector` in `reim/ingestion/connectors/regional/cepalstat.py`, after
`_value_of`.

Add to `cepalstat.py`'s imports whatever the method needs and the module does
not already have: `CheckSeverity`, `CheckType` from `reim.core.constants`, and
`NormalizedObservation`, `QualityResult` from `reim.domain.pipelines.models`.

Then remove from `cepalstat_monetary.py` any import that is now unused. Ruff
will name them.

- [ ] **Step 3: Widen the base class docstring, which currently forbids this**

`cepalstat.py`'s module docstring says the base class "holds the protocol — the
envelope, the JSON decode, a dimension's member table, a row's label and a row's
value — and nothing about any indicator family's shape."

Replace the sentence beginning "This base class is deliberately not" through the
end of that paragraph with:

```text
This base class is deliberately not a generic CEPALSTAT engine. It holds two
things. The first is the protocol — the envelope, the JSON decode, a
dimension's member table, a row's label and a row's value. The second is
behaviour that is about periods rather than about any family's shape:
``_check_monthly_continuity`` walks a country's own span looking for holes and
would read identically in every monthly connector, so it lives here rather than
being copied. Nothing about an indicator family's dimensions belongs in this
file. Each connector still names its own dimensions and writes its own
``extract``, ``transform`` and ``validate``: GDP reads a country-by-year matrix,
the monetary aggregates carry a third period-within-year dimension, public debt
carries four, and the exchange rate carries a twelve-member month dimension of
its own. Merging those transforms was rejected in design and stays rejected.
```

- [ ] **Step 4: Run the monetary tests to prove nothing changed**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_monetary_connector.py -q`
Expected: PASS, same count as before the move.

- [ ] **Step 5: Run the whole gate**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy . && .venv/bin/python -m pytest -q`
Expected: all clean, 510 passed.

- [ ] **Step 6: Commit**

```bash
git add reim/ingestion/connectors/regional/cepalstat.py \
        reim/ingestion/connectors/regional/cepalstat_monetary.py
git commit -m "refactor(cepalstat): share the monthly continuity check"
```

---

### Task 4: Parse the rate matrix into observations

**Files:**
- Create: `reim/ingestion/connectors/regional/cepalstat_exchange_rate.py`
- Test: `tests/unit/test_cepalstat_fx_connector.py`

**Interfaces:**
- Consumes: `CepalstatConnector` from Task 3, the fixtures from Task 1, the
  indicator and source from Task 2.
- Produces: `CepalstatExchangeRateConnector` with `connector_key =
  "cepalstat_exchange_rate_monthly"`; module constants `PERIOD_DIMENSION = 515`,
  `CENTRAL_AMERICA: frozenset[str]`, `QUOTED_CURRENCY: dict[str, str]`,
  `MONTHS_BY_SPANISH_NAME: dict[str, int]`, `CEPAL_ID = 2179`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_cepalstat_fx_connector.py`:

```python
"""Unit tests for the CEPALSTAT monthly exchange-rate connector.

Every payload replayed here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from reim.core.constants import Frequency
from reim.domain.pipelines.models import RawDataset
from reim.domain.sources.catalog import load_catalog
from reim.ingestion.connectors.regional.cepalstat_exchange_rate import (
    CENTRAL_AMERICA,
    CepalstatExchangeRateConnector,
)
from tests.conftest import REPO_ROOT

#: What the recording holds, measured on 2026-09-06.
ROWS_FOR_THE_SEVEN = 2749
SPANS = {
    "BLZ": ("1993-06", "2025-09", 388),
    "CRI": ("1994-02", "2025-09", 380),
    "GTM": ("1993-06", "2025-09", 388),
    "HND": ("1993-06", "2025-09", 388),
    "NIC": ("1993-06", "2025-09", 388),
    "PAN": ("1990-01", "2025-09", 429),
    "SLV": ("1993-06", "2025-09", 388),
}


@pytest.fixture
def connector() -> CepalstatExchangeRateConnector:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    source = next(s for s in catalog.sources if s.key == "cepalstat_exchange_rate_monthly")
    return CepalstatExchangeRateConnector(source)


@pytest.fixture
def raw(cepalstat_fx_2179_json: str, cepalstat_fx_dimensions_json: str) -> RawDataset:
    return RawDataset(
        source_key="cepalstat_exchange_rate_monthly",
        retrieved_at=datetime(2026, 9, 6, tzinfo=UTC),
        source_url="https://api-cepalstat.cepal.org/cepalstat/api/v1",
        payload={"data": cepalstat_fx_2179_json, "dimensions": cepalstat_fx_dimensions_json},
        content_type="application/json",
        http_status=200,
        metadata={"indicator_id": 2179, "lang": "en", "dimensions_lang": "es"},
    )


def test_stores_only_the_seven_countries(
    connector: CepalstatExchangeRateConnector, raw: RawDataset
) -> None:
    """The matrix carries 30 countries; REIM keeps seven."""
    observations = connector.transform(raw)

    assert len(observations) == ROWS_FOR_THE_SEVEN
    assert {obs.country_iso3 for obs in observations} == set(CENTRAL_AMERICA)


def test_each_country_span_matches_the_recording(
    connector: CepalstatExchangeRateConnector, raw: RawDataset
) -> None:
    """Panama reaches back to 1990 and Costa Rica starts in 1994."""
    observations = connector.transform(raw)

    for iso3, (first, last, count) in SPANS.items():
        labels = sorted(obs.period.label for obs in observations if obs.country_iso3 == iso3)
        assert (labels[0], labels[-1], len(labels)) == (first, last, count)


def test_the_rate_is_quoted_in_the_currency_it_prices_not_the_country_s_own(
    connector: CepalstatExchangeRateConnector, raw: RawDataset
) -> None:
    """El Salvador's rate is in colones, though the country transacts in USD.

    This is the regression test for spec §3.1. Taking the currency from the
    country registry would label these observations `USD per USD`.
    """
    observations = connector.transform(raw)
    salvadoran = [obs for obs in observations if obs.country_iso3 == "SLV"]

    assert {obs.currency_code for obs in salvadoran} == {"SVC"}
    assert {obs.unit for obs in salvadoran} == {"SVC per USD"}

    recent = next(obs for obs in salvadoran if obs.period.label == "2025-09")
    assert recent.value_numeric == Decimal("8.8")


def test_values_are_stored_exactly_as_published(
    connector: CepalstatExchangeRateConnector, raw: RawDataset
) -> None:
    """No scaling: the monetary family's factor of a million does not apply."""
    observations = connector.transform(raw)
    by_key = {(obs.country_iso3, obs.period.label): obs for obs in observations}

    assert by_key[("PAN", "2025-09")].value_numeric == Decimal("1")
    assert by_key[("BLZ", "2025-09")].value_numeric == Decimal("2")
    assert by_key[("NIC", "2000-01")].value_numeric == Decimal("12.3")
    assert by_key[("CRI", "2000-01")].value_numeric == Decimal("297.1")


def test_each_observation_carries_its_provenance(
    connector: CepalstatExchangeRateConnector, raw: RawDataset
) -> None:
    """The published figure and CEPAL's own contradictory provenance are kept."""
    observations = connector.transform(raw)
    one = next(
        obs for obs in observations if (obs.country_iso3, obs.period.label) == ("NIC", "2000-01")
    )

    assert one.period.frequency is Frequency.MONTHLY
    assert one.source_record_id == "cepalstat:2179:NIC:2000-01"
    assert one.source_url.endswith("/indicator/2179/data")
    assert one.raw_metadata["cepalstat_indicator_id"] == 2179
    assert one.raw_metadata["cepalstat_published_value"] == "12.3"
    assert one.raw_metadata["cepalstat_published_unit"] == "National currency by USA dolar"
    assert one.raw_metadata["cepalstat_methodology"] == "Daily exchange rate, monthly average"
    assert one.raw_metadata["cepalstat_data_features"] == "Source Bloomberg"


def test_no_month_is_missing_inside_any_span(
    connector: CepalstatExchangeRateConnector, raw: RawDataset
) -> None:
    """Measured: the seven have no interior holes at all."""
    observations = connector.transform(raw)

    for iso3 in CENTRAL_AMERICA:
        months = sorted(
            (obs.period.start.year, obs.period.start.month)
            for obs in observations
            if obs.country_iso3 == iso3
        )
        width = (months[-1][0] - months[0][0]) * 12 + months[-1][1] - months[0][1] + 1
        assert len(months) == width
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_fx_connector.py -q`
Expected: FAIL at collection — `ModuleNotFoundError: reim.ingestion.connectors.regional.cepalstat_exchange_rate`.

- [ ] **Step 3: Write the connector's module header and constants**

Create `reim/ingestion/connectors/regional/cepalstat_exchange_rate.py`:

```python
"""Central America — monthly nominal exchange rates published through CEPALSTAT.

The API, its lack of documentation and the way its routes were recovered are
documented in ``cepalstat.py``, which this connector's base class comes from;
only what differs is recorded here.

Three things differ from the monetary family this connector otherwise mirrors:

1. **Dimension 515 carries twelve members and nothing else.** The monetary
   family's period dimension mixes months with an annual figure and four
   quarters that restate a month; this one is months only, so no member is
   dropped. The Spanish member table is still fetched, for the same reason:
   in ``lang=en`` the member names are the untranslated ``descripcion_ingles``.
2. **Values are stored exactly as published.** There is no factor of a million.
3. **The currency is the one the rate prices, not the one the country
   transacts in.** These are not the same question, and for El Salvador they
   give different answers: CEPAL quotes it at 8.7-8.8 colones per dollar
   through 2025, twenty-four years after it adopted the dollar, because that
   is the colón's fixed legal conversion rate and CEPAL never stopped
   publishing it. The country registry would say ``USD``, which would label
   these observations ``USD per USD``. So the quoted currency comes from this
   module's own table.

Two things about the series are worth knowing before anything is built on it.
Its ``calculation_methodology`` is "Daily exchange rate, monthly average", so
it is an average and not an end-of-month rate. And its ``data_features`` says
"Source Bloomberg" while its ``sources`` array says "On the basis of official
figures"; the payload contradicts itself, both strings are stored in
``raw_metadata``, and REIM repeats neither claim as its own.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

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

#: This family's own period dimension. Twelve members, all months.
PERIOD_DIMENSION = 515

#: The single indicator this connector reads.
CEPAL_ID = 2179

CENTRAL_AMERICA = frozenset({"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"})

#: The currency each country's rate is **quoted in**, which is not what
#: ``reim.domain.countries.registry`` answers. El Salvador is the case that
#: forces the distinction: it transacts in dollars and is quoted in colones.
QUOTED_CURRENCY = {
    "BLZ": "BZD",
    "CRI": "CRC",
    "GTM": "GTQ",
    "HND": "HNL",
    "NIC": "NIO",
    "PAN": "PAB",
    "SLV": "SVC",
}

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

#: The pegs, and the month from which the recording shows them holding. Both
#: are legal facts rather than market outcomes, so a departure means the matrix
#: has been misread far more probably than that Panama has floated the balboa.
PEGS = {"PAN": Decimal("1"), "BLZ": Decimal("2")}
PEGS_HOLD_FROM = (1993, 6)
```

- [ ] **Step 4: Write the transform**

Append to the same file:

```python
class CepalstatExchangeRateConnector(CepalstatConnector):
    """Monthly nominal exchange rates for the seven Central American countries."""

    connector_key = "cepalstat_exchange_rate_monthly"
    version = "1.0.0"
    expected_frequency = Frequency.MONTHLY

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Normalize the matrix into one observation per country-month.

        Pure function of ``raw``.

        Raises:
            TransformationError: The payload is not the expected mapping, a
                dimension is missing, or a row names a member that does not
                exist.
        """
        payload = raw.payload
        if not isinstance(payload, dict) or "data" not in payload:
            msg = "CEPALSTAT payload must carry 'data' and 'dimensions' mappings"
            raise TransformationError(msg, source_key=self.source.key)

        body = self._decode(str(payload["data"]), CEPAL_ID)["body"]
        months = self._months_of(self._decode(str(payload["dimensions"]), CEPAL_ID))
        years = self._members_of(body, YEARS_DIMENSION, "years", CEPAL_ID)
        metadata = body["metadata"]
        published_unit = str(metadata["unit"])
        methodology = str(metadata["calculation_methodology"])
        data_features = str(metadata["data_features"])
        sources = {source["id"]: source["description"] for source in body["sources"]}
        credits = [entry["description"] for entry in body["credits"] if entry["id"] != 0]

        observations: list[NormalizedObservation] = []
        for row in body["data"]:
            iso3 = row.get("iso3")
            if iso3 not in CENTRAL_AMERICA:
                continue
            month = self._month_of(row, months)
            year = self._label_of(row, years, YEARS_DIMENSION, "year", CEPAL_ID)
            value = self._value_of(row, CEPAL_ID)
            label = f"{year}-{month:02d}"
            currency = QUOTED_CURRENCY[str(iso3)]
            observations.append(
                NormalizedObservation(
                    country_iso3=str(iso3),
                    indicator_code="exchange_rate_nominal_monthly",
                    source_key=self.source.key,
                    period=parse_period(label, Frequency.MONTHLY),
                    unit=f"{currency} per USD",
                    currency_code=currency,
                    value_numeric=value,
                    retrieved_at=raw.retrieved_at,
                    source_url=f"{raw.source_url}/indicator/{CEPAL_ID}/data",
                    source_record_id=f"cepalstat:{CEPAL_ID}:{iso3}:{label}",
                    raw_metadata={
                        "cepalstat_indicator_id": CEPAL_ID,
                        "cepalstat_published_value": format(value.normalize(), "f"),
                        "cepalstat_published_unit": published_unit,
                        "cepalstat_methodology": methodology,
                        # CEPAL's own two answers about where this comes from.
                        # They disagree; both are kept rather than picked between.
                        "cepalstat_data_features": data_features,
                        "cepalstat_source": sources.get(row.get("source_id"), ""),
                        "cepalstat_credits": credits,
                        "contract_status": "verified",
                    },
                )
            )
        observations.sort(key=lambda obs: (obs.country_iso3, obs.period.start))
        return observations

    def _months_of(self, dimensions_document: object) -> dict[int, int]:
        """Map each period member id to a month number.

        Unlike the monetary family every member is a month, so the mapping is
        total and nothing is dropped. A label that is not a known month name
        means CEPAL renamed or added a member, which is a contract break.

        Raises:
            TransformationError: The period dimension is absent, or a member
                carries a label that is not a Spanish month name.
        """
        members = self._members_of(
            dimensions_document["body"],  # type: ignore[index]
            PERIOD_DIMENSION,
            "period",
            CEPAL_ID,
        )
        months: dict[int, int] = {}
        for member_id, label in members.items():
            if label not in MONTHS_BY_SPANISH_NAME:
                msg = (
                    f"CEPALSTAT period member {member_id} for indicator {CEPAL_ID} "
                    f"carries the unrecognized label {label!r}"
                )
                raise TransformationError(msg, source_key=self.source.key)
            months[member_id] = MONTHS_BY_SPANISH_NAME[label]
        return months

    def _month_of(self, row: object, months: dict[int, int]) -> int:
        """Resolve a row's month.

        Raises:
            TransformationError: The row names a period member id that is not
                in the dimension's member table.
        """
        member = row.get(f"dim_{PERIOD_DIMENSION}")  # type: ignore[attr-defined]
        if member not in months:
            msg = (
                f"CEPALSTAT row for indicator {CEPAL_ID} names an unknown period member {member!r}"
            )
            raise TransformationError(msg, source_key=self.source.key)
        return months[member]
```

If mypy objects to the `object` annotations and the `type: ignore` comments,
type the two parameters the way `cepalstat_monetary.py` types its equivalents —
read that file and match it rather than inventing a signature.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_fx_connector.py -q`
Expected: PASS, 6 tests. `test_the_rate_is_quoted_in_the_currency_it_prices...`
is the one that matters most — if it fails with `USD`, the currency is coming
from the country registry.

- [ ] **Step 6: Commit**

```bash
git add reim/ingestion/connectors/regional/cepalstat_exchange_rate.py \
        tests/unit/test_cepalstat_fx_connector.py
git commit -m "feat(cepalstat): parse the monthly exchange rate matrix"
```

---

### Task 5: Cover the two new quality checks

**Files:**
- Modify: `reim/ingestion/connectors/regional/cepalstat_exchange_rate.py`
- Test: `tests/unit/test_cepalstat_fx_connector.py`

**Interfaces:**
- Consumes: Task 4's connector and Task 3's inherited
  `_check_monthly_continuity`.
- Produces: `validate()` returning three `QualityResult`s named
  `cepalstat_fx_expected_countries`, `cepalstat_fx_pegs_hold` and
  `cepalstat_monthly_continuity`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cepalstat_fx_connector.py`:

```python
def test_validate_passes_on_the_recording(
    connector: CepalstatExchangeRateConnector, raw: RawDataset
) -> None:
    """All three checks pass on real data, which is the point of recording it."""
    results = connector.validate(connector.transform(raw))

    assert [r.check_name for r in results] == [
        "cepalstat_fx_expected_countries",
        "cepalstat_fx_pegs_hold",
        "cepalstat_monthly_continuity",
    ]
    assert all(r.status is CheckStatus.PASSED for r in results)


def test_a_missing_country_is_critical(
    connector: CepalstatExchangeRateConnector, raw: RawDataset
) -> None:
    """A country dropping out of the matrix is not a gap, it is a break."""
    observations = [obs for obs in connector.transform(raw) if obs.country_iso3 != "HND"]

    result = next(
        r
        for r in connector.validate(observations)
        if r.check_name == "cepalstat_fx_expected_countries"
    )

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.CRITICAL
    assert "HND" in result.message


def test_an_unexpected_country_is_reported_too(
    connector: CepalstatExchangeRateConnector, raw: RawDataset
) -> None:
    """An expectation, not a floor: arriving is as loud as disappearing."""
    observations = connector.transform(raw)
    intruder = replace(observations[0], country_iso3="MEX")

    result = next(
        r
        for r in connector.validate([*observations, intruder])
        if r.check_name == "cepalstat_fx_expected_countries"
    )

    assert result.status is CheckStatus.FAILED
    assert "MEX" in result.message


def test_a_broken_peg_is_an_error(
    connector: CepalstatExchangeRateConnector, raw: RawDataset
) -> None:
    """Panama at anything but 1 means the matrix has been misread."""
    observations = connector.transform(raw)
    index = next(
        i
        for i, obs in enumerate(observations)
        if obs.country_iso3 == "PAN" and obs.period.label == "2010-05"
    )
    observations[index] = replace(observations[index], value_numeric=Decimal("1.4"))

    result = next(
        r for r in connector.validate(observations) if r.check_name == "cepalstat_fx_pegs_hold"
    )

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.ERROR
    assert "PAN" in result.message
    assert "2010-05" in result.message


def test_the_peg_check_ignores_months_before_the_pegs_were_verified(
    connector: CepalstatExchangeRateConnector, raw: RawDataset
) -> None:
    """Panama's 1990-01 to 1993-05 rows predate the window the recording proves.

    They are 1 in the recording, but the check's window is what was measured,
    and asserting outside it would be asserting something unverified.
    """
    observations = connector.transform(raw)
    index = next(
        i
        for i, obs in enumerate(observations)
        if obs.country_iso3 == "PAN" and obs.period.label == "1991-03"
    )
    observations[index] = replace(observations[index], value_numeric=Decimal("1.4"))

    result = next(
        r for r in connector.validate(observations) if r.check_name == "cepalstat_fx_pegs_hold"
    )

    assert result.status is CheckStatus.PASSED
```

Add `from dataclasses import replace` and
`from reim.core.constants import CheckSeverity, CheckStatus` to the test file's
imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_fx_connector.py -k "validate or country or peg" -q`
Expected: FAIL — `AttributeError`, or the base class's default `validate`
returning an empty list.

- [ ] **Step 3: Implement the two checks and validate**

Append to `CepalstatExchangeRateConnector`:

```text
    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert CEPALSTAT-specific expectations beyond the standard battery."""
        return [
            self._check_expected_countries(observations),
            self._check_pegs_hold(observations),
            self._check_monthly_continuity(observations),
        ]

    def _check_expected_countries(
        self, observations: list[NormalizedObservation]
    ) -> QualityResult:
        """All seven, every run.

        An expectation rather than a floor, so that a country arriving is
        reported as loudly as one disappearing.
        """
        seen = {obs.country_iso3 for obs in observations}
        problems = [f"lost {iso3}" for iso3 in sorted(CENTRAL_AMERICA - seen)]
        problems += [f"gained {iso3}" for iso3 in sorted(seen - CENTRAL_AMERICA)]

        if not problems:
            return QualityResult.passed(
                "cepalstat_fx_expected_countries",
                CheckType.COMPLETENESS,
                f"All {len(CENTRAL_AMERICA)} countries returned rates",
                expected_value=str(len(CENTRAL_AMERICA)),
                actual_value=str(len(seen)),
            )

        return QualityResult.failure(
            "cepalstat_fx_expected_countries",
            CheckType.COMPLETENESS,
            CheckSeverity.CRITICAL,
            f"{len(problems)} change(s) in country coverage: {', '.join(problems[:5])}",
            expected_value=str(len(CENTRAL_AMERICA)),
            actual_value=str(len(seen)),
        )

    def _check_pegs_hold(self, observations: list[NormalizedObservation]) -> QualityResult:
        """Panama at 1 and Belize at 2, from the month the recording verified.

        Both are legal facts rather than market outcomes. A value off the peg
        means a dimension has been mis-keyed or a country column shifted, far
        more probably than that either country has floated its currency.

        The window starts at ``PEGS_HOLD_FROM`` because that is where the
        measurement starts; Panama's earlier rows are also 1, but asserting
        outside what was measured would be asserting something unverified.
        """
        broken: list[str] = []
        compared = 0
        for obs in observations:
            expected = PEGS.get(obs.country_iso3)
            if expected is None or obs.value_numeric is None:
                continue
            if (obs.period.start.year, obs.period.start.month) < PEGS_HOLD_FROM:
                continue
            compared += 1
            if obs.value_numeric != expected:
                broken.append(f"{obs.country_iso3} {obs.period.label} = {obs.value_numeric}")

        if not broken:
            return QualityResult.passed(
                "cepalstat_fx_pegs_hold",
                CheckType.CONSISTENCY,
                f"Both pegs hold across all {compared} pegged country-month(s)",
                expected_value="0 off peg",
                actual_value="0",
            )

        shown = ", ".join(broken[:5])
        suffix = f" (+{len(broken) - 5} more)" if len(broken) > 5 else ""
        return QualityResult.failure(
            "cepalstat_fx_pegs_hold",
            CheckType.CONSISTENCY,
            CheckSeverity.ERROR,
            f"{len(broken)} pegged rate(s) off their peg: {shown}{suffix}",
            expected_value="0 off peg",
            actual_value=str(len(broken)),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_fx_connector.py -q`
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
git add reim/ingestion/connectors/regional/cepalstat_exchange_rate.py \
        tests/unit/test_cepalstat_fx_connector.py
git commit -m "test(cepalstat): cover the two exchange rate quality checks"
```

---

### Task 6: Cover the two-request extract

**Files:**
- Modify: `reim/ingestion/connectors/regional/cepalstat_exchange_rate.py`
- Test: `tests/unit/test_cepalstat_fx_connector.py`

**Interfaces:**
- Consumes: Task 5's connector.
- Produces: `async def extract(self) -> RawDataset` whose payload is
  `{"data": str, "dimensions": str}` — the shape Task 4's `transform` already
  reads.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cepalstat_fx_connector.py`:

```python
@pytest.mark.asyncio
@respx.mock
async def test_extract_makes_exactly_two_requests(
    connector: CepalstatExchangeRateConnector,
    cepalstat_fx_2179_json: str,
    cepalstat_fx_dimensions_json: str,
) -> None:
    """One for the data in English, one for the month names in Spanish."""
    base = "https://api-cepalstat.cepal.org/cepalstat/api/v1"
    data_route = respx.get(f"{base}/indicator/2179/data").mock(
        return_value=httpx.Response(
            200, text=cepalstat_fx_2179_json, headers={"content-type": "application/json"}
        )
    )
    dims_route = respx.get(f"{base}/indicator/2179/dimensions").mock(
        return_value=httpx.Response(
            200, text=cepalstat_fx_dimensions_json, headers={"content-type": "application/json"}
        )
    )

    raw = await connector.extract()

    assert data_route.call_count == 1
    assert dims_route.call_count == 1
    assert data_route.calls[0].request.url.params["lang"] == "en"
    assert dims_route.calls[0].request.url.params["lang"] == "es"
    assert raw.http_status == 200
    assert raw.metadata["indicator_id"] == 2179


@pytest.mark.asyncio
@respx.mock
async def test_the_language_split_is_pinned(
    connector: CepalstatExchangeRateConnector,
    cepalstat_fx_2179_json: str,
    cepalstat_fx_dimensions_json: str,
) -> None:
    """Collapsing the two requests to one language breaks one of them.

    An English dimensions response names every month `descripcion_ingles`, so
    the transform cannot tell January from July. This test exists so that a
    later simplification to a single request fails loudly.
    """
    base = "https://api-cepalstat.cepal.org/cepalstat/api/v1"
    respx.get(f"{base}/indicator/2179/data").mock(
        return_value=httpx.Response(
            200, text=cepalstat_fx_2179_json, headers={"content-type": "application/json"}
        )
    )
    respx.get(f"{base}/indicator/2179/dimensions").mock(
        return_value=httpx.Response(
            200, text=cepalstat_fx_dimensions_json, headers={"content-type": "application/json"}
        )
    )

    raw = await connector.extract()
    observations = connector.transform(raw)

    assert len(observations) == ROWS_FOR_THE_SEVEN


@pytest.mark.asyncio
@respx.mock
async def test_a_failing_envelope_raises_whatever_the_status_line_says(
    connector: CepalstatExchangeRateConnector,
) -> None:
    """CEPAL answers 500 with `success: false` for an unknown indicator."""
    base = "https://api-cepalstat.cepal.org/cepalstat/api/v1"
    respx.get(f"{base}/indicator/2179/data").mock(
        return_value=httpx.Response(
            200,
            text='{"header": {"success": false, "code": 500, "message": "no data"}, "body": {}}',
            headers={"content-type": "application/json"},
        )
    )

    with pytest.raises(ExtractionError, match="500"):
        await connector.extract()
```

Add `import httpx`, `import respx` and
`from reim.core.exceptions import ExtractionError` to the test file's imports.

Check how the other connector tests mark async tests — if the suite uses
`anyio` rather than `pytest.mark.asyncio`, match it. Find out with:

```bash
grep -n "asyncio\|anyio" tests/unit/test_cepalstat_monetary_connector.py pyproject.toml | head
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_cepalstat_fx_connector.py -k extract -q`
Expected: FAIL — the inherited `extract` is abstract or does not exist.

- [ ] **Step 3: Implement extract**

Insert into `CepalstatExchangeRateConnector`, before `transform`:

```text
    async def extract(self) -> RawDataset:
        """Fetch the rate matrix and its Spanish member table.

        Two requests: one for data in English, one for dimensions in Spanish.
        The Spanish request exists only because the English period members are
        untranslated; nothing from it is stored.

        Raises:
            ExtractionError: The API was unreachable, answered with something
                other than JSON, reported ``success: false`` in its envelope,
                or returned an empty data array.
        """
        base = str(self.source.base_url).rstrip("/")
        retrieved_at = datetime.now(UTC)

        async with http_client() as client:
            url = f"{base}/indicator/{CEPAL_ID}/data"
            response = await fetch(client, url, params={"lang": "en"})
            ensure_ok(response, expected_content_type="json")
            self._ensure_envelope_ok(response.text, CEPAL_ID, url)
            data = response.text
            status = response.status_code
            content_type = response.headers.get("content-type")

            url = f"{base}/indicator/{CEPAL_ID}/dimensions"
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
            metadata={"indicator_id": CEPAL_ID, "lang": "en", "dimensions_lang": "es"},
        )
```

- [ ] **Step 4: Run the whole gate**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy . && .venv/bin/python -m pytest -q`
Expected: all clean, 524 passed (510 before this plan, plus 14 new).

- [ ] **Step 5: Commit**

```bash
git add reim/ingestion/connectors/regional/cepalstat_exchange_rate.py \
        tests/unit/test_cepalstat_fx_connector.py
git commit -m "test(cepalstat): cover the two-request exchange rate extract"
```

---

### Task 7: Run it live, then write down what happened

**Files:**
- Modify: `docs/sources.md`
- Modify: `ROADMAP.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: no code. The measured outcome of a real run, recorded.

- [ ] **Step 1: Bring up the database and run the pipeline**

```bash
make db-up CONTAINER_ENGINE=podman
.venv/bin/alembic upgrade head
.venv/bin/reim seed
.venv/bin/reim run cepalstat_exchange_rate_monthly
```

If the CLI's verbs differ, read `reim/cli/main.py` rather than guessing.

- [ ] **Step 2: Record what the run actually produced**

```bash
.venv/bin/reim status cepalstat_exchange_rate_monthly
```

Write down: observations inserted, every check's status, and the exact span per
country. Expect 2,749 observations and three passing checks. **If a check
fails, that is a finding, not a failure to hide** — the monetary connector ships
with Honduras failing freshness deliberately, and the precedent is to document
the failure and say why the threshold is right.

- [ ] **Step 3: Add the source section to `docs/sources.md`**

Follow the shape of the monetary and debt sections exactly: a properties table
(organization, host, endpoint, protocol, auth, frequency, coverage, countries,
volume, licence, status), an indicator table, and then the subsections. Write
these four, with `####` headings:

1. **"The rate is quoted in a currency El Salvador retired in 2001"** — spec
   §3.1, including that the country registry gives a different and wrong answer,
   and that this is why the connector carries its own table.
2. **"A monthly average, against end-of-period stocks"** — spec §3.2. State
   plainly that anything converting M1 with this rate inherits the mismatch, and
   that CEPAL publishes no end-of-month alternative.
3. **"The payload contradicts itself about provenance"** — spec §3.3, quoting
   both `data_features` and the `sources` description, and saying REIM stores
   both and repeats neither.
4. **"Declared two decimals, published one"** — spec §3.4, with the measured
   1,813 / 936 split and what it means for anything derived from the rate.

- [ ] **Step 4: Amend the sentence this increment makes untrue**

`docs/sources.md`'s monetary section says REIM "performs no conversion — doing
so would make REIM the author of an exchange-rate choice it has no basis to
make." After this increment REIM has a basis; after increment B it will convert.

Change it to say that REIM now stores a published monthly rate for all seven
countries, that it still performs no conversion **today**, and link the new
section. Do not claim conversion exists — it does not until increment B.

- [ ] **Step 5: Update `ROADMAP.md`**

The v0.3.0 line reads "Currency handling for genuinely multi-currency
comparisons — always alongside the original figure, never replacing it."

Do **not** tick it — increment B is what completes it. Add a nested note under
it recording that the rate series is in, with its observation count and span,
and that the converted view is the remaining half. Also correct the frequency
tally in the v0.2.0 "Monthly frequency exercised end to end" bullet: the catalog
now holds 8 monthly series, not 7.

- [ ] **Step 6: Update `README.md`**

Find the source and indicator tables and add the new row and the new indicator.
Update any total counts the README states — grep for the current observation
total and the source count and correct both.

- [ ] **Step 7: Verify every number you wrote**

```bash
grep -rn "2,749\|2749" docs/sources.md ROADMAP.md README.md
```

Every figure in prose must match what step 2 actually printed. The repo's
history includes a commit fixing exactly this kind of drift
(`36554d0 docs(cepalstat): fix debt-section freshness arithmetic and stale dates`);
do not add another.

- [ ] **Step 8: Run the whole gate one more time**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy . && .venv/bin/python -m pytest -q`
Expected: all clean, 524 passed.

`ruff format` silently rewrites any ` ```python ` block in a Markdown file that
is not a valid standalone module. If it reports changes to a `.md` file, the
fix is to fence that block as ` ```text `, not to accept the rewrite.

- [ ] **Step 9: Commit**

```bash
git add docs/sources.md ROADMAP.md README.md
git commit -m "feat: CEPALSTAT monthly exchange rates — REIM's first regional rate series"
```

---

## Done when

* `.venv/bin/reim run cepalstat_exchange_rate_monthly` stores 2,749
  observations for seven countries with three passing checks.
* El Salvador's rows carry `SVC`, not `USD` — the one defect that would make
  increment B silently wrong.
* The full gate is clean and `docs/sources.md` records the four findings from
  spec §3.
* `currency_convertible` does **not** exist yet, and no comparison endpoint code
  has been touched.
