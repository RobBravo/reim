# Time-Series Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `GET /series` — one indicator plotted over time across several countries, server-rendered as SVG with no JavaScript, sharing an axis only when both comparability flags allow it.

**Architecture:** The view calls `reim.repositories.comparison` directly and adds no query of its own. All computation that does not need a session — shaping cells into rows, axis ticks, scales, SVG paths — lives in a new `apps/web/charts.py` of pure functions, which is where the exhaustive tests go. The value table beneath each chart is the SVG's accessible equivalent and the test surface both.

**Tech Stack:** FastAPI, Jinja2, SQLAlchemy 2 (PostgreSQL), Pydantic v2, pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-12-time-series-dashboard-design.md`

## Global Constraints

* **No JavaScript, no charting library, no CDN, no build step.** The SVG is written by our own code (spec D1).
* **Nothing is downsampled, smoothed, or interpolated.** REIM "never rounds a published figure and never fills a gap" — a gap **breaks the line**, it is never bridged (spec D5).
* **Views call repositories and services, never the app's own HTTP API.** Pinned by `test_the_pages_make_no_outbound_http_requests` in `tests/integration/test_web.py`.
* **Database availability is discovered by querying and catching `SQLAlchemyError`, never by a pre-check.** `check_database_connection()` must not appear in `apps/web/routes.py`.
* **Tests assert content, not markup — and never a `<path>`'s `d` attribute or any coordinate.** Assert the table's figures, the series names, the source links, the notes, and the `<svg>`'s `<title>`/`<desc>` text. A chart whose geometry moves by a pixel must not fail a test; a chart that lost a country must (spec D7).
* **Every one of the nine states in spec §6 gets its own sentence.** No two conditions may render the same words.
* **The verification gate, which must pass before every commit:**
  ```bash
  .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q
  ```
* **No `pip` in the venv** — use `.venv/bin/<tool>`. Test database: `make db-up CONTAINER_ENGINE=podman` prints the `export REIM_TEST_DATABASE_URL=...` line; standalone `alembic upgrade head` needs `REIM_DATABASE_URL` exported too.
* **mypy strict** over `reim` and `apps`. Test functions need `-> None`.
* `ruff format` rewrites ```python blocks in Markdown that are not valid standalone modules; fence such fragments as ```text.

---

## File Structure

| File | Responsibility |
|---|---|
| `apps/web/charts.py` (create) | Everything computed without a session: pivoting cells into rows, tick selection, scales, SVG paths |
| `apps/web/routes.py` (modify) | The `/series` view, parameter parsing, the two 404s, the database call |
| `apps/web/templates/series.html` (create) | The form, the chart(s), the value table, and seven of the nine states |
| `apps/web/templates/series_not_found.html` (create) | States 3 and 4 — an unregistered indicator or country |
| `apps/web/templates/base.html` (modify) | A third nav link |
| `apps/web/static/reim.css` (modify) | Chart, legend and small-multiple styling |
| `tests/unit/test_charts.py` (create) | Every branch of `charts.py`, no database |
| `tests/integration/test_web_series.py` (create) | The page and all nine states |
| `tests/integration/test_web.py` (modify) | Add `/series` to the outbound-HTTP guard |
| `ROADMAP.md`, `README.md` (modify) | Mark v0.4.0's last increment done; describe the page |

---

### Task 1: The pure functions — pivoting and geometry

**Files:**
- Create: `apps/web/charts.py`
- Test: `tests/unit/test_charts.py`

**Interfaces:**
- Consumes: `ComparisonCell` from `reim.repositories.comparison` (fields `period_start: date`, `period_end: date`, `period_label: str`, `country_iso3: str`, `value_numeric: Decimal | None`, `currency_code: str | None`).
- Produces, relied on by Tasks 2, 3 and 4:
  ```text
  SeriesRow(period_start: date, period_label: str, values: dict[str, Decimal | None])
  pivot_cells(cells, iso3_order) -> list[SeriesRow]
  Scale(domain_min, domain_max, pixel_min, pixel_max).to_pixel(value: float) -> float
  nice_ticks(minimum: float, maximum: float, count: int = 5) -> list[float]
  value_domain(rows, iso3_codes) -> tuple[float, float] | None
  series_path(points, x_scale, y_scale) -> str
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_charts.py`:

```python
"""``apps/web/charts.py``: everything the series page computes without a session.

Axis ticks, scales and path building are where chart bugs actually live —
ticks at 0.0000001 intervals, a division by zero on a constant series, a line
drawn straight across a gap the publisher never filled. None of it needs a
database, a request or a template, so all of it is tested directly here
rather than inferred from a rendered page.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.web.charts import (
    Scale,
    SeriesRow,
    nice_ticks,
    pivot_cells,
    series_path,
    value_domain,
)
from reim.repositories.comparison import ComparisonCell


def _cell(iso3: str, year: int, value: str | None) -> ComparisonCell:
    return ComparisonCell(
        period_start=date(year, 1, 1),
        period_end=date(year, 12, 31),
        period_label=str(year),
        country_iso3=iso3,
        value_numeric=None if value is None else Decimal(value),
        currency_code=None,
    )


def test_pivot_gives_every_country_a_key_in_every_row() -> None:
    """A gap is stated, never implied by a missing key.

    ``/compare`` makes the same promise in JSON; the page must not quietly
    reintroduce the ambiguity by leaving a country out of a row.
    """
    cells = [_cell("NIC", 2020, "1"), _cell("GTM", 2020, "2"), _cell("NIC", 2021, "3")]

    rows = pivot_cells(cells, ["NIC", "GTM"])

    assert [row.period_label for row in rows] == ["2020", "2021"]
    assert rows[0].values == {"NIC": Decimal("1"), "GTM": Decimal("2")}
    assert rows[1].values == {"NIC": Decimal("3"), "GTM": None}


def test_pivot_orders_rows_oldest_first() -> None:
    """A time axis reads left to right; the caller must not have to sort."""
    rows = pivot_cells([_cell("NIC", 2022, "1"), _cell("NIC", 2020, "2")], ["NIC"])

    assert [row.period_label for row in rows] == ["2020", "2022"]


def test_pivot_of_nothing_is_no_rows() -> None:
    assert pivot_cells([], ["NIC"]) == []


def test_the_domain_spans_every_country_shown() -> None:
    rows = [
        SeriesRow(date(2020, 1, 1), "2020", {"NIC": Decimal("5"), "GTM": Decimal("-2")}),
        SeriesRow(date(2021, 1, 1), "2021", {"NIC": Decimal("9"), "GTM": None}),
    ]

    assert value_domain(rows, ["NIC", "GTM"]) == (-2.0, 9.0)


def test_the_domain_ignores_countries_not_being_shown() -> None:
    """Small multiples scale each panel on its own country, not on all of them."""
    rows = [SeriesRow(date(2020, 1, 1), "2020", {"NIC": Decimal("5"), "GTM": Decimal("900")})]

    assert value_domain(rows, ["NIC"]) == (5.0, 5.0)


def test_a_series_with_no_values_has_no_domain() -> None:
    """``None`` rather than a fabricated ``(0, 1)``: there is nothing to scale."""
    rows = [SeriesRow(date(2020, 1, 1), "2020", {"NIC": None})]

    assert value_domain(rows, ["NIC"]) is None


def test_a_scale_maps_the_domain_onto_the_pixels() -> None:
    scale = Scale(domain_min=0.0, domain_max=10.0, pixel_min=0.0, pixel_max=100.0)

    assert scale.to_pixel(0.0) == 0.0
    assert scale.to_pixel(5.0) == 50.0
    assert scale.to_pixel(10.0) == 100.0


def test_a_scale_inverts_when_the_pixels_run_backwards() -> None:
    """SVG's y axis grows downward, so the value axis is built inverted."""
    scale = Scale(domain_min=0.0, domain_max=10.0, pixel_min=200.0, pixel_max=0.0)

    assert scale.to_pixel(0.0) == 200.0
    assert scale.to_pixel(10.0) == 0.0


def test_a_constant_series_lands_in_the_middle_rather_than_dividing_by_zero() -> None:
    scale = Scale(domain_min=7.0, domain_max=7.0, pixel_min=0.0, pixel_max=100.0)

    assert scale.to_pixel(7.0) == 50.0


@pytest.mark.parametrize(
    ("minimum", "maximum", "expected"),
    [
        (0.0, 100.0, [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]),
        (0.0, 1.0, [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]),
        (-5.0, 5.0, [-4.0, -2.0, 0.0, 2.0, 4.0]),
        (0.001, 0.005, [0.001, 0.002, 0.003, 0.004, 0.005]),
        (
            1_000_000.0,
            3_000_000.0,
            [1_000_000.0, 1_500_000.0, 2_000_000.0, 2_500_000.0, 3_000_000.0],
        ),
    ],
)
def test_ticks_are_round_numbers_at_every_magnitude(
    minimum: float, maximum: float, expected: list[float]
) -> None:
    assert nice_ticks(minimum, maximum) == expected


def test_a_constant_series_gets_one_tick_saying_what_the_value_is() -> None:
    """There is no range to divide, but the reader still needs the number."""
    assert nice_ticks(42.0, 42.0) == [42.0]


def test_ticks_never_run_outside_the_domain() -> None:
    ticks = nice_ticks(3.3, 7.7)

    assert ticks
    assert min(ticks) >= 3.3
    assert max(ticks) <= 7.7


def test_a_reversed_domain_is_read_the_right_way_round() -> None:
    assert nice_ticks(100.0, 0.0) == nice_ticks(0.0, 100.0)


def test_a_path_of_nothing_is_empty() -> None:
    scale = Scale(0.0, 1.0, 0.0, 1.0)

    assert series_path([], scale, scale) == ""


def test_a_gap_breaks_the_line_instead_of_being_bridged() -> None:
    """The whole reason this function exists.

    REIM never fills a gap. Joining the points either side of a missing
    period would draw a value the publisher never reported — indistinguishable,
    to the eye, from data.
    """
    x_scale = Scale(domain_min=0.0, domain_max=2.0, pixel_min=0.0, pixel_max=200.0)
    y_scale = Scale(domain_min=0.0, domain_max=10.0, pixel_min=100.0, pixel_max=0.0)

    path = series_path([(0.0, 1.0), (1.0, None), (2.0, 3.0)], x_scale, y_scale)

    assert path.count("M") == 2, f"the gap did not break the line: {path}"
    assert path.count("L") == 0


def test_a_run_of_values_is_one_stroke() -> None:
    x_scale = Scale(0.0, 2.0, 0.0, 200.0)
    y_scale = Scale(0.0, 10.0, 100.0, 0.0)

    path = series_path([(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)], x_scale, y_scale)

    assert path.count("M") == 1
    assert path.count("L") == 2


def test_a_series_that_is_entirely_gaps_draws_nothing() -> None:
    scale = Scale(0.0, 1.0, 0.0, 1.0)

    assert series_path([(0.0, None), (1.0, None)], scale, scale) == ""
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_charts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.web.charts'`

- [ ] **Step 3: Write the module**

Create `apps/web/charts.py`:

```python
"""Everything the series page computes without a session.

Nothing here touches a database, a request or a template, which is what makes
it testable directly rather than through a rendered page. Two
responsibilities, both pure: shaping the repository's flat cells into rows,
and the geometry that turns rows into an SVG.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from reim.repositories.comparison import ComparisonCell


@dataclass(frozen=True, slots=True)
class SeriesRow:
    """Every requested country's figure for one period.

    ``values`` holds a key for **every** requested country, ``None`` where
    that country published nothing. A missing key would make a gap
    indistinguishable from a country that was never asked for — the same
    promise ``/compare`` makes in JSON.
    """

    period_start: date
    period_label: str
    values: dict[str, Decimal | None]


def pivot_cells(cells: Iterable[ComparisonCell], iso3_order: Sequence[str]) -> list[SeriesRow]:
    """Turn the repository's flat cells into one row per period, oldest first.

    Oldest first because a time axis reads left to right, and sorting here
    means no caller has to remember to.
    """
    by_period: dict[date, SeriesRow] = {}
    for cell in cells:
        row = by_period.get(cell.period_start)
        if row is None:
            row = SeriesRow(
                period_start=cell.period_start,
                period_label=cell.period_label,
                values=dict.fromkeys(iso3_order),
            )
            by_period[cell.period_start] = row
        if cell.country_iso3 in row.values:
            row.values[cell.country_iso3] = cell.value_numeric
    return [by_period[key] for key in sorted(by_period)]


def value_domain(
    rows: Sequence[SeriesRow], iso3_codes: Sequence[str]
) -> tuple[float, float] | None:
    """Return the lowest and highest value among ``iso3_codes``, or ``None``.

    ``None`` when those countries published nothing at all: there is no range
    to scale, and inventing ``(0, 1)`` would draw an axis describing data that
    does not exist.

    Restricted to the countries being drawn, because a small-multiple panel
    scales on its own country — sharing one domain across panels would
    reintroduce exactly the cross-country comparison small multiples exist to
    prevent.
    """
    values = [
        float(value)
        for row in rows
        for code in iso3_codes
        if (value := row.values.get(code)) is not None
    ]
    if not values:
        return None
    return min(values), max(values)


@dataclass(frozen=True, slots=True)
class Scale:
    """Maps a value in the data's domain onto a pixel coordinate.

    ``pixel_min`` may be greater than ``pixel_max``: SVG's y axis grows
    downward, so the value axis is built inverted and the same arithmetic
    serves both.
    """

    domain_min: float
    domain_max: float
    pixel_min: float
    pixel_max: float

    def to_pixel(self, value: float) -> float:
        """Return the pixel coordinate for ``value``.

        A zero-width domain — a series that never changes — puts every point
        at the midpoint rather than dividing by zero. A flat line through the
        middle is the honest picture of a constant series.
        """
        span = self.domain_max - self.domain_min
        if span == 0:
            return (self.pixel_min + self.pixel_max) / 2
        ratio = (value - self.domain_min) / span
        return self.pixel_min + ratio * (self.pixel_max - self.pixel_min)


#: Step sizes a reader recognises as round, in units of the step's magnitude.
_NICE_MULTIPLES = (1.0, 2.0, 2.5, 5.0, 10.0)


def nice_ticks(minimum: float, maximum: float, count: int = 5) -> list[float]:
    """Return round tick values inside ``[minimum, maximum]``.

    Ticks stay strictly within the domain rather than extending past it: an
    axis labelled beyond the data invites the reader to believe the series
    reaches values it never does.

    A constant series returns the single value. There is no range to divide,
    and the reader still needs the number.
    """
    if count < 1:
        msg = f"count must be at least 1, got {count}"
        raise ValueError(msg)
    if minimum > maximum:
        minimum, maximum = maximum, minimum
    if minimum == maximum:
        return [minimum]

    raw_step = (maximum - minimum) / count
    magnitude = 10.0 ** math.floor(math.log10(raw_step))
    step = next(
        (multiple * magnitude for multiple in _NICE_MULTIPLES if raw_step <= multiple * magnitude),
        10.0 * magnitude,
    )
    first = math.ceil(minimum / step) * step
    total = int(math.floor((maximum - first) / step)) + 1
    return [round(first + index * step, 10) for index in range(max(total, 0))]


def series_path(
    points: Sequence[tuple[float, float | None]], x_scale: Scale, y_scale: Scale
) -> str:
    """Return the SVG ``d`` for one series, breaking the line at every gap.

    A ``None`` value is a period the publisher did not report. The stroke
    stops and restarts rather than joining its neighbours across it: a segment
    drawn over a gap invents a value REIM does not have, and to the eye it is
    indistinguishable from data. Not filling gaps is the project's oldest
    promise; here it is a drawing rule.
    """
    commands: list[str] = []
    pen_is_down = False
    for x_value, y_value in points:
        if y_value is None:
            pen_is_down = False
            continue
        x_pixel = round(x_scale.to_pixel(x_value), 2)
        y_pixel = round(y_scale.to_pixel(y_value), 2)
        commands.append(f"{'L' if pen_is_down else 'M'} {x_pixel} {y_pixel}")
        pen_is_down = True
    return " ".join(commands)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_charts.py -q`
Expected: PASS (20 tests)

If a `nice_ticks` parametrised case disagrees with the implementation, **check the expectation by hand before changing either** — `nice_ticks(0.0, 1.0)` should give six ticks at 0.2 intervals, and `nice_ticks(-5.0, 5.0)` five at 2.0 starting at -4.0 (0 is not a tick boundary requirement; staying inside the domain is). Fix whichever is actually wrong and say which in your report.

- [ ] **Step 5: Run the whole gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q
git add apps/web/charts.py tests/unit/test_charts.py
git commit -m "feat(web): the arithmetic behind a chart, with gaps that stay gaps"
```

---

### Task 2: The route, the form, and every state that draws nothing

**Files:**
- Modify: `apps/web/routes.py` (append the view and its helpers)
- Create: `apps/web/templates/series.html`, `apps/web/templates/series_not_found.html`
- Test: `tests/integration/test_web_series.py`

**Interfaces:**
- Consumes from Task 1: `pivot_cells`, `SeriesRow`.
- Produces, relied on by Tasks 3 and 4:
  ```text
  PERIOD_LIMIT: int = 1500
  SeriesPageData(indicator, countries, rows, summaries, comparable,
                 levels_comparable, notes, total_periods)
  load_series_page(session, indicator, countries, date_from, date_to) -> SeriesPageData | None
  ```
  The template receives `data` (`None` when the database did not answer), `indicator_options`, `country_options`, `selection`, and `period_limit`.

**This task delivers a working page that never draws a chart** — the form, the value table, and states 1, 2, 3, 4, 5, 6 and 9 of spec §6. Tasks 3 and 4 add the SVG. Leave a placeholder comment where the chart will go; do not build a partial one.

**Both 404s are decided before any database access**, because the indicator and country registries are in-process (`INDICATORS_BY_CODE`, `COUNTRIES_BY_ISO2`, `COUNTRIES_BY_ISO3`). A mistyped indicator therefore gets a proper 404 even when PostgreSQL is down. Keep that ordering.

As on the run-detail page, the view **does not raise** `ResourceNotFoundError`: every handler in `apps/api/errors.py` returns JSON unconditionally, which is right for the API and useless to a browser.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_web_series.py`:

```python
"""The series page: the form, the value table, and the states that draw nothing.

The chart itself arrives in later tasks. What is pinned here is that every one
of the page's no-chart states says its own sentence — an operator who cannot
tell "the database is down" from "you asked for an indicator that does not
exist" from "these countries hold no data" cannot act on any of them.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.dependencies import get_db
from apps.api.main import create_app
from reim.database.models import Observation
from reim.repositories.reference import (
    get_country_by_iso3,
    get_indicator_by_code,
    get_source_by_key,
)
from tests.conftest import requires_db


@pytest.fixture
def client(seeded_session: Session) -> Iterator[TestClient]:
    """A client backed by a seeded schema: countries, indicators and sources."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: seeded_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _add_observation(
    session: Session,
    *,
    iso3: str,
    code: str,
    year: int,
    value: str,
    unit: str = "index",
) -> None:
    """Store one annual observation.

    ``value`` is required: ``observations`` carries
    ``CheckConstraint("value_numeric IS NOT NULL OR value_text IS NOT NULL")``,
    so a gap is **the absence of a row**, never a row holding null. Build a gap
    by giving one country a period its neighbour has and not inserting the
    other's.

    ``unit`` is a parameter because comparability turns on it: two countries
    reporting in different units make ``comparable`` false, and one country
    reporting in two units over time is the case decision D4 refuses to chart.
    """
    country = get_country_by_iso3(session, iso3)
    indicator = get_indicator_by_code(session, code)
    source = get_source_by_key(session, "worldbank_ni_cpi_inflation")
    assert country is not None, f"{iso3} is not seeded"
    assert indicator is not None, f"{code} is not seeded"
    assert source is not None, "the catalog sources are not seeded"
    session.add(
        Observation(
            id=uuid.uuid4(),
            country_id=country.id,
            indicator_id=indicator.id,
            source_id=source.id,
            period_start=date(year, 1, 1),
            period_end=date(year, 12, 31),
            period_label=str(year),
            value_numeric=Decimal(value),
            unit=unit,
            currency_code=None,
            retrieved_at=datetime.now(UTC),
            source_url="https://example.invalid/series",
            content_hash=f"{iso3}-{code}-{year}-{value}",
            connector_version="0.0.0",
            pipeline_version="0.0.0",
        )
    )
    session.flush()


def test_the_series_page_is_served_with_no_selection() -> None:
    """State 1: the first visit is a form, not an error and not an empty chart."""
    client = TestClient(create_app())

    response = client.get("/series")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_the_form_offers_every_indicator_and_every_country() -> None:
    """A picker missing an option is a page that cannot answer a fair question."""
    from reim.domain.countries.registry import COUNTRIES
    from reim.domain.indicators.registry import INDICATORS

    client = TestClient(create_app())

    body = client.get("/series").text

    assert len(INDICATORS) == 63
    assert len(COUNTRIES) == 7
    for country in COUNTRIES:
        assert country.name in body, f"{country.name} is missing from the form"
    for indicator in INDICATORS:
        assert indicator.code in body, f"{indicator.code} is missing from the form"


def test_an_unregistered_indicator_gets_a_page_not_a_json_envelope() -> None:
    """State 3 — and it must not need a database to answer."""
    client = TestClient(create_app())

    response = client.get("/series?indicator=no_such_indicator&country=NIC")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "no_such_indicator" in response.text


def test_an_unregistered_country_gets_the_same_page() -> None:
    """State 4, named separately from the indicator so the reader knows which."""
    client = TestClient(create_app())

    response = client.get("/series?indicator=cpi_index_monthly&country=ZZZ")

    assert response.status_code == 404
    assert "ZZZ" in response.text


def test_a_dead_database_is_said_out_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    """State 2, distinct from every "nothing to show" sentence on the page."""

    def _raise(*args: object, **kwargs: object) -> None:
        raise SQLAlchemyError("database is down")

    monkeypatch.setattr("apps.web.routes.comparison_repo.count_comparison_periods", _raise)
    client = TestClient(create_app())

    body = client.get("/series?indicator=cpi_index_monthly&country=NIC").text

    assert "database is not responding" in body.lower()
    assert "holds no data" not in body.lower()


@requires_db
def test_a_valid_selection_with_no_data_says_so(client: TestClient) -> None:
    """State 5: the seeded schema has reference data and no observations."""
    body = client.get("/series?indicator=cpi_index_monthly&country=NIC").text

    assert "holds no data" in body.lower()
    assert "database is not responding" not in body.lower()


@requires_db
def test_the_countries_holding_nothing_are_named_not_dropped(
    client: TestClient, seeded_session: Session
) -> None:
    """State 6: a silently missing country reads as a country with a flat line."""
    _add_observation(seeded_session, iso3="NIC", code="cpi_index_monthly", year=2020, value="5.5")

    body = client.get("/series?indicator=cpi_index_monthly&country=NIC&country=GTM").text

    assert "Guatemala" in body
    assert "no data" in body.lower()


@requires_db
def test_the_table_carries_every_figure(client: TestClient, seeded_session: Session) -> None:
    """The table is the chart's accessible equivalent and the test surface both."""
    _add_observation(seeded_session, iso3="NIC", code="cpi_index_monthly", year=2020, value="5.5")
    _add_observation(seeded_session, iso3="NIC", code="cpi_index_monthly", year=2021, value="7.25")

    body = client.get("/series?indicator=cpi_index_monthly&country=NIC").text

    assert "5.5" in body
    assert "7.25" in body
    assert "2020" in body
    assert "2021" in body
```

**The helper's columns were measured, not guessed** (`reim/database/models/observation.py:47-90`): `source_id`, `unit`, `source_url`, `content_hash`, `connector_version` and `pipeline_version` are all NOT NULL. Measuring it also surfaced `CheckConstraint("value_numeric IS NOT NULL OR value_text IS NOT NULL")` — **a gap is the absence of a row, not a row holding null** — which is why `value` is required above.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/integration/test_web_series.py -q`
Expected: FAIL — `/series` returns 404, the route does not exist.

- [ ] **Step 3: Add the view**

In `apps/web/routes.py`, extend the imports:

```python
from apps.web.charts import SeriesRow, pivot_cells
from reim.domain.countries.registry import COUNTRIES, COUNTRIES_BY_ISO2, COUNTRIES_BY_ISO3
from reim.domain.countries.registry import CountryDefinition
from reim.domain.indicators.registry import INDICATORS, INDICATORS_BY_CODE, IndicatorDefinition
from reim.repositories import comparison as comparison_repo
from reim.repositories.comparison import ComparisonQuery, SeriesSummary
from reim.repositories.reference import get_country_by_iso3
from reim.schemas.comparison import assess_comparability, levels_comparable
```

Add the constant beside `RUN_HISTORY_LIMIT`:

```python
#: How many distinct periods one chart may draw. Nothing is ever downsampled —
#: REIM does not discard published figures to cheapen a drawing — so a denser
#: range is refused with an explanation instead. The cap bites only on the two
#: daily sources (BCN and Banguat exchange rates): 1,500 points is about four
#: years of daily data, but 125 years of monthly and 375 of quarterly.
PERIOD_LIMIT = 1500
```

Then the view and its helpers:

```python
@dataclass(frozen=True)
class SeriesPageData:
    """Everything ``/series`` draws once a selection resolves."""

    indicator: IndicatorDefinition
    countries: list[CountryDefinition]
    rows: list[SeriesRow]
    summaries: list[SeriesSummary]
    comparable: bool
    levels_comparable: bool
    notes: list[str]
    total_periods: int


def load_series_page(
    session: Session,
    indicator: IndicatorDefinition,
    countries: list[CountryDefinition],
    date_from: date | None,
    date_to: date | None,
) -> SeriesPageData | None:
    """Return the page's data, or ``None`` when the database did not answer.

    Four queries share one ``try``: with any of them failing there is no
    partial page worth rendering, and one ``except`` means one place decides
    "unreachable" — the same argument ``load_pipeline_summaries`` and
    ``load_runs_page`` make, and the reason none of them pings the database
    first.

    ``total_periods`` is counted before the cells are fetched so the page can
    say how dense a range is even when it declines to draw it.
    """
    try:
        resolved = [get_country_by_iso3(session, country.iso3) for country in countries]
        query = ComparisonQuery(
            indicator_code=indicator.code,
            country_ids=tuple(row.id for row in resolved if row is not None),
            period_start_from=date_from,
            period_start_to=date_to,
        )
        total_periods = comparison_repo.count_comparison_periods(session, query)
        cells = (
            comparison_repo.fetch_comparison_cells(
                session, query, limit=PERIOD_LIMIT, offset=0, descending=False
            )
            if total_periods <= PERIOD_LIMIT
            else []
        )
        summaries = comparison_repo.summarise_series(
            session, query, [row for row in resolved if row is not None]
        )
    except SQLAlchemyError:
        return None

    definition = INDICATORS_BY_CODE.get(indicator.code)
    comparable, notes = assess_comparability(summaries, definition)
    return SeriesPageData(
        indicator=indicator,
        countries=countries,
        rows=pivot_cells(cells, [country.iso3 for country in countries]),
        summaries=summaries,
        comparable=comparable,
        levels_comparable=levels_comparable(definition),
        notes=notes,
        total_periods=total_periods,
    )


@router.get("/series", response_class=HTMLResponse)
def series(
    request: Request,
    session: SessionDep,
    indicator: str | None = None,
    country: Annotated[list[str] | None, Query()] = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> HTMLResponse:
    """One indicator over time across several countries.

    The indicator and the countries are resolved from the in-process
    registries **before** any database access, so a mistyped code answers with
    a proper 404 page even when PostgreSQL is unreachable. The view never
    raises ``ResourceNotFoundError``: every handler in ``apps/api/errors.py``
    answers in JSON, which is right for the API and useless to a browser.
    """
    context: dict[str, object] = {
        "indicator_options": INDICATORS,
        "country_options": COUNTRIES,
        "selection": {
            "indicator": indicator,
            "country": country or [],
            "date_from": date_from,
            "date_to": date_to,
        },
        "period_limit": PERIOD_LIMIT,
        "data": None,
    }

    if not indicator or not country:
        # State 1: nothing chosen yet. Not an error, and not an empty chart.
        return templates.TemplateResponse(request, "series.html", context)

    definition = INDICATORS_BY_CODE.get(indicator)
    if definition is None:
        return _series_not_found(request, "indicator", indicator)

    countries: list[CountryDefinition] = []
    seen: set[str] = set()
    for code in country:
        value = code.upper()
        found = COUNTRIES_BY_ISO2.get(value) if len(value) == 2 else COUNTRIES_BY_ISO3.get(value)
        if found is None:
            return _series_not_found(request, "country", value)
        if found.iso3 not in seen:
            seen.add(found.iso3)
            countries.append(found)

    context["data"] = load_series_page(session, definition, countries, date_from, date_to)
    context["selection"] = {
        "indicator": indicator,
        "country": [c.iso3 for c in countries],
        "date_from": date_from,
        "date_to": date_to,
    }
    return templates.TemplateResponse(request, "series.html", context)


def _series_not_found(request: Request, kind: str, value: str) -> HTMLResponse:
    """States 3 and 4 — an unregistered indicator or country, named as such."""
    return templates.TemplateResponse(
        request, "series_not_found.html", {"kind": kind, "value": value}, status_code=404
    )
```

`Annotated`, `Query` and `date` need importing; check what `apps/web/routes.py` already has before adding.

- [ ] **Step 4: Create `series_not_found.html`**

```html
{% extends "base.html" %}

{% block title %}Not found · REIM{% endblock %}

{% block content %}
<section class="series">
  <h2>{{ kind | capitalize }} not found</h2>
  {#
    The value is echoed back because the commonest way here is a mistyped or
    truncated link, and the reader cannot check it against what they meant
    unless they can see it. The kind is named because "not found" alone leaves
    them guessing which half of the request was wrong.
  #}
  <p>No {{ kind }} is registered under <code>{{ value }}</code>.</p>
  <p><a href="/series">Back to the series picker</a></p>
</section>
{% endblock %}
```

- [ ] **Step 5: Create `series.html` — the form, the table, and the no-chart states**

```html
{% extends "base.html" %}

{% block title %}Series · REIM{% endblock %}

{% block content %}
<section class="series">
  <h2>Series</h2>
  <p class="muted">One indicator over time, across the countries you choose.</p>

  {#
    A plain GET form: the browser serialises and reloads, so the page needs no
    JavaScript at all. The indicator and country lists come from the in-process
    registries, so the form renders even when the database is unreachable.
  #}
  <form class="series-form" method="get" action="/series">
    <label for="indicator">Indicator</label>
    <select id="indicator" name="indicator">
      <option value="">Choose an indicator</option>
      {% for option in indicator_options %}
      <option value="{{ option.code }}"{% if selection.indicator == option.code %} selected{% endif %}>
        {{ option.code }} &mdash; {{ option.name }} ({{ option.unit }})
      </option>
      {% endfor %}
    </select>

    <label for="country">Countries</label>
    <select id="country" name="country" multiple size="7">
      {% for option in country_options %}
      <option value="{{ option.iso3 }}"{% if option.iso3 in selection.country %} selected{% endif %}>
        {{ option.name }}
      </option>
      {% endfor %}
    </select>

    <label for="date_from">From</label>
    <input id="date_from" type="date" name="date_from" value="{{ selection.date_from or '' }}" />
    <label for="date_to">To</label>
    <input id="date_to" type="date" name="date_to" value="{{ selection.date_to or '' }}" />

    <button type="submit">Draw</button>
  </form>

  {% if not selection.indicator or not selection.country %}
  {# State 1. A first visit has nothing to say yet, and saying nothing is correct. #}
  <p class="muted">Choose an indicator and at least one country.</p>
  {% elif data is none %}
  {# State 2. Distinct from every "nothing to show" sentence below. #}
  <p class="notice" role="status">The series cannot be read: the database is not responding.</p>
  {% elif data.total_periods > period_limit %}
  {#
    State 9. Nothing is downsampled, so a denser range is declined with the
    number that makes the refusal actionable rather than mysterious.
  #}
  <p class="notice" role="status">
    This range holds {{ data.total_periods }} periods; the chart draws at most
    {{ period_limit }}. Narrow the dates.
  </p>
  {% elif not data.rows %}
  {# State 5. #}
  <p class="muted">
    No country you chose holds data for {{ data.indicator.name }}.
  </p>
  {% else %}
  {% set empty_countries = data.summaries | selectattr("observations", "equalto", 0) | list %}
  {% if empty_countries %}
  {# State 6: named, never silently dropped — a missing country reads as a flat line. #}
  <p class="muted">
    No data for
    {% for summary in empty_countries %}{{ summary.country_name }}{% if not loop.last %}, {% endif %}{% endfor %}.
  </p>
  {% endif %}

  {% if data.notes %}
  <ul class="comparability-notes">
    {% for note in data.notes %}<li>{{ note }}</li>{% endfor %}
  </ul>
  {% endif %}

  {# The chart is added in Task 3; small multiples in Task 4. #}

  <div class="table-wrapper">
    <table class="series-table">
      {#
        The table is the SVG's accessible equivalent and what the tests assert.
        Every figure is here in full, exactly as published.
      #}
      <caption>{{ data.indicator.name }} ({{ data.indicator.unit }}), {{ data.rows | length }} periods</caption>
      <thead>
        <tr>
          <th scope="col">Period</th>
          {% for country in data.countries %}<th scope="col">{{ country.name }}</th>{% endfor %}
        </tr>
      </thead>
      <tbody>
        {% for row in data.rows %}
        <tr>
          <th scope="row">{{ row.period_label }}</th>
          {% for country in data.countries %}
          {% set value = row.values.get(country.iso3) %}
          {# A gap is a dash, never a zero and never blank. #}
          <td>{% if value is none %}<span class="muted">—</span>{% else %}{{ value }}{% endif %}</td>
          {% endfor %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/integration/test_web_series.py -q`
Expected: PASS

- [ ] **Step 7: Prove the table test has teeth**

Blank the value cell (`<td></td>` in place of the `{% if value is none %}` block) and run `test_the_table_carries_every_figure`. It must FAIL. Restore it, re-run, confirm PASS and a clean `git diff`.

- [ ] **Step 8: Run the whole gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q
git add apps/web/routes.py apps/web/templates/series.html \
        apps/web/templates/series_not_found.html tests/integration/test_web_series.py
git commit -m "feat(web): pick an indicator and some countries, and get the figures"
```

---

### Task 3: The overlaid chart

**Files:**
- Modify: `apps/web/templates/series.html` (replace the Task 2 placeholder comment), `apps/web/static/reim.css`
- Modify: `apps/web/routes.py` (the drawing helper)
- Test: `tests/integration/test_web_series.py` (append), `tests/unit/test_charts.py` (append if the helper is pure)

**Interfaces:**
- Consumes from Task 1: `Scale`, `nice_ticks`, `series_path`, `value_domain`. From Task 2: `SeriesPageData`.
- Produces, relied on by Task 4:
  ```text
  build_chart(rows, iso3_codes, width=760, height=320) -> Chart | None
  Chart(paths: dict[str, str], ticks: list[float], width: int, height: int,
        plot_left: float, plot_right: float, plot_top: float, plot_bottom: float,
        x_positions: list[float], domain_min: float, domain_max: float)
  ```

**This task draws only the overlaid case**, which renders when `data.comparable and data.levels_comparable`. The small-multiples branch is Task 4 — leave the placeholder for it.

`build_chart` is pure: it takes rows and codes, returns geometry, touches nothing else. Put it in `apps/web/charts.py` beside its neighbours and unit-test it there. It returns `None` when `value_domain` does, so a selection with no plottable values renders the table alone rather than an empty axis.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_charts.py`:

```python
def test_a_chart_has_one_path_per_country_with_values() -> None:
    rows = [
        SeriesRow(date(2020, 1, 1), "2020", {"NIC": Decimal("1"), "GTM": Decimal("2")}),
        SeriesRow(date(2021, 1, 1), "2021", {"NIC": Decimal("3"), "GTM": Decimal("4")}),
    ]

    chart = build_chart(rows, ["NIC", "GTM"])

    assert chart is not None
    assert set(chart.paths) == {"NIC", "GTM"}
    assert chart.paths["NIC"].startswith("M")


def test_a_chart_of_gaps_only_is_no_chart() -> None:
    """``None`` rather than an axis around nothing."""
    rows = [SeriesRow(date(2020, 1, 1), "2020", {"NIC": None})]

    assert build_chart(rows, ["NIC"]) is None


def test_a_single_period_still_draws_its_point() -> None:
    """One observation is data; an empty chart would say it is not."""
    rows = [SeriesRow(date(2020, 1, 1), "2020", {"NIC": Decimal("4")})]

    chart = build_chart(rows, ["NIC"])

    assert chart is not None
    assert chart.paths["NIC"].count("M") == 1
```

Append to `tests/integration/test_web_series.py`:

```python
@requires_db
def test_a_comparable_selection_is_drawn_as_one_chart(
    client: TestClient, seeded_session: Session
) -> None:
    """The SVG's title and description are content, and are what we assert."""
    _add_observation(seeded_session, iso3="NIC", code="cpi_index_monthly", year=2020, value="5.5")

    body = client.get("/series?indicator=cpi_index_monthly&country=NIC").text

    assert "<svg" in body
    assert "Nicaragua" in body
    # The accessible name carries the indicator, not a generic "chart".
    assert "cpi_index_monthly" in body or "Inflation" in body


@requires_db
def test_the_chart_says_what_it_is_for_a_screen_reader(
    client: TestClient, seeded_session: Session
) -> None:
    _add_observation(seeded_session, iso3="NIC", code="cpi_index_monthly", year=2020, value="5.5")

    body = client.get("/series?indicator=cpi_index_monthly&country=NIC").text

    assert 'role="img"' in body
    assert "<title>" in body
    assert "<desc>" in body
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_charts.py tests/integration/test_web_series.py -q`
Expected: FAIL — `cannot import name 'build_chart'`, and no `<svg>` on the page.

- [ ] **Step 3: Add `build_chart` to `apps/web/charts.py`**

```python
@dataclass(frozen=True, slots=True)
class Chart:
    """The geometry of one plotted panel, ready for a template to render."""

    paths: dict[str, str]
    ticks: list[float]
    x_positions: list[float]
    width: int
    height: int
    plot_left: float
    plot_right: float
    plot_top: float
    plot_bottom: float
    domain_min: float
    domain_max: float


#: Room for the value labels on the left and the period labels underneath.
_MARGIN_LEFT = 64.0
_MARGIN_RIGHT = 12.0
_MARGIN_TOP = 12.0
_MARGIN_BOTTOM = 32.0


def build_chart(
    rows: Sequence[SeriesRow],
    iso3_codes: Sequence[str],
    *,
    width: int = 760,
    height: int = 320,
) -> Chart | None:
    """Return the geometry for one panel, or ``None`` when there is nothing to draw.

    ``None`` rather than an empty axis: a chart drawn around no values tells
    the reader a series exists and is flat, when in fact it is absent.

    Periods are placed by their **index**, not by their date. The series is a
    sequence of published periods, and spacing them by calendar distance would
    imply REIM knows what happened in the intervals — which, for a publisher
    that skipped a quarter, it does not.
    """
    domain = value_domain(rows, iso3_codes)
    if domain is None or not rows:
        return None
    domain_min, domain_max = domain

    plot_left, plot_right = _MARGIN_LEFT, float(width) - _MARGIN_RIGHT
    plot_top, plot_bottom = _MARGIN_TOP, float(height) - _MARGIN_BOTTOM

    last_index = float(max(len(rows) - 1, 1))
    x_scale = Scale(0.0, last_index, plot_left, plot_right)
    y_scale = Scale(domain_min, domain_max, plot_bottom, plot_top)

    paths = {
        code: series_path(
            [
                (float(index), None if (value := row.values.get(code)) is None else float(value))
                for index, row in enumerate(rows)
            ],
            x_scale,
            y_scale,
        )
        for code in iso3_codes
    }
    return Chart(
        paths={code: path for code, path in paths.items() if path},
        ticks=nice_ticks(domain_min, domain_max),
        x_positions=[round(x_scale.to_pixel(float(index)), 2) for index in range(len(rows))],
        width=width,
        height=height,
        plot_left=plot_left,
        plot_right=plot_right,
        plot_top=plot_top,
        plot_bottom=plot_bottom,
        domain_min=domain_min,
        domain_max=domain_max,
    )
```

Add `build_chart` and `Chart` to the test file's import list.

- [ ] **Step 4: Compute the chart in the view**

In `load_series_page`, after building `rows`, add the overlaid chart to `SeriesPageData`:

```text
chart: Chart | None          # new field on SeriesPageData
```

built as `build_chart(rows, [c.iso3 for c in countries])` **only when** `comparable and levels_comparable(definition)`; otherwise `None`, because Task 4 owns that case. Assign a colour per country from a fixed palette so the legend and the stroke agree; put the palette in `charts.py` as a module constant and index it by the country's position in the request.

- [ ] **Step 5: Render it**

Replace `{# The chart is added in Task 3; small multiples in Task 4. #}` in `series.html` with a block that renders the SVG when `data.chart` is set: an `<svg role="img" viewBox="0 0 W H">` carrying `<title>` and `<desc>` with the indicator name, the country names and the period range in words; the y-axis ticks as `<line>` plus `<text>`; the first, middle and last period labels on the x axis (all of them would collide); one `<path fill="none">` per country; and a legend of country name against colour beneath.

Keep the placeholder comment for Task 4 in the `{% else %}` branch.

- [ ] **Step 6: Style it**

Append to `apps/web/static/reim.css`: `.series-chart { max-width: 100%; height: auto; }`, axis line and label colours, `.series-legend` as a horizontal list with a colour swatch per entry, and `.series-form` as a simple grid. Keep the palette's colours distinguishable in greyscale as well as in colour — a reader printing the page still needs to tell the lines apart.

- [ ] **Step 7: Run the tests, prove the teeth, commit**

Run the unit and integration files. Then delete one country's `<path>` from the template, confirm `test_a_comparable_selection_is_drawn_as_one_chart` still passes (it asserts content, not paths) but that the **table** test still covers that country's figures — and say so in your report. That is the intended division: the table is what proves data is present, the chart tests prove it is drawn and described.

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q
git add apps/web/charts.py apps/web/routes.py apps/web/templates/series.html \
        apps/web/static/reim.css tests/unit/test_charts.py tests/integration/test_web_series.py
git commit -m "feat(web): draw the series, and break the line where the data breaks"
```

---

### Task 4: Small multiples, and the country that changes unit

**Files:**
- Modify: `apps/web/routes.py`, `apps/web/templates/series.html`, `apps/web/static/reim.css`
- Test: `tests/integration/test_web_series.py` (append)

**Interfaces:**
- Consumes from Tasks 1-3: `build_chart`, `Chart`, `SeriesPageData`.
- Produces: nothing later tasks consume.

**The decision this task implements (spec D3 and D4):**

* **Overlay only when `comparable` and `levels_comparable` are both true.** Otherwise one panel per country, each scaled on its own values — `value_domain` already restricts to the codes it is given, which is what makes a panel independent.
* `comparable` false means **units or currencies differ**: a shared axis between a percentage and millions of dollars is meaningless, not merely misleading.
* `levels_comparable` false means **the publisher measures a different thing in each country**. Three indicators declare it, all CEPAL interest rates, whose own methodology field reads "According to the definition from each country".
* **A country whose own `units` tuple holds more than one entry is not charted at all** (spec D4). Its own axis cannot rescue a line crossing a unit switch. Its values stay in the table, and a sentence names the units it carries and says why no line is drawn.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_web_series.py`:

```python
@requires_db
def test_incomparable_levels_are_never_put_on_one_axis(
    client: TestClient, seeded_session: Session
) -> None:
    """CEPAL's interest rates measure a different instrument in each country.

    One axis would tell the reader that one country sits above another when
    what differs is what is being measured.
    """
    for iso3, value in (("PAN", "7.5"), ("GTM", "12.0")):
        _add_observation(
            seeded_session,
            iso3=iso3,
            code="lending_rate_nominal_monthly",
            year=2024,
            value=value,
        )

    body = client.get("/series?indicator=lending_rate_nominal_monthly&country=PAN&country=GTM").text

    assert body.count("<svg") == 2, "levels are not comparable; one axis is wrong"
    assert "definition from each country" in body.lower() or "methodolog" in body.lower()


@requires_db
def test_a_comparable_indicator_stays_on_one_axis(
    client: TestClient, seeded_session: Session
) -> None:
    """The other half of the rule: don't split what may honestly be compared."""
    for iso3, value in (("NIC", "5.5"), ("GTM", "4.0")):
        _add_observation(
            seeded_session, iso3=iso3, code="cpi_index_monthly", year=2020, value=value
        )

    body = client.get("/series?indicator=cpi_index_monthly&country=NIC&country=GTM").text

    assert body.count("<svg") == 1
```

**The codes above were measured.** Exactly three indicators declare `methodology_varies_by_country=True` — `lending_rate_nominal_monthly` (`reim/domain/indicators/registry.py:579`), `deposit_rate_nominal_monthly` (`:601`) and `policy_rate_monthly` (`:624`), all CEPAL interest rates. `cpi_index_monthly` (`:558`) is regional and declares none, so its levels are comparable, which is what makes it the right indicator for the second test. Still confirm every literal you assert appears in the rendered body: three tests in the previous increment asserted strings the page never rendered.

For the unit-change state, construct it directly: `unit` is a column on `observations` (`reim/database/models/observation.py:65`), so storing two periods for one country with different `unit` values puts two entries in that country's `SeriesSummary.units`. Assert that country is named as not drawn, that both units appear, and that the number of `<svg>` elements is one fewer than the number of countries holding data.

- [ ] **Step 2: Run them to verify they fail**

Expected: FAIL — the page renders at most one chart and never mentions units.

- [ ] **Step 3: Implement**

In `load_series_page`, replace the single `chart` field with both shapes on `SeriesPageData`:

```text
chart: Chart | None                       # the overlaid case, as in Task 3
panels: list[tuple[CountryDefinition, Chart | None]]   # the small-multiple case
undrawable: list[tuple[CountryDefinition, tuple[str, ...]]]  # country -> its units
```

A country goes into `undrawable` when its summary's `units` tuple has more than one entry, and is then excluded from both `chart` and `panels`. When `comparable and levels_comparable` and nothing is undrawable, fill `chart` and leave `panels` empty; otherwise fill `panels` — one `build_chart(rows, [country.iso3])` per drawable country — and leave `chart` `None`.

In `series.html`, render `data.chart` when set, else the `data.panels` grid with a heading per panel, and in either case a sentence for each entry in `data.undrawable` naming its units.

- [ ] **Step 4: Prove the branch matters**

Force the overlaid branch to run for the incomparable case (drop the `levels_comparable` condition), watch `test_incomparable_levels_are_never_put_on_one_axis` fail, and restore. Report what you saw. A test that passes with the condition removed is not testing the decision this task exists for.

- [ ] **Step 5: Run the whole gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q
git add apps/web/routes.py apps/web/templates/series.html apps/web/static/reim.css \
        tests/integration/test_web_series.py
git commit -m "fix(web): refuse one axis when one axis would lie"
```

---

### Task 5: The guard, the navigation, a live look, and the documentation

**Files:**
- Modify: `tests/integration/test_web.py` (the outbound-HTTP guard), `apps/web/templates/base.html`, `ROADMAP.md`, `README.md`

- [ ] **Step 1: Extend the outbound-HTTP guard to `/series`**

`test_the_pages_make_no_outbound_http_requests` currently requests `/`, `/runs` and `/runs/{run_id}`. Add `/series` — both the bare form and a request carrying a real indicator and country. The previous increment's spec claimed this guard covered its new routes when it did not; do not repeat that. Note that the detail route's assertion there accepts `{200, 404}` because both are correct depending on whether a database is present — follow that pattern rather than forcing one status.

Update the test's docstring to name the series page.

- [ ] **Step 2: Add the nav link**

In `apps/web/templates/base.html`, add `<a href="/series">Series</a>` after the Runs link. Append a test to `tests/integration/test_web_series.py` asserting `href="/series"` appears on `/`, `/runs` and `/series`, with a docstring saying why an attribute is the right assertion here (a link *is* its href; there is no rendered content that proves reachability).

- [ ] **Step 3: See it with real data**

```bash
make db-up CONTAINER_ENGINE=podman
export REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim
export REIM_DATABASE_URL=$REIM_TEST_DATABASE_URL
.venv/bin/alembic upgrade head
.venv/bin/python -m reim.cli db seed
.venv/bin/python -m reim.cli pipeline run worldbank_ni_cpi_inflation
.venv/bin/uvicorn apps.api.main:app --port 8123 &
sleep 3
curl -s "localhost:8123/series?indicator=<the code that pipeline fills>&country=NIC" | head -80
```

Find the indicator code that pipeline actually populates (`reim.cli catalog` or the catalog entry's `indicators` list) rather than guessing. Then look at the page and report **concretely**: how many periods were drawn, whether the path broke anywhere (a gap in the World Bank series would prove the gap rule works on real data), what the ticks came out as, and whether the table and the chart agree. Kill the server (`kill %1`) when done.

If a second country's data is available, request two and report whether it overlaid or split, and whether that was right.

- [ ] **Step 4: Update the roadmap and README**

`ROADMAP.md` has a **Web dashboard** bullet in v0.4.0 saying the charting approach is still an open decision, and this branch closes it. Rewrite that entry in the style of the two struck-through entries above it: what shipped, the SVG-without-JavaScript decision and why, the overlay-versus-small-multiples rule, that gaps break the line rather than being bridged, and the 1,500-period cap with its reason. Do not claim interactivity, currency conversion, or a country-by-indicator view — none shipped.

`README.md`'s `## Web pages` section describes two pages. Make it three, with a paragraph for `/series` covering what it plots, the no-JavaScript decision, and the comparability rule. Check every sentence already there is still true.

- [ ] **Step 5: Check the formatter and commit**

```bash
.venv/bin/ruff format --check .
```
If it reports a Markdown file, fence the offending fragment as ```text rather than reformatting prose. Then run the whole gate and commit.

---

## Self-Review

**Spec coverage.** §1 (no new query) → Tasks 2-4 add none. §2 (the form, no JS) → Task 2. §2.1 (no conversion) → nothing implements it, by design. §3 (pure functions) → Task 1. §4 and §4.1 (the axis rule, the unit change) → Task 4. §5 (no downsampling, the cap) → the cap in Task 2, the gap rule in Task 1's `series_path`. §6 (nine states) → states 1-6 and 9 in Task 2, 7 and 8 in Task 4. §7 (testing) → distributed, with the no-`d`-attribute rule in Global Constraints. §8 D9 (`charts.py`) → Task 1.

**Two claims that were unverified in the first draft and have since been measured:**

1. **`_add_observation`.** The first draft invented `indicator.source_id` and omitted five NOT NULL columns; it would have failed on its first run. Measuring the model also surfaced `CheckConstraint("value_numeric IS NOT NULL OR value_text IS NOT NULL")` — a gap is the absence of a row, not a row holding null — which is why the helper takes a required `value` and why integration-level gaps are built by omitting an insert.
2. **The indicator codes.** `ca_lending_rate_nominal_monthly` did not exist. The three declaring `methodology_varies_by_country=True` are `lending_rate_nominal_monthly`, `deposit_rate_nominal_monthly` and `policy_rate_monthly`. `ni_cpi_inflation_annual` exists but is Nicaragua-specific, so a two-country test on it would have been meaningless; `cpi_index_monthly` is the regional one and is used instead.

1. **`_add_observation` in Task 2 is a sketch, not verified code.** `Observation`'s required columns were not read while writing this plan, and the conftest already builds observations for other suites. The step says to read both first and copy the existing approach.
2. **The indicator codes in Task 4's tests are guesses.** `lending_rate_nominal_monthly` and `cpi_index_monthly` were not verified against `reim/domain/indicators/registry.py`. The step says to find the three indicators declaring `methodology_varies_by_country=True` and use a real one. The previous increment shipped three tests asserting strings the page never rendered; this is where the same mistake would land.

**Type consistency.** `SeriesRow`, `Scale`, `nice_ticks`, `value_domain` and `series_path` are defined in Task 1 and used under those names in Tasks 2-4. `build_chart` and `Chart` are defined in Task 3 and used in Task 4. `SeriesPageData` gains `chart` in Task 3 and `panels`/`undrawable` in Task 4 — Task 4 says so explicitly rather than leaving the field set to drift.

**One deliberate reading of the spec.** §1 says the increment adds "one module of pure geometry". `pivot_cells` and `value_domain` are data shaping rather than geometry, and they live in `charts.py` anyway: the module's rule is *no session, no request, no template*, and splitting two small pure helpers into a second module would cost more than it explains.
