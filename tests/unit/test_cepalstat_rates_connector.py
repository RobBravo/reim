"""Unit tests for the CEPALSTAT monthly interest-rates connector.

Every payload replayed here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from reim.core.constants import Frequency
from reim.core.exceptions import TransformationError
from reim.domain.pipelines.models import RawDataset
from reim.domain.sources.catalog import load_catalog
from reim.ingestion.connectors.regional.cepalstat_rates import (
    CENTRAL_AMERICA,
    CepalstatRatesConnector,
)
from tests.conftest import REPO_ROOT

BASE_URL = "https://api-cepalstat.cepal.org/cepalstat/api/v1"


def build_connector() -> CepalstatRatesConnector:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    return CepalstatRatesConnector(catalog.get("cepalstat_rates_monthly"))


def data_url(cepal_id: int) -> str:
    return f"{BASE_URL}/indicator/{cepal_id}/data"


def dimensions_url(cepal_id: int) -> str:
    return f"{BASE_URL}/indicator/{cepal_id}/dimensions"


def json_response(text: str) -> httpx.Response:
    return httpx.Response(200, text=text, headers={"content-type": "application/json"})


@respx.mock
async def test_extract_makes_four_requests_not_six(
    cepalstat_rates_856_json: str,
    cepalstat_rates_857_json: str,
    cepalstat_rates_1206_json: str,
    cepalstat_dimensions_856_json: str,
) -> None:
    """Dimension 3981's member table is fetched once, not once per indicator.

    It belongs to the dimension, not to an indicator, and was measured
    byte-identical across 856, 857 and 1206.
    """
    data_routes = {
        856: respx.get(data_url(856)).mock(return_value=json_response(cepalstat_rates_856_json)),
        857: respx.get(data_url(857)).mock(return_value=json_response(cepalstat_rates_857_json)),
        1206: respx.get(data_url(1206)).mock(return_value=json_response(cepalstat_rates_1206_json)),
    }
    dimensions_route = respx.get(dimensions_url(856)).mock(
        return_value=json_response(cepalstat_dimensions_856_json)
    )
    # Proves the dimensions request is not repeated per indicator.
    dimensions_857_route = respx.get(dimensions_url(857)).mock(
        return_value=json_response(cepalstat_dimensions_856_json)
    )
    dimensions_1206_route = respx.get(dimensions_url(1206)).mock(
        return_value=json_response(cepalstat_dimensions_856_json)
    )

    raw = await build_connector().extract()

    assert data_routes[856].call_count == 1
    assert data_routes[857].call_count == 1
    assert data_routes[1206].call_count == 1
    assert dimensions_route.call_count == 1
    assert dimensions_857_route.call_count == 0
    assert dimensions_1206_route.call_count == 0

    assert dimensions_route.calls[0].request.url.params["lang"] == "es"
    for route in data_routes.values():
        assert route.calls[0].request.url.params["lang"] == "en"

    assert set(raw.payload["data"]) == {856, 857, 1206}
    assert isinstance(raw.payload["dimensions"], str)


def build_raw(data: dict[int, str], dimensions: str) -> RawDataset:
    return RawDataset(
        source_key="cepalstat_rates_monthly",
        retrieved_at=datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
        source_url=BASE_URL,
        payload={"data": data, "dimensions": dimensions},
        content_type="application/json",
        http_status=200,
    )


@pytest.fixture
def raw(
    cepalstat_rates_856_json: str,
    cepalstat_rates_857_json: str,
    cepalstat_rates_1206_json: str,
    cepalstat_dimensions_856_json: str,
) -> RawDataset:
    return build_raw(
        {
            856: cepalstat_rates_856_json,
            857: cepalstat_rates_857_json,
            1206: cepalstat_rates_1206_json,
        },
        cepalstat_dimensions_856_json,
    )


#: What the recordings hold, measured on 2026-09-07.
STORED_CELLS = {
    "lending_rate_nominal_monthly": 2490,
    "deposit_rate_nominal_monthly": 2453,
    "policy_rate_monthly": 1621,
}


def test_stores_only_the_monthly_members_of_the_seven(raw: RawDataset) -> None:
    """Annual and quarterly members are means of their months and are dropped."""
    observations = build_connector().transform(raw)

    counts = Counter(obs.indicator_code for obs in observations)
    assert dict(counts) == STORED_CELLS
    assert {obs.country_iso3 for obs in observations} <= CENTRAL_AMERICA
    assert {obs.period.frequency for obs in observations} == {Frequency.MONTHLY}


def test_panama_has_lending_and_deposit_rates_but_no_policy_rate(raw: RawDataset) -> None:
    """CEPAL's sixteen zero, unattributed 2022 cells are an artifact, not data."""
    observations = build_connector().transform(raw)

    by_code = {
        code: {obs.country_iso3 for obs in observations if obs.indicator_code == code}
        for code in STORED_CELLS
    }
    assert "PAN" in by_code["lending_rate_nominal_monthly"]
    assert "PAN" in by_code["deposit_rate_nominal_monthly"]
    assert "PAN" not in by_code["policy_rate_monthly"]
    assert by_code["policy_rate_monthly"] == CENTRAL_AMERICA - {"PAN"}


def test_nicaragua_keeps_its_two_genuine_policy_rate_zeros(raw: RawDataset) -> None:
    """Real cells in a live attributed series, unlike Panama's placeholder."""
    observations = build_connector().transform(raw)

    zeros = sorted(
        obs.period.label
        for obs in observations
        if obs.indicator_code == "policy_rate_monthly"
        and obs.country_iso3 == "NIC"
        and obs.value_numeric == Decimal(0)
    )
    assert zeros == ["2010-03", "2010-04"]


def test_values_are_stored_exactly_as_published(raw: RawDataset) -> None:
    """856 declares `decimals: 0` and publishes two. Nothing is rounded."""
    observations = build_connector().transform(raw)

    lending = {
        (obs.country_iso3, obs.period.label): obs.value_numeric
        for obs in observations
        if obs.indicator_code == "lending_rate_nominal_monthly"
    }
    assert lending[("NIC", "2011-12")] == Decimal("13.19")
    assert lending[("NIC", "2011-11")] == Decimal("9.09")
    assert all(obs.unit == "percent per annum" for obs in observations)
    assert all(obs.currency_code is None for obs in observations)


def test_costa_rica_keeps_cepals_bolivian_misattribution(raw: RawDataset) -> None:
    """CEPAL cites the Central Bank of Bolivia for Costa Rica's deposit rate.

    856 and 1206 both say CBCR. REIM does not repair a publisher's provenance,
    so this pins the defect: if CEPAL corrects it, this test fails and the
    correction is noticed rather than absorbed.
    """
    observations = build_connector().transform(raw)

    deposit = [
        obs
        for obs in observations
        if obs.indicator_code == "deposit_rate_nominal_monthly" and obs.country_iso3 == "CRI"
    ]
    assert deposit
    assert {obs.raw_metadata["cepalstat_source"] for obs in deposit} == {"Central Bank of Bolivia"}


def test_null_source_id_becomes_an_empty_attribution(raw: RawDataset) -> None:
    """345 rows of 1206 carry no source_id; that is a gap, not an exception."""
    observations = build_connector().transform(raw)

    unattributed = [
        obs
        for obs in observations
        if obs.indicator_code == "policy_rate_monthly" and obs.country_iso3 == "HND"
    ]
    assert unattributed
    assert {obs.raw_metadata["cepalstat_source"] for obs in unattributed} == {""}


def test_english_only_run_cannot_name_a_month(
    cepalstat_rates_856_json: str,
    cepalstat_rates_857_json: str,
    cepalstat_rates_1206_json: str,
) -> None:
    """The Spanish fetch is load-bearing, not incidental.

    In `lang=en` all seventeen members of dimension 3981 are the string
    `descripcion_ingles`, which is neither a month nor a known non-month
    member, so the classification must raise rather than drop every row.
    """
    broken = build_raw(
        {
            856: cepalstat_rates_856_json,
            857: cepalstat_rates_857_json,
            1206: cepalstat_rates_1206_json,
        },
        cepalstat_rates_856_json,
    )

    with pytest.raises(TransformationError, match="descripcion_ingles"):
        build_connector().transform(broken)
