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

from reim.core.constants import CheckSeverity, CheckStatus, Frequency
from reim.core.exceptions import TransformationError
from reim.domain.pipelines.models import NormalizedObservation, QualityResult, RawDataset
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


def results_of(observations: list[NormalizedObservation]) -> dict[str, QualityResult]:
    return {result.check_name: result for result in build_connector().validate(observations)}


def test_all_five_checks_pass_on_the_recording(raw: RawDataset) -> None:
    """The expected first-run state, from spec section 6.3."""
    results = results_of(build_connector().transform(raw))
    assert set(results) == {
        "cepalstat_bop_current_account",
        "cepalstat_bop_goods",
        "cepalstat_bop_goods_services",
        "cepalstat_bop_global_balance",
        "cepalstat_bop_expected_countries",
    }
    for name, result in results.items():
        assert result.status is CheckStatus.PASSED, f"{name}: {result.message}"


def test_the_current_account_identity_catches_a_constructed_break(raw: RawDataset) -> None:
    """I = goods and services + income + current transfers, at error severity."""
    observations = build_connector().transform(raw)
    assert results_of(observations)["cepalstat_bop_current_account"].status is CheckStatus.PASSED

    broken = [
        obs
        for obs in observations
        if obs.indicator_code == "bop_current_account_quarterly"
        and (obs.country_iso3, obs.period.label) == ("HND", "2015-Q2")
    ]
    assert broken, "fixture must hold HND 2015-Q2 for this test to mean anything"
    broken[0].value_numeric += Decimal("5000000")

    result = results_of(observations)["cepalstat_bop_current_account"]
    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.ERROR
    assert "HND 2015-Q2" in result.message


def test_a_vanished_part_series_warns_instead_of_passing_over_nothing(
    raw: RawDataset,
) -> None:
    """``checked == 0`` must not read as the identity holding.

    If ``bop_balance_income_quarterly`` vanished entirely, the current
    account identity — one of its parts — would otherwise report green
    over zero country-quarters. It is not a hole:
    ``cepalstat_bop_expected_countries`` fires critical for the same
    disappearance. But a run report that says an identity "holds" over
    nothing is misleading regardless.
    """
    observations = build_connector().transform(raw)
    without_income = [
        obs for obs in observations if obs.indicator_code != "bop_balance_income_quarterly"
    ]

    results = results_of(without_income)

    current_account = results["cepalstat_bop_current_account"]
    assert current_account.status is CheckStatus.FAILED
    assert current_account.severity is CheckSeverity.WARNING
    assert "could not be evaluated" in current_account.message

    assert results["cepalstat_bop_expected_countries"].status is CheckStatus.FAILED
    assert results["cepalstat_bop_expected_countries"].severity is CheckSeverity.CRITICAL


def test_the_goods_identity_catches_a_constructed_break(raw: RawDataset) -> None:
    """Balance on goods = exports + imports; imports are stored negative."""
    observations = build_connector().transform(raw)
    assert results_of(observations)["cepalstat_bop_goods"].status is CheckStatus.PASSED

    broken = [
        obs
        for obs in observations
        if obs.indicator_code == "bop_balance_goods_quarterly"
        and (obs.country_iso3, obs.period.label) == ("SLV", "2012-Q3")
    ]
    assert broken, "fixture must hold SLV 2012-Q3 for this test to mean anything"
    broken[0].value_numeric += Decimal("5000000")

    result = results_of(observations)["cepalstat_bop_goods"]
    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.ERROR
    assert "SLV 2012-Q3" in result.message


def test_the_goods_and_services_identity_catches_a_constructed_break(raw: RawDataset) -> None:
    """Goods and services = goods + services credit + services debit."""
    observations = build_connector().transform(raw)
    assert results_of(observations)["cepalstat_bop_goods_services"].status is CheckStatus.PASSED

    broken = [
        obs
        for obs in observations
        if obs.indicator_code == "bop_balance_goods_services_quarterly"
        and (obs.country_iso3, obs.period.label) == ("NIC", "2016-Q4")
    ]
    assert broken, "fixture must hold NIC 2016-Q4 for this test to mean anything"
    broken[0].value_numeric += Decimal("5000000")

    result = results_of(observations)["cepalstat_bop_goods_services"]
    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.ERROR
    assert "NIC 2016-Q4" in result.message


def test_the_global_balance_check_allows_only_panamas_two_known_exceptions(
    raw: RawDataset,
) -> None:
    """Panama 2004-Q3 and 2021-Q4 are real and encoded; a third would fire."""
    observations = build_connector().transform(raw)
    assert results_of(observations)["cepalstat_bop_global_balance"].status is CheckStatus.PASSED

    broken = [
        obs
        for obs in observations
        if obs.indicator_code == "bop_global_balance_quarterly"
        and (obs.country_iso3, obs.period.label) == ("CRI", "2010-Q1")
    ]
    assert broken, "fixture must hold CRI 2010-Q1 for this test to mean anything"
    broken[0].value_numeric += Decimal("5000000")

    result = results_of(observations)["cepalstat_bop_global_balance"]
    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.WARNING
    assert "CRI 2010-Q1" in result.message
    assert "PAN 2004-Q3" not in result.message
    assert "PAN 2021-Q4" not in result.message


def test_cepal_declares_bpm5_while_six_of_seven_countries_carry_the_bpm6_footnote(
    raw: RawDataset, cepalstat_bop_547_json: str
) -> None:
    """CEPAL's own metadata contradicts itself, and Guatemala is the exception.

    ``calculation_methodology`` states the fifth edition of the IMF's Balance
    of Payments Manual (BPM5); footnote 10138, attached to six of the seven
    countries' rows, says the sixth (BPM6) was actually used. REIM does not
    resolve the contradiction — see the module docstring — but documents it,
    so this pins both texts and the six-of-seven split the same way
    ``test_costa_rica_keeps_cepals_bolivian_misattribution`` pins the rates
    connector's CBBO defect: if CEPAL ever reconciles the two statements,
    this test fails and the documentation gets corrected rather than quietly
    going stale.
    """
    document = json.loads(cepalstat_bop_547_json)
    body = document["body"]
    methodology = str(body["metadata"]["calculation_methodology"])
    assert "fifth edition" in methodology
    assert "1993" in methodology

    footnotes = {footnote["id"]: footnote["description"] for footnote in body["footnotes"]}
    assert footnotes[10138] == (
        "Analytical presentation based on the official figures of the countries "
        "according to the 6th version of the IMF Balance of Payments Manual."
    )

    observations = build_connector().transform(build_raw(cepalstat_bop_547_json))
    notes_by_country: dict[str, set[str]] = {}
    for obs in observations:
        notes_by_country.setdefault(obs.country_iso3, set()).update(
            obs.raw_metadata["cepalstat_notes_ids"]
        )

    carries_10138 = {iso3 for iso3, notes in notes_by_country.items() if "10138" in notes}
    assert carries_10138 == CENTRAL_AMERICA - {"GTM"}
    assert len(carries_10138) == 6
    assert "10138" not in notes_by_country["GTM"]
