# Currency conversion on `/compare` — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `GET /api/v1/compare?...&convert_to=USD` returns a dollar figure beside
every published figure, carrying the rate that produced it, without ever
replacing the original.

**Architecture:** Conversion is computed at request time from rates already
stored as ordinary observations. A new pure-domain module holds the rules and
the arithmetic; the repository gains one page-scoped rate query; the router
wires them together behind an opt-in query parameter. No derived row is ever
written, and no existing response changes when the parameter is absent.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2, Pydantic v2, pytest.
Run tools as `.venv/bin/<tool>` — there is no `pip` in the venv. Integration
tests need `make db-up CONTAINER_ENGINE=podman` and
`REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim`.

**Spec:** `docs/superpowers/specs/2026-09-06-currency-conversion-design.md`
(increment B is section 4 onward; sections 6.4–6.6 are its components)

## Scope

Increment A shipped on 2026-09-06 — the rate series is live, 2,749
observations. This plan builds **only** the converted view.

## Global Constraints

* **No derived row is ever written to `observations`** (D2). This plan adds no
  writes and no migration.
* **Conversion keys on the observation's own `currency_code`, never on the
  country** (D3). El Salvador's monetary rows carry `USD` and must pass through
  untouched; converting them at CEPAL's 8.8 colón rate understates them
  ninefold, silently.
* **Exact period match only** (D7). No nearest rate, no carry-forward, no
  annual average standing in for a month.
* **`comparable` is unaffected by conversion** (D8) — it describes what the
  publisher published.
* **When `convert_to` is absent the response gains no keys at all**, not even
  null ones (§6.6).
* **The two refusals return different status codes** (D6): an unsupported
  target is **422** from FastAPI's `Literal` validation; a non-convertible
  indicator is **400** `invalid_request` via `InvalidRequestError`.
* Constants, fixed here so every task uses the same strings:
  `TARGET_CURRENCY = "USD"`, `RATE_INDICATOR_CODE =
  "exchange_rate_nominal_monthly"`, `RATE_BASIS = "monthly average"`,
  `QUANTUM = Decimal("0.01")`.

---

### Task 1: Declare which indicators may be converted

**Files:**
- Modify: `reim/domain/indicators/registry.py`
- Modify: `sources/catalog.yml`
- Test: `tests/unit/test_catalog.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `IndicatorDefinition.currency_convertible: bool`, defaulting to
  `False`, `True` on `money_m1_monthly`, `money_m2_monthly` and
  `money_m3_monthly` only.

**The flag lives in the registry and nowhere else.** `reim/services/seeding.py`
copies a fixed list of columns into the `indicators` table and this is not one
of them, deliberately: it is a static property of the concept, not data, so it
needs no column and no Alembic migration. Task 6 therefore looks it up by code
rather than reading it off the ORM row the router already has.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_catalog.py`:

```python
def test_only_the_monetary_aggregates_are_convertible() -> None:
    """The flag is an allow-list, asserted whole so an addition is deliberate."""
    convertible = {i.code for i in INDICATORS if i.currency_convertible}

    assert convertible == {"money_m1_monthly", "money_m2_monthly", "money_m3_monthly"}


def test_a_rate_indicator_is_not_convertible() -> None:
    """The trap D5 exists for: 36.8 NIO *per USD* divided by 36.8 is 1.00."""
    for code in ("exchange_rate_nominal_monthly", "ni_exchange_rate_official_daily"):
        assert INDICATORS_BY_CODE[code].currency_convertible is False


def test_dollar_indicators_are_not_convertible_either() -> None:
    """Converting USD to USD is a no-op, but declaring it convertible is a claim."""
    assert INDICATORS_BY_CODE["gdp_current_usd_annual"].currency_convertible is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog.py -k convertible -v`
Expected: FAIL — `AttributeError: 'IndicatorDefinition' object has no attribute 'currency_convertible'`.

- [ ] **Step 3: Add the field**

In `reim/domain/indicators/registry.py`, add to `IndicatorDefinition` after
`seasonal_adjustment`, keeping every existing entry valid by defaulting it:

```text
    #: Whether this indicator's values are amounts denominated in a currency
    #: and may therefore be converted into another one. False for rates,
    #: indices and ratios, which are expressed *per* a currency rather than
    #: *in* it — see the currency-conversion design, decision D5.
    currency_convertible: bool = False
```

`is_active: bool = True` must stay last or move with it; dataclass fields with
defaults may be reordered freely among themselves, but check the file compiles.

- [ ] **Step 4: Set it on the three monetary indicators**

Add `currency_convertible=True,` to the `money_m1_monthly`, `money_m2_monthly`
and `money_m3_monthly` entries, and delete the clause that stops being true.
In `money_m1_monthly`'s description replace:

```text
            "currency, so values are not comparable across countries without "
            "a conversion REIM does not perform."
```

with:

```text
            "currency, so values are not comparable across countries as "
            "published. `/compare?convert_to=USD` returns a converted view "
            "beside the published figures, never in place of them."
```

`money_m2_monthly` and `money_m3_monthly` refer to `money_m1_monthly` for the
currency caveat rather than repeating it; read them and adjust only if they
carry the same clause verbatim.

- [ ] **Step 5: Update the catalog description that says the same thing**

`sources/catalog.yml`, entry `cepalstat_monetary_monthly`, contains "so the
series are not comparable across countries without a conversion REIM does not
perform." Replace the tail with "so the series are not comparable across
countries as published; `/compare` can return a converted view beside them."

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add reim/domain/indicators/registry.py sources/catalog.yml tests/unit/test_catalog.py
git commit -m "feat(compare): declare which indicators may be converted"
```

---

### Task 2: Carry each cell's own currency

**Files:**
- Modify: `reim/repositories/comparison.py`
- Test: `tests/integration/test_comparison_repository.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ComparisonCell.currency_code: str | None`, populated by
  `fetch_comparison_cells`.

This is D12. Without it D3 is not implementable: the cell carries only a value
today, and `SeriesSummary.currency_codes` is a **tuple** precisely because one
country's series may hold more than one currency over time.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_comparison_repository.py`, following the fixture
style already in that file:

```python
def test_cells_carry_their_own_currency(session, make_observation) -> None:  # type: ignore[no-untyped-def]
    """Not the country's currency — the observation's, which can differ."""
    from reim.services.observation_writer import write_observations

    write_observations(
        session,
        [
            make_observation(
                "2024-01",
                "100",
                indicator_code="exports_goods_monthly",
                source_key="imf_imts_nicaragua",
                country_iso3="NIC",
                unit="current USD",
                currency_code="USD",
            )
        ],
        connector_version="1.0.0",
    )
    session.commit()

    country = get_country_by_iso3(session, "NIC")
    assert country is not None
    cells = fetch_comparison_cells(
        session,
        ComparisonQuery(indicator_code="exports_goods_monthly", country_ids=(country.id,)),
        limit=10,
        offset=0,
    )

    assert [cell.currency_code for cell in cells] == ["USD"]
```

Import whatever of `get_country_by_iso3`, `ComparisonQuery` and
`fetch_comparison_cells` the file does not already import, and match its
existing fixture names — read the file first rather than assuming `session`.

- [ ] **Step 2: Run test to verify it fails**

Run: `REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/python -m pytest tests/integration/test_comparison_repository.py -k currency -v`
Expected: FAIL — `TypeError` or `AttributeError` on `currency_code`.

- [ ] **Step 3: Add the field and select it**

In `reim/repositories/comparison.py`, add to `ComparisonCell`:

```text
    country_iso3: str
    value_numeric: Decimal | None
    #: The observation's own currency, not the country's. Two countries can
    #: report one indicator in different currencies, and one country's series
    #: can change currency over time; conversion keys on this.
    currency_code: str | None
```

In `fetch_comparison_cells`, add `Observation.currency_code` to the `select`
after `Observation.value_numeric`, and pass `currency_code=row[5]` when building
each `ComparisonCell`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/python -m pytest tests/integration/test_comparison_repository.py -q`
Expected: PASS, all tests in the file.

- [ ] **Step 5: Commit**

```bash
git add reim/repositories/comparison.py tests/integration/test_comparison_repository.py
git commit -m "feat(compare): carry each cell's own currency"
```

---

### Task 3: The conversion rules, as pure functions

**Files:**
- Create: `reim/domain/conversion.py`
- Test: `tests/unit/test_conversion.py`

**Interfaces:**
- Consumes: Task 1's `currency_convertible`.
- Produces: `TARGET_CURRENCY`, `RATE_INDICATOR_CODE`, `RATE_BASIS`, `QUANTUM`,
  `CAVEATS`; `ConvertedCell(value, rate, basis)`;
  `ConversionSummary(target_currency, rate_indicator_code, rate_source_key,
  basis, converted, already_at_target, no_rate, caveats)`;
  `ensure_convertible(definition) -> None`;
  `convert(value, currency_code, rate) -> ConvertedCell`;
  `summarise(pairs, rate_source_key) -> ConversionSummary`, where each pair is
  `(published_value, ConvertedCell)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_conversion.py`:

```python
"""Conversion rules. No database, no network — pure logic."""

from __future__ import annotations

from decimal import Decimal

import pytest

from reim.core.exceptions import InvalidRequestError
from reim.domain.conversion import (
    ConvertedCell,
    convert,
    ensure_convertible,
    summarise,
)
from reim.domain.indicators.registry import INDICATORS_BY_CODE


def test_a_figure_already_in_dollars_passes_through_untouched() -> None:
    """The regression test for the ninefold error.

    El Salvador's M1 carries `USD` while CEPAL still quotes the country at 8.8
    colones per dollar. Converting on the country rather than the observation
    would divide an already-dollar figure by 8.8 and look plausible doing it.
    """
    cell = convert(Decimal("9482300000"), "USD", Decimal("8.8"))

    assert cell == ConvertedCell(value=Decimal("9482300000"), rate=None, basis=None)


def test_a_local_currency_figure_is_divided_by_its_rate() -> None:
    cell = convert(Decimal("119875800000"), "NIO", Decimal("36.8"))

    assert cell.value == Decimal("3257494565.22")
    assert cell.rate == Decimal("36.8")
    assert cell.basis == "monthly average"


def test_a_missing_rate_yields_null_rather_than_a_guess() -> None:
    """D7: no nearest rate, no carry-forward."""
    cell = convert(Decimal("100"), "BZD", None)

    assert cell == ConvertedCell(value=None, rate=None, basis=None)


def test_an_observation_with_no_currency_is_not_converted() -> None:
    """Guessing from the country would be D3's bug wearing a different hat."""
    cell = convert(Decimal("100"), None, Decimal("2"))

    assert cell == ConvertedCell(value=None, rate=None, basis=None)


def test_a_cell_with_no_published_value_short_circuits() -> None:
    cell = convert(None, "NIO", Decimal("36.8"))

    assert cell == ConvertedCell(value=None, rate=None, basis=None)


def pair(value: Decimal | None, currency: str | None, rate: Decimal | None):  # type: ignore[no-untyped-def]
    """A published value and what converting it produced — what summarise takes."""
    return (value, convert(value, currency, rate))


def test_the_summary_counts_the_three_outcomes_separately() -> None:
    cells = [
        pair(Decimal("100"), "NIO", Decimal("36.8")),
        pair(Decimal("200"), "USD", None),
        pair(Decimal("300"), "BZD", None),
    ]

    summary = summarise(cells, "cepalstat_exchange_rate_monthly")

    assert (summary.converted, summary.already_at_target, summary.no_rate) == (1, 1, 1)
    assert summary.rate_source_key == "cepalstat_exchange_rate_monthly"
    assert summary.basis == "monthly average"
    assert summary.target_currency == "USD"


def test_a_cell_with_no_published_value_is_counted_in_nothing() -> None:
    """/compare is rectangular, so most cells in a wide comparison are holes in
    the published data. Counting them as 'no rate' would blame the rate series
    for the publisher's gap."""
    summary = summarise([pair(None, "NIO", Decimal("36.8"))], "s")

    assert (summary.converted, summary.already_at_target, summary.no_rate) == (0, 0, 0)


def test_the_summary_always_states_both_caveats() -> None:
    summary = summarise([], None)

    assert len(summary.caveats) == 2
    assert any("indicative" in c for c in summary.caveats)
    assert any("one decimal" in c for c in summary.caveats)


def test_a_convertible_indicator_is_accepted() -> None:
    ensure_convertible(INDICATORS_BY_CODE["money_m1_monthly"])


@pytest.mark.parametrize(
    "code", ["ni_exchange_rate_official_daily", "exchange_rate_nominal_monthly"]
)
def test_a_rate_indicator_is_refused_by_name(code: str) -> None:
    with pytest.raises(InvalidRequestError) as caught:
        ensure_convertible(INDICATORS_BY_CODE[code])

    assert caught.value.http_status == 400
    assert code in str(caught.value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_conversion.py -q`
Expected: FAIL at collection — `ModuleNotFoundError: reim.domain.conversion`.

- [ ] **Step 3: Write the module**

Create `reim/domain/conversion.py`:

```python
"""Converting a published figure into dollars, beside it and never instead.

REIM stores what publishers publish. This module is the one place it derives a
number, and every rule here exists to keep that derivation from being mistaken
for a source's own figure.

Three of them matter more than the rest:

* **Conversion keys on the observation's own currency, never on its country.**
  El Salvador transacts in dollars and CEPAL still quotes it at 8.8 colones per
  dollar, twenty-four years after dollarisation. A conversion keyed on the
  country would divide El Salvador's already-dollar figures by 8.8 and look
  entirely plausible doing it.
* **A missing rate is a gap, not a fallback.** No nearest period, no
  carry-forward, no annual average standing in for a month.
* **The result is indicative.** The rate is an average across the month while
  the series it converts are end-of-period stocks, and CEPAL publishes no
  end-of-period alternative. That mismatch cannot be fixed, so it travels with
  every figure instead.

See `docs/superpowers/specs/2026-09-06-currency-conversion-design.md`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from reim.core.exceptions import InvalidRequestError
from reim.domain.indicators.registry import IndicatorDefinition

#: The only target. Rates are local-currency-per-USD, so any other target means
#: triangulating through the dollar and squaring the rate's rounding error.
TARGET_CURRENCY = "USD"

RATE_INDICATOR_CODE = "exchange_rate_nominal_monthly"

#: What the rate is, carried per cell so a client charting the converted series
#: cannot miss it.
RATE_BASIS = "monthly average"

#: Converted amounts are quantized to this. The real precision limit is the
#: rate's single published decimal, which `CAVEATS` states rather than implying
#: with twenty digits of division.
QUANTUM = Decimal("0.01")

CAVEATS = (
    "Converted figures are indicative. The rate is the average of the daily "
    "rates within the month, while these observations are end-of-period "
    "stocks; CEPAL publishes no end-of-period rate.",
    "The rate is published to one decimal, which is the precision limit of "
    "every figure derived from it.",
)


@dataclass(frozen=True, slots=True)
class ConvertedCell:
    """One cell's converted figure, and what produced it.

    ``rate`` and ``basis`` are ``None`` whenever no rate was applied — both
    when the cell was already at the target and when no rate existed for its
    period. ``value`` distinguishes the two: it carries the untouched figure in
    the first case and ``None`` in the second.
    """

    value: Decimal | None
    rate: Decimal | None
    basis: str | None


#: The one outcome that is neither converted, already-at-target nor missing a
#: rate: there was nothing published to convert.
_NOTHING = ConvertedCell(value=None, rate=None, basis=None)


@dataclass(frozen=True, slots=True)
class ConversionSummary:
    """What a converted response did, and what the reader must know about it."""

    target_currency: str
    rate_indicator_code: str
    #: The source that supplied these rates, when exactly one did. ``None``
    #: when none did — an operator who has never run the rate pipeline gets a
    #: valid response with everything counted under ``no_rate``.
    rate_source_key: str | None
    basis: str
    converted: int
    already_at_target: int
    no_rate: int
    caveats: tuple[str, ...]


def ensure_convertible(definition: IndicatorDefinition) -> None:
    """Refuse an indicator whose values are not amounts in a currency.

    ``ni_exchange_rate_official_daily`` carries ``currency_code = NIO`` and
    means "36.8 NIO **per** USD". Dividing it by a rate returns a confident
    ``1.00``. An amount denominated in a currency and a ratio expressed per
    that currency are different things, and only the registry can tell them
    apart.

    Raises:
        InvalidRequestError: The indicator does not declare itself convertible.
    """
    if not definition.currency_convertible:
        msg = (
            f"Indicator {definition.code!r} does not carry amounts denominated "
            f"in a currency, so it cannot be converted to {TARGET_CURRENCY}"
        )
        raise InvalidRequestError(msg, indicator=definition.code)


def convert(
    value: Decimal | None, currency_code: str | None, rate: Decimal | None
) -> ConvertedCell:
    """Convert one cell. Total, and raises nothing.

    Args:
        value: The published figure, or ``None`` where the publisher has a gap.
        currency_code: The **observation's** currency, never the country's.
        rate: Local currency per USD for exactly this period, or ``None``.
    """
    if value is None or currency_code is None:
        return _NOTHING
    if currency_code == TARGET_CURRENCY:
        return ConvertedCell(value=value, rate=None, basis=None)
    if rate is None or not rate:
        return _NOTHING
    return ConvertedCell(value=(value / rate).quantize(QUANTUM), rate=rate, basis=RATE_BASIS)


def summarise(
    pairs: Iterable[tuple[Decimal | None, ConvertedCell]],
    rate_source_key: str | None,
) -> ConversionSummary:
    """Count the three outcomes and attach the caveats.

    Takes the **published value alongside** each converted cell, because the
    cell alone cannot distinguish "nothing was published" from "no rate
    existed" — both are all-``None``. A cell with nothing published is counted
    in none of the three: ``/compare`` is rectangular, so most cells in a wide
    comparison are holes in the published data, and counting them as missing a
    rate would blame the rate series for the publisher's gap.
    """
    converted = already = no_rate = 0
    for published, cell in pairs:
        if published is None:
            continue
        if cell.rate is not None:
            converted += 1
        elif cell.value is not None:
            already += 1
        else:
            no_rate += 1

    return ConversionSummary(
        target_currency=TARGET_CURRENCY,
        rate_indicator_code=RATE_INDICATOR_CODE,
        rate_source_key=rate_source_key,
        basis=RATE_BASIS,
        converted=converted,
        already_at_target=already,
        no_rate=no_rate,
        caveats=CAVEATS,
    )
```

Note the signature: `summarise` takes the published value **alongside** each
converted cell. The cell alone cannot tell "nothing was published" from "no
rate existed" — both are all-`None` — and Task 5's router holds both anyway.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_conversion.py -q`
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
git add reim/domain/conversion.py tests/unit/test_conversion.py
git commit -m "feat(compare): the conversion rules, as pure functions"
```

---

### Task 4: Fetch the page's rates

**Files:**
- Modify: `reim/repositories/comparison.py`
- Test: `tests/integration/test_comparison_repository.py`

**Interfaces:**
- Consumes: Task 3's `RATE_INDICATOR_CODE`.
- Produces: `fetch_rates(session, *, country_ids, period_starts) ->
  RateTable`, where `RateTable` carries `by_period: dict[tuple[str, date],
  Decimal]` and `source_key: str | None`.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_comparison_repository.py`:

```python
def test_fetch_rates_keys_on_country_and_period(session, make_observation) -> None:  # type: ignore[no-untyped-def]
    from reim.services.observation_writer import write_observations

    write_observations(
        session,
        [
            make_observation(
                period,
                value,
                indicator_code="exchange_rate_nominal_monthly",
                source_key="cepalstat_exchange_rate_monthly",
                country_iso3="NIC",
                unit="NIO per USD",
                currency_code="NIO",
            )
            for period, value in (("2024-01", "36.6"), ("2024-02", "36.7"))
        ],
        connector_version="1.0.0",
    )
    session.commit()
    country = get_country_by_iso3(session, "NIC")
    assert country is not None

    table = fetch_rates(
        session,
        country_ids=(country.id,),
        period_starts=[date(2024, 1, 1)],
    )

    assert table.by_period == {("NIC", date(2024, 1, 1)): Decimal("36.6")}
    assert table.source_key == "cepalstat_exchange_rate_monthly"


def test_fetch_rates_returns_empty_when_the_series_is_not_loaded(session) -> None:  # type: ignore[no-untyped-def]
    """Not an error: an operator who never ran the pipeline still gets a page."""
    table = fetch_rates(session, country_ids=(), period_starts=[date(2024, 1, 1)])

    assert table.by_period == {}
    assert table.source_key is None
```

The first test asserts **2024-02 is absent**: the rate query is scoped to the
periods actually on the page, so a one-page slice of a thirty-year comparison
fetches that page's rates and no more.

- [ ] **Step 2: Run tests to verify they fail**

Run: `REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/python -m pytest tests/integration/test_comparison_repository.py -k rates -v`
Expected: FAIL — `ImportError: cannot import name 'fetch_rates'`.

- [ ] **Step 3: Implement it**

Add to `reim/repositories/comparison.py`, importing `Sequence` from
`collections.abc` and `RATE_INDICATOR_CODE` from `reim.domain.conversion`:

```python
@dataclass(frozen=True, slots=True)
class RateTable:
    """The rates for one page of a comparison, and where they came from."""

    by_period: dict[tuple[str, date], Decimal]
    #: The source that supplied them, when exactly one did. ``None`` when the
    #: rate series holds nothing for this page, and also when more than one
    #: source supplies it — REIM has one today, and a second would be a real
    #: change to reckon with rather than one to average over silently.
    source_key: str | None


def fetch_rates(
    session: Session,
    *,
    country_ids: tuple[uuid.UUID, ...],
    period_starts: Sequence[date],
) -> RateTable:
    """Active monthly rates for exactly these countries and periods.

    Scoped to the page's periods rather than to a range, so a request for one
    page of a thirty-year comparison fetches that page's rates and no more.
    """
    if not country_ids or not period_starts:
        return RateTable(by_period={}, source_key=None)

    statement = (
        select(
            Country.iso3,
            Observation.period_start,
            Observation.value_numeric,
            DataSource.source_key,
        )
        .join(Observation.indicator)
        .join(Observation.country)
        .join(Observation.source)
        .where(
            Indicator.code == RATE_INDICATOR_CODE,
            Observation.country_id.in_(country_ids),
            Observation.period_start.in_(period_starts),
            Observation.status == ObservationStatus.ACTIVE,
            Observation.value_numeric.is_not(None),
        )
    )

    by_period: dict[tuple[str, date], Decimal] = {}
    sources: set[str] = set()
    for iso3, start, value, source_key in session.execute(statement):
        by_period[(iso3, start)] = value
        sources.add(source_key)

    return RateTable(by_period=by_period, source_key=sources.pop() if len(sources) == 1 else None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/python -m pytest tests/integration/test_comparison_repository.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add reim/repositories/comparison.py tests/integration/test_comparison_repository.py
git commit -m "feat(compare): fetch the page's exchange rates"
```

---

### Task 5: Wire the converted view into the endpoint

**Files:**
- Modify: `reim/schemas/comparison.py`
- Modify: `apps/api/routers/comparison.py`
- Test: `tests/integration/test_api.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: `?convert_to=USD` on `GET /api/v1/compare`; `ComparisonRow` fields
  `values_converted`, `rates`, `rate_basis`; `ComparisonResponse.conversion`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/integration/test_api.py`, after the existing compare tests. The
fixture builds two countries reporting one convertible indicator in different
currencies, plus the rates for one of them:

```python
@pytest.fixture
def convert_client(seeded_session: Session, make_observation) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    """Nicaragua in córdobas, El Salvador already in dollars, rates for both."""
    from reim.services.observation_writer import write_observations

    write_observations(
        seeded_session,
        [
            make_observation(
                "2024-01",
                "36800",
                indicator_code="money_m1_monthly",
                source_key="cepalstat_monetary_monthly",
                country_iso3="NIC",
                unit="NIO",
                currency_code="NIO",
            ),
            make_observation(
                "2024-01",
                "9482",
                indicator_code="money_m1_monthly",
                source_key="cepalstat_monetary_monthly",
                country_iso3="SLV",
                unit="USD",
                currency_code="USD",
            ),
            make_observation(
                "2024-01",
                "36.8",
                indicator_code="exchange_rate_nominal_monthly",
                source_key="cepalstat_exchange_rate_monthly",
                country_iso3="NIC",
                unit="NIO per USD",
                currency_code="NIO",
            ),
            make_observation(
                "2024-01",
                "8.8",
                indicator_code="exchange_rate_nominal_monthly",
                source_key="cepalstat_exchange_rate_monthly",
                country_iso3="SLV",
                unit="SVC per USD",
                currency_code="SVC",
            ),
        ],
        connector_version="1.0.0",
    )
    seeded_session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: seeded_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_convert_puts_dollars_beside_the_published_figure(
    convert_client: TestClient,
) -> None:
    body = convert_client.get(
        "/api/v1/compare",
        params={
            "indicator": "money_m1_monthly",
            "country": ["NI", "SV"],
            "convert_to": "USD",
        },
    ).json()

    row = body["data"][0]
    assert row["values"]["NIC"] == "36800"
    assert row["values_converted"]["NIC"] == "1000.00"
    assert row["rates"]["NIC"] == "36.8"
    assert row["rate_basis"]["NIC"] == "monthly average"


def test_el_salvador_is_not_divided_by_a_currency_it_retired(
    convert_client: TestClient,
) -> None:
    """The ninefold error, asserted through the endpoint.

    CEPAL publishes a rate for El Salvador and REIM stores it. The converted
    figure must still equal the published one, because the observation is
    already in dollars.
    """
    body = convert_client.get(
        "/api/v1/compare",
        params={
            "indicator": "money_m1_monthly",
            "country": ["NI", "SV"],
            "convert_to": "USD",
        },
    ).json()

    row = body["data"][0]
    assert row["values"]["SLV"] == "9482"
    assert row["values_converted"]["SLV"] == "9482"
    assert row["rates"]["SLV"] is None
    assert row["rate_basis"]["SLV"] is None


def test_conversion_does_not_make_the_series_comparable(
    convert_client: TestClient,
) -> None:
    """D8: `comparable` describes what the publisher published."""
    body = convert_client.get(
        "/api/v1/compare",
        params={
            "indicator": "money_m1_monthly",
            "country": ["NI", "SV"],
            "convert_to": "USD",
        },
    ).json()

    assert body["comparable"] is False
    assert body["conversion"]["converted"] == 1
    assert body["conversion"]["already_at_target"] == 1
    assert body["conversion"]["no_rate"] == 0
    assert body["conversion"]["rate_source_key"] == "cepalstat_exchange_rate_monthly"
    assert len(body["conversion"]["caveats"]) == 2


def test_without_convert_to_the_response_gains_no_keys(
    convert_client: TestClient,
) -> None:
    """Asserted key-by-key rather than against a rendered string."""
    body = convert_client.get(
        "/api/v1/compare",
        params={"indicator": "money_m1_monthly", "country": ["NI", "SV"]},
    ).json()

    assert "conversion" not in body
    assert set(body["data"][0]) == {"period_start", "period_end", "period_label", "values"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/python -m pytest tests/integration/test_api.py -k convert -v`
Expected: FAIL — the response has no `values_converted`.

- [ ] **Step 3: Add the response models**

In `reim/schemas/comparison.py`, add the optional fields.

**Do not reach for a blanket `response_model_exclude_none=True` on the route.**
It would drop the keys correctly, and it would also drop `first_period` and
`last_period` from any country with no data — silently changing a response this
increment is not supposed to touch. Measured on 2026-09-06 with this
repository's Pydantic: `exclude_none` removes `None` *model fields* at every
depth, while leaving `None` values *inside* a dict untouched, so `values`'
explicit nulls (C2) survive it but `ComparisonSeries`' do not.

Use a targeted `model_serializer` instead, which drops exactly the three keys
and nothing else:

```python
@model_serializer(mode="wrap")
def _drop_absent_conversion(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
    """Omit the conversion keys entirely when none was requested.

    A null `values_converted` would read as "conversion ran and produced
    nothing", which is a different claim from "conversion was not asked for".
    """
    data = handler(self)
    if self.values_converted is None:
        for key in ("values_converted", "rates", "rate_basis"):
            data.pop(key, None)
    return data
```

Add the same idea to `ComparisonResponse` for its `conversion` field. Import
`Any` from `typing` and `SerializerFunctionWrapHandler`, `model_serializer`
from `pydantic`.

```python
class ConversionBlock(BaseModel):
    """What a converted response did, and what the reader must know about it."""

    model_config = ConfigDict(from_attributes=True)

    target_currency: str
    rate_indicator_code: str
    rate_source_key: str | None
    basis: str
    converted: int
    already_at_target: int
    no_rate: int
    caveats: list[str]
```

Add to `ComparisonRow`:

```text
    values_converted: dict[str, Decimal | None] | None = Field(
        default=None,
        description=(
            "Country ISO-3 to the figure in the target currency, beside the "
            "published one and never in place of it. Absent unless convert_to "
            "was requested."
        ),
    )
    rates: dict[str, Decimal | None] | None = Field(
        default=None,
        description="The rate applied to each country's cell, or null where none was.",
    )
    rate_basis: dict[str, str | None] | None = Field(
        default=None,
        description="What each rate is; null where no rate was applied.",
    )
```

Add to `ComparisonResponse`:

```text
    conversion: ConversionBlock | None = None
```

- [ ] **Step 4: Wire the router**

In `apps/api/routers/comparison.py`, add the parameter after `order`:

```text
    convert_to: Annotated[
        Literal["USD"] | None,
        Query(description="Return a converted view beside the published figures."),
    ] = None,
```

After the indicator is resolved and before the queries, run the gate. The
router holds the ORM `Indicator`, not the registry's `IndicatorDefinition`, so
look the definition up by code:

```text
    if convert_to is not None:
        registered = INDICATORS_BY_CODE.get(definition.code)
        if registered is None:
            msg = f"Indicator {definition.code!r} is not in the registry"
            raise ResourceNotFoundError(msg, indicator=definition.code)
        ensure_convertible(registered)
```

After `cells` is fetched, build the rate table and convert, keeping the
published value alongside each converted cell for `summarise`. Import
`ConvertedCell`, `convert`, `ensure_convertible` and `summarise` from
`reim.domain.conversion`, `fetch_rates` from `reim.repositories.comparison`,
`INDICATORS_BY_CODE` from `reim.domain.indicators.registry`, and `Literal` from
`typing`:

```text
    conversion: ConversionBlock | None = None
    converted: dict[tuple[str, str], ConvertedCell] = {}
    if convert_to is not None:
        table = fetch_rates(
            session,
            country_ids=query.country_ids,
            period_starts=[cell.period_start for cell in cells],
        )
        pairs = []
        for cell in cells:
            result = convert(
                cell.value_numeric,
                cell.currency_code,
                table.by_period.get((cell.country_iso3, cell.period_start)),
            )
            converted[(cell.period_label, cell.country_iso3)] = result
            pairs.append((cell.value_numeric, result))
        conversion = ConversionBlock.model_validate(summarise(pairs, table.source_key))
```

When building each `ComparisonRow`, populate the three dicts only when
`convert_to` was given, keyed by `requested` exactly as `values` is, so every
row stays rectangular. Pass `conversion=conversion` to `ComparisonResponse`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/python -m pytest tests/integration/test_api.py -k compare -q`
Expected: PASS — the new tests and the four that already existed.

- [ ] **Step 6: Commit**

```bash
git add reim/schemas/comparison.py apps/api/routers/comparison.py tests/integration/test_api.py
git commit -m "feat(compare): return a converted view beside the published one"
```

---

### Task 6: The two refusals, and the unloaded-rates case

**Files:**
- Test: `tests/integration/test_api.py`

**Interfaces:**
- Consumes: Task 5's endpoint. No production code should be needed — if a test
  here fails, Task 5 is incomplete.

- [ ] **Step 1: Write the tests**

```python
def test_converting_a_rate_indicator_is_refused_with_400(
    convert_client: TestClient,
) -> None:
    """36.8 NIO *per USD* divided by 36.8 is a confident, meaningless 1.00."""
    response = convert_client.get(
        "/api/v1/compare",
        params={
            "indicator": "exchange_rate_nominal_monthly",
            "country": ["NI", "SV"],
            "convert_to": "USD",
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert "exchange_rate_nominal_monthly" in body["error"]["message"]


def test_an_unsupported_target_is_refused_with_422(convert_client: TestClient) -> None:
    """From FastAPI's Literal, not from code this increment wrote.

    Asserted so that widening the type later cannot silently accept a target
    with no rates behind it.
    """
    response = convert_client.get(
        "/api/v1/compare",
        params={
            "indicator": "money_m1_monthly",
            "country": ["NI", "SV"],
            "convert_to": "EUR",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.fixture
def no_rates_client(seeded_session: Session, make_observation) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    """A convertible indicator in local currencies, and no rates at all.

    `compare_client` cannot serve this: its indicator is not convertible, so
    the gate would refuse the request before an empty rate table ever mattered.
    """
    from reim.services.observation_writer import write_observations

    write_observations(
        seeded_session,
        [
            make_observation(
                "2024-01",
                value,
                indicator_code="money_m1_monthly",
                source_key="cepalstat_monetary_monthly",
                country_iso3=iso3,
                unit=currency,
                currency_code=currency,
            )
            for iso3, currency, value in (("NIC", "NIO", "36800"), ("GTM", "GTQ", "7800"))
        ],
        connector_version="1.0.0",
    )
    seeded_session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: seeded_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_an_unloaded_rate_series_converts_nothing_and_still_returns_200(
    no_rates_client: TestClient,
) -> None:
    """A missing rate is a gap (D7), not a failure.

    An operator who has never run `cepalstat_exchange_rate_monthly` gets a
    page, with the count saying plainly that nothing converted.
    """
    response = no_rates_client.get(
        "/api/v1/compare",
        params={
            "indicator": "money_m1_monthly",
            "country": ["NI", "GT"],
            "convert_to": "USD",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversion"]["no_rate"] == 2
    assert body["conversion"]["converted"] == 0
    assert body["conversion"]["rate_source_key"] is None
    assert body["data"][0]["values_converted"] == {"NIC": None, "GTM": None}
```

- [ ] **Step 2: Run the tests**

Run: `REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/python -m pytest tests/integration/test_api.py -k "refused or unloaded" -v`
Expected: PASS without touching production code. If the 400 test returns 500,
`InvalidRequestError` is being raised outside the handler's reach — check that
the gate runs inside the route function.

- [ ] **Step 3: Run the whole gate**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/python -m pytest -q`
Expected: all clean. 640 tests before this plan, plus roughly 20 new.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_api.py
git commit -m "test(compare): cover both refusals and an unloaded rate series"
```

---

### Task 7: Write down what shipped

**Files:**
- Modify: `README.md`
- Modify: `ROADMAP.md`
- Modify: `docs/sources.md`

**Interfaces:**
- Consumes: everything above. No code.

- [ ] **Step 1: Document the parameter in the README's API section**

Find where `/api/v1/compare` is described and add `convert_to`. Cover, in this
order: it is opt-in; the converted figure never replaces the published one; the
rate and its basis travel with every converted cell; `comparable` is unchanged;
and the figures are **indicative** because the rate is a within-month average
against end-of-period stocks.

Show the El Salvador row as the worked example. It is the one that teaches the
rule — published and converted are the same number, rate `null` — and a reader
who understands why will not misread the rest.

- [ ] **Step 2: Tick the roadmap line**

`ROADMAP.md`'s v0.3.0 currency line currently says "**Half done.**" Both halves
now exist. Rewrite it as done, in the style of the other completed entries:
strike the title, state what shipped, and keep the two caveats that matter —
El Salvador quoted in a retired currency, and the average-versus-stock
mismatch. Do **not** delete those; they are the reason the feature is safe.

- [ ] **Step 3: Close the loop in `docs/sources.md`**

The monetary section says REIM "performs no conversion today" and that a
converted view "is designed but not yet built". Both clauses are now false.
Rewrite that paragraph to say what `/compare?convert_to=USD` does and what it
refuses to do, and link the exchange-rate section for the rate's provenance.

- [ ] **Step 4: Verify every figure you wrote**

```bash
grep -rn "convert_to" README.md ROADMAP.md docs/sources.md
```

Every claim must match the endpoint's actual behaviour. The repository's
history includes a commit fixing exactly this kind of drift
(`36554d0 docs(cepalstat): fix debt-section freshness arithmetic and stale dates`).

- [ ] **Step 5: Run the whole gate**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/python -m pytest -q`
Expected: all clean.

`ruff format` silently rewrites any ` ```python ` block in a Markdown file that
is not a valid standalone module. If it reports changes to a `.md` file, fence
that block as ` ```text ` rather than accepting the rewrite.

- [ ] **Step 6: Commit**

```bash
git add README.md ROADMAP.md docs/sources.md
git commit -m "feat: converted figures beside published ones on /compare"
```

---

## Done when

* `GET /api/v1/compare?indicator=money_m1_monthly&country=NI&country=SV&convert_to=USD`
  returns Nicaragua converted at its published rate and El Salvador untouched,
  with `rates.SLV` null.
* `convert_to` on a rate indicator returns 400; `convert_to=EUR` returns 422.
* Omitting `convert_to` returns a payload with no conversion keys.
* No row was written to `observations` by any of it, and no migration exists.
* The full gate is clean and the roadmap's v0.3.0 currency line is done.
