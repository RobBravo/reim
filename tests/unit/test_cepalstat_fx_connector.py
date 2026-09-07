"""Unit tests for the CEPALSTAT monthly exchange-rate connector.

Every payload replayed here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from reim.core.constants import CheckSeverity, CheckStatus, Frequency
from reim.core.exceptions import ExtractionError
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


def test_the_rate_is_quoted_in_the_currency_it_prices_not_the_countrys_own(
    connector: CepalstatExchangeRateConnector, raw: RawDataset
) -> None:
    """El Salvador's rate is in colones, though the country transacts in USD.

    The regression test for spec section 3.1. Taking the currency from the
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


def test_belizes_ten_months_at_one_point_nine_do_not_trip_the_peg_check(
    connector: CepalstatExchangeRateConnector, raw: RawDataset
) -> None:
    """The band exists for exactly these rows.

    Belize is pegged 2:1 and unchanged since 1976, yet reads 1.9 in ten months
    of the recording — a market quote averaged and rounded to one decimal. An
    equality check would call that a defect on real data.
    """
    observations = connector.transform(raw)
    off_parity = [
        obs
        for obs in observations
        if obs.country_iso3 == "BLZ" and obs.value_numeric != Decimal("2")
    ]

    assert len(off_parity) == 10
    assert {obs.value_numeric for obs in off_parity} == {Decimal("1.9")}

    result = next(
        r for r in connector.validate(observations) if r.check_name == "cepalstat_fx_pegs_hold"
    )
    assert result.status is CheckStatus.PASSED


def test_a_rate_far_off_its_peg_is_an_error(
    connector: CepalstatExchangeRateConnector, raw: RawDataset
) -> None:
    """Panama at a Guatemalan-looking rate means the matrix has been misread."""
    observations = connector.transform(raw)
    index = next(
        i
        for i, obs in enumerate(observations)
        if obs.country_iso3 == "PAN" and obs.period.label == "2010-05"
    )
    observations[index] = replace(observations[index], value_numeric=Decimal("7.7"))

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
    observations[index] = replace(observations[index], value_numeric=Decimal("7.7"))

    result = next(
        r for r in connector.validate(observations) if r.check_name == "cepalstat_fx_pegs_hold"
    )

    assert result.status is CheckStatus.PASSED


BASE_URL = "https://api-cepalstat.cepal.org/cepalstat/api/v1"


@respx.mock
async def test_extract_makes_exactly_two_requests(
    connector: CepalstatExchangeRateConnector,
    cepalstat_fx_2179_json: str,
    cepalstat_fx_dimensions_json: str,
) -> None:
    """One for the data in English, one for the month names in Spanish."""
    data_route = respx.get(f"{BASE_URL}/indicator/2179/data").mock(
        return_value=httpx.Response(
            200, text=cepalstat_fx_2179_json, headers={"content-type": "application/json"}
        )
    )
    dims_route = respx.get(f"{BASE_URL}/indicator/2179/dimensions").mock(
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
    respx.get(f"{BASE_URL}/indicator/2179/data").mock(
        return_value=httpx.Response(
            200, text=cepalstat_fx_2179_json, headers={"content-type": "application/json"}
        )
    )
    respx.get(f"{BASE_URL}/indicator/2179/dimensions").mock(
        return_value=httpx.Response(
            200, text=cepalstat_fx_dimensions_json, headers={"content-type": "application/json"}
        )
    )

    raw = await connector.extract()
    observations = connector.transform(raw)

    assert len(observations) == ROWS_FOR_THE_SEVEN


@respx.mock
async def test_a_failing_envelope_raises_whatever_the_status_line_says(
    connector: CepalstatExchangeRateConnector,
) -> None:
    """CEPAL answers `success: false` for an unknown indicator, sometimes at 200."""
    respx.get(f"{BASE_URL}/indicator/2179/data").mock(
        return_value=httpx.Response(
            200,
            text=(
                '{"header": {"success": false, "code": 500, "message": "no data"}, '
                '"body": {"data": []}}'
            ),
            headers={"content-type": "application/json"},
        )
    )

    with pytest.raises(ExtractionError, match="500"):
        await connector.extract()
