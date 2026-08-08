"""Unit tests for the BCN daily exchange-rate connector.

Every SOAP payload here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

from datetime import date

import pytest

from reim.core.exceptions import ExtractionError
from reim.domain.sources.catalog import SourceEntry
from reim.ingestion.connectors.nicaragua.bcn_exchange_rate import (
    BcnExchangeRateConnector,
)

SOAP_URL = "https://servicios.bcn.gob.ni/Tc_Servicio/ServicioTC.asmx"


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
