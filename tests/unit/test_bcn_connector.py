"""Unit tests for the BCN daily exchange-rate connector.

Every SOAP payload here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from reim.core.exceptions import ExtractionError, TransformationError
from reim.domain.pipelines.models import RawDataset
from reim.domain.sources.catalog import SourceEntry
from reim.ingestion.connectors.nicaragua.bcn_exchange_rate import (
    BcnExchangeRateConnector,
)

SOAP_URL = "https://servicios.bcn.gob.ni/Tc_Servicio/ServicioTC.asmx"
FIXTURES = Path(__file__).parent.parent / "fixtures"


def build_connector(**options: object) -> BcnExchangeRateConnector:
    """Build the connector with a catalog entry carrying ``options``."""
    entry = SourceEntry.model_validate(
        {
            "key": "bcn_exchange_rate",
            "name": "Nicaragua official exchange rate (daily)",
            "organization": "BCN",
            "country": "NI",
            "category": "exchange_rate",
            "access_type": "soap",
            "frequency": "daily",
            "format": "xml",
            "base_url": SOAP_URL,
            "connector": "reim.ingestion.connectors.nicaragua.bcn_exchange_rate",
            "indicators": ["ni_exchange_rate_official_daily"],
            "tls_profile": "legacy",
            "tls_note": "TLS 1.0 only; verification stays enforced.",
            "options": dict(options),
        }
    )
    return BcnExchangeRateConnector(entry)


# --------------------------------------------------------------------------
# Month resolution
# --------------------------------------------------------------------------
def test_default_window_is_the_current_month_and_the_previous_one() -> None:
    connector = build_connector()

    assert connector.resolve_months(date(2026, 8, 8)) == [(2026, 7), (2026, 8)]


def test_default_window_crosses_a_year_boundary() -> None:
    connector = build_connector()

    assert connector.resolve_months(date(2026, 1, 20)) == [(2025, 12), (2026, 1)]


def test_months_back_of_one_asks_for_the_current_month_only() -> None:
    connector = build_connector(months_back=1)

    assert connector.resolve_months(date(2026, 8, 8)) == [(2026, 8)]


def test_explicit_range_overrides_months_back() -> None:
    connector = build_connector(months_back=2, start_month="2012-01", end_month="2012-03")

    assert connector.resolve_months(date(2026, 8, 8)) == [(2012, 1), (2012, 2), (2012, 3)]


def test_explicit_start_defaults_its_end_to_the_current_month() -> None:
    connector = build_connector(start_month="2026-06")

    assert connector.resolve_months(date(2026, 8, 8)) == [(2026, 6), (2026, 7), (2026, 8)]


def test_a_start_before_coverage_is_rejected() -> None:
    connector = build_connector(start_month="2011-12")

    with pytest.raises(ExtractionError, match="2012-01"):
        connector.resolve_months(date(2026, 8, 8))


def test_an_inverted_range_is_rejected() -> None:
    connector = build_connector(start_month="2026-06", end_month="2026-03")

    with pytest.raises(ExtractionError, match="precedes"):
        connector.resolve_months(date(2026, 8, 8))


def test_a_range_over_the_cap_is_rejected() -> None:
    connector = build_connector(start_month="2012-01", end_month="2200-01")

    with pytest.raises(ExtractionError, match="400"):
        connector.resolve_months(date(2026, 8, 8))


def test_a_malformed_month_option_is_rejected() -> None:
    connector = build_connector(start_month="March 2020")

    with pytest.raises(ExtractionError, match="YYYY-MM"):
        connector.resolve_months(date(2026, 8, 8))


def test_a_non_positive_months_back_is_rejected() -> None:
    connector = build_connector(months_back=0)

    with pytest.raises(ExtractionError, match="months_back"):
        connector.resolve_months(date(2026, 8, 8))


# --------------------------------------------------------------------------
# transform
# --------------------------------------------------------------------------
def build_raw(*months: tuple[int, int], retrieved_at: datetime) -> RawDataset:
    """Build a RawDataset from the recorded fixtures for ``months``."""
    payload = [
        {
            "ano": year,
            "mes": month,
            "xml": (FIXTURES / f"bcn_tc_mes_{year}_{month:02d}.xml").read_text(encoding="utf-8"),
        }
        for year, month in months
    ]
    return RawDataset(
        source_key="bcn_exchange_rate",
        retrieved_at=retrieved_at,
        source_url=SOAP_URL,
        payload=payload,
        content_type="text/xml; charset=utf-8",
        http_status=200,
        metadata={"months": [f"{y}-{m:02d}" for y, m in months]},
    )


def test_transform_reads_every_calendar_day_of_a_month() -> None:
    connector = build_connector()
    raw = build_raw((2012, 1), retrieved_at=datetime(2026, 8, 8, tzinfo=UTC))

    observations = connector.transform(raw)

    assert len(observations) == 31
    assert observations[0].period.start == date(2012, 1, 1)
    assert observations[-1].period.start == date(2012, 1, 31)


def test_transform_sorts_the_unordered_source_rows() -> None:
    """The recording of March 2020 genuinely starts at the 7th."""
    connector = build_connector()
    raw = build_raw((2020, 3), retrieved_at=datetime(2026, 8, 8, tzinfo=UTC))

    days = [obs.period.start for obs in connector.transform(raw)]

    assert days == sorted(days)


def test_transform_preserves_the_published_decimal_exactly() -> None:
    connector = build_connector()
    raw = build_raw((2012, 1), retrieved_at=datetime(2026, 8, 8, tzinfo=UTC))

    first = connector.transform(raw)[0]

    assert first.value_numeric == Decimal("22.9797")
    assert str(first.value_numeric) == "22.9797"


def test_transform_emits_single_day_periods_with_full_provenance() -> None:
    connector = build_connector()
    raw = build_raw((2012, 1), retrieved_at=datetime(2026, 8, 8, tzinfo=UTC))

    first = connector.transform(raw)[0]

    assert first.period.start == first.period.end == date(2012, 1, 1)
    assert first.period.label == "2012-01-01"
    assert first.country_iso3 == "NIC"
    assert first.indicator_code == "ni_exchange_rate_official_daily"
    assert first.unit == "NIO per USD"
    assert first.currency_code == "NIO"
    assert first.source_record_id == "tc_dia:2012-01-01"
    assert first.raw_metadata["bcn_operation"] == "RecuperaTC_Mes"
    assert first.raw_metadata["bcn_requested_month"] == "2012-01"
    assert first.raw_metadata["contract_status"] == "verified"


def test_transform_discards_rows_dated_after_the_retrieval_date() -> None:
    connector = build_connector()
    raw = build_raw((2026, 12), retrieved_at=datetime(2026, 12, 10, tzinfo=UTC))

    observations = connector.transform(raw)

    assert len(observations) == 10
    assert observations[-1].period.start == date(2026, 12, 10)


def test_transform_discards_a_wholly_future_month() -> None:
    """The service projects the frozen rate forward; none of it is observed."""
    connector = build_connector()
    raw = build_raw((2026, 12), retrieved_at=datetime(2026, 8, 8, tzinfo=UTC))

    assert connector.transform(raw) == []


def test_transform_tolerates_a_month_outside_coverage() -> None:
    connector = build_connector()
    raw = build_raw((2011, 12), retrieved_at=datetime(2026, 8, 8, tzinfo=UTC))

    assert connector.transform(raw) == []


def test_transform_rejects_the_same_day_with_two_different_values() -> None:
    connector = build_connector()
    original = (FIXTURES / "bcn_tc_mes_2012_01.xml").read_text(encoding="utf-8")
    conflicting = original.replace("22.9797", "99.9999", 1)
    raw = RawDataset(
        source_key="bcn_exchange_rate",
        retrieved_at=datetime(2026, 8, 8, tzinfo=UTC),
        source_url=SOAP_URL,
        payload=[
            {"ano": 2012, "mes": 1, "xml": original},
            {"ano": 2012, "mes": 1, "xml": conflicting},
        ],
    )

    with pytest.raises(TransformationError, match="two different values"):
        connector.transform(raw)


def test_transform_accepts_the_same_day_repeated_with_one_value() -> None:
    connector = build_connector()
    xml = (FIXTURES / "bcn_tc_mes_2012_01.xml").read_text(encoding="utf-8")
    raw = RawDataset(
        source_key="bcn_exchange_rate",
        retrieved_at=datetime(2026, 8, 8, tzinfo=UTC),
        source_url=SOAP_URL,
        payload=[{"ano": 2012, "mes": 1, "xml": xml}, {"ano": 2012, "mes": 1, "xml": xml}],
    )

    assert len(connector.transform(raw)) == 31


def test_transform_raises_on_a_soap_fault() -> None:
    connector = build_connector()
    fault = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        "<soap:Body><soap:Fault><faultcode>soap:Server</faultcode>"
        "<faultstring>Server was unable to read request.</faultstring>"
        "</soap:Fault></soap:Body></soap:Envelope>"
    )
    raw = RawDataset(
        source_key="bcn_exchange_rate",
        retrieved_at=datetime(2026, 8, 8, tzinfo=UTC),
        source_url=SOAP_URL,
        payload=[{"ano": 2012, "mes": 1, "xml": fault}],
    )

    with pytest.raises(TransformationError, match="unable to read request"):
        connector.transform(raw)


def test_transform_raises_on_malformed_xml() -> None:
    connector = build_connector()
    raw = RawDataset(
        source_key="bcn_exchange_rate",
        retrieved_at=datetime(2026, 8, 8, tzinfo=UTC),
        source_url=SOAP_URL,
        payload=[{"ano": 2012, "mes": 1, "xml": "<soap:Envelope>truncated"}],
    )

    with pytest.raises(TransformationError, match="malformed XML"):
        connector.transform(raw)


def test_transform_rejects_a_payload_that_is_not_a_list() -> None:
    connector = build_connector()
    raw = RawDataset(
        source_key="bcn_exchange_rate",
        retrieved_at=datetime(2026, 8, 8, tzinfo=UTC),
        source_url=SOAP_URL,
        payload="<soap:Envelope/>",
    )

    with pytest.raises(TransformationError, match="list of per-month"):
        connector.transform(raw)
