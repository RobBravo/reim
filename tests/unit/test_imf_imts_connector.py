"""IMF IMTS monthly trade connector, replayed against a recorded response.

No test here performs a real network call except the opt-in `live` one.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from reim.core.constants import CheckSeverity, CheckStatus, Frequency
from reim.core.exceptions import ExtractionError, TransformationError
from reim.domain.pipelines.models import QualityResult, RawDataset
from reim.domain.sources.catalog import SourceEntry
from reim.ingestion.connectors.nicaragua.imf_imts_trade import ImfImtsTradeConnector

BASE_URL = "https://api.imf.org/external/sdmx/2.1"
RETRIEVED_AT = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


def build_connector(**options: object) -> ImfImtsTradeConnector:
    entry = SourceEntry.model_validate(
        {
            "key": "imf_imts_nicaragua",
            "name": "Nicaragua merchandise trade (monthly)",
            "country": "NI",
            "organization": "IMF",
            "category": "external_sector",
            "access_type": "http_api",
            "frequency": "monthly",
            "format": "csv",
            "base_url": BASE_URL,
            "connector": "reim.ingestion.connectors.nicaragua.imf_imts_trade",
            "indicators": [
                "exports_goods_monthly",
                "imports_goods_monthly",
                "trade_balance_goods_monthly",
            ],
            "license": "imf_terms_of_use",
            "options": dict(options),
        }
    )
    return ImfImtsTradeConnector(entry)


def raw_from(csv_text: str) -> RawDataset:
    return RawDataset(
        source_key="imf_imts_nicaragua",
        retrieved_at=RETRIEVED_AT,
        source_url=f"{BASE_URL}/data/IMF.STA,IMTS/NIC..G001.M",
        payload=csv_text,
        content_type="application/vnd.sdmx.data+csv;version=2.0.0",
        http_status=200,
    )


# --------------------------------------------------------------------------
# transform
# --------------------------------------------------------------------------
def test_transform_reads_all_three_series(imf_imts_csv: str) -> None:
    connector = build_connector()

    observations = connector.transform(raw_from(imf_imts_csv))

    counts: dict[str, int] = {}
    for obs in observations:
        counts[obs.indicator_code] = counts.get(obs.indicator_code, 0) + 1

    assert counts == {
        "exports_goods_monthly": 436,
        "imports_goods_monthly": 436,
        "trade_balance_goods_monthly": 436,
    }
    assert len(observations) == 1308


def test_transform_converts_the_sdmx_month_label(imf_imts_csv: str) -> None:
    """SDMX writes 2026-M04; REIM stores 2026-04 as a closed month."""
    connector = build_connector()

    observations = connector.transform(raw_from(imf_imts_csv))
    latest = max(obs.period.start for obs in observations)
    newest = next(obs for obs in observations if obs.period.start == latest)

    assert newest.period.label == "2026-04"
    assert newest.period.frequency is Frequency.MONTHLY
    assert newest.period.start == date(2026, 4, 1)
    assert newest.period.end == date(2026, 4, 30)


def test_transform_does_not_apply_scale(imf_imts_csv: str) -> None:
    """Every row says SCALE=6 while carrying full USD; applying it would
    inflate the series a millionfold."""
    connector = build_connector()

    observations = connector.transform(raw_from(imf_imts_csv))
    exports = {
        obs.period.label: obs.value_numeric
        for obs in observations
        if obs.indicator_code == "exports_goods_monthly"
    }

    assert exports["2026-04"] == Decimal("601982690")
    assert observations[0].raw_metadata["imf_scale"] == "6"


def test_transform_keeps_the_published_precision(imf_imts_csv: str) -> None:
    """The 1990 figures carry 16 significant digits; none may be rounded away."""
    connector = build_connector()

    observations = connector.transform(raw_from(imf_imts_csv))
    balance = {
        obs.period.label: obs.value_numeric
        for obs in observations
        if obs.indicator_code == "trade_balance_goods_monthly"
    }

    assert balance["2026-04"] == Decimal("-274932625")
    assert balance["1990-01"] == Decimal("-50033856.85436923")


def test_transform_records_provenance(imf_imts_csv: str) -> None:
    connector = build_connector()

    obs = connector.transform(raw_from(imf_imts_csv))[0]

    assert obs.country_iso3 == "NIC"
    assert obs.unit == "current USD"
    assert obs.currency_code == "USD"
    assert obs.retrieved_at == RETRIEVED_AT
    assert obs.published_at is not None
    assert obs.published_at.tzinfo is not None
    assert obs.raw_metadata["imf_indicator"] in {"XG_FOB_USD", "MG_CIF_USD", "TBG_USD"}
    assert obs.raw_metadata["imf_counterpart"] == "G001"
    assert obs.raw_metadata["imf_unit"] == "USD"
    assert obs.source_record_id is not None
    assert obs.source_record_id.startswith("imts:")


def test_transform_discards_a_non_world_counterpart(imf_imts_csv: str) -> None:
    """Counterpart groups overlap, so anything but G001 must be dropped."""
    connector = build_connector()
    lines = imf_imts_csv.splitlines()
    doctored = "\n".join([lines[0], lines[1].replace(",G001,", ",USA,", 1)])

    assert connector.transform(raw_from(doctored)) == []


def test_transform_skips_the_dataflow_metadata_row(imf_imts_csv: str) -> None:
    """One row carries dataset metadata and no TIME_PERIOD."""
    connector = build_connector()

    observations = connector.transform(raw_from(imf_imts_csv))

    assert all(obs.period.label for obs in observations)


def test_transform_skips_a_row_without_a_value(imf_imts_csv: str) -> None:
    """A month the IMF does not publish produces no observation, never a zero."""
    connector = build_connector()
    lines = imf_imts_csv.splitlines()
    columns = lines[0].split(",")
    fields = lines[1].split(",")
    fields[columns.index("OBS_VALUE")] = ""
    doctored = "\n".join([lines[0], ",".join(fields)])

    assert connector.transform(raw_from(doctored)) == []


def test_transform_rejects_a_csv_missing_columns() -> None:
    connector = build_connector()

    with pytest.raises(TransformationError, match="missing column"):
        connector.transform(raw_from("COUNTRY,INDICATOR\nNIC,XG_FOB_USD\n"))


def test_transform_rejects_an_unparseable_period(imf_imts_csv: str) -> None:
    connector = build_connector()
    lines = imf_imts_csv.splitlines()
    doctored = "\n".join([lines[0], lines[1].replace("-M01", "-Q01", 1)])

    with pytest.raises(TransformationError, match="period"):
        connector.transform(raw_from(doctored))


def test_transform_rejects_a_non_numeric_value(imf_imts_csv: str) -> None:
    connector = build_connector()
    lines = imf_imts_csv.splitlines()
    columns = lines[0].split(",")
    fields = lines[1].split(",")
    fields[columns.index("OBS_VALUE")] = "n/a"
    doctored = "\n".join([lines[0], ",".join(fields)])

    with pytest.raises(TransformationError, match="non-numeric"):
        connector.transform(raw_from(doctored))


def test_transform_rejects_a_non_string_payload() -> None:
    connector = build_connector()
    raw = raw_from("")
    raw.payload = {"not": "csv"}

    with pytest.raises(TransformationError, match="CSV text"):
        connector.transform(raw)


# --------------------------------------------------------------------------
# validate
# --------------------------------------------------------------------------
def results_by_name(results: list[QualityResult]) -> dict[str, QualityResult]:
    return {r.check_name: r for r in results}


def test_validate_returns_the_three_source_checks(imf_imts_csv: str) -> None:
    connector = build_connector()
    observations = connector.transform(raw_from(imf_imts_csv))

    assert set(results_by_name(connector.validate(observations))) == {
        "imf_imts_world_aggregate_present",
        "imf_imts_all_indicators_present",
        "imf_imts_balance_identity",
    }


def test_validate_passes_on_the_recorded_response(imf_imts_csv: str) -> None:
    connector = build_connector()
    observations = connector.transform(raw_from(imf_imts_csv))

    assert [r for r in connector.validate(observations) if r.failed] == []


def test_missing_world_aggregate_is_critical() -> None:
    """Without G001 the run has no totals and must not be committed."""
    connector = build_connector()

    check = results_by_name(connector.validate([]))["imf_imts_world_aggregate_present"]

    assert check.status is CheckStatus.FAILED
    assert check.severity is CheckSeverity.CRITICAL


def test_a_missing_series_is_an_error(imf_imts_csv: str) -> None:
    connector = build_connector()
    observations = [
        obs
        for obs in connector.transform(raw_from(imf_imts_csv))
        if obs.indicator_code != "trade_balance_goods_monthly"
    ]

    check = results_by_name(connector.validate(observations))["imf_imts_all_indicators_present"]

    assert check.status is CheckStatus.FAILED
    assert check.severity is CheckSeverity.ERROR
    assert "trade_balance_goods_monthly" in check.message


def test_balance_identity_holds_on_the_real_series(imf_imts_csv: str) -> None:
    """TBG equals XG - MG to within a cent across all 436 months."""
    connector = build_connector()
    observations = connector.transform(raw_from(imf_imts_csv))

    check = results_by_name(connector.validate(observations))["imf_imts_balance_identity"]

    assert check.status is CheckStatus.PASSED
    assert check.actual_value == "0"
    assert "436" in check.message


def test_the_identity_tolerates_the_publisher_rounding(imf_imts_csv: str) -> None:
    """12 of 436 months differ in their last digit; that is not a fault."""
    connector = build_connector()
    observations = connector.transform(raw_from(imf_imts_csv))
    balance = next(
        obs for obs in observations if obs.indicator_code == "trade_balance_goods_monthly"
    )
    assert balance.value_numeric is not None
    balance.value_numeric += Decimal("0.000001")

    check = results_by_name(connector.validate(observations))["imf_imts_balance_identity"]

    assert check.status is CheckStatus.PASSED


def test_a_broken_balance_identity_is_an_error(imf_imts_csv: str) -> None:
    connector = build_connector()
    observations = connector.transform(raw_from(imf_imts_csv))
    broken = next(
        obs for obs in observations if obs.indicator_code == "trade_balance_goods_monthly"
    )
    broken.value_numeric = Decimal("1")

    check = results_by_name(connector.validate(observations))["imf_imts_balance_identity"]

    assert check.status is CheckStatus.FAILED
    assert check.severity is CheckSeverity.ERROR
    assert broken.period.label in check.message


# --------------------------------------------------------------------------
# extract
# --------------------------------------------------------------------------
DATA_URL = f"{BASE_URL}/data/IMF.STA,IMTS/NIC..G001.M"


def _csv_response(body: str) -> httpx.Response:
    return httpx.Response(200, text=body, headers={"Content-Type": "application/vnd.sdmx.data+csv"})


@respx.mock
async def test_extract_requests_the_filtered_key(imf_imts_csv: str) -> None:
    route = respx.get(DATA_URL).mock(return_value=_csv_response(imf_imts_csv))

    raw = await build_connector().extract()

    assert route.call_count == 1
    assert raw.http_status == 200
    assert raw.payload == imf_imts_csv
    request = route.calls.last.request
    assert "NIC..G001.M" in str(request.url)
    assert request.url.params["startPeriod"] == "1990-01"


@respx.mock
async def test_extract_pins_the_csv_media_type(imf_imts_csv: str) -> None:
    """The API ignores a JSON Accept, so the CSV type must be pinned."""
    route = respx.get(DATA_URL).mock(return_value=_csv_response(imf_imts_csv))

    await build_connector().extract()

    assert (
        route.calls.last.request.headers["Accept"] == "application/vnd.sdmx.data+csv;version=2.0.0"
    )


@respx.mock
async def test_extract_honours_a_configured_start_period(imf_imts_csv: str) -> None:
    route = respx.get(DATA_URL).mock(return_value=_csv_response(imf_imts_csv))

    await build_connector(start_period="2020-01").extract()

    assert route.calls.last.request.url.params["startPeriod"] == "2020-01"


@respx.mock
async def test_extract_rejects_an_xml_response() -> None:
    """The API answers SDMX-ML when it feels like it; that must not be parsed."""
    respx.get(DATA_URL).mock(
        return_value=httpx.Response(
            200,
            text="<?xml version='1.0'?><message:StructureSpecificData/>",
            headers={"Content-Type": "application/vnd.sdmx.structurespecificdata+xml"},
        )
    )

    with pytest.raises(ExtractionError, match="csv"):
        await build_connector().extract()


@respx.mock
async def test_extract_raises_on_a_server_error() -> None:
    respx.get(DATA_URL).mock(return_value=httpx.Response(404, text="not found"))

    with pytest.raises(ExtractionError, match="HTTP 404"):
        await build_connector().extract()


@pytest.mark.live
async def test_live_api_answers_the_documented_contract() -> None:
    """Opt-in: hits the real IMF API. Run with `pytest -m live`."""
    connector = build_connector(start_period="2025-01")

    raw = await connector.extract()
    observations = connector.transform(raw)

    assert observations
    assert {obs.indicator_code for obs in observations} == {
        "exports_goods_monthly",
        "imports_goods_monthly",
        "trade_balance_goods_monthly",
    }
    assert [r for r in connector.validate(observations) if r.failed] == []
