# Banguat Daily Exchange Rate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest Guatemala's daily quetzal/US-dollar buy and sell rates from the Banco de Guatemala, REIM's first national primary source outside Nicaragua.

**Architecture:** One SOAP call to `TipoCambioRango` returns the whole 1990-onward series, so the connector has no routine window and no separate backfill — a rebuild is complete by default. Each row yields two observations, because the buy and sell rates genuinely differ across nearly half the history.

**Tech Stack:** Python 3.12, httpx, `xml.etree.ElementTree`, pytest + respx.

## Global Constraints

- Endpoint `https://www.banguat.gob.gt/variables/ws/TipoCambio.asmx`, namespace `http://www.banguat.gob.gt/variables/ws/`, operation `TipoCambioRango(fechainit, fechafin)` with dates as **`dd/mm/yyyy`**.
- **Two indicators**: `gt_exchange_rate_official_daily_buy` (`compra`, the lower) and `gt_exchange_rate_official_daily_sell` (`venta`, the higher). Never collapsed into one.
- **One request per run**, `1990-01-01` to today. No routine window, no backfill mode.
- The `sell ≥ buy` check applies **only from 1992 onward**: 84 rows violate it, all in 1990-91, and they are real history.
- Missing days are **reported at `info`**, never a failure. Five days are missing in 36 years.
- Values are `Decimal` built from the published string. Never `float`.
- Unit `GTQ per USD`, `currency_code` `GTQ`.
- Verify with the commands CI runs, over the whole repo, **each as its own command that reports its own exit code**. Do not chain them with `&&`, `set -e` or a pipe into `tail` — all three have masked a failure in this repository and let a broken gate reach a commit.

---

### Task 1: Register Banguat, its indicators and their rules

**Files:**
- Modify: `reim/domain/sources/organizations.py`
- Modify: `reim/domain/indicators/registry.py`
- Modify: `sources/quality_rules.yml`
- Test: `tests/unit/test_quality.py`

**Interfaces:**
- Consumes: nothing.
- Produces: organization code `BANGUAT`; indicator codes `gt_exchange_rate_official_daily_buy` and `gt_exchange_rate_official_daily_sell`. Tasks 3-6 emit exactly these strings.

The catalog entry is **not** added here: `reim catalog validate` imports every
connector a catalog entry names, and the module does not exist until Task 3.
Task 6 adds it.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_quality.py`:

```python
def test_guatemala_exchange_rate_indicators_have_their_own_rules(
    quality_rules: QualityRuleSet,
) -> None:
    """Both sides of the published pair need bounds before ingestion."""
    for code in (
        "gt_exchange_rate_official_daily_buy",
        "gt_exchange_rate_official_daily_sell",
    ):
        assert code in quality_rules.indicators, f"{code} has no rule set of its own"


def test_the_quetzal_rate_has_no_ceiling(quality_rules: QualityRuleSet) -> None:
    """It ran 3.41 to 8.39 over 36 years; a narrow band would reject real history."""
    rule = quality_rules.indicators["gt_exchange_rate_official_daily_sell"]

    assert rule.allow_negative is False
    assert rule.max_value is None
    assert rule.max_period_change_pct is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_quality.py -k guatemala -v`
Expected: FAIL — `KeyError`, no rule set exists for these codes.

- [ ] **Step 3: Register the organization**

In `reim/domain/sources/organizations.py`, after the Nicaraguan block, add a
Guatemala section:

```text
    # -- Guatemala --------------------------------------------------------
    OrganizationDefinition(
        code="BANGUAT",
        name="Banco de Guatemala",
        short_name="Banguat",
        organization_type=OrganizationType.CENTRAL_BANK,
        website_url="https://www.banguat.gob.gt",
        country_iso2="GT",
    ),
```

- [ ] **Step 4: Register the two indicators**

In `reim/domain/indicators/registry.py`, after the Nicaraguan exchange-rate
entries:

```text
    IndicatorDefinition(
        code="gt_exchange_rate_official_daily_buy",
        name="Guatemala — official exchange rate, buy (daily)",
        description=(
            "Rate at which the Banco de Guatemala buys US dollars, published "
            "for each calendar day. This is the lower of the published pair; "
            "'compra' is stated from the bank's side, so it is the rate a "
            "seller of dollars receives."
        ),
        category=IndicatorCategory.EXCHANGE_RATE,
        frequency=Frequency.DAILY,
        unit="GTQ per USD",
        value_type=ValueType.RATE,
        methodology_url="https://www.banguat.gob.gt/variables/ws/TipoCambio.asmx",
    ),
    IndicatorDefinition(
        code="gt_exchange_rate_official_daily_sell",
        name="Guatemala — official exchange rate, sell (daily)",
        description=(
            "Rate at which the Banco de Guatemala sells US dollars, published "
            "for each calendar day. This is the higher of the published pair "
            "from 1992 onward; through the 1990-91 liberalisation the buy rate "
            "sat fixed above it."
        ),
        category=IndicatorCategory.EXCHANGE_RATE,
        frequency=Frequency.DAILY,
        unit="GTQ per USD",
        value_type=ValueType.RATE,
        methodology_url="https://www.banguat.gob.gt/variables/ws/TipoCambio.asmx",
    ),
```

- [ ] **Step 5: Add the quality rules**

In `sources/quality_rules.yml`, in the exchange-rate section:

```yaml
  # Guatemala's published pair. Bounded by sign only: the quetzal ran from
  # 3.41332 in 1990 to 8.39482 at its peak, and v0.1.0 already learned what a
  # narrow band costs — a min_value of 1 rejected 31 real observations.
  # No max_period_change_pct: the 1990-91 liberalisation moved the rate
  # sharply and genuinely.
  gt_exchange_rate_official_daily_buy:
    min_value: 0
    allow_negative: false
    allow_zero: false
    freshness_max_age_days: 7
    min_observations: 1000

  gt_exchange_rate_official_daily_sell:
    min_value: 0
    allow_negative: false
    allow_zero: false
    freshness_max_age_days: 7
    min_observations: 1000
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit -q`
Expected: PASS.

Run: `.venv/bin/reim catalog validate`
Expected: still 14 sources; the rule-set count rises from 19 to 21.

- [ ] **Step 7: Gate and commit**

Run each on its own and check its exit code before committing:

```bash
.venv/bin/ruff check .            ; echo "ruff: $?"
.venv/bin/ruff format --check .   ; echo "format: $?"
.venv/bin/mypy reim apps          ; echo "mypy: $?"
```

```bash
git add reim/domain/ sources/quality_rules.yml tests/unit/test_quality.py
git commit -m "feat(banguat): register the Banco de Guatemala and its rate pair

Two indicators, not one: Banguat publishes a buy and a sell rate, and
6,174 of 13,364 rows have them differ. Collapsing the pair would destroy
real information.

Bounded by sign only. The quetzal ran 3.41 to 8.39 over 36 years, and a
narrow band is how v0.1.0 rejected 31 legitimate observations."
```

---

### Task 2: Record the service response as a fixture

**Files:**
- Create: `tests/fixtures/banguat_tipocambio_rango.xml.gz`
- Modify: `tests/conftest.py`, `tests/fixtures/README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: pytest fixture `banguat_rango_xml() -> str` returning the decompressed SOAP envelope: 13,364 `<Var>` elements, `01/01/1990` to `08/08/2026`.

- [ ] **Step 1: Record the live response**

```bash
cat > /tmp/banguat_req.xml <<'EOF'
<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <TipoCambioRango xmlns="http://www.banguat.gob.gt/variables/ws/">
      <fechainit>01/01/1990</fechainit><fechafin>08/08/2026</fechafin>
    </TipoCambioRango>
  </soap:Body>
</soap:Envelope>
EOF
curl -s -H 'Content-Type: text/xml; charset=utf-8' \
  -H 'SOAPAction: "http://www.banguat.gob.gt/variables/ws/TipoCambioRango"' \
  --data-binary @/tmp/banguat_req.xml \
  "https://www.banguat.gob.gt/variables/ws/TipoCambio.asmx" \
  | gzip -9 > tests/fixtures/banguat_tipocambio_rango.xml.gz
```

- [ ] **Step 2: Verify the recording**

```bash
.venv/bin/python - <<'PY'
import gzip, re
text = gzip.decompress(open("tests/fixtures/banguat_tipocambio_rango.xml.gz","rb").read()).decode("utf-8")
rows = re.findall(r"<fecha>([^<]+)</fecha><venta>([^<]+)</venta><compra>([^<]+)</compra>", text)
print("rows:", len(rows), "| first:", rows[0][0], "| last:", rows[-1][0])
print("differing:", sum(1 for _, v, c in rows if v != c))
print("gzipped bytes:", len(open("tests/fixtures/banguat_tipocambio_rango.xml.gz","rb").read()))
PY
```

Expected: `rows: 13364 | first: 01/01/1990 | last: 08/08/2026`, `differing: 6174`,
about 90 KB gzipped from 1.33 MB raw.

If `last` is a later date because days have passed, that is fine — but then
**adjust the expected counts in Tasks 3 and 4 to match your recording**, keeping
them exact rather than approximate. The 1990-91 rows the tests depend on do not
move.

- [ ] **Step 3: Add the pytest fixture**

In `tests/conftest.py`, next to `imf_imts_csv`:

```python
@pytest.fixture(scope="session")
def banguat_rango_xml() -> str:
    """Real Banguat TipoCambioRango response, 1990 onward (stored gzipped)."""
    return gzip.decompress((FIXTURES / "banguat_tipocambio_rango.xml.gz").read_bytes()).decode(
        "utf-8"
    )
```

- [ ] **Step 4: Document the recording**

Add to the "Recorded from live official sources" table in
`tests/fixtures/README.md`:

```markdown
| `banguat_tipocambio_rango.xml.gz` | `POST https://www.banguat.gob.gt/variables/ws/TipoCambio.asmx`, `TipoCambioRango(01/01/1990, 08/08/2026)`, byte-for-byte, gzipped (1.33 MB → 90 KB). The complete series: 13,364 days, including the 1990-91 rows where the buy rate sat above the sell rate and the five days the service omits. | 2026-08-08 |
```

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/banguat_tipocambio_rango.xml.gz tests/fixtures/README.md tests/conftest.py
git commit -m "test(banguat): record the full TipoCambioRango response

The whole 36-year series rather than a sample. The tests that matter
need it: the 84 inverted rows are all in 1990-91 and the five missing
days are scattered across 2000-2004."
```

---

### Task 3: The connector and `transform`

**Files:**
- Create: `reim/ingestion/connectors/guatemala/banguat_exchange_rate.py`
- Test: `tests/unit/test_banguat_connector.py` (create)

**Interfaces:**
- Consumes: the indicator codes from Task 1; the `banguat_rango_xml` fixture from Task 2.
- Produces: `BanguatExchangeRate` with `connector_key = "banguat_exchange_rate"`, `version = "1.0.0"`; module constants `SOAP_NAMESPACE`, `SOAP_ACTION`, `START_DATE`, `SPREAD_ENFORCED_FROM_YEAR`, `SIDES`; module helper `_utc_today() -> date`; `transform(raw) -> list[NormalizedObservation]` reading `raw.payload` as the response **text**.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_banguat_connector.py`:

```python
"""Banguat daily exchange rate, replayed against a recorded response.

Every value asserted here was measured from that recording.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from reim.core.constants import Frequency
from reim.core.exceptions import TransformationError
from reim.domain.pipelines.models import RawDataset
from reim.domain.sources.catalog import SourceEntry
from reim.ingestion.connectors.guatemala.banguat_exchange_rate import BanguatExchangeRate

SOAP_URL = "https://www.banguat.gob.gt/variables/ws/TipoCambio.asmx"
RETRIEVED_AT = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


def build_connector(**options: object) -> BanguatExchangeRate:
    entry = SourceEntry.model_validate(
        {
            "key": "banguat_exchange_rate",
            "name": "Guatemala official exchange rate (daily)",
            "country": "GT",
            "organization": "BANGUAT",
            "category": "exchange_rate",
            "access_type": "soap",
            "frequency": "daily",
            "format": "xml",
            "base_url": SOAP_URL,
            "connector": "reim.ingestion.connectors.guatemala.banguat_exchange_rate",
            "indicators": [
                "gt_exchange_rate_official_daily_buy",
                "gt_exchange_rate_official_daily_sell",
            ],
            "options": dict(options),
        }
    )
    return BanguatExchangeRate(entry)


def raw_from(xml: str) -> RawDataset:
    return RawDataset(
        source_key="banguat_exchange_rate",
        retrieved_at=RETRIEVED_AT,
        source_url=SOAP_URL,
        payload=xml,
        content_type="text/xml; charset=utf-8",
        http_status=200,
    )


def test_transform_emits_both_sides_of_every_day(banguat_rango_xml: str) -> None:
    connector = build_connector()

    observations = connector.transform(raw_from(banguat_rango_xml))

    counts: dict[str, int] = {}
    for obs in observations:
        counts[obs.indicator_code] = counts.get(obs.indicator_code, 0) + 1

    assert counts == {
        "gt_exchange_rate_official_daily_buy": 13364,
        "gt_exchange_rate_official_daily_sell": 13364,
    }
    assert len(observations) == 26728


def test_transform_reads_the_published_values(banguat_rango_xml: str) -> None:
    """Cross-checked by hand against the recorded envelope."""
    connector = build_connector()

    observations = connector.transform(raw_from(banguat_rango_xml))
    by_key = {(obs.indicator_code, obs.period.label): obs.value_numeric for obs in observations}

    assert by_key[("gt_exchange_rate_official_daily_sell", "1990-01-01")] == Decimal("3.41332")
    assert by_key[("gt_exchange_rate_official_daily_buy", "1990-01-01")] == Decimal("3.4081")
    assert by_key[("gt_exchange_rate_official_daily_sell", "2026-07-01")] == Decimal("7.62415")


def test_transform_keeps_the_pair_distinct(banguat_rango_xml: str) -> None:
    """6,174 of 13,364 days publish different buy and sell rates."""
    connector = build_connector()

    observations = connector.transform(raw_from(banguat_rango_xml))
    sell = {
        obs.period.label: obs.value_numeric
        for obs in observations
        if obs.indicator_code == "gt_exchange_rate_official_daily_sell"
    }
    buy = {
        obs.period.label: obs.value_numeric
        for obs in observations
        if obs.indicator_code == "gt_exchange_rate_official_daily_buy"
    }

    assert sell.keys() == buy.keys()
    assert sum(1 for label in sell if sell[label] != buy[label]) == 6174


def test_transform_converts_the_day_first_date(banguat_rango_xml: str) -> None:
    """Banguat writes 08/11/1990 as 8 November, not 11 August."""
    connector = build_connector()

    observations = connector.transform(raw_from(banguat_rango_xml))
    november = next(
        obs
        for obs in observations
        if obs.period.label == "1990-11-08"
        and obs.indicator_code == "gt_exchange_rate_official_daily_sell"
    )

    assert november.value_numeric == Decimal("4.62181")
    assert november.period.start == november.period.end == date(1990, 11, 8)
    assert november.period.frequency is Frequency.DAILY


def test_transform_records_provenance(banguat_rango_xml: str) -> None:
    connector = build_connector()

    obs = connector.transform(raw_from(banguat_rango_xml))[0]

    assert obs.country_iso3 == "GTM"
    assert obs.unit == "GTQ per USD"
    assert obs.currency_code == "GTQ"
    assert obs.retrieved_at == RETRIEVED_AT
    assert obs.source_record_id is not None
    assert obs.source_record_id.startswith("tc_rango:")
    assert obs.raw_metadata["banguat_operation"] == "TipoCambioRango"
    assert obs.raw_metadata["banguat_moneda"] == "2"
    assert obs.raw_metadata["banguat_side"] in {"buy", "sell"}


def test_transform_sorts_by_date(banguat_rango_xml: str) -> None:
    connector = build_connector()

    sell = [
        obs.period.start
        for obs in connector.transform(raw_from(banguat_rango_xml))
        if obs.indicator_code == "gt_exchange_rate_official_daily_sell"
    ]

    assert sell == sorted(sell)


def test_transform_rejects_a_soap_fault() -> None:
    connector = build_connector()
    fault = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        "<soap:Body><soap:Fault><faultcode>soap:Server</faultcode>"
        "<faultstring>Server was unable to process request.</faultstring>"
        "</soap:Fault></soap:Body></soap:Envelope>"
    )

    with pytest.raises(TransformationError, match="unable to process"):
        connector.transform(raw_from(fault))


def test_transform_rejects_malformed_xml() -> None:
    connector = build_connector()

    with pytest.raises(TransformationError, match="malformed XML"):
        connector.transform(raw_from("<soap:Envelope>truncated"))


def test_transform_rejects_a_non_numeric_rate(banguat_rango_xml: str) -> None:
    connector = build_connector()
    doctored = banguat_rango_xml.replace("<venta>3.41332</venta>", "<venta>n/a</venta>", 1)

    with pytest.raises(TransformationError, match="non-numeric"):
        connector.transform(raw_from(doctored))


def test_transform_rejects_an_unparseable_date(banguat_rango_xml: str) -> None:
    connector = build_connector()
    doctored = banguat_rango_xml.replace("<fecha>01/01/1990</fecha>", "<fecha>1990-01</fecha>", 1)

    with pytest.raises(TransformationError, match="date"):
        connector.transform(raw_from(doctored))


def test_transform_rejects_the_same_day_twice_with_different_values(
    banguat_rango_xml: str,
) -> None:
    connector = build_connector()
    first = banguat_rango_xml.index("<Var>")
    end = banguat_rango_xml.index("</Var>", first) + len("</Var>")
    block = banguat_rango_xml[first:end]
    conflicting = block.replace("3.41332", "9.99999")
    doctored = banguat_rango_xml[:end] + conflicting + banguat_rango_xml[end:]

    with pytest.raises(TransformationError, match="two different values"):
        connector.transform(raw_from(doctored))


def test_transform_rejects_a_non_string_payload() -> None:
    connector = build_connector()
    raw = raw_from("")
    raw.payload = {"not": "xml"}

    with pytest.raises(TransformationError, match="response XML"):
        connector.transform(raw)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_banguat_connector.py -q`
Expected: FAIL — `ModuleNotFoundError:
reim.ingestion.connectors.guatemala.banguat_exchange_rate`.

- [ ] **Step 3: Write the connector**

Create `reim/ingestion/connectors/guatemala/banguat_exchange_rate.py`:

```python
"""Guatemala — daily official exchange rate published by the Banco de Guatemala.

Banguat exposes a free, unauthenticated SOAP service at
``https://www.banguat.gob.gt/variables/ws/TipoCambio.asmx``. Its
``TipoCambioRango`` operation returns every published day between two dates, so
**one request covers the whole series** — 13,364 days from 1990-01-01, about
1.3 MB, in under a second.

That is why this connector has no routine window and no separate backfill mode.
The BCN's connector needs one because its history costs 176 requests; the
consequence there is that a rebuild from an empty database silently produces a
truncated series unless a documented one-off is run. Guatemala does not need
that trade-off, so it does not make it.

Two properties of the source shape this connector:

1. **Two rates per day.** ``venta`` is the rate at which the bank sells US
   dollars and ``compra`` the rate at which it buys them — both stated from the
   bank's side. They differ on 6,174 of 13,364 days, so REIM publishes both as
   separate series rather than collapsing them.
2. **The pair inverted during the 1990-91 liberalisation.** On 84 days the buy
   rate sat fixed at ``5.15`` while the sell rate floated as low as ``4.62``.
   That is real history, so the ``sell >= buy`` check only applies from
   :data:`SPREAD_ENFORCED_FROM_YEAR`.

Dates are ``dd/mm/yyyy`` in both directions: ``08/11/1990`` is 8 November.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import ClassVar
from xml.etree import ElementTree

from reim.core.constants import Frequency
from reim.core.exceptions import TransformationError
from reim.domain.observations.periods import parse_period
from reim.domain.pipelines.models import (
    NormalizedObservation,
    QualityResult,
    RawDataset,
)
from reim.ingestion.base import BaseConnector

SOAP_NAMESPACE = "http://www.banguat.gob.gt/variables/ws/"
SOAP_ACTION = f"{SOAP_NAMESPACE}TipoCambioRango"
SOAP_ENVELOPE_NS = "http://schemas.xmlsoap.org/soap/envelope/"

#: Earliest day Banguat publishes.
START_DATE = date(1990, 1, 1)

#: The buy rate exceeded the sell rate on 84 days in 1990 and 1991, while the
#: quetzal was being liberalised. Enforcing the spread over that stretch would
#: fail on every run, so the check starts after it.
SPREAD_ENFORCED_FROM_YEAR = 1992

#: XML tag, REIM indicator code, and the side label recorded for provenance.
SIDES: tuple[tuple[str, str, str], ...] = (
    ("compra", "gt_exchange_rate_official_daily_buy", "buy"),
    ("venta", "gt_exchange_rate_official_daily_sell", "sell"),
)

_DDMMYYYY = re.compile(r"^(?P<day>\d{2})/(?P<month>\d{2})/(?P<year>\d{4})$")

_SOAP_ENVELOPE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<soap:Envelope xmlns:soap="{envelope_ns}">'
    "<soap:Body>"
    '<TipoCambioRango xmlns="{namespace}">'
    "<fechainit>{start}</fechainit><fechafin>{end}</fechafin>"
    "</TipoCambioRango>"
    "</soap:Body></soap:Envelope>"
)


def _utc_today() -> date:
    """Return today's UTC date. Indirected so tests can pin it."""
    return datetime.now(UTC).date()


class BanguatExchangeRate(BaseConnector):
    """Daily GTQ/USD buy and sell rates from the Banco de Guatemala."""

    connector_key = "banguat_exchange_rate"
    version = "1.0.0"
    expected_frequency = Frequency.DAILY
    country_iso3: ClassVar[str] = "GTM"
    unit: ClassVar[str] = "GTQ per USD"
    currency_code: ClassVar[str] = "GTQ"

    async def extract(self) -> RawDataset:
        """Not yet implemented; see Task 5 of the implementation plan."""
        raise NotImplementedError

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Turn each published day into one buy and one sell observation.

        Pure function of ``raw``.

        Raises:
            TransformationError: The payload is not XML text, the envelope is
                malformed or carries a SOAP fault, a date or rate cannot be
                read, or one day arrives twice with different values.
        """
        if not isinstance(raw.payload, str):
            msg = "Banguat payload must be the response XML text"
            raise TransformationError(msg, source_key=self.source.key)

        root = self._parse_envelope(raw.payload)

        values: dict[tuple[date, str], Decimal] = {}
        monedas: dict[date, str] = {}
        for node in root.iter("Var"):
            day = self._read_date(node.findtext("fecha"))
            monedas[day] = (node.findtext("moneda") or "").strip()
            for tag, _code, side in SIDES:
                value = self._read_decimal(node.findtext(tag), tag, day)
                previous = values.get((day, side))
                if previous is not None and previous != value:
                    msg = (
                        f"Banguat returned {day.isoformat()} {side} with two "
                        f"different values: {previous} and {value}"
                    )
                    raise TransformationError(msg, source_key=self.source.key)
                values[(day, side)] = value

        observations = [
            NormalizedObservation(
                country_iso3=self.country_iso3,
                indicator_code=code,
                source_key=self.source.key,
                period=parse_period(day.isoformat(), Frequency.DAILY),
                unit=self.unit,
                currency_code=self.currency_code,
                value_numeric=values[(day, side)],
                retrieved_at=raw.retrieved_at,
                source_url=raw.source_url,
                source_record_id=f"tc_rango:{day.isoformat()}:{side}",
                raw_metadata={
                    "banguat_operation": "TipoCambioRango",
                    "banguat_moneda": monedas.get(day, ""),
                    "banguat_side": side,
                },
            )
            for _tag, code, side in SIDES
            for day in sorted({d for d, s in values if s == side})
        ]

        observations.sort(key=lambda obs: (obs.indicator_code, obs.period.start))
        self.logger.info(
            "banguat.transformed",
            observations=len(observations),
            days=len({obs.period.label for obs in observations}),
        )
        return observations

    def _parse_envelope(self, xml: str) -> ElementTree.Element:
        """Parse the SOAP envelope, surfacing a fault as a transformation error."""
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError as exc:
            msg = f"Banguat returned malformed XML: {exc}"
            raise TransformationError(msg, source_key=self.source.key) from exc

        fault = root.find(f".//{{{SOAP_ENVELOPE_NS}}}Fault")
        if fault is not None:
            detail = (fault.findtext("faultstring") or "no faultstring").strip()
            msg = f"Banguat returned a SOAP fault: {detail}"
            raise TransformationError(msg, source_key=self.source.key)
        return root

    def _read_date(self, raw_value: str | None) -> date:
        """Read Banguat's ``dd/mm/yyyy``, which is day-first."""
        text = (raw_value or "").strip()
        match = _DDMMYYYY.match(text)
        if match is None:
            msg = f"Banguat returned an unparseable date {text!r}"
            raise TransformationError(msg, source_key=self.source.key)
        try:
            return date(int(match["year"]), int(match["month"]), int(match["day"]))
        except ValueError as exc:
            msg = f"Banguat returned an impossible date {text!r}"
            raise TransformationError(msg, source_key=self.source.key) from exc

    def _read_decimal(self, raw_value: str | None, tag: str, day: date) -> Decimal:
        """Build a Decimal from the published string, never through float."""
        text = (raw_value or "").strip()
        try:
            return Decimal(text)
        except InvalidOperation as exc:
            msg = f"Banguat returned a non-numeric {tag} {text!r} for {day.isoformat()}"
            raise TransformationError(msg, source_key=self.source.key) from exc

    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Not yet implemented; see Task 4 of the implementation plan."""
        raise NotImplementedError
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_banguat_connector.py -q`
Expected: PASS, 12 tests.

- [ ] **Step 5: Gate and commit**

Run each check on its own and read its exit code:

```bash
.venv/bin/ruff check .            ; echo "ruff: $?"
.venv/bin/ruff format --check .   ; echo "format: $?"
.venv/bin/mypy reim apps          ; echo "mypy: $?"
.venv/bin/python -m pytest -q     ; echo "pytest: $?"
```

```bash
git add reim/ingestion/connectors/guatemala/banguat_exchange_rate.py tests/unit/test_banguat_connector.py
git commit -m "feat(banguat): parse TipoCambioRango into buy and sell series

Each published day becomes two observations. Dates are day-first, so
08/11/1990 is 8 November; reading it the other way would have silently
scrambled 36 years of history."
```

---

### Task 4: `validate`

**Files:**
- Modify: `reim/ingestion/connectors/guatemala/banguat_exchange_rate.py`
- Test: `tests/unit/test_banguat_connector.py`

**Interfaces:**
- Consumes: `transform`, `SIDES` and `SPREAD_ENFORCED_FROM_YEAR` from Task 3.
- Produces: `validate(observations) -> list[QualityResult]` returning exactly three checks named `banguat_both_sides_present`, `banguat_sell_not_below_buy`, `banguat_calendar_gaps`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_banguat_connector.py`:

```python
from reim.core.constants import CheckSeverity, CheckStatus
from reim.domain.pipelines.models import QualityResult


def results_by_name(results: list[QualityResult]) -> dict[str, QualityResult]:
    return {r.check_name: r for r in results}


def test_validate_returns_the_three_source_checks(banguat_rango_xml: str) -> None:
    connector = build_connector()
    observations = connector.transform(raw_from(banguat_rango_xml))

    assert set(results_by_name(connector.validate(observations))) == {
        "banguat_both_sides_present",
        "banguat_sell_not_below_buy",
        "banguat_calendar_gaps",
    }


def test_validate_passes_on_the_recorded_response(banguat_rango_xml: str) -> None:
    """The 84 inverted rows of 1990-91 must not fail the run."""
    connector = build_connector()
    observations = connector.transform(raw_from(banguat_rango_xml))

    assert [r for r in connector.validate(observations) if r.failed] == []


def test_a_missing_side_is_critical(banguat_rango_xml: str) -> None:
    connector = build_connector()
    observations = [
        obs
        for obs in connector.transform(raw_from(banguat_rango_xml))
        if obs.indicator_code != "gt_exchange_rate_official_daily_buy"
    ]

    check = results_by_name(connector.validate(observations))["banguat_both_sides_present"]

    assert check.status is CheckStatus.FAILED
    assert check.severity is CheckSeverity.CRITICAL


def test_the_1990_inversions_are_tolerated(banguat_rango_xml: str) -> None:
    """84 days in 1990-91 publish a buy rate above the sell rate."""
    connector = build_connector()
    observations = connector.transform(raw_from(banguat_rango_xml))

    check = results_by_name(connector.validate(observations))["banguat_sell_not_below_buy"]

    assert check.status is CheckStatus.PASSED
    assert str(SPREAD_ENFORCED_FROM_YEAR) in check.message


def test_an_inversion_after_the_threshold_is_an_error(banguat_rango_xml: str) -> None:
    connector = build_connector()
    observations = connector.transform(raw_from(banguat_rango_xml))
    modern_sell = next(
        obs
        for obs in observations
        if obs.indicator_code == "gt_exchange_rate_official_daily_sell"
        and obs.period.start.year >= 2020
    )
    modern_sell.value_numeric = Decimal("0.01")

    check = results_by_name(connector.validate(observations))["banguat_sell_not_below_buy"]

    assert check.status is CheckStatus.FAILED
    assert check.severity is CheckSeverity.ERROR
    assert modern_sell.period.label in check.message


def test_the_gap_check_reports_the_five_missing_days(banguat_rango_xml: str) -> None:
    """Five days are absent across 36 years; that is the source's history."""
    connector = build_connector()
    observations = connector.transform(raw_from(banguat_rango_xml))

    check = results_by_name(connector.validate(observations))["banguat_calendar_gaps"]

    assert check.status is CheckStatus.PASSED
    assert check.actual_value == "5"
```

Add `SPREAD_ENFORCED_FROM_YEAR` to the module import at the top of the file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_banguat_connector.py -q`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement `validate`**

First widen the constants import, which Task 3 deliberately left minimal because
`ruff` fails the build on an unused import:

```python
from reim.core.constants import CheckSeverity, CheckType, Frequency
```

Then replace the placeholder `validate` with:

```text
    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert Banguat-specific expectations beyond the standard battery."""
        return [
            self._check_both_sides_present(observations),
            self._check_sell_not_below_buy(observations),
            self._check_calendar_gaps(observations),
        ]

    def _check_both_sides_present(
        self, observations: list[NormalizedObservation]
    ) -> QualityResult:
        """Both published rates must arrive, or half the source was dropped."""
        expected = {code for _tag, code, _side in SIDES}
        found = {obs.indicator_code for obs in observations}
        missing = sorted(expected - found)

        if not missing:
            return QualityResult.passed(
                "banguat_both_sides_present",
                CheckType.COMPLETENESS,
                "Both the buy and the sell series received data",
                expected_value=str(sorted(expected)),
                actual_value=str(sorted(found)),
            )
        return QualityResult.failure(
            "banguat_both_sides_present",
            CheckType.COMPLETENESS,
            CheckSeverity.CRITICAL,
            f"No data parsed for: {', '.join(missing)}",
            expected_value=str(sorted(expected)),
            actual_value=str(sorted(found)),
        )

    def _check_sell_not_below_buy(
        self, observations: list[NormalizedObservation]
    ) -> QualityResult:
        """From 1992 the sell rate must sit at or above the buy rate.

        Not before: through the 1990-91 liberalisation Banguat held the buy
        rate at 5.15 while the sell rate floated as low as 4.62, so 84 real
        days invert the spread. Enforcing it over them would fail every run
        forever — the same reasoning that makes ``inide_cpi_monthly`` enforce
        continuity only from 2011.
        """
        sell = {
            obs.period.start: obs.value_numeric
            for obs in observations
            if obs.indicator_code == "gt_exchange_rate_official_daily_sell"
        }
        buy = {
            obs.period.start: obs.value_numeric
            for obs in observations
            if obs.indicator_code == "gt_exchange_rate_official_daily_buy"
        }

        inverted: list[date] = []
        checked = 0
        for day, sell_value in sell.items():
            buy_value = buy.get(day)
            if (
                day.year < SPREAD_ENFORCED_FROM_YEAR
                or sell_value is None
                or buy_value is None
            ):
                continue
            checked += 1
            if sell_value < buy_value:
                inverted.append(day)

        if not inverted:
            return QualityResult.passed(
                "banguat_sell_not_below_buy",
                CheckType.CONSISTENCY,
                f"Sell at or above buy on all {checked} day(s) from "
                f"{SPREAD_ENFORCED_FROM_YEAR}; earlier inversions are the "
                f"published history of the 1990-91 liberalisation",
                expected_value="0",
                actual_value="0",
            )

        inverted.sort()
        shown = ", ".join(day.isoformat() for day in inverted[:5])
        suffix = f" (+{len(inverted) - 5} more)" if len(inverted) > 5 else ""
        return QualityResult.failure(
            "banguat_sell_not_below_buy",
            CheckType.CONSISTENCY,
            CheckSeverity.ERROR,
            f"{len(inverted)} of {checked} day(s) from {SPREAD_ENFORCED_FROM_YEAR} "
            f"have sell below buy: {shown}{suffix}",
            expected_value="0",
            actual_value=str(len(inverted)),
        )

    def _check_calendar_gaps(
        self, observations: list[NormalizedObservation]
    ) -> QualityResult:
        """Report days Banguat does not publish, without calling them a fault.

        Five days are missing across the whole series. Reporting the count
        keeps a widening hole visible without failing on the source's own
        history.
        """
        days = {obs.period.start for obs in observations}
        if len(days) < 2:
            return QualityResult.passed(
                "banguat_calendar_gaps",
                CheckType.COMPLETENESS,
                "Too few days to assess gaps",
                actual_value=str(len(days)),
            )

        first, last = min(days), max(days)
        span = (last - first).days + 1
        missing = span - len(days)
        return QualityResult.passed(
            "banguat_calendar_gaps",
            CheckType.COMPLETENESS,
            f"{missing} calendar day(s) unpublished between {first} and {last}, "
            f"out of {span}",
            expected_value=f"{span} days",
            actual_value=str(missing),
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_banguat_connector.py -q`
Expected: PASS, 18 tests.

- [ ] **Step 5: Gate and commit**

```bash
.venv/bin/ruff check .            ; echo "ruff: $?"
.venv/bin/ruff format --check .   ; echo "format: $?"
.venv/bin/mypy reim apps          ; echo "mypy: $?"
.venv/bin/python -m pytest -q     ; echo "pytest: $?"
```

```bash
git add reim/ingestion/connectors/guatemala/banguat_exchange_rate.py tests/unit/test_banguat_connector.py
git commit -m "feat(banguat): source-specific quality checks

The spread check starts in 1992 on purpose: 84 days in 1990-91 publish a
buy rate above the sell rate, because the quetzal was being liberalised.
Asserting the invariant unconditionally would have failed every run
forever. Gaps are reported at info — five days are missing in 36 years,
and that is the source's history, not a fault."
```

---

### Task 5: `extract`

**Files:**
- Modify: `reim/ingestion/connectors/guatemala/banguat_exchange_rate.py`
- Test: `tests/unit/test_banguat_connector.py`

**Interfaces:**
- Consumes: `_utc_today`, `START_DATE`, `_SOAP_ENVELOPE`, `SOAP_ACTION` from Task 3.
- Produces: `extract() -> RawDataset` whose `payload` is the response **text** Task 3's `transform` consumes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_banguat_connector.py`:

```python
import httpx
import respx

from reim.core.exceptions import ExtractionError
from reim.ingestion.connectors.guatemala import banguat_exchange_rate


@pytest.fixture
def pinned_today(monkeypatch: pytest.MonkeyPatch) -> date:
    """Pin the connector's notion of today so the request is deterministic."""
    today = date(2026, 8, 8)
    monkeypatch.setattr(banguat_exchange_rate, "_utc_today", lambda: today)
    return today


@respx.mock
async def test_extract_requests_the_whole_series(
    banguat_rango_xml: str, pinned_today: date
) -> None:
    route = respx.post(SOAP_URL).mock(
        return_value=httpx.Response(
            200, text=banguat_rango_xml, headers={"Content-Type": "text/xml; charset=utf-8"}
        )
    )

    raw = await build_connector().extract()

    assert route.call_count == 1
    assert raw.http_status == 200
    assert raw.payload == banguat_rango_xml
    body = route.calls.last.request.content.decode("utf-8")
    assert "<fechainit>01/01/1990</fechainit>" in body
    assert "<fechafin>08/08/2026</fechafin>" in body


@respx.mock
async def test_extract_sends_the_documented_soap_contract(
    banguat_rango_xml: str, pinned_today: date
) -> None:
    route = respx.post(SOAP_URL).mock(return_value=httpx.Response(200, text=banguat_rango_xml))

    await build_connector().extract()
    request = route.calls.last.request

    assert (
        request.headers["SOAPAction"] == '"http://www.banguat.gob.gt/variables/ws/TipoCambioRango"'
    )
    assert request.headers["Content-Type"] == "text/xml; charset=utf-8"
    assert '<TipoCambioRango xmlns="http://www.banguat.gob.gt/variables/ws/">' in (
        request.content.decode("utf-8")
    )


@respx.mock
async def test_extract_raises_on_an_error_status(pinned_today: date) -> None:
    respx.post(SOAP_URL).mock(return_value=httpx.Response(404, text="not found"))

    with pytest.raises(ExtractionError, match="HTTP 404"):
        await build_connector().extract()


@respx.mock
async def test_extract_rejects_a_non_xml_response(pinned_today: date) -> None:
    respx.post(SOAP_URL).mock(
        return_value=httpx.Response(200, text="{}", headers={"Content-Type": "application/json"})
    )

    with pytest.raises(ExtractionError, match="xml"):
        await build_connector().extract()


@pytest.mark.live
async def test_live_service_answers_the_documented_contract() -> None:
    """Opt-in: hits the real Banguat service. Run with `pytest -m live`."""
    connector = build_connector()

    raw = await connector.extract()
    observations = connector.transform(raw)

    assert len(observations) > 20000
    assert {obs.indicator_code for obs in observations} == {
        "gt_exchange_rate_official_daily_buy",
        "gt_exchange_rate_official_daily_sell",
    }
    assert [r for r in connector.validate(observations) if r.failed] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_banguat_connector.py -k extract -q`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement `extract`**

Add the HTTP import to the module's import block:

```python
from reim.ingestion.http import ensure_ok, http_client, post
```

and `ExtractionError` to the exceptions import:

```python
from reim.core.exceptions import ExtractionError, TransformationError
```

Replace the placeholder `extract` with:

```text
    async def extract(self) -> RawDataset:
        """Fetch the whole series in one ``TipoCambioRango`` call.

        Raises:
            ExtractionError: The service was unreachable, returned an error
                status, or answered with something other than XML.
        """
        end = _utc_today()
        url = str(self.source.base_url)
        body = _SOAP_ENVELOPE.format(
            envelope_ns=SOAP_ENVELOPE_NS,
            namespace=SOAP_NAMESPACE,
            start=START_DATE.strftime("%d/%m/%Y"),
            end=end.strftime("%d/%m/%Y"),
        )
        retrieved_at = datetime.now(UTC)

        async with http_client() as client:
            response = await post(
                client,
                url,
                content=body.encode("utf-8"),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": f'"{SOAP_ACTION}"',
                },
            )
            ensure_ok(response, expected_content_type="xml")
            payload = response.text

        self.logger.info("banguat.extracted", start=START_DATE.isoformat(), end=end.isoformat())
        return RawDataset(
            source_key=self.source.key,
            retrieved_at=retrieved_at,
            source_url=url,
            payload=payload,
            content_type=response.headers.get("content-type"),
            http_status=response.status_code,
            metadata={
                "operation": "TipoCambioRango",
                "start": START_DATE.isoformat(),
                "end": end.isoformat(),
            },
        )
```

`SOAPAction` is sent **quoted**, matching what the live service was verified
against.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_banguat_connector.py -q`
Expected: PASS, 22 tests run; the 23rd is the `live` one, deselected.

- [ ] **Step 5: Run the live test**

Run: `.venv/bin/python -m pytest tests/unit/test_banguat_connector.py -m live -q`
Expected: PASS against the real service.

- [ ] **Step 6: Gate and commit**

```bash
.venv/bin/ruff check .            ; echo "ruff: $?"
.venv/bin/ruff format --check .   ; echo "format: $?"
.venv/bin/mypy reim apps          ; echo "mypy: $?"
.venv/bin/python -m pytest -q     ; echo "pytest: $?"
```

```bash
git add reim/ingestion/connectors/guatemala/banguat_exchange_rate.py tests/unit/test_banguat_connector.py
git commit -m "feat(banguat): fetch the whole series in one request

1990 to today in a single TipoCambioRango call, about 1.3 MB. No routine
window and no backfill mode, so a rebuild from an empty database is
complete by default."
```

---

### Task 6: Enable the source, verify end to end and document

**Files:**
- Modify: `sources/catalog.yml`, `docs/sources.md`, `docs/implementation-plan.md`, `ROADMAP.md`, `README.md`
- Test: `tests/unit/test_catalog.py`

- [ ] **Step 1: Add the catalog entry**

Append to `sources/catalog.yml`:

```yaml
  # ------------------------------------------------------------------------
  # Guatemala — Banco de Guatemala
  #
  # REIM's first national primary source outside Nicaragua. One SOAP call
  # returns the whole 1990-onward series, so this connector has no backfill
  # mode. See docs/sources.md.
  # ------------------------------------------------------------------------
  - key: banguat_exchange_rate
    name: Guatemala official exchange rate (daily)
    description: >-
      Official GTQ/USD buy and sell rates published for each day by the Banco
      de Guatemala through its public SOAP service, covering January 1990
      onwards.
    country: GT
    organization: BANGUAT
    category: exchange_rate
    access_type: soap
    frequency: daily
    format: xml
    base_url: https://www.banguat.gob.gt/variables/ws/TipoCambio.asmx
    documentation_url: https://www.banguat.gob.gt/variables/ws/TipoCambio.asmx?WSDL
    connector: reim.ingestion.connectors.guatemala.banguat_exchange_rate
    indicators:
      - gt_exchange_rate_official_daily_buy
      - gt_exchange_rate_official_daily_sell
    license: public_official_data
    official: true
    enabled: true
```

- [ ] **Step 2: Add the catalog test**

Add to `tests/unit/test_catalog.py`:

```python
def test_banguat_publishes_both_sides_of_the_rate(catalog: SourceCatalog) -> None:
    """Guatemala's pair is two series, because the source publishes two."""
    entry = catalog.get("banguat_exchange_rate")

    assert entry.country == "GT"
    assert entry.organization == "BANGUAT"
    assert set(entry.indicators) == {
        "gt_exchange_rate_official_daily_buy",
        "gt_exchange_rate_official_daily_sell",
    }
```

- [ ] **Step 3: Validate and run the suite**

Run: `.venv/bin/reim catalog validate`
Expected: **15 sources, 15 enabled**, 21 rule sets, all 15 connectors import.

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 4: Run against a real database**

```bash
make db-up CONTAINER_ENGINE=podman
export REIM_DATABASE_URL="postgresql+psycopg://reim:reim@localhost:55432/reim"
.venv/bin/alembic upgrade head
.venv/bin/reim db seed
.venv/bin/reim pipeline run banguat_exchange_rate
```

Expected: status `success`, **26,728 observations**, 0 rejected. Seeding creates
one organization and two indicators. This machine has no Docker daemon;
`CONTAINER_ENGINE=podman` is required.

- [ ] **Step 5: Prove idempotency**

Run: `.venv/bin/reim pipeline run banguat_exchange_rate`
Expected: 0 inserted, 0 updated, 26,728 unchanged.

- [ ] **Step 6: Check the stored pair**

```bash
podman exec reim-test-postgres psql -U reim -d reim -t -A -F' | ' -c \
"SELECT i.code, count(*), min(o.period_label), max(o.period_label),
        round(min(o.value_numeric), 5) AS lowest, round(max(o.value_numeric), 5) AS highest
   FROM observations o JOIN indicators i ON i.id = o.indicator_id
  WHERE i.code LIKE 'gt_exchange_rate%'
  GROUP BY i.code ORDER BY i.code;"
```

Expected: two rows of 13,364 observations each, spanning `1990-01-01` to the
latest published day, with a lowest near `3.4` and a highest near `8.4`. The two
rows must **not** be identical — that would mean one side was written twice.

- [ ] **Step 7: Check the quality checks**

```bash
podman exec reim-test-postgres psql -U reim -d reim -t -A -F' | ' -c \
"SELECT check_name, status, actual_value FROM data_quality_checks
  WHERE check_name LIKE 'banguat%' ORDER BY created_at DESC LIMIT 3;"
podman exec reim-test-postgres psql -U reim -d reim -t -A -c \
"SELECT count(*) FROM data_quality_checks WHERE status='failed' AND severity IN ('error','critical');"
```

Expected: the three Banguat checks present and passing, the gap check reporting
`5`, and 0 failures at `error` or `critical`.

- [ ] **Step 8: Update the documentation**

`docs/sources.md` — add a Banguat section recording: the endpoint, operation and
day-first date format; that one request returns 13,364 days from 1990; that the
source publishes a buy and a sell rate which differ on 6,174 days, hence two
indicators; that 84 days in 1990-91 invert the spread and why, so the check
starts in 1992; and the five missing days. Then add a short subsection on the
**other five central banks**, recording exactly what was probed and found:
BCCR `503` on both URL casings and known to need an account; BCR, BCH, INEC and
the Central Bank of Belize reachable but with no machine-readable endpoint
located. None is behind a bot wall.

`docs/implementation-plan.md` — add `## 17. Post-MVP increment — Banguat daily
exchange rate (2026-08-08)` with a verification table covering Steps 3-7, and
record that piece C now has one of six countries delivered.

`ROADMAP.md` — under v0.3.0, split the national-central-banks bullet: Guatemala
done, the other five with their measured state.

`README.md` — add Banguat to the data table as a Guatemalan national primary
source; note in the rebuild section that Banguat, like INIDE and the IMF, ships
its full history in the routine run, so only the BCN needs the one-off.

- [ ] **Step 9: Final gate and commit**

```bash
export REIM_TEST_DATABASE_URL="postgresql+psycopg://reim:reim@localhost:55432/reim"
.venv/bin/python -m pytest -q     ; echo "pytest: $?"
.venv/bin/ruff check .            ; echo "ruff: $?"
.venv/bin/ruff format --check .   ; echo "format: $?"
.venv/bin/mypy reim apps          ; echo "mypy: $?"
.venv/bin/reim catalog validate   ; echo "catalog: $?"
```

```bash
git add sources/catalog.yml docs/ ROADMAP.md README.md tests/unit/test_catalog.py
git commit -m "feat(banguat): enable Guatemala's daily exchange rate

26,728 observations over 36 years, REIM's first national primary source
outside Nicaragua. Records what probing the other five central banks
found, so the next person does not repeat it."
podman stop reim-test-postgres
```

---

## Self-review notes

**Spec coverage.** §2 the source → Tasks 3 and 5; §3 G1 → Task 1's two indicators and `SIDES`; G2 → the `gt_` prefix; G3 → Task 5's single request with no window option; G4 → Task 1 Step 3; G5 → Task 4's `SPREAD_ENFORCED_FROM_YEAR`; G6 → Task 4's gap check at `info`; §4 both corrections → Task 4's threshold and gap check, with tests that pin them; §5.1 → Task 1 Step 3; §5.2 → Task 1 Step 4; §5.3 → Task 1 Step 5; §5.4 → Tasks 3-5; §5.5 → Task 6 Step 1; §5.6 → Task 6 Step 8; §6 testing → Tasks 3-5; §7 → Task 6 Step 4; §8 out of scope — nothing here touches the other currencies, operations or central banks.

**Everything asserted was measured, not estimated:** 13,364 rows and 26,728 observations; 6,174 days where the pair differs; sell `3.41332` and buy `3.4081` on 1990-01-01; sell `4.62181` against buy `5.15` on 1990-11-08; sell `7.62415` on 2026-07-01; 84 inversions, 76 in 1990 and 8 in 1991; five missing days; `text/xml; charset=utf-8`; 1.33 MB compressing to 90 KB.

**Two hazards a reviewer should check rather than assume.**

- **Day-first dates.** `08/11/1990` is 8 November. Reading it month-first would silently scramble the series without failing anything, so `test_transform_converts_the_day_first_date` pins a date whose two readings differ and asserts the value that belongs to the November one.
- **The two sides must not be written from the same tag.** A copy-paste error would give both indicators identical values and every count would still match. `test_transform_keeps_the_pair_distinct` asserts exactly 6,174 differing days, and Task 6 Step 6 repeats the check against stored data.

**On the gate commands.** Each is run separately with its exit code printed, rather than chained. Chaining has failed in this repository three separate ways — `| tail` masking the status, one-per-line without `set -e`, and `set -e` not aborting — and each time a broken gate reached a commit.
