"""IMF IMTS monthly trade connector, replayed against a recorded response.

No test here performs a real network call except the opt-in `live` one.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from reim.core.constants import Frequency
from reim.core.exceptions import TransformationError
from reim.domain.pipelines.models import RawDataset
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
                "ni_exports_goods_monthly",
                "ni_imports_goods_monthly",
                "ni_trade_balance_goods_monthly",
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
        "ni_exports_goods_monthly": 436,
        "ni_imports_goods_monthly": 436,
        "ni_trade_balance_goods_monthly": 436,
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
        if obs.indicator_code == "ni_exports_goods_monthly"
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
        if obs.indicator_code == "ni_trade_balance_goods_monthly"
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
