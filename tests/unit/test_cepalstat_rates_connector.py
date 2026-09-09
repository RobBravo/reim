"""Unit tests for the CEPALSTAT monthly interest-rates connector.

Every payload replayed here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

import httpx
import respx

from reim.domain.sources.catalog import load_catalog
from reim.ingestion.connectors.regional.cepalstat_rates import (
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
