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
    fetch_rates,
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


def test_cells_carry_their_own_currency(
    seeded_session: Session, two_countries: ComparisonQuery
) -> None:
    """The observation's currency, not the country's.

    Two countries can report one indicator in different currencies, and one
    country's series can change currency over time; conversion keys on this.
    """
    cells = fetch_comparison_cells(seeded_session, two_countries, limit=10, offset=0)

    assert {cell.currency_code for cell in cells} == {"USD"}


def test_a_provincial_observation_is_invisible_to_compare(
    seeded_session: Session, make_observation
) -> None:  # type: ignore[no-untyped-def]
    """/compare has no correct behaviour for a per-province row; it must not see one.

    Plants a provincial observation for an indicator/country pair /compare
    already reads, and confirms the comparison result is identical to what it
    would be without that row — same cell count, same value, no error.

    Asserts on ``fetch_comparison_cells``, not ``count_comparison_periods``:
    both observations share one period_start, so the periods count is
    ``DISTINCT``-deduplicated to 1 either way and can't see a second row for
    the same period. The cell count can, and does.
    """
    from reim.services.observation_writer import write_observations

    panama = get_country_by_iso3(seeded_session, "PAN")
    assert panama is not None

    national = make_observation(
        "2023", "205.1", country_iso3="PAN", indicator_code="ni_cpi_inflation_annual"
    )
    write_observations(seeded_session, [national], connector_version="1.0.0")
    seeded_session.flush()

    query = ComparisonQuery(
        indicator_code="ni_cpi_inflation_annual",
        country_ids=(panama.id,),
        period_start_from=None,
        period_start_to=None,
    )
    before_periods = count_comparison_periods(seeded_session, query)
    before_cells = fetch_comparison_cells(seeded_session, query, limit=10, offset=0)

    provincial = make_observation(
        "2023",
        "9.6",
        country_iso3="PAN",
        indicator_code="ni_cpi_inflation_annual",
        administrative_area_code="01",
    )
    write_observations(seeded_session, [provincial], connector_version="1.0.0")
    seeded_session.flush()

    after_periods = count_comparison_periods(seeded_session, query)
    after_cells = fetch_comparison_cells(seeded_session, query, limit=10, offset=0)

    assert after_periods == before_periods
    assert after_cells == before_cells
    assert len(after_cells) == 1
    assert after_cells[0].value_numeric == Decimal("205.1")


@pytest.fixture
def nicaraguan_rates(seeded_session: Session, make_observation) -> None:  # type: ignore[no-untyped-def]
    """Two months of rates, so a page-scoped query can be seen to skip one."""
    from reim.services.observation_writer import write_observations

    write_observations(
        seeded_session,
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
    seeded_session.commit()


def test_fetch_rates_keys_on_country_and_period(
    seeded_session: Session, nicaraguan_rates: None
) -> None:
    """Scoped to the page's periods: 2024-02 exists and is deliberately absent."""
    nic = get_country_by_iso3(seeded_session, "NIC")
    assert nic is not None

    table = fetch_rates(
        seeded_session,
        country_ids=(nic.id,),
        period_starts=[date(2024, 1, 1)],
    )

    assert table.by_period == {("NIC", date(2024, 1, 1)): Decimal("36.6")}
    assert table.source_key == "cepalstat_exchange_rate_monthly"


def test_fetch_rates_returns_empty_when_the_series_is_not_loaded(
    seeded_session: Session,
) -> None:
    """Not an error: an operator who never ran the pipeline still gets a page."""
    nic = get_country_by_iso3(seeded_session, "NIC")
    assert nic is not None

    table = fetch_rates(seeded_session, country_ids=(nic.id,), period_starts=[date(2024, 1, 1)])

    assert table.by_period == {}
    assert table.source_key is None
