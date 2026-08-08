# IMF Monthly Merchandise Trade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest Nicaragua's monthly merchandise exports, imports and trade balance from the IMF's SDMX API, giving REIM monthly external-sector data the BCN will not serve.

**Architecture:** One new connector reads a single CSV response from `api.imf.org`, filtering the world-aggregate counterpart inside the SDMX key so the request stays under 1 MB. The CSV maps three self-describing IMF indicator codes onto three new REIM indicators, and the trade-balance identity is asserted as a quality check.

**Tech Stack:** Python 3.12, httpx, `csv` from the standard library, pytest + respx.

## Global Constraints

- Endpoint `https://api.imf.org/external/sdmx/2.1`, dataflow `IMF.STA,IMTS`, key `NIC..G001.M`.
- Key dimensions are, in order, `COUNTRY.INDICATOR.COUNTERPART_COUNTRY.FREQUENCY`.
- Request header `Accept: application/vnd.sdmx.data+csv;version=2.0.0`. The API ignores a JSON `Accept` and returns SDMX-ML, so a non-CSV response must raise rather than be parsed.
- `COUNTERPART_COUNTRY == "G001"` is **required**; rows with any other counterpart are discarded and an absent `G001` is a `critical` failure. Never sum counterparts — the groups overlap.
- **`SCALE` is not a multiplier.** Every row reports `SCALE=6` while carrying full USD. Record it in `raw_metadata`; never apply it.
- Values are `Decimal` built from the raw CSV string. Never `float`.
- REIM unit label is `"current USD"`, matching `ni_exports_goods_services`; the IMF's own `UNIT` value (`USD`) goes in `raw_metadata`.
- `TIME_PERIOD` arrives as SDMX `YYYY-Mmm` (e.g. `2026-M04`) and must become REIM's `YYYY-MM`.
- Verify with the commands CI runs, over the whole repo: `ruff check . && ruff format --check . && mypy reim apps && pytest`.

---

### Task 1: Register the three trade indicators

**Files:**
- Modify: `reim/domain/indicators/registry.py`
- Modify: `sources/quality_rules.yml`
- Test: `tests/unit/test_quality.py`

**Interfaces:**
- Consumes: nothing.
- Produces: indicator codes `ni_exports_goods_monthly`, `ni_imports_goods_monthly`, `ni_trade_balance_goods_monthly`. Tasks 3–6 emit exactly these strings.

The catalog entry is deliberately **not** added here: `reim catalog validate` imports every connector named in the catalog, and the connector module does not exist until Task 3. Task 6 adds it.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_quality.py`:

```python
def test_monthly_trade_indicators_have_their_own_rules(
    quality_rules: QualityRuleSet,
) -> None:
    """Every monthly trade series needs bounds of its own before ingestion.

    Asserted against `.indicators`, not `for_indicator()`: the latter falls
    back to `defaults` for an unknown code and would pass even with no rule
    set at all.
    """
    for code in (
        "ni_exports_goods_monthly",
        "ni_imports_goods_monthly",
        "ni_trade_balance_goods_monthly",
    ):
        assert code in quality_rules.indicators, f"{code} has no rule set of its own"


def test_trade_balance_may_be_negative(quality_rules: QualityRuleSet) -> None:
    """Nicaragua ran a merchandise deficit in 433 of 436 published months."""
    balance = quality_rules.indicators["ni_trade_balance_goods_monthly"]

    assert balance.allow_negative is True
    assert balance.min_value is None
```

`QualityRuleSet.for_indicator()` returns `defaults` rather than `None` for an
unregistered code — `test_unknown_indicator_falls_back_to_defaults` in this
file already asserts that — so any test written against it would be vacuous
here. The `quality_rules` fixture is the one the file's existing tests use.

`QualityRuleSet` also validates that every rule key is a **registered**
indicator code, which is why Step 3 and Step 4 belong to the same task: adding
the rules before the indicators would fail catalog validation.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_quality.py -k "monthly_trade or balance_may_be_negative" -v`
Expected: FAIL — no rule set exists for these codes.

- [ ] **Step 3: Add the three indicator definitions**

In `reim/domain/indicators/registry.py`, after `ni_imports_goods_services`:

```python
(
    IndicatorDefinition(
        code="ni_exports_goods_monthly",
        name="Nicaragua — merchandise exports FOB (monthly)",
        description=(
            "Exports of goods, free on board, compiled by the IMF from national "
            "customs data (International Merchandise Trade Statistics). Goods "
            "only: this does not replace the annual, broader "
            "ni_exports_goods_services, which also covers services."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.MONTHLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url="https://www.imf.org/external/terms.htm",
    ),
)
(
    IndicatorDefinition(
        code="ni_imports_goods_monthly",
        name="Nicaragua — merchandise imports CIF (monthly)",
        description=(
            "Imports of goods including cost, insurance and freight, compiled "
            "by the IMF from national customs data. Goods only: this does not "
            "replace the annual, broader ni_imports_goods_services."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.MONTHLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url="https://www.imf.org/external/terms.htm",
    ),
)
(
    IndicatorDefinition(
        code="ni_trade_balance_goods_monthly",
        name="Nicaragua — merchandise trade balance (monthly)",
        description=(
            "Merchandise exports FOB minus imports CIF, as published by the "
            "IMF. Negative in 433 of the 436 months published: Nicaragua runs "
            "a persistent merchandise deficit."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.MONTHLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url="https://www.imf.org/external/terms.htm",
    ),
)
```

- [ ] **Step 4: Add the three quality rule sets**

In `sources/quality_rules.yml`, in the external-sector section:

```yaml
  # Monthly merchandise trade (IMF IMTS). No max_period_change_pct on any of
  # the three: monthly trade is genuinely volatile, and the balance crosses
  # zero, which makes a percentage change OF it unbounded and meaningless —
  # the same reasoning already applied to ni_cpi_inflation_monthly.
  ni_exports_goods_monthly:
    min_value: 0
    allow_negative: false
    allow_zero: false
    freshness_max_age_days: 120
    min_observations: 300

  ni_imports_goods_monthly:
    min_value: 0
    allow_negative: false
    allow_zero: false
    freshness_max_age_days: 120
    min_observations: 300

  ni_trade_balance_goods_monthly:
    # NOT bounded below. A trade balance crosses zero; a sign constraint here
    # would reject 433 of the 436 real months.
    allow_negative: true
    allow_zero: true
    freshness_max_age_days: 120
    min_observations: 300
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit -q`
Expected: PASS.

Run: `.venv/bin/reim catalog validate`
Expected: still 8 sources; the rule-set count rises from 16 to 19.

- [ ] **Step 6: Gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy reim apps
git add reim/domain/indicators/registry.py sources/quality_rules.yml tests/unit/test_quality.py
git commit -m "feat(indicators): register monthly merchandise trade series

Exports FOB, imports CIF and the balance between them. The balance
carries no lower bound: it crossed zero in only 3 of 436 published
months, so a sign constraint would reject almost the whole series.

Goods only — these do not replace the annual World Bank goods-and-
services series."
```

---

### Task 2: Record the API response as a fixture

**Files:**
- Create: `tests/fixtures/imf_imts_nic_g001.csv.gz`
- Modify: `tests/conftest.py`, `tests/fixtures/README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: pytest fixture `imf_imts_csv() -> str` returning the decompressed CSV text; 1,308 data rows plus 1 metadata row, 436 months from `1990-M01` to `2026-M04`.

- [ ] **Step 1: Record the live response**

```bash
curl -sL -H "Accept: application/vnd.sdmx.data+csv;version=2.0.0" \
  "https://api.imf.org/external/sdmx/2.1/data/IMF.STA,IMTS/NIC..G001.M?startPeriod=1990-01" \
  | gzip -9 > tests/fixtures/imf_imts_nic_g001.csv.gz
```

The uncompressed response is ~791 KB and gzips to ~18 KB, a 43× reduction, so
the **complete** response is committed rather than a trimmed sample. Tests can
then assert the real series length instead of a slice of it.

- [ ] **Step 2: Verify the recording**

```bash
.venv/bin/python - <<'PY'
import csv, gzip, io
text = gzip.decompress(open("tests/fixtures/imf_imts_nic_g001.csv.gz","rb").read()).decode("utf-8")
rows = [r for r in csv.DictReader(io.StringIO(text)) if r["TIME_PERIOD"]]
months = sorted({r["TIME_PERIOD"] for r in rows})
print("data rows:", len(rows), "months:", len(months), months[0], "->", months[-1])
print("counterparts:", {r["COUNTERPART_COUNTRY"] for r in rows})
print("indicators:", sorted({r["INDICATOR"] for r in rows}))
PY
```

Expected: `data rows: 1308 months: 436 1990-M01 -> 2026-M04`, a single
counterpart `{'G001'}`, and indicators
`['MG_CIF_USD', 'TBG_USD', 'XG_FOB_USD']`. If the month count is higher, the
IMF has published further months since — adjust the expected counts in Tasks 3
and 5 to match the recording, keeping them exact rather than approximate.

- [ ] **Step 3: Add the pytest fixture**

In `tests/conftest.py`, next to `inide_workbook_bytes`:

```python
@pytest.fixture(scope="session")
def imf_imts_csv() -> str:
    """Real IMF IMTS response for Nicaragua, world aggregate (stored gzipped)."""
    return gzip.decompress((FIXTURES / "imf_imts_nic_g001.csv.gz").read_bytes()).decode("utf-8")
```

- [ ] **Step 4: Document the recording**

Add to the "Recorded from live official sources" table in
`tests/fixtures/README.md`:

```markdown
| `imf_imts_nic_g001.csv.gz` | `GET https://api.imf.org/external/sdmx/2.1/data/IMF.STA,IMTS/NIC..G001.M?startPeriod=1990-01` with `Accept: application/vnd.sdmx.data+csv;version=2.0.0`, byte-for-byte, gzipped only to keep the repo small (791 KB → 18 KB). Tests decompress it before parsing. | 2026-08-08 |
```

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/imf_imts_nic_g001.csv.gz tests/fixtures/README.md tests/conftest.py
git commit -m "test(imf): record the IMTS response for Nicaragua

The complete response rather than a sample: 791 KB gzips to 18 KB, so
tests can assert the real 1,308 observations across 436 months instead
of a slice."
```

---

### Task 3: The connector module and `transform`

**Files:**
- Create: `reim/ingestion/connectors/nicaragua/imf_imts_trade.py`
- Test: `tests/unit/test_imf_imts_connector.py` (create)

**Interfaces:**
- Consumes: the indicator codes from Task 1; the `imf_imts_csv` fixture from Task 2.
- Produces: `ImfImtsTradeConnector` with `connector_key = "imf_imts_nicaragua"`, `version = "1.0.0"`; module constants `DATAFLOW`, `COUNTERPART_WORLD`, `CSV_MEDIA_TYPE`, `DEFAULT_START_PERIOD`, `INDICATORS: dict[str, tuple[str, str]]`; `transform(raw: RawDataset) -> list[NormalizedObservation]` reading `raw.payload` as the CSV **text**.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_imf_imts_connector.py`:

```python
"""IMF IMTS monthly trade connector, replayed against a recorded response.

No test here performs a real network call except the opt-in `live` one.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from reim.core.constants import Frequency
from reim.core.exceptions import TransformationError
from reim.domain.pipelines.models import RawDataset
from reim.domain.sources.catalog import SourceEntry
from reim.ingestion.connectors.nicaragua.imf_imts_trade import ImfImtsTradeConnector

BASE_URL = "https://api.imf.org/external/sdmx/2.1"
RETRIEVED_AT = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


def build_connector(**options: object) -> ImfImtsTradeConnector:
    entry = SourceEntry.model_validate(
        {
            "key": "imf_imts_nicaragua",
            "name": "Nicaragua merchandise trade (monthly)",
            "country": "NI",
            "organization": "IMF",
            "category": "external_sector",
            "access_type": "http_api",
            "frequency": "monthly",
            "format": "csv",
            "base_url": BASE_URL,
            "connector": "reim.ingestion.connectors.nicaragua.imf_imts_trade",
            "indicators": [
                "ni_exports_goods_monthly",
                "ni_imports_goods_monthly",
                "ni_trade_balance_goods_monthly",
            ],
            "license": "imf_terms_of_use",
            "options": dict(options),
        }
    )
    return ImfImtsTradeConnector(entry)


def raw_from(csv_text: str) -> RawDataset:
    return RawDataset(
        source_key="imf_imts_nicaragua",
        retrieved_at=RETRIEVED_AT,
        source_url=f"{BASE_URL}/data/IMF.STA,IMTS/NIC..G001.M",
        payload=csv_text,
        content_type="application/vnd.sdmx.data+csv;version=2.0.0",
        http_status=200,
    )


def test_transform_reads_all_three_series(imf_imts_csv: str) -> None:
    connector = build_connector()

    observations = connector.transform(raw_from(imf_imts_csv))

    counts: dict[str, int] = {}
    for obs in observations:
        counts[obs.indicator_code] = counts.get(obs.indicator_code, 0) + 1

    assert counts == {
        "ni_exports_goods_monthly": 436,
        "ni_imports_goods_monthly": 436,
        "ni_trade_balance_goods_monthly": 436,
    }
    assert len(observations) == 1308


def test_transform_converts_the_sdmx_month_label(imf_imts_csv: str) -> None:
    """SDMX writes 2026-M04; REIM stores 2026-04 as a closed month."""
    connector = build_connector()

    observations = connector.transform(raw_from(imf_imts_csv))
    latest = max(obs.period.start for obs in observations)
    newest = next(obs for obs in observations if obs.period.start == latest)

    assert newest.period.label == "2026-04"
    assert newest.period.frequency is Frequency.MONTHLY
    assert newest.period.start == date(2026, 4, 1)
    assert newest.period.end == date(2026, 4, 30)


def test_transform_does_not_apply_scale(imf_imts_csv: str) -> None:
    """Every row says SCALE=6 while carrying full USD; applying it would
    inflate the series a millionfold."""
    connector = build_connector()

    observations = connector.transform(raw_from(imf_imts_csv))
    exports = {
        obs.period.label: obs.value_numeric
        for obs in observations
        if obs.indicator_code == "ni_exports_goods_monthly"
    }

    assert exports["2026-04"] == Decimal("601982690")
    assert observations[0].raw_metadata["imf_scale"] == "6"


def test_transform_keeps_the_negative_balance_exact(imf_imts_csv: str) -> None:
    connector = build_connector()

    observations = connector.transform(raw_from(imf_imts_csv))
    balance = {
        obs.period.label: obs.value_numeric
        for obs in observations
        if obs.indicator_code == "ni_trade_balance_goods_monthly"
    }

    assert balance["2026-04"] == Decimal("-274932625")
    assert balance["1990-01"] == Decimal("-50033856.9")


def test_transform_records_provenance(imf_imts_csv: str) -> None:
    connector = build_connector()

    obs = connector.transform(raw_from(imf_imts_csv))[0]

    assert obs.country_iso3 == "NIC"
    assert obs.unit == "current USD"
    assert obs.currency_code == "USD"
    assert obs.retrieved_at == RETRIEVED_AT
    assert obs.published_at == datetime(2026, 8, 5, 23, 36, 59, 553138, tzinfo=UTC)
    assert obs.raw_metadata["imf_indicator"] in {"XG_FOB_USD", "MG_CIF_USD", "TBG_USD"}
    assert obs.raw_metadata["imf_counterpart"] == "G001"
    assert obs.raw_metadata["imf_unit"] == "USD"
    assert obs.source_record_id.startswith("imts:")


def test_transform_discards_a_non_world_counterpart(imf_imts_csv: str) -> None:
    """Counterpart groups overlap, so anything but G001 must be dropped."""
    connector = build_connector()
    lines = imf_imts_csv.splitlines()
    doctored = "\n".join(lines[:3] + [lines[2].replace(",G001,", ",USA,", 1)])

    observations = connector.transform(raw_from(doctored))

    assert all(obs.raw_metadata["imf_counterpart"] == "G001" for obs in observations)


def test_transform_skips_the_dataflow_metadata_row(imf_imts_csv: str) -> None:
    """The first CSV row carries dataset metadata and no TIME_PERIOD."""
    connector = build_connector()

    observations = connector.transform(raw_from(imf_imts_csv))

    assert all(obs.period.label for obs in observations)


def test_transform_skips_a_row_without_a_value(imf_imts_csv: str) -> None:
    """A month the IMF does not publish produces no observation, never a zero."""
    connector = build_connector()
    lines = imf_imts_csv.splitlines()
    header, first = lines[0], lines[2]
    columns = header.split(",")
    fields = first.split(",")
    fields[columns.index("OBS_VALUE")] = ""
    doctored = "\n".join([header, ",".join(fields)])

    assert connector.transform(raw_from(doctored)) == []


def test_transform_rejects_a_csv_missing_columns() -> None:
    connector = build_connector()
    doctored = "COUNTRY,INDICATOR\nNIC,XG_FOB_USD\n"

    with pytest.raises(TransformationError, match="missing column"):
        connector.transform(raw_from(doctored))


def test_transform_rejects_an_unparseable_period(imf_imts_csv: str) -> None:
    connector = build_connector()
    lines = imf_imts_csv.splitlines()
    doctored = "\n".join([lines[0], lines[2].replace("-M", "-Q", 1)])

    with pytest.raises(TransformationError, match="period"):
        connector.transform(raw_from(doctored))


def test_transform_rejects_a_non_numeric_value(imf_imts_csv: str) -> None:
    connector = build_connector()
    lines = imf_imts_csv.splitlines()
    columns = lines[0].split(",")
    fields = lines[2].split(",")
    fields[columns.index("OBS_VALUE")] = "n/a"
    doctored = "\n".join([lines[0], ",".join(fields)])

    with pytest.raises(TransformationError, match="non-numeric"):
        connector.transform(raw_from(doctored))


def test_transform_rejects_a_non_string_payload() -> None:
    connector = build_connector()
    raw = raw_from("")
    raw.payload = {"not": "csv"}

    with pytest.raises(TransformationError, match="CSV text"):
        connector.transform(raw)
```

Note for the implementer: the doctored-row tests slice `lines[2]` because
`lines[0]` is the header and `lines[1]` is the dataflow metadata row. Confirm
that with `head -3` on the decompressed fixture before relying on it; if the
metadata row is absent, use `lines[1]`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_imf_imts_connector.py -v`
Expected: FAIL — `ModuleNotFoundError: reim.ingestion.connectors.nicaragua.imf_imts_trade`.

- [ ] **Step 3: Create the connector module**

Create `reim/ingestion/connectors/nicaragua/imf_imts_trade.py`:

```python
"""Nicaragua — monthly merchandise trade from the IMF's SDMX API.

Why the IMF and not the Banco Central de Nicaragua
--------------------------------------------------
The BCN publishes these figures in its monthly bulletins, but
``www.bcn.gob.ni`` redirects every automated request to a Radware bot manager
challenge. Passing it would mean defeating an access control the publisher
installed deliberately, so REIM reads the same indicators from the IMF's
International Merchandise Trade Statistics instead. See ``docs/sources.md``.

The request
-----------
``GET {base_url}/data/IMF.STA,IMTS/NIC..G001.M?startPeriod=1990-01`` with
``Accept: application/vnd.sdmx.data+csv;version=2.0.0``. The key dimensions are
``COUNTRY.INDICATOR.COUNTERPART_COUNTRY.FREQUENCY``.

Three properties of the source shape this connector:

1. **The counterpart is filtered in the key, not after download.** Asking for
   every counterpart returns 103 of them and 62.9 MB; asking for ``G001``
   alone returns the same 1,308 usable rows in 791 KB.
2. **Counterpart groups overlap, so they must never be summed.** Adding all
   103 counterparts for June 2025 gives 1,804 million USD against a real 481
   million, because ``G001`` (world) and the regional groups already contain
   the individual countries.
3. **``SCALE`` is not a multiplier.** Every row reports ``SCALE=6`` while
   carrying full USD. It is recorded for provenance and never applied.

The API also ignores content negotiation — asking for SDMX-JSON returns
SDMX-ML regardless — so the connector pins the CSV media type and refuses a
response that is not CSV.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
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

#: SDMX agency and dataflow holding merchandise trade.
DATAFLOW = "IMF.STA,IMTS"
#: ISO-3166 alpha-3 of the reporting country.
COUNTRY_ISO3 = "NIC"
#: World aggregate. Counterpart groups overlap, so this is selected in the key
#: rather than reconstructed by summing.
COUNTERPART_WORLD = "G001"
#: SDMX frequency code for monthly.
FREQUENCY_CODE = "M"
#: Earliest month the dataflow holds for Nicaragua.
DEFAULT_START_PERIOD = "1990-01"
#: Media type pinned on the request and required of the response.
CSV_MEDIA_TYPE = "application/vnd.sdmx.data+csv;version=2.0.0"

#: IMF indicator code mapped to the REIM indicator it feeds and its unit.
INDICATORS: dict[str, tuple[str, str]] = {
    "XG_FOB_USD": ("ni_exports_goods_monthly", "current USD"),
    "MG_CIF_USD": ("ni_imports_goods_monthly", "current USD"),
    "TBG_USD": ("ni_trade_balance_goods_monthly", "current USD"),
}

#: Columns the parser cannot work without.
REQUIRED_COLUMNS = ("INDICATOR", "COUNTERPART_COUNTRY", "TIME_PERIOD", "OBS_VALUE")

_SDMX_MONTH = re.compile(r"^(?P<year>\d{4})-M(?P<month>0[1-9]|1[0-2])$")


class ImfImtsTradeConnector(BaseConnector):
    """Monthly merchandise exports, imports and balance for Nicaragua."""

    connector_key = "imf_imts_nicaragua"
    version = "1.0.0"
    expected_frequency = Frequency.MONTHLY
    country_iso3: ClassVar[str] = COUNTRY_ISO3
    currency_code: ClassVar[str] = "USD"

    @property
    def start_period(self) -> str:
        """First month requested; overridable through the catalog ``options``."""
        configured = self.source.options.get("start_period")
        return str(configured) if configured else DEFAULT_START_PERIOD

    @property
    def request_url(self) -> str:
        """Full SDMX data URL, counterpart already filtered."""
        base = str(self.source.base_url).rstrip("/")
        key = f"{COUNTRY_ISO3}..{COUNTERPART_WORLD}.{FREQUENCY_CODE}"
        return f"{base}/data/{DATAFLOW}/{key}"

    async def extract(self) -> RawDataset:
        """Not yet implemented; see Task 5 of the implementation plan."""
        raise NotImplementedError

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Map the SDMX CSV onto one observation per month and series.

        Pure function of ``raw``. Rows for any counterpart other than
        :data:`COUNTERPART_WORLD` are discarded, and the leading dataflow
        metadata row — which carries no ``TIME_PERIOD`` — is skipped.

        Raises:
            TransformationError: The payload is not CSV text, a required column
                is absent, a period is unparseable, or a value is non-numeric.
        """
        if not isinstance(raw.payload, str):
            msg = "IMF payload must be the response CSV text"
            raise TransformationError(msg, source_key=self.source.key)

        reader = csv.DictReader(io.StringIO(raw.payload))
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or ())]
        if missing:
            msg = f"IMF CSV is missing column(s): {', '.join(missing)}"
            raise TransformationError(msg, source_key=self.source.key)

        observations: list[NormalizedObservation] = []
        for row in reader:
            period_label = (row.get("TIME_PERIOD") or "").strip()
            if not period_label:
                # Leading dataflow metadata row: no period, no observation.
                continue
            if (row.get("COUNTERPART_COUNTRY") or "").strip() != COUNTERPART_WORLD:
                continue

            mapped = INDICATORS.get((row.get("INDICATOR") or "").strip())
            if mapped is None:
                continue
            indicator_code, unit = mapped

            raw_value = (row.get("OBS_VALUE") or "").strip()
            if not raw_value:
                # The IMF publishes no figure for this month. Skip it; never
                # substitute a zero.
                continue

            period = parse_period(self._month_label(period_label), Frequency.MONTHLY)
            observations.append(
                NormalizedObservation(
                    country_iso3=self.country_iso3,
                    indicator_code=indicator_code,
                    source_key=self.source.key,
                    period=period,
                    unit=unit,
                    currency_code=self.currency_code,
                    value_numeric=self._to_decimal(raw_value, period_label),
                    retrieved_at=raw.retrieved_at,
                    source_url=raw.source_url,
                    published_at=self._published_at(row),
                    source_record_id=f"imts:{row['INDICATOR'].strip()}:{period.label}",
                    raw_metadata={
                        "imf_dataflow": (row.get("DATAFLOW") or "").strip(),
                        "imf_indicator": row["INDICATOR"].strip(),
                        "imf_counterpart": COUNTERPART_WORLD,
                        "imf_unit": (row.get("UNIT") or "").strip(),
                        # Reported by the source but deliberately NOT applied:
                        # the values are already full USD.
                        "imf_scale": (row.get("SCALE") or "").strip(),
                    },
                )
            )

        observations.sort(key=lambda obs: (obs.indicator_code, obs.period.start))
        self.logger.info(
            "imf_imts.transformed",
            observations=len(observations),
            months=len({obs.period.label for obs in observations}),
        )
        return observations

    def _month_label(self, sdmx_period: str) -> str:
        """Convert SDMX ``2026-M04`` into REIM's ``2026-04``."""
        match = _SDMX_MONTH.match(sdmx_period)
        if match is None:
            msg = f"Unrecognised IMF monthly period {sdmx_period!r}"
            raise TransformationError(msg, source_key=self.source.key)
        return f"{match['year']}-{match['month']}"

    def _to_decimal(self, value: str, period_label: str) -> Decimal:
        """Build a Decimal from the published string, never through float."""
        try:
            return Decimal(value)
        except InvalidOperation as exc:
            msg = f"IMF returned a non-numeric value {value!r} for {period_label}"
            raise TransformationError(msg, source_key=self.source.key) from exc

    @staticmethod
    def _published_at(row: dict[str, Any]) -> datetime | None:
        """Read the dataset refresh timestamp, when the row carries one."""
        stamp = (row.get("PUBLICATION_DATE") or "").strip()
        if not stamp:
            return None
        try:
            parsed = datetime.fromisoformat(stamp)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Not yet implemented; see Task 4 of the implementation plan."""
        raise NotImplementedError
```

Python 3.12's `datetime.fromisoformat` parses the IMF's
`2026-08-05T23:36:59.553138600Z` — nine fractional digits and a `Z` — directly.
No truncation is needed.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_imf_imts_connector.py -v`
Expected: PASS, 12 tests.

- [ ] **Step 5: Gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy reim apps
git add reim/ingestion/connectors/nicaragua/imf_imts_trade.py tests/unit/test_imf_imts_connector.py
git commit -m "feat(imf): parse the IMTS trade CSV into monthly observations

Filters the world counterpart, converts SDMX 2026-M04 into REIM's
2026-04, and records SCALE without applying it — the values are already
full USD, so treating SCALE=6 as millions would inflate the series a
millionfold."
```

---

### Task 4: `validate`

**Files:**
- Modify: `reim/ingestion/connectors/nicaragua/imf_imts_trade.py`
- Test: `tests/unit/test_imf_imts_connector.py`

**Interfaces:**
- Consumes: `transform` and `INDICATORS` from Task 3.
- Produces: `validate(observations) -> list[QualityResult]` returning exactly three checks named `imf_imts_world_aggregate_present`, `imf_imts_all_indicators_present`, `imf_imts_balance_identity`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_imf_imts_connector.py`:

```python
from reim.core.constants import CheckSeverity, CheckStatus
from reim.domain.pipelines.models import QualityResult


def results_by_name(results: list[QualityResult]) -> dict[str, QualityResult]:
    return {r.check_name: r for r in results}


def test_validate_returns_the_three_source_checks(imf_imts_csv: str) -> None:
    connector = build_connector()
    observations = connector.transform(raw_from(imf_imts_csv))

    assert set(results_by_name(connector.validate(observations))) == {
        "imf_imts_world_aggregate_present",
        "imf_imts_all_indicators_present",
        "imf_imts_balance_identity",
    }


def test_validate_passes_on_the_recorded_response(imf_imts_csv: str) -> None:
    connector = build_connector()
    observations = connector.transform(raw_from(imf_imts_csv))

    assert [r for r in connector.validate(observations) if r.failed] == []


def test_missing_world_aggregate_is_critical() -> None:
    """Without G001 the run has no totals and must not be committed."""
    connector = build_connector()

    check = results_by_name(connector.validate([]))["imf_imts_world_aggregate_present"]

    assert check.status is CheckStatus.FAILED
    assert check.severity is CheckSeverity.CRITICAL


def test_a_missing_series_is_an_error(imf_imts_csv: str) -> None:
    connector = build_connector()
    observations = [
        obs
        for obs in connector.transform(raw_from(imf_imts_csv))
        if obs.indicator_code != "ni_trade_balance_goods_monthly"
    ]

    check = results_by_name(connector.validate(observations))["imf_imts_all_indicators_present"]

    assert check.status is CheckStatus.FAILED
    assert check.severity is CheckSeverity.ERROR
    assert "ni_trade_balance_goods_monthly" in check.message


def test_balance_identity_holds_on_the_real_series(imf_imts_csv: str) -> None:
    """TBG = XG - MG, exact at both ends of the 436-month series."""
    connector = build_connector()
    observations = connector.transform(raw_from(imf_imts_csv))

    check = results_by_name(connector.validate(observations))["imf_imts_balance_identity"]

    assert check.status is CheckStatus.PASSED
    assert check.actual_value == "0"


def test_a_broken_balance_identity_is_an_error(imf_imts_csv: str) -> None:
    connector = build_connector()
    observations = connector.transform(raw_from(imf_imts_csv))
    broken = next(
        obs for obs in observations if obs.indicator_code == "ni_trade_balance_goods_monthly"
    )
    broken.value_numeric = Decimal("1")

    check = results_by_name(connector.validate(observations))["imf_imts_balance_identity"]

    assert check.status is CheckStatus.FAILED
    assert check.severity is CheckSeverity.ERROR
    assert broken.period.label in check.message
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_imf_imts_connector.py -k validate -v`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement `validate`**

Replace the placeholder `validate` with:

```python
def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
    """Assert IMF-specific expectations beyond the standard battery."""
    return [
        self._check_world_aggregate_present(observations),
        self._check_all_indicators_present(observations),
        self._check_balance_identity(observations),
    ]


def _check_world_aggregate_present(
    self, observations: list[NormalizedObservation]
) -> QualityResult:
    """Without the world aggregate there are no totals to publish.

    Critical rather than error: the alternative to having ``G001`` is
    summing 103 overlapping counterpart groups, which double-counts. A run
    without it must not be committed at all.
    """
    kept = [
        obs for obs in observations if obs.raw_metadata.get("imf_counterpart") == COUNTERPART_WORLD
    ]
    if kept:
        return QualityResult.passed(
            "imf_imts_world_aggregate_present",
            CheckType.COMPLETENESS,
            f"{len(kept)} observation(s) carry the {COUNTERPART_WORLD} world aggregate",
            expected_value=f">0 {COUNTERPART_WORLD} rows",
            actual_value=str(len(kept)),
        )
    return QualityResult.failure(
        "imf_imts_world_aggregate_present",
        CheckType.COMPLETENESS,
        CheckSeverity.CRITICAL,
        f"No {COUNTERPART_WORLD} rows: the response carries no world totals",
        expected_value=f">0 {COUNTERPART_WORLD} rows",
        actual_value="0",
    )


def _check_all_indicators_present(self, observations: list[NormalizedObservation]) -> QualityResult:
    """All three series must arrive, or a column stopped mapping."""
    expected = {code for code, _ in INDICATORS.values()}
    found = {obs.indicator_code for obs in observations}
    missing = sorted(expected - found)

    if not missing:
        return QualityResult.passed(
            "imf_imts_all_indicators_present",
            CheckType.COMPLETENESS,
            f"All {len(expected)} indicators received data",
            expected_value=str(len(expected)),
            actual_value=str(len(found)),
        )
    return QualityResult.failure(
        "imf_imts_all_indicators_present",
        CheckType.COMPLETENESS,
        CheckSeverity.ERROR,
        f"No data parsed for: {', '.join(missing)}",
        expected_value=str(sorted(expected)),
        actual_value=str(sorted(found)),
    )


def _check_balance_identity(self, observations: list[NormalizedObservation]) -> QualityResult:
    """The published balance must equal exports minus imports.

    Verified exact at both ends of the series, so any break means the rows
    were misaligned or a value was misparsed rather than a rounding
    difference.
    """
    by_period: dict[str, dict[str, Decimal]] = {}
    for obs in observations:
        if obs.value_numeric is None:
            continue
        by_period.setdefault(obs.period.label, {})[obs.indicator_code] = obs.value_numeric

    breaks: list[str] = []
    checked = 0
    for label in sorted(by_period):
        series = by_period[label]
        exports = series.get("ni_exports_goods_monthly")
        imports = series.get("ni_imports_goods_monthly")
        balance = series.get("ni_trade_balance_goods_monthly")
        if exports is None or imports is None or balance is None:
            continue
        checked += 1
        if balance != exports - imports:
            breaks.append(label)

    if not breaks:
        return QualityResult.passed(
            "imf_imts_balance_identity",
            CheckType.CONSISTENCY,
            f"Balance equals exports minus imports in all {checked} complete month(s)",
            expected_value="0",
            actual_value="0",
        )

    shown = ", ".join(breaks[:5])
    suffix = f" (+{len(breaks) - 5} more)" if len(breaks) > 5 else ""
    return QualityResult.failure(
        "imf_imts_balance_identity",
        CheckType.CONSISTENCY,
        CheckSeverity.ERROR,
        f"{len(breaks)} of {checked} month(s) break TBG = XG - MG: {shown}{suffix}",
        expected_value="0",
        actual_value=str(len(breaks)),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_imf_imts_connector.py -v`
Expected: PASS, 18 tests.

- [ ] **Step 5: Gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy reim apps
git add reim/ingestion/connectors/nicaragua/imf_imts_trade.py tests/unit/test_imf_imts_connector.py
git commit -m "feat(imf): source-specific quality checks

A missing world aggregate is critical, because the only alternative to
G001 is summing overlapping counterpart groups. The published balance is
checked against exports minus imports, an identity that holds exactly at
both ends of the 436-month series."
```

---

### Task 5: `extract`

**Files:**
- Modify: `reim/ingestion/connectors/nicaragua/imf_imts_trade.py`
- Test: `tests/unit/test_imf_imts_connector.py`

**Interfaces:**
- Consumes: `request_url`, `start_period`, `CSV_MEDIA_TYPE` from Task 3.
- Produces: `extract() -> RawDataset` whose `payload` is the CSV **text** Task 3's `transform` consumes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_imf_imts_connector.py`:

```python
import httpx
import respx

from reim.core.exceptions import ExtractionError

DATA_URL = f"{BASE_URL}/data/IMF.STA,IMTS/NIC..G001.M"


@respx.mock
async def test_extract_requests_the_filtered_key(imf_imts_csv: str) -> None:
    route = respx.get(DATA_URL).mock(
        return_value=httpx.Response(
            200, text=imf_imts_csv, headers={"Content-Type": "application/vnd.sdmx.data+csv"}
        )
    )

    connector = build_connector()
    raw = await connector.extract()

    assert route.call_count == 1
    assert raw.http_status == 200
    assert raw.payload == imf_imts_csv
    request = route.calls.last.request
    assert "NIC..G001.M" in str(request.url)
    assert request.url.params["startPeriod"] == "1990-01"


@respx.mock
async def test_extract_pins_the_csv_media_type(imf_imts_csv: str) -> None:
    """The API ignores a JSON Accept, so the CSV type must be pinned."""
    route = respx.get(DATA_URL).mock(
        return_value=httpx.Response(
            200, text=imf_imts_csv, headers={"Content-Type": "application/vnd.sdmx.data+csv"}
        )
    )

    await build_connector().extract()

    accept = route.calls.last.request.headers["Accept"]
    assert accept == "application/vnd.sdmx.data+csv;version=2.0.0"


@respx.mock
async def test_extract_honours_a_configured_start_period(imf_imts_csv: str) -> None:
    route = respx.get(DATA_URL).mock(
        return_value=httpx.Response(
            200, text=imf_imts_csv, headers={"Content-Type": "application/vnd.sdmx.data+csv"}
        )
    )

    await build_connector(start_period="2020-01").extract()

    assert route.calls.last.request.url.params["startPeriod"] == "2020-01"


@respx.mock
async def test_extract_rejects_an_xml_response() -> None:
    """The API answers SDMX-ML when it feels like it; that must not be parsed."""
    respx.get(DATA_URL).mock(
        return_value=httpx.Response(
            200,
            text="<?xml version='1.0'?><message:StructureSpecificData/>",
            headers={"Content-Type": "application/vnd.sdmx.structurespecificdata+xml"},
        )
    )

    with pytest.raises(ExtractionError, match="csv"):
        await build_connector().extract()


@respx.mock
async def test_extract_raises_on_a_server_error() -> None:
    respx.get(DATA_URL).mock(return_value=httpx.Response(404, text="not found"))

    with pytest.raises(ExtractionError, match="HTTP 404"):
        await build_connector().extract()


@pytest.mark.live
async def test_live_api_answers_the_documented_contract() -> None:
    """Opt-in: hits the real IMF API. Run with `pytest -m live`."""
    connector = build_connector(start_period="2025-01")

    raw = await connector.extract()
    observations = connector.transform(raw)

    assert observations
    assert {obs.indicator_code for obs in observations} == {
        "ni_exports_goods_monthly",
        "ni_imports_goods_monthly",
        "ni_trade_balance_goods_monthly",
    }
    assert [r for r in connector.validate(observations) if r.failed] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_imf_imts_connector.py -k extract -v`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement `extract`**

Add the HTTP import to the module's import block:

```python
from reim.ingestion.http import ensure_ok, fetch, http_client
```

Replace the placeholder `extract` with:

```python
    async def extract(self) -> RawDataset:
        """Fetch the whole series as one CSV response.

        Raises:
            ExtractionError: The API was unreachable, returned an error status,
                or answered with something other than CSV.
        """
        params = {"startPeriod": self.start_period}
        retrieved_at = datetime.now(UTC)

        async with http_client() as client:
            response = await fetch(
                client,
                self.request_url,
                params=params,
                headers={"Accept": CSV_MEDIA_TYPE},
            )
            ensure_ok(response, expected_content_type="csv")
            payload = response.text

        self.logger.info(
            "imf_imts.extracted",
            start_period=self.start_period,
            bytes=len(payload),
        )
        return RawDataset(
            source_key=self.source.key,
            retrieved_at=retrieved_at,
            source_url=str(response.request.url),
            payload=payload,
            content_type=response.headers.get("content-type"),
            http_status=response.status_code,
            metadata={
                "dataflow": DATAFLOW,
                "counterpart": COUNTERPART_WORLD,
                "start_period": self.start_period,
            },
        )
```

`ensure_ok(..., expected_content_type="csv")` performs a case-insensitive
substring check. The live endpoint answers
`application/vnd.sdmx.data+csv;version=2.0.0`, which matches; an SDMX-ML
fallback does not and raises.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_imf_imts_connector.py -v`
Expected: PASS, 23 tests run; the 24th is the `live` one, deselected by default.

- [ ] **Step 5: Run the live test**

Run: `.venv/bin/python -m pytest tests/unit/test_imf_imts_connector.py -m live -v`
Expected: PASS against the real API.

- [ ] **Step 6: Gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy reim apps
git add reim/ingestion/connectors/nicaragua/imf_imts_trade.py tests/unit/test_imf_imts_connector.py
git commit -m "feat(imf): fetch the IMTS series as pinned CSV

One request with the counterpart already filtered in the SDMX key: 791
KB instead of the 62.9 MB an unfiltered query returns. The CSV media
type is pinned and enforced, because the API ignores content
negotiation and will answer SDMX-ML."
```

---

### Task 6: Enable the source, verify end to end and document

**Files:**
- Modify: `sources/catalog.yml`, `docs/sources.md`, `docs/implementation-plan.md`, `ROADMAP.md`, `README.md`
- Test: `tests/unit/test_catalog.py`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Add the catalog entry**

Append to `sources/catalog.yml`, after the BCN entry:

```yaml
  # ------------------------------------------------------------------------
  # Nicaragua — International Monetary Fund
  #
  # Monthly merchandise trade. Read from the IMF rather than the BCN because
  # www.bcn.gob.ni redirects automated requests to a bot-manager challenge.
  # NOTE: unlike every other source here, the IMF's data is NOT openly
  # licensed. See docs/sources.md.
  # ------------------------------------------------------------------------
  - key: imf_imts_nicaragua
    name: Nicaragua merchandise trade (monthly)
    description: >-
      Monthly merchandise exports FOB, imports CIF and the balance between
      them, from the IMF's International Merchandise Trade Statistics,
      world aggregate, covering January 1990 onwards.
    country: NI
    organization: IMF
    category: external_sector
    access_type: http_api
    frequency: monthly
    format: csv
    base_url: https://api.imf.org/external/sdmx/2.1
    documentation_url: https://www.imf.org/external/terms.htm
    connector: reim.ingestion.connectors.nicaragua.imf_imts_trade
    indicators:
      - ni_exports_goods_monthly
      - ni_imports_goods_monthly
      - ni_trade_balance_goods_monthly
    license: imf_terms_of_use
    official: true
    enabled: true
```

- [ ] **Step 2: Add the catalog test**

Add to `tests/unit/test_catalog.py`:

```python
def test_imf_source_declares_its_non_open_licence(catalog: SourceCatalog) -> None:
    """The IMF is the one source here whose data is not openly licensed."""
    entry = catalog.get("imf_imts_nicaragua")

    assert entry.license == "imf_terms_of_use"
    assert entry.license != "public_official_data"
    assert entry.enabled is True
```

- [ ] **Step 3: Validate the catalog and run the suite**

Run: `.venv/bin/reim catalog validate`
Expected: 9 sources, 9 enabled, 19 rule sets, all 9 connectors import.

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 4: Seed and run against a real database**

```bash
make db-up CONTAINER_ENGINE=podman
export REIM_DATABASE_URL="postgresql+psycopg://reim:reim@localhost:55432/reim"
.venv/bin/alembic upgrade head
.venv/bin/reim db seed
.venv/bin/reim pipeline run imf_imts_nicaragua
```

Expected: status `success`, **1,308 observations**, 0 rejected. This machine has
no Docker daemon; `CONTAINER_ENGINE=podman` is required.

- [ ] **Step 5: Prove idempotency**

Run: `.venv/bin/reim pipeline run imf_imts_nicaragua`
Expected: 0 inserted, 0 updated, 1,308 unchanged.

- [ ] **Step 6: Check the stored series**

```bash
podman exec reim-test-postgres psql -U reim -d reim -t -A -F' | ' -c \
"SELECT i.code, count(*), min(o.period_label), max(o.period_label),
        round(min(o.value_numeric)) AS lowest, round(max(o.value_numeric)) AS highest
   FROM observations o JOIN indicators i ON i.id = o.indicator_id
  WHERE i.code LIKE 'ni_%_goods_monthly' OR i.code = 'ni_trade_balance_goods_monthly'
  GROUP BY i.code ORDER BY i.code;"
```

Expected: three rows of 436 observations each, spanning `1990-01` to `2026-04`.
Exports and imports must have a positive minimum; the balance must have a
**negative** minimum — if its minimum is positive the sign was lost somewhere.

- [ ] **Step 7: Check the quality checks**

```bash
podman exec reim-test-postgres psql -U reim -d reim -t -A -F' | ' -c \
"SELECT check_name, status, severity FROM data_quality_checks
  WHERE check_name LIKE 'imf%' ORDER BY created_at DESC LIMIT 3;"
podman exec reim-test-postgres psql -U reim -d reim -t -A -c \
"SELECT count(*) FROM data_quality_checks WHERE status='failed' AND severity IN ('error','critical');"
```

Expected: the three IMF checks present and passing, and 0 failures at `error`
or `critical`.

- [ ] **Step 8: Update the documentation**

`docs/sources.md` — two changes.

First, rewrite the BCN "statistics portal" note into a full entry recording
that `www.bcn.gob.ni` is behind a Radware bot manager: every request, including
one with a browser User-Agent, is redirected to `validate.perfdrive.com`;
passing it requires executing a JavaScript challenge; REIM will not do that,
because a bot manager is the publisher's explicit decision about automated
access. Record that `servicios.bcn.gob.ni` exposes only `Tc_Servicio`.

Second, add an IMF section stating: the endpoint and key; that the counterpart
is filtered in the key (791 KB versus 62.9 MB); that counterpart groups overlap
and must never be summed (1,804 M versus a real 481 M for June 2025); that
`SCALE=6` is not a multiplier; that the API ignores content negotiation; the
coverage of 436 months; and — prominently — that **the IMF's data is not openly
licensed**, quoting the `LICENSE` field verbatim, noting the rows also carry
`ACCESS_SHARING_LEVEL = PUBLIC_OPEN`, and stating that the terms page could not
be retrieved programmatically so its contents are not summarised.

Also record why monetary aggregates, remittances and reserves are absent:
Nicaragua returns 0 observations from `MFS_MA` (against 183 for Costa Rica) and
0 from `BOP` at every frequency; `IRFCL` has 1,740 monthly Nicaraguan
observations but its 60 indicator codes cannot be named, because
`codelist/IMF.STA/CL_INDICATOR` returns 204, the `INDICATOR` dimension carries
no enumeration, and SDMX-JSON requests return SDMX-ML. Note the unblocking
step: map the codes against the IMF's *IRFCL Guidelines for a Data Template*.

`docs/implementation-plan.md` — add `## 14. Post-MVP increment — IMF monthly
trade (2026-08-08)` with a verification table covering Steps 3–7 and the
licence decision.

`ROADMAP.md` — under v0.2.0, replace the "BCN monthly statistics" bullet with an
honest outcome: trade delivered from the IMF, the BCN route blocked by a bot
manager, and monetary aggregates and remittances still open.

`README.md` — update the test count, and add a limitation bullet stating that
one source's data is not openly licensed.

- [ ] **Step 9: Final gate and commit**

```bash
export REIM_TEST_DATABASE_URL="postgresql+psycopg://reim:reim@localhost:55432/reim"
.venv/bin/python -m pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy reim apps
.venv/bin/reim catalog validate
git add sources/catalog.yml docs/ ROADMAP.md README.md tests/unit/test_catalog.py
git commit -m "feat(imf): enable monthly merchandise trade

1,308 observations across three monthly series from 1990-01, filling
part of the gap the BCN's bot manager leaves. Documents plainly that
this source, alone among REIM's, is not openly licensed."
podman stop reim-test-postgres
```

---

## Self-review notes

**Spec coverage.** Spec §2 series table → Task 1; §3 T1/T2 → Task 3 `request_url` and `transform`, plus Task 4's critical check; §3 T3 → Task 3 (`imf_scale` recorded, never applied) with `test_transform_does_not_apply_scale`; §3 T4 → Task 5 (`Accept` pinned, `ensure_ok` enforcing CSV) with `test_extract_rejects_an_xml_response`; §3 T5 → Task 6 Step 8 documentation; §3 T6 → Task 6 Steps 1–2; §3 T7 → Task 4 `_check_balance_identity`; §4.1 → Task 1; §4.2 → Task 1; §4.3 → Task 6; §4.4 → Tasks 3–5; §5 licence → Task 6 Steps 1, 2 and 8; §6 reserves → Task 6 Step 8; §7 testing → Tasks 3–5; §8 → Task 6 Step 4.

**Corrections to the spec made while planning.**

- The spec said the fixture would be "the real response trimmed to a documented year range". It is not trimmed: 791 KB gzips to 18 KB, so the **complete** response is committed and the tests assert the real 1,308 observations and 436-month span rather than a slice.
- The spec's §4.1 said `value_type=CURRENCY`. That member does not exist — `ValueType` offers `LEVEL`, `INDEX`, `RATE`, `PERCENT`, `PERCENT_CHANGE`, `RATIO`. The plan uses `LEVEL` with `unit="current USD"`, matching `ni_exports_goods_services`. (The spec was corrected before it was committed.)
- No `PUBLICATION_DATE` truncation is needed: Python 3.12's `fromisoformat` parses the IMF's nine-digit fractional seconds and trailing `Z` directly. An earlier assumption that it would need trimming to six digits was wrong and is not in the plan.

**Verified against live data, not assumed.** The counts (436 months, 1,308 rows), the exact values asserted in tests (`601982690`, `-274932625`, `-50033856.9`), the response `Content-Type`, the single `PUBLICATION_DATE`, the absence of empty `OBS_VALUE`, and the balance identity at both ends of the series were all measured from the recorded response.

**Two flaws caught in this self-review.**

- Task 1's first draft asserted `rules.for_indicator(code) is not None`. That test would have passed **before** the rules were added: `for_indicator` falls back to `defaults` for an unknown code, as `test_unknown_indicator_falls_back_to_defaults` already asserts. It now checks membership of `.indicators`, which actually fails first.
- The "expected N tests" figures were estimates. Counted: Task 3 defines 12, Task 4 adds 6 (18), Task 5 adds 6 (24, of which the `live` one is deselected, so 23 run).

**Deliberately untested-by-fixture branch.** `transform` skips rows with an empty `OBS_VALUE`, which the recording never exercises — the IMF publishes a value for all 1,308 rows. `test_transform_skips_a_row_without_a_value` doctors a row to cover it.
