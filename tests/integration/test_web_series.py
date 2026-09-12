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
    assert response.headers["content-type"].startswith("text/html")
    assert "ZZZ" in response.text


def test_a_dead_database_is_said_out_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    """State 2, distinct from every "nothing to show" sentence on the page."""

    def _raise(*args: object, **kwargs: object) -> None:
        raise SQLAlchemyError("database is down")

    monkeypatch.setattr("apps.web.routes.comparison_repo.count_comparison_periods", _raise)
    client = TestClient(create_app())

    body = client.get("/series?indicator=cpi_index_monthly&country=NIC").text

    assert "database is not responding" in body.lower()
    assert "None of the countries you chose holds any data for" not in body


@requires_db
def test_a_valid_selection_with_no_data_says_so(client: TestClient) -> None:
    """State 5: the seeded schema has reference data and no observations.

    Asserts the state-5 sentence verbatim, not the brief's "holds no data":
    the template says "None of the countries you chose holds any data for
    {indicator}", which shares no distinctive substring with state 6's "No
    data for {country}" — so a test for one state cannot be satisfied by the
    other's rendering.
    """
    body = client.get("/series?indicator=cpi_index_monthly&country=NIC").text

    assert "None of the countries you chose holds any data for" in body
    assert "database is not responding" not in body.lower()


@requires_db
def test_the_countries_holding_nothing_are_named_not_dropped(
    client: TestClient, seeded_session: Session
) -> None:
    """State 6: a silently missing country reads as a country with a flat line."""
    _add_observation(seeded_session, iso3="NIC", code="cpi_index_monthly", year=2020, value="5.5")

    body = client.get("/series?indicator=cpi_index_monthly&country=NIC&country=GTM").text

    assert "No data for Guatemala" in body


@requires_db
def test_the_same_country_given_twice_collapses_to_one_column(
    client: TestClient, seeded_session: Session
) -> None:
    """``?country=NI&country=NIC`` names Nicaragua under both its codes.

    The view dedupes by ISO-3 (``apps/web/routes.py``'s ``seen`` set); without
    it the table would carry two identical columns for the same country and
    double-count its figure.
    """
    _add_observation(seeded_session, iso3="NIC", code="cpi_index_monthly", year=2020, value="5.5")

    body = client.get("/series?indicator=cpi_index_monthly&country=NI&country=NIC").text

    assert body.count('<th scope="col">Nicaragua</th>') == 1
    # Not ``body.count("5.5") == 1``: with the chart drawn, "5.5" is also the
    # sole point's y-axis tick label, which is separate, correct content. The
    # table cell is the thing the dedupe must not duplicate.
    assert body.count("<td>5.5</td>") == 1


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


def _tag_text(body: str, tag: str) -> str:
    """Return the text between the first ``<tag>`` and ``</tag>``, or "" when absent."""
    start_marker = f"<{tag}>"
    end_marker = f"</{tag}>"
    start = body.find(start_marker)
    if start == -1:
        return ""
    start += len(start_marker)
    end = body.find(end_marker, start)
    if end == -1:
        return ""
    return body[start:end]


def _svg_tag_text(body: str, tag: str) -> str:
    """Return the text of ``<tag>`` **inside the page's ``<svg>``**, or "".

    HTML's own ``<title>`` — the browser-tab title in ``<head>``, from
    ``series.html``'s ``{% block title %}`` — shares a tag name with SVG's
    accessible-name element. ``_tag_text(body, "title")`` alone would find
    that one first and pass regardless of whether the chart drew anything,
    which is exactly the vacuous-assertion trap the brief warns about:
    scoping to the SVG region is what makes the assertion about the chart.

    The page renders a ``<select>`` listing every indicator code and every
    country name on every request, so ``"Nicaragua" in body`` is true before
    any chart is drawn too — the reason every chart assertion in this file
    goes through this helper rather than testing ``body`` directly.
    """
    svg_start = body.find("<svg")
    if svg_start == -1:
        return ""
    svg_end = body.find("</svg>", svg_start)
    svg_region = body[svg_start : svg_end if svg_end != -1 else len(body)]
    return _tag_text(svg_region, tag)


@requires_db
def test_a_comparable_selection_is_drawn_as_one_chart(
    client: TestClient, seeded_session: Session
) -> None:
    """The SVG's title and description are content, and are what we assert."""
    _add_observation(seeded_session, iso3="NIC", code="cpi_index_monthly", year=2020, value="5.5")

    body = client.get("/series?indicator=cpi_index_monthly&country=NIC").text

    assert "<svg" in body
    title = _svg_tag_text(body, "title")
    desc = _svg_tag_text(body, "desc")
    assert title, f"no <title> found in body: {body}"
    assert "Nicaragua" in title
    # The accessible name carries the indicator, not a generic "chart".
    assert "Consumer price index (monthly)" in title or "Consumer price index (monthly)" in desc


@requires_db
def test_the_chart_names_every_selected_country_not_only_the_drawn_ones(
    client: TestClient, seeded_session: Session
) -> None:
    """A country that reports nothing must still be named, not silently dropped.

    NIC has an observation; GTM does not, so only NIC gets a ``<path>``. The
    description must still say both, or a country that vanished from the
    drawing would also vanish from the page's account of what it shows.
    """
    _add_observation(seeded_session, iso3="NIC", code="cpi_index_monthly", year=2020, value="5.5")

    body = client.get("/series?indicator=cpi_index_monthly&country=NIC&country=GTM").text

    desc = _svg_tag_text(body, "desc")
    assert desc, f"no <desc> found in body: {body}"
    assert "Nicaragua" in desc
    assert "Guatemala" in desc


@requires_db
def test_the_chart_says_what_it_is_for_a_screen_reader(
    client: TestClient, seeded_session: Session
) -> None:
    _add_observation(seeded_session, iso3="NIC", code="cpi_index_monthly", year=2020, value="5.5")

    body = client.get("/series?indicator=cpi_index_monthly&country=NIC").text

    assert 'role="img"' in body
    assert "<title>" in body
    assert "<desc>" in body


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


@requires_db
def test_a_country_that_changes_unit_is_named_but_not_charted(
    client: TestClient, seeded_session: Session
) -> None:
    """Spec D4: a country's own axis cannot rescue a line crossing a unit switch.

    NIC reports one unit throughout, GTM switches unit between periods, so
    GTM's summary carries two entries in ``units``. GTM's figures stay in the
    table; only NIC gets a panel.
    """
    _add_observation(
        seeded_session, iso3="NIC", code="cpi_index_monthly", year=2020, value="5.5", unit="index"
    )
    _add_observation(
        seeded_session, iso3="GTM", code="cpi_index_monthly", year=2020, value="4.0", unit="index"
    )
    _add_observation(
        seeded_session,
        iso3="GTM",
        code="cpi_index_monthly",
        year=2021,
        value="4.5",
        unit="percent change",
    )

    body = client.get("/series?indicator=cpi_index_monthly&country=NIC&country=GTM").text

    # "index, percent change" and "more than one unit" are novel phrases this
    # state introduces; neither is a bare indicator code or country name that
    # the page would render regardless of this behaviour.
    assert "more than one unit" in body.lower()
    assert "index, percent change" in body
    assert "Guatemala" in body
    # Two countries hold data (NIC and GTM); GTM is undrawable, so one fewer
    # <svg> than countries-with-data is drawn.
    assert body.count("<svg") == 1
