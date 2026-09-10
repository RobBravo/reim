"""Unit tests for the CEPALSTAT quarterly balance-of-payments connector.

Every payload replayed here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from reim.core.constants import Frequency
from reim.core.exceptions import TransformationError
from reim.domain.pipelines.models import RawDataset
from reim.domain.sources.catalog import load_catalog
from reim.ingestion.connectors.regional.cepalstat_bop import (
    CENTRAL_AMERICA,
    ITEMS,
    CepalstatBopConnector,
)
from tests.conftest import REPO_ROOT

BASE_URL = "https://api-cepalstat.cepal.org/cepalstat/api/v1"
DATA_URL = f"{BASE_URL}/indicator/547/data"

#: What the recording holds, measured on 2026-09-09.
STORED_OBSERVATIONS = 19582


def build_connector() -> CepalstatBopConnector:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    return CepalstatBopConnector(catalog.get("cepalstat_bop_quarterly"))


def json_response(text: str) -> httpx.Response:
    return httpx.Response(200, text=text, headers={"content-type": "application/json"})


def build_raw(text: str) -> RawDataset:
    return RawDataset(
        source_key="cepalstat_bop_quarterly",
        retrieved_at=datetime(2026, 9, 9, 12, 0, tzinfo=UTC),
        source_url=BASE_URL,
        payload={"data": text},
        content_type="application/json",
        http_status=200,
    )


@pytest.fixture
def raw(cepalstat_bop_547_json: str) -> RawDataset:
    return build_raw(cepalstat_bop_547_json)


@respx.mock
async def test_extract_makes_one_request_and_asks_for_english(
    cepalstat_bop_547_json: str,
) -> None:
    """No Spanish dimensions fetch: this family's item names are translated."""
    data_route = respx.get(DATA_URL).mock(return_value=json_response(cepalstat_bop_547_json))
    dimensions_route = respx.get(f"{BASE_URL}/indicator/547/dimensions").mock(
        return_value=json_response(cepalstat_bop_547_json)
    )

    await build_connector().extract()

    assert data_route.call_count == 1
    assert dimensions_route.call_count == 0
    assert data_route.calls[0].request.url.params["lang"] == "en"


def test_stores_twenty_five_series_for_the_seven(raw: RawDataset) -> None:
    """41 of the 66 item members are discarded, and so is Mexico."""
    observations = build_connector().transform(raw)

    assert len(observations) == STORED_OBSERVATIONS
    assert {obs.country_iso3 for obs in observations} == CENTRAL_AMERICA
    assert {obs.indicator_code for obs in observations} == set(ITEMS.values())
    assert len(ITEMS) == 25
    assert {obs.period.frequency for obs in observations} == {Frequency.QUARTERLY}


def test_mexico_is_discarded_although_it_is_in_the_recording(
    raw: RawDataset, cepalstat_bop_547_json: str
) -> None:
    """The recording keeps Mexico so this filter has something to prove."""
    assert '"MEX"' in cepalstat_bop_547_json
    observations = build_connector().transform(raw)
    assert "MEX" not in {obs.country_iso3 for obs in observations}


def test_values_are_scaled_to_whole_dollars_and_never_rounded(raw: RawDataset) -> None:
    """Published in millions; stored in units, matching the debt and GDP totals.

    CEPAL declares zero decimals and publishes up to 22, so the scale must be
    applied without rounding the noise away.
    """
    observations = build_connector().transform(raw)

    published = {
        (obs.country_iso3, obs.indicator_code, obs.period.label): obs for obs in observations
    }
    sample = published[("PAN", "bop_current_account_quarterly", "2004-Q3")]
    assert sample.unit == "current USD"
    assert sample.currency_code == "USD"
    assert sample.value_numeric == Decimal(
        sample.raw_metadata["cepalstat_published_value"]
    ) * Decimal("1000000")

    # At least one stored value keeps more than two decimals of published noise.
    noisy = [
        obs
        for obs in observations
        if -Decimal(obs.raw_metadata["cepalstat_published_value"]).as_tuple().exponent > 8
    ]
    assert noisy, "the recording holds cells with more than eight decimals"


def test_negatives_and_zeros_are_stored(raw: RawDataset) -> None:
    """9,924 negatives and 594 zeros: both ordinary in a balance of payments."""
    values = [obs.value_numeric for obs in build_connector().transform(raw)]
    assert sum(1 for v in values if v is not None and v < 0) == 9924
    assert sum(1 for v in values if v == 0) == 594


def test_a_renamed_item_member_raises_rather_than_changing_a_series(
    cepalstat_bop_547_json: str,
) -> None:
    """Rows are filtered by member id, which is silent when CEPAL relabels one.

    The filter would keep matching and REIM would store a different series under
    the same indicator code, which is exactly the failure `cepalstat_debt.py`'s
    `_assert_selected_members` exists to prevent.
    """
    document = json.loads(cepalstat_bop_547_json)
    for dimension in document["body"]["dimensions"]:
        if dimension["id"] == 1272:
            for member in dimension["members"]:
                if member["id"] == 1274:
                    member["name"] = "I.  SOMETHING ELSE ENTIRELY"

    with pytest.raises(TransformationError, match="1274"):
        build_connector().transform(build_raw(json.dumps(document)))
