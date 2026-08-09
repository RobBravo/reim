# Cross-Country Comparison Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve one indicator across many countries as a period-aligned matrix, with gaps and comparability stated in the payload rather than left to the caller.

**Architecture:** A new repository module runs three queries — the page of periods, the cells within them, and a per-country summary — and a new router pivots the cells into rectangular rows. Comparability is derived from the summaries by a pure function, so the branch that matters can be unit-tested as logic and integration-tested end to end.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic 2, pytest.

## Global Constraints

- Endpoint is `GET /api/v1/compare`. `indicator` is required; `country` is repeatable, **2 to 20** values.
- Rows are **rectangular**: every row carries one entry per requested country, `null` where that country has no figure. Never omit the key, never substitute zero.
- Rows are the **union** of periods across the requested countries, bounded by `date_from` / `date_to` on `period_start`.
- `comparable` is `false` when the requested series differ in **unit or currency**. Differing **sources** are noted but do not flip it.
- **No currency conversion, ever.** Heterogeneous units are surfaced, never reconciled.
- Values serialise as **strings**, matching `ObservationRead.value_numeric`; JSON numbers would lose `NUMERIC` precision.
- Only `ObservationStatus.ACTIVE` observations are compared.
- `units`, `currency_codes` and `source_keys` are **lists** on every series — a country's series can carry more than one over time.
- Verify with the commands CI runs, over the whole repo, as **one chain that stops on the first failure**: `set -e; ruff check .; ruff format --check .; mypy reim apps; pytest`. Never pipe a check through `tail` — it masks the exit code.

---

### Task 1: The comparison queries

**Files:**
- Create: `reim/repositories/comparison.py`
- Test: `tests/integration/test_comparison_repository.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `ComparisonQuery(indicator_code: str, country_ids: tuple[uuid.UUID, ...], period_start_from: date | None = None, period_start_to: date | None = None)`
  - `ComparisonCell(period_start: date, period_end: date, period_label: str, country_iso3: str, value_numeric: Decimal | None)`
  - `SeriesSummary(country_iso2: str, country_iso3: str, country_name: str, units: tuple[str, ...], currency_codes: tuple[str | None, ...], source_keys: tuple[str, ...], observations: int, first_period: str | None, last_period: str | None)`
  - `count_comparison_periods(session, query) -> int`
  - `fetch_comparison_cells(session, query, *, limit, offset, descending=False) -> list[ComparisonCell]`
  - `summarise_series(session, query, countries) -> list[SeriesSummary]`

`summarise_series` takes the resolved `Country` rows so a country with **zero**
observations still gets a summary — a grouped query alone would drop it.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_comparison_repository.py`:

```python
"""Comparison queries against a live schema (requires PostgreSQL)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from reim.repositories.comparison import (
    ComparisonQuery,
    count_comparison_periods,
    fetch_comparison_cells,
    summarise_series,
)
from reim.repositories.reference import get_country_by_iso3
from tests.conftest import requires_db

pytestmark = [requires_db, pytest.mark.integration]


@pytest.fixture
def two_countries(seeded_session: Session, make_observation) -> ComparisonQuery:  # type: ignore[no-untyped-def]
    """Nicaragua has three months, Guatemala only two — a real gap."""
    from reim.services.observation_writer import write_observations

    rows = [
        make_observation(
            period,
            value,
            indicator_code="exports_goods_monthly",
            source_key=source,
            country_iso3=iso3,
            unit="current USD",
            currency_code="USD",
        )
        for period, value, iso3, source in (
            ("2024-01", "100", "NIC", "imf_imts_nicaragua"),
            ("2024-02", "110", "NIC", "imf_imts_nicaragua"),
            ("2024-03", "120", "NIC", "imf_imts_nicaragua"),
            ("2024-01", "500", "GTM", "imf_imts_guatemala"),
            ("2024-03", "520", "GTM", "imf_imts_guatemala"),
        )
    ]
    write_observations(seeded_session, rows, connector_version="1.0.0")
    seeded_session.commit()

    nic = get_country_by_iso3(seeded_session, "NIC")
    gtm = get_country_by_iso3(seeded_session, "GTM")
    assert nic is not None and gtm is not None
    return ComparisonQuery(
        indicator_code="exports_goods_monthly",
        country_ids=(nic.id, gtm.id),
    )


def test_counts_the_union_of_periods(
    seeded_session: Session, two_countries: ComparisonQuery
) -> None:
    """Three periods exist in total, even though Guatemala holds only two."""
    assert count_comparison_periods(seeded_session, two_countries) == 3


def test_cells_carry_every_country_that_has_a_figure(
    seeded_session: Session, two_countries: ComparisonQuery
) -> None:
    cells = fetch_comparison_cells(seeded_session, two_countries, limit=10, offset=0)

    assert len(cells) == 5
    by_period: dict[str, set[str]] = {}
    for cell in cells:
        by_period.setdefault(cell.period_label, set()).add(cell.country_iso3)
    assert by_period == {
        "2024-01": {"NIC", "GTM"},
        "2024-02": {"NIC"},
        "2024-03": {"NIC", "GTM"},
    }


def test_cells_are_ordered_by_period(
    seeded_session: Session, two_countries: ComparisonQuery
) -> None:
    ascending = fetch_comparison_cells(seeded_session, two_countries, limit=10, offset=0)
    descending = fetch_comparison_cells(
        seeded_session, two_countries, limit=10, offset=0, descending=True
    )

    assert ascending[0].period_label == "2024-01"
    assert descending[0].period_label == "2024-03"


def test_paging_slices_periods_not_cells(
    seeded_session: Session, two_countries: ComparisonQuery
) -> None:
    """A page of one period must carry that period's cells, not one cell."""
    cells = fetch_comparison_cells(seeded_session, two_countries, limit=1, offset=0)

    assert {c.period_label for c in cells} == {"2024-01"}
    assert len(cells) == 2


def test_date_bounds_narrow_the_periods(
    seeded_session: Session, two_countries: ComparisonQuery
) -> None:
    bounded = ComparisonQuery(
        indicator_code=two_countries.indicator_code,
        country_ids=two_countries.country_ids,
        period_start_from=date(2024, 2, 1),
    )

    assert count_comparison_periods(seeded_session, bounded) == 2


def test_values_are_decimals(seeded_session: Session, two_countries: ComparisonQuery) -> None:
    cells = fetch_comparison_cells(seeded_session, two_countries, limit=10, offset=0)
    first = next(c for c in cells if c.period_label == "2024-01" and c.country_iso3 == "NIC")

    assert first.value_numeric == Decimal("100")


def test_summaries_describe_each_country(
    seeded_session: Session, two_countries: ComparisonQuery
) -> None:
    countries = [get_country_by_iso3(seeded_session, iso3) for iso3 in ("NIC", "GTM")]
    summaries = {
        s.country_iso3: s
        for s in summarise_series(seeded_session, two_countries, [c for c in countries if c])
    }

    assert summaries["NIC"].observations == 3
    assert summaries["NIC"].first_period == "2024-01"
    assert summaries["NIC"].last_period == "2024-03"
    assert summaries["NIC"].units == ("current USD",)
    assert summaries["NIC"].source_keys == ("imf_imts_nicaragua",)
    assert summaries["GTM"].observations == 2


def test_a_country_with_no_data_still_gets_a_summary(
    seeded_session: Session, two_countries: ComparisonQuery
) -> None:
    """Omitting it would hide the very fact worth knowing."""
    honduras = get_country_by_iso3(seeded_session, "HND")
    nicaragua = get_country_by_iso3(seeded_session, "NIC")
    assert honduras is not None and nicaragua is not None
    query = ComparisonQuery(
        indicator_code="exports_goods_monthly",
        country_ids=(nicaragua.id, honduras.id),
    )

    summaries = {
        s.country_iso3: s for s in summarise_series(seeded_session, query, [nicaragua, honduras])
    }

    assert summaries["HND"].observations == 0
    assert summaries["HND"].first_period is None
    assert summaries["HND"].last_period is None
    assert summaries["HND"].units == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration -q`
Expected: FAIL — `ModuleNotFoundError: reim.repositories.comparison`.

The integration suite needs the test schema; run the whole `tests/integration`
directory rather than the single file, because the schema setup is
session-scoped and a lone file will error on `TRUNCATE`.

- [ ] **Step 3: Write the repository**

Create `reim/repositories/comparison.py`:

```python
"""Queries backing the cross-country comparison endpoint.

Kept apart from :mod:`reim.repositories.observations`, which already carries
ten functions over a different shape: that module answers "which observations
match these filters", this one answers "what does this indicator look like
across these countries, period by period".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from reim.core.constants import ObservationStatus
from reim.database.models import Country, DataSource, Indicator, Observation


@dataclass(frozen=True, slots=True)
class ComparisonQuery:
    """One indicator, several countries, optionally bounded in time."""

    indicator_code: str
    country_ids: tuple[uuid.UUID, ...]
    period_start_from: date | None = None
    period_start_to: date | None = None


@dataclass(frozen=True, slots=True)
class ComparisonCell:
    """One country's figure for one period."""

    period_start: date
    period_end: date
    period_label: str
    country_iso3: str
    value_numeric: Decimal | None


@dataclass(frozen=True, slots=True)
class SeriesSummary:
    """What one country's series looks like, including when it is empty.

    ``units``, ``currency_codes`` and ``source_keys`` are tuples because a
    country's series can carry more than one of each over time, and collapsing
    that to a scalar would hide exactly the difference a comparison must show.
    """

    country_iso2: str
    country_iso3: str
    country_name: str
    units: tuple[str, ...]
    currency_codes: tuple[str | None, ...]
    source_keys: tuple[str, ...]
    observations: int
    first_period: str | None
    last_period: str | None


def _restrict[S: Select[Any]](statement: S, query: ComparisonQuery) -> S:
    """Narrow a statement already joined to indicator and country."""
    statement = statement.where(
        Indicator.code == query.indicator_code,
        Observation.country_id.in_(query.country_ids),
        Observation.status == ObservationStatus.ACTIVE,
    )
    if query.period_start_from is not None:
        statement = statement.where(Observation.period_start >= query.period_start_from)
    if query.period_start_to is not None:
        statement = statement.where(Observation.period_start <= query.period_start_to)
    return statement


def _period_page(
    query: ComparisonQuery, *, limit: int, offset: int, descending: bool
) -> Select[tuple[date, date, str]]:
    """The page of distinct periods, which is what pagination slices."""
    order = Observation.period_start.desc() if descending else Observation.period_start.asc()
    statement = (
        select(Observation.period_start, Observation.period_end, Observation.period_label)
        .join(Observation.indicator)
        .distinct()
        .order_by(order)
        .limit(limit)
        .offset(offset)
    )
    return _restrict(statement, query)


def count_comparison_periods(session: Session, query: ComparisonQuery) -> int:
    """Count the distinct periods any requested country reports."""
    inner = _restrict(
        select(Observation.period_start).join(Observation.indicator).distinct(), query
    ).subquery()
    return int(session.scalar(select(func.count()).select_from(inner)) or 0)


def fetch_comparison_cells(
    session: Session,
    query: ComparisonQuery,
    *,
    limit: int,
    offset: int,
    descending: bool = False,
) -> list[ComparisonCell]:
    """Return every country's figure for the requested page of periods.

    Pagination slices **periods**, not rows: a page of one period carries that
    period's cell for every country holding it.
    """
    periods = session.execute(
        _period_page(query, limit=limit, offset=offset, descending=descending)
    ).all()
    if not periods:
        return []

    starts = [row[0] for row in periods]
    statement = _restrict(
        select(
            Observation.period_start,
            Observation.period_end,
            Observation.period_label,
            Country.iso3,
            Observation.value_numeric,
        )
        .join(Observation.indicator)
        .join(Observation.country),
        query,
    ).where(Observation.period_start.in_(starts))

    order = Observation.period_start.desc() if descending else Observation.period_start.asc()
    rows = session.execute(statement.order_by(order, Country.iso3)).all()
    return [
        ComparisonCell(
            period_start=row[0],
            period_end=row[1],
            period_label=row[2],
            country_iso3=row[3],
            value_numeric=row[4],
        )
        for row in rows
    ]


def summarise_series(
    session: Session, query: ComparisonQuery, countries: list[Country]
) -> list[SeriesSummary]:
    """Describe each requested country's series, empty ones included.

    ``countries`` is passed in rather than derived from the data so a country
    holding nothing still appears — a grouped query would silently drop it.
    """
    statement = _restrict(
        select(
            Country.iso3,
            Observation.unit,
            Observation.currency_code,
            DataSource.source_key,
            Observation.period_start,
            Observation.period_label,
        )
        .join(Observation.indicator)
        .join(Observation.country)
        .join(Observation.source),
        query,
    )

    units: dict[str, set[str]] = {}
    currencies: dict[str, set[str | None]] = {}
    sources: dict[str, set[str]] = {}
    counts: dict[str, int] = {}
    earliest: dict[str, tuple[date, str]] = {}
    latest: dict[str, tuple[date, str]] = {}

    for iso3, unit, currency, source_key, start, label in session.execute(statement):
        units.setdefault(iso3, set()).add(unit)
        currencies.setdefault(iso3, set()).add(currency)
        sources.setdefault(iso3, set()).add(source_key)
        counts[iso3] = counts.get(iso3, 0) + 1
        if iso3 not in earliest or start < earliest[iso3][0]:
            earliest[iso3] = (start, label)
        if iso3 not in latest or start > latest[iso3][0]:
            latest[iso3] = (start, label)

    return [
        SeriesSummary(
            country_iso2=country.iso2,
            country_iso3=country.iso3,
            country_name=country.name,
            units=tuple(sorted(units.get(country.iso3, set()))),
            currency_codes=tuple(
                sorted(currencies.get(country.iso3, set()), key=lambda c: (c is None, c or ""))
            ),
            source_keys=tuple(sorted(sources.get(country.iso3, set()))),
            observations=counts.get(country.iso3, 0),
            first_period=earliest.get(country.iso3, (None, None))[1],
            last_period=latest.get(country.iso3, (None, None))[1],
        )
        for country in countries
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/integration -q`
Expected: PASS.

- [ ] **Step 5: Gate and commit**

```bash
set -e
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy reim apps
.venv/bin/python -m pytest -q
git add reim/repositories/comparison.py tests/integration/test_comparison_repository.py
git commit -m "feat(api): queries for cross-country comparison

Pagination slices periods rather than rows, so a page always carries
every country's figure for the periods it covers. Series summaries take
the resolved countries as input, so a country holding nothing still gets
an entry — dropping it would hide the fact most worth knowing."
```

---

### Task 2: Comparability, and the response models

**Files:**
- Create: `reim/schemas/comparison.py`
- Test: `tests/unit/test_comparison.py` (create)

**Interfaces:**
- Consumes: `SeriesSummary` from Task 1.
- Produces:
  - `assess_comparability(summaries: list[SeriesSummary]) -> tuple[bool, list[str]]`
  - Pydantic models `ComparisonIndicator`, `ComparisonSeries`, `ComparisonRow`, `ComparisonResponse`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_comparison.py`:

```python
"""Comparability rules. No database, no network — pure logic."""

from __future__ import annotations

from reim.repositories.comparison import SeriesSummary
from reim.schemas.comparison import assess_comparability


def summary(
    iso3: str,
    *,
    units: tuple[str, ...] = ("current USD",),
    currencies: tuple[str | None, ...] = ("USD",),
    sources: tuple[str, ...] = ("imf_imts_nicaragua",),
    observations: int = 10,
) -> SeriesSummary:
    return SeriesSummary(
        country_iso2=iso3[:2],
        country_iso3=iso3,
        country_name=iso3,
        units=units,
        currency_codes=currencies,
        source_keys=sources,
        observations=observations,
        first_period="2024-01" if observations else None,
        last_period="2024-10" if observations else None,
    )


def test_identical_series_are_comparable() -> None:
    comparable, notes = assess_comparability([summary("NIC"), summary("GTM")])

    assert comparable is True
    assert notes == []


def test_differing_units_are_not_comparable() -> None:
    comparable, notes = assess_comparability(
        [summary("NIC"), summary("GTM", units=("quetzales",), currencies=("GTQ",))]
    )

    assert comparable is False
    assert any("nit" in note.lower() for note in notes)
    assert any("GTM" in note for note in notes)


def test_differing_sources_are_noted_but_still_comparable() -> None:
    """Two publishers measuring the same thing in the same unit is normal."""
    comparable, notes = assess_comparability(
        [summary("NIC"), summary("GTM", sources=("banguat_trade",))]
    )

    assert comparable is True
    assert any("ource" in note for note in notes)


def test_a_country_with_no_data_is_named() -> None:
    comparable, notes = assess_comparability([summary("NIC"), summary("GTM", observations=0)])

    assert any("GTM" in note and "no observations" in note for note in notes)


def test_an_empty_country_does_not_by_itself_break_comparability() -> None:
    """Having no data is a gap to report, not a unit mismatch."""
    comparable, _ = assess_comparability(
        [summary("NIC"), summary("GTM", observations=0, units=(), currencies=())]
    )

    assert comparable is True


def test_one_country_carrying_two_units_is_not_comparable() -> None:
    comparable, notes = assess_comparability(
        [summary("NIC", units=("current USD", "quetzales")), summary("GTM")]
    )

    assert comparable is False
    assert any("NIC" in note for note in notes)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_comparison.py -q`
Expected: FAIL — `ModuleNotFoundError: reim.schemas.comparison`.

- [ ] **Step 3: Write the schemas and the rule**

Create `reim/schemas/comparison.py`:

```python
"""Response models for the cross-country comparison endpoint."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from reim.core.constants import Frequency
from reim.repositories.comparison import SeriesSummary
from reim.schemas.common import PageMeta


def assess_comparability(summaries: list[SeriesSummary]) -> tuple[bool, list[str]]:
    """Decide whether these series may be read against each other, and why not.

    Comparability turns on **unit and currency only**. Differing sources are
    reported but do not make series incomparable: two publishers measuring the
    same thing in the same unit is ordinary, and conflating that with a unit
    mismatch would cry wolf. Having no data at all is a gap to report, not an
    incomparability.

    Returns:
        ``(comparable, notes)`` — notes are human-readable and always
        populated when something differs, whether or not it flips the flag.
    """
    notes: list[str] = []

    empty = [s.country_iso3 for s in summaries if s.observations == 0]
    if empty:
        notes.append(f"No observations for this indicator: {', '.join(sorted(empty))}.")

    populated = [s for s in summaries if s.observations > 0]

    mixed_within = sorted(s.country_iso3 for s in populated if len(s.units) > 1)
    if mixed_within:
        notes.append(
            f"More than one unit within a single country's series: {', '.join(mixed_within)}."
        )

    units = {unit for s in populated for unit in s.units}
    currencies = {code for s in populated for code in s.currency_codes}
    if len(units) > 1:
        notes.append(f"Units differ across countries: {', '.join(sorted(units))}.")
    if len(currencies) > 1:
        shown = ", ".join(sorted(c or "none" for c in currencies))
        notes.append(f"Currencies differ across countries: {shown}.")

    sources = {key for s in populated for key in s.source_keys}
    if len(sources) > 1:
        notes.append(f"Sources differ across countries: {', '.join(sorted(sources))}.")

    comparable = len(units) <= 1 and len(currencies) <= 1 and not mixed_within
    return comparable, notes


class ComparisonIndicator(BaseModel):
    """The single indicator being compared."""

    code: str
    name: str
    frequency: Frequency


class ComparisonSeries(BaseModel):
    """What one country brings to the comparison, including nothing at all."""

    model_config = ConfigDict(from_attributes=True)

    country_iso2: str
    country_iso3: str
    country_name: str
    units: list[str]
    currency_codes: list[str | None]
    source_keys: list[str]
    observations: int = Field(description="Active observations for this indicator and country.")
    first_period: str | None
    last_period: str | None


class ComparisonRow(BaseModel):
    """One period, with an entry for every requested country."""

    period_start: date
    period_end: date
    period_label: str
    values: dict[str, Decimal | None] = Field(
        description="Country ISO-3 to value. Null where that country has no figure."
    )


class ComparisonResponse(BaseModel):
    """A period-aligned comparison of one indicator across countries."""

    meta: PageMeta
    indicator: ComparisonIndicator
    comparable: bool = Field(
        description="False when the series differ in unit or currency. Sources differing "
        "does not make them incomparable."
    )
    comparability_notes: list[str]
    series: list[ComparisonSeries]
    data: list[ComparisonRow]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_comparison.py -q`
Expected: PASS, 6 tests.

- [ ] **Step 5: Gate and commit**

```bash
set -e
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy reim apps
.venv/bin/python -m pytest -q
git add reim/schemas/comparison.py tests/unit/test_comparison.py
git commit -m "feat(api): comparability rules and comparison response models

Comparability turns on unit and currency only. Differing sources are
reported but do not flip the flag: two publishers measuring the same
thing in the same unit is ordinary. Having no data is a gap to report,
not an incomparability."
```

---

### Task 3: The endpoint

**Files:**
- Create: `apps/api/routers/comparison.py`
- Modify: `apps/api/main.py`
- Test: `tests/integration/test_api.py`

**Interfaces:**
- Consumes: everything from Tasks 1 and 2.
- Produces: `GET /api/v1/compare` returning `ComparisonResponse`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_api.py`. The file's `client` fixture already
writes Nicaraguan observations; this adds a second country so there is
something to compare:

```python
# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------
@pytest.fixture
def compare_client(seeded_session: Session, make_observation) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    """A client with one indicator held by two countries, Guatemala missing a month."""
    from reim.services.observation_writer import write_observations

    write_observations(
        seeded_session,
        [
            make_observation(
                period,
                value,
                indicator_code="exports_goods_monthly",
                source_key=source,
                country_iso3=iso3,
                unit="current USD",
                currency_code="USD",
            )
            for period, value, iso3, source in (
                ("2024-01", "100", "NIC", "imf_imts_nicaragua"),
                ("2024-02", "110", "NIC", "imf_imts_nicaragua"),
                ("2024-03", "120", "NIC", "imf_imts_nicaragua"),
                ("2024-01", "500", "GTM", "imf_imts_guatemala"),
                ("2024-03", "520", "GTM", "imf_imts_guatemala"),
            )
        ],
        connector_version="1.0.0",
    )
    seeded_session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: seeded_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_compare_aligns_periods(compare_client: TestClient) -> None:
    body = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "exports_goods_monthly", "country": ["NI", "GT"]},
    ).json()

    assert body["meta"]["total"] == 3
    assert [row["period_label"] for row in body["data"]] == ["2024-01", "2024-02", "2024-03"]


def test_compare_reports_a_gap_as_an_explicit_null(compare_client: TestClient) -> None:
    """Guatemala has no February. The key must be present and null."""
    body = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "exports_goods_monthly", "country": ["NI", "GT"]},
    ).json()
    february = next(row for row in body["data"] if row["period_label"] == "2024-02")

    assert "GTM" in february["values"]
    assert february["values"]["GTM"] is None
    assert february["values"]["NIC"] == "110"


def test_compare_matches_the_observations_endpoint(compare_client: TestClient) -> None:
    """The comparison must not transform anything."""
    observations = compare_client.get(
        "/api/v1/observations",
        params={"country": "GT", "indicator": "exports_goods_monthly", "limit": 100},
    ).json()["data"]
    expected = {o["period_label"]: o["value_numeric"] for o in observations}

    body = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "exports_goods_monthly", "country": ["NI", "GT"]},
    ).json()
    got = {
        row["period_label"]: row["values"]["GTM"]
        for row in body["data"]
        if row["values"]["GTM"] is not None
    }

    assert got == expected


def test_compare_reports_series_metadata(compare_client: TestClient) -> None:
    body = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "exports_goods_monthly", "country": ["NI", "GT"]},
    ).json()
    series = {s["country_iso3"]: s for s in body["series"]}

    assert body["comparable"] is True
    assert series["NIC"]["observations"] == 3
    assert series["GTM"]["observations"] == 2
    assert series["NIC"]["units"] == ["current USD"]
    assert series["NIC"]["first_period"] == "2024-01"


def test_compare_names_a_country_holding_nothing(compare_client: TestClient) -> None:
    body = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "exports_goods_monthly", "country": ["NI", "HN"]},
    ).json()
    series = {s["country_iso3"]: s for s in body["series"]}

    assert series["HND"]["observations"] == 0
    assert all(row["values"]["HND"] is None for row in body["data"])
    assert any("HND" in note for note in body["comparability_notes"])


def test_compare_flags_differing_units(
    seeded_session: Session, compare_client: TestClient, make_observation
) -> None:  # type: ignore[no-untyped-def]
    """Not reachable from ingested data yet, but storable and served honestly."""
    from reim.services.observation_writer import write_observations

    write_observations(
        seeded_session,
        [
            make_observation(
                "2024-01",
                "9",
                indicator_code="exports_goods_monthly",
                source_key="imf_imts_honduras",
                country_iso3="HND",
                unit="lempiras",
                currency_code="HNL",
            )
        ],
        connector_version="1.0.0",
    )
    seeded_session.commit()

    body = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "exports_goods_monthly", "country": ["NI", "HN"]},
    ).json()

    assert body["comparable"] is False
    assert any("nit" in note for note in body["comparability_notes"])


def test_compare_paginates_periods(compare_client: TestClient) -> None:
    body = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "exports_goods_monthly", "country": ["NI", "GT"], "limit": 1},
    ).json()

    assert body["meta"]["total"] == 3
    assert body["meta"]["has_more"] is True
    assert len(body["data"]) == 1
    assert body["data"][0]["period_label"] == "2024-01"


def test_compare_orders_descending(compare_client: TestClient) -> None:
    body = compare_client.get(
        "/api/v1/compare",
        params={
            "indicator": "exports_goods_monthly",
            "country": ["NI", "GT"],
            "order": "desc",
        },
    ).json()

    assert body["data"][0]["period_label"] == "2024-03"


def test_compare_requires_at_least_two_countries(compare_client: TestClient) -> None:
    response = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "exports_goods_monthly", "country": ["NI"]},
    )

    assert response.status_code == 422


def test_compare_rejects_more_than_twenty_countries(compare_client: TestClient) -> None:
    response = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "exports_goods_monthly", "country": ["NI"] * 21},
    )

    assert response.status_code == 422


def test_compare_rejects_an_unknown_indicator(compare_client: TestClient) -> None:
    response = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "not_an_indicator", "country": ["NI", "GT"]},
    )

    assert response.status_code == 404


def test_compare_rejects_an_unknown_country(compare_client: TestClient) -> None:
    response = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "exports_goods_monthly", "country": ["NI", "ZZ"]},
    )

    assert response.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration -q`
Expected: FAIL — every compare request returns `404`, because the route does
not exist.

- [ ] **Step 3: Write the router**

Create `apps/api/routers/comparison.py`:

```python
"""Cross-country comparison endpoint."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from apps.api.dependencies import PaginationDep, SessionDep
from reim.core.exceptions import ResourceNotFoundError
from reim.database.models import Country
from reim.repositories.comparison import (
    ComparisonQuery,
    count_comparison_periods,
    fetch_comparison_cells,
    summarise_series,
)
from reim.repositories.reference import (
    get_country_by_iso2,
    get_country_by_iso3,
    get_indicator_by_code,
)
from reim.schemas.common import PageMeta
from reim.schemas.comparison import (
    ComparisonIndicator,
    ComparisonResponse,
    ComparisonRow,
    ComparisonSeries,
    assess_comparability,
)

router = APIRouter(prefix="/api/v1/compare", tags=["comparison"])


def _resolve_countries(session: SessionDep, codes: list[str]) -> list[Country]:
    """Resolve ISO-2 or ISO-3 codes to countries, preserving request order.

    Duplicates are dropped, so ?country=NI&country=NI is one column rather than
    two identical ones.
    """
    resolved: list[Country] = []
    seen: set[str] = set()
    for code in codes:
        value = code.upper()
        country = (
            get_country_by_iso2(session, value)
            if len(value) == 2
            else get_country_by_iso3(session, value)
        )
        if country is None:
            msg = f"Country {value!r} is not registered"
            raise ResourceNotFoundError(msg, country=value)
        if country.iso3 not in seen:
            seen.add(country.iso3)
            resolved.append(country)
    return resolved


@router.get("", response_model=ComparisonResponse, summary="Compare one indicator across countries")
def compare(
    session: SessionDep,
    pagination: PaginationDep,
    indicator: Annotated[str, Query(description="REIM indicator code.")],
    country: Annotated[
        list[str],
        Query(min_length=2, max_length=20, description="ISO alpha-2 or alpha-3 codes."),
    ],
    date_from: Annotated[
        date | None, Query(description="Earliest period start, inclusive (YYYY-MM-DD).")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="Latest period start, inclusive (YYYY-MM-DD).")
    ] = None,
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
) -> ComparisonResponse:
    """Return one indicator across several countries, aligned by period.

    Every row carries an entry for every requested country, ``null`` where that
    country publishes no figure: a gap is stated in the payload rather than
    inferred from a missing key.
    """
    definition = get_indicator_by_code(session, indicator)
    if definition is None:
        msg = f"Indicator {indicator!r} is not registered"
        raise ResourceNotFoundError(msg, indicator=indicator)

    countries = _resolve_countries(session, country)
    query = ComparisonQuery(
        indicator_code=definition.code,
        country_ids=tuple(c.id for c in countries),
        period_start_from=date_from,
        period_start_to=date_to,
    )

    total = count_comparison_periods(session, query)
    cells = fetch_comparison_cells(
        session,
        query,
        limit=pagination.limit,
        offset=pagination.offset,
        descending=order == "desc",
    )
    summaries = summarise_series(session, query, countries)
    comparable, notes = assess_comparability(summaries)

    requested = [c.iso3 for c in countries]
    rows: list[ComparisonRow] = []
    seen: dict[str, ComparisonRow] = {}
    for cell in cells:
        row = seen.get(cell.period_label)
        if row is None:
            row = ComparisonRow(
                period_start=cell.period_start,
                period_end=cell.period_end,
                period_label=cell.period_label,
                values=dict.fromkeys(requested),
            )
            seen[cell.period_label] = row
            rows.append(row)
        row.values[cell.country_iso3] = cell.value_numeric

    return ComparisonResponse(
        meta=PageMeta(
            total=total,
            limit=pagination.limit,
            offset=pagination.offset,
            returned=len(rows),
            has_more=pagination.offset + len(rows) < total,
        ),
        indicator=ComparisonIndicator(
            code=definition.code,
            name=definition.name,
            frequency=definition.frequency,
        ),
        comparable=comparable,
        comparability_notes=notes,
        series=[ComparisonSeries.model_validate(s) for s in summaries],
        data=rows,
    )
```

- [ ] **Step 4: Register the router**

In `apps/api/main.py`, add `comparison` to the `from apps.api.routers import (...)`
block, keeping the names alphabetical, and register it after the observations
router:

```text
    app.include_router(observations.router)
    app.include_router(comparison.router)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/integration -q`
Expected: PASS, including the twelve new comparison tests.

- [ ] **Step 6: Gate and commit**

```bash
set -e
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy reim apps
.venv/bin/python -m pytest -q
git add apps/api/routers/comparison.py apps/api/main.py tests/integration/test_api.py
git commit -m "feat(api): GET /api/v1/compare

One indicator across two to twenty countries, aligned by period. Every
row carries an entry per requested country, null where that country has
no figure, so a gap is stated rather than inferred.

Comparability is declared, not enforced: differing units flip a flag and
the notes name what differs, but the endpoint never refuses and never
converts."
```

---

### Task 4: Verify against real data and document

**Files:**
- Modify: `README.md`, `docs/implementation-plan.md`, `ROADMAP.md`

- [ ] **Step 1: Run the full suite**

```bash
make db-up CONTAINER_ENGINE=podman
export REIM_TEST_DATABASE_URL="postgresql+psycopg://reim:reim@localhost:55432/reim"
set -e
.venv/bin/python -m pytest -q
```

Expected: PASS with no skipped integration tests. This machine has no Docker
daemon; `CONTAINER_ENGINE=podman` is required.

- [ ] **Step 2: Serve the real six-country data**

```bash
export REIM_DATABASE_URL="postgresql+psycopg://reim:reim@localhost:55432/reim"
.venv/bin/alembic upgrade head
.venv/bin/reim db seed
for c in nicaragua guatemala el_salvador honduras costa_rica panama; do
  .venv/bin/reim pipeline run "imf_imts_$c" >/dev/null 2>&1
done
.venv/bin/uvicorn apps.api.main:app --port 8123 --log-level warning &
sleep 4
curl -s 'http://localhost:8123/api/v1/compare?indicator=exports_goods_monthly&country=NI&country=GT&country=CR&country=HN&country=SV&country=PA&limit=3&order=desc' \
  | python3 -m json.tool | head -40
kill %1
```

Expected: `meta.total` is **436**, `comparable` is `true`,
`comparability_notes` is empty, `series` has six entries of 436 observations
each, and every row's `values` object has six keys with no nulls.

- [ ] **Step 3: Check the honest cases against real data**

```bash
.venv/bin/uvicorn apps.api.main:app --port 8123 --log-level warning &
sleep 4
echo "--- an indicator only Nicaragua holds ---"
curl -s 'http://localhost:8123/api/v1/compare?indicator=ni_cpi_index_monthly&country=NI&country=GT&limit=2' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('notes:', d['comparability_notes']); print('series:', [(s['country_iso3'], s['observations']) for s in d['series']]); print('first row:', d['data'][0]['values'] if d['data'] else 'none')"
echo "--- one country is a 422 ---"
curl -s -o /dev/null -w "%{http_code}\n" 'http://localhost:8123/api/v1/compare?indicator=exports_goods_monthly&country=NI'
kill %1
```

Expected: Guatemala reported with `observations: 0`, a note naming `GTM`, its
column `null` in every row, and `422` for the single-country request.

- [ ] **Step 4: Update the documentation**

`README.md` — add `/api/v1/compare` wherever the endpoints are listed, update
the test count, and state in one line that the comparison endpoint reports gaps
as explicit nulls and never converts currencies.

`docs/implementation-plan.md` — add `## 16. Post-MVP increment — comparison
endpoint (2026-08-08)` with a verification table covering Steps 1–3, and note
that piece B of v0.3.0 is delivered.

`ROADMAP.md` — under v0.3.0, mark the comparison endpoints done, recording that
`comparable` turns on unit and currency, that gaps are explicit nulls, and that
currency handling remains open and deliberately separate.

- [ ] **Step 5: Final gate and commit**

```bash
export REIM_TEST_DATABASE_URL="postgresql+psycopg://reim:reim@localhost:55432/reim"
set -e
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy reim apps
.venv/bin/reim catalog validate
git add README.md docs/ ROADMAP.md
git commit -m "docs: record the comparison endpoint

Piece B of v0.3.0. Verified against the real six-country series: 436
aligned periods, no nulls, comparable true; and against an indicator
only Nicaragua holds, where the other country is reported with zero
observations and a null column rather than being dropped."
podman stop reim-test-postgres
```

---

## Self-review notes

**Spec coverage.** §2 parameters → Task 3 Step 3; §3 response shape → Task 2 models and Task 3 pivot; §3.1 rectangular nulls → Task 3's `dict.fromkeys(requested)` and `test_compare_reports_a_gap_as_an_explicit_null`; §3.2 comparability → Task 2 `assess_comparability`; §4 C1–C7 → C1 Task 3, C2 Task 3, C3 Task 2, C4 Task 3 Step 3, C5 nothing converts anywhere, C6 `Decimal` fields serialise as strings, C7 `_restrict` filters `ACTIVE`; §5.1 → Task 1; §5.2 → Task 2; §5.3 → Task 3; §6 testing → Tasks 1–3; §7 risks → the value-parity test in Task 3.

**Two refinements to the spec, both already folded back into it.**

- The spec said the `comparable: false` branch could only be covered by constructed unit tests. It is also **integration**-testable: two countries can hold one indicator with different units, verified against the real writer — 2 inserted, 0 rejected. Task 3 has that test.
- `units` and `currency_codes` became **lists**, symmetric with `source_keys`. A single country's series can carry more than one over time, and a scalar would hide it. `assess_comparability` therefore also flags a single country carrying two units, which a scalar model could not have expressed.

**Deliberate design points a reviewer should check rather than assume.**

- Pagination slices **periods**, not observation rows. `test_paging_slices_periods_not_cells` is the guard: `limit=1` must return one period carrying two cells, not one cell.
- `_resolve_countries` drops duplicates, so `?country=NI&country=NI` yields one column. It preserves request order, so the caller controls column order.
- `has_more` is computed from period counts, consistent with `total` counting periods.

**Verified against the codebase, not assumed:** `ResourceNotFoundError` maps to
404 through the existing `REIMError` handler; `PaginationDep` caps `limit` at
`REIM_MAX_PAGE_SIZE`; `make_observation` accepts `country_iso3`, `unit` and
`currency_code`; a lone integration file fails on `TRUNCATE` because the schema
setup is session-scoped, so the whole `tests/integration` directory must be run.
