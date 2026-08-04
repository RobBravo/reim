"""Connector transforms, replayed against recorded and synthetic fixtures.

No test in this file performs a real network call.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx

from reim.core.constants import CheckSeverity, Frequency
from reim.core.exceptions import ExtractionError, TransformationError
from reim.domain.pipelines.models import RawDataset
from reim.domain.sources.catalog import SourceEntry
from reim.ingestion.connectors.nicaragua.bcn_exchange_rate import BcnExchangeRateConnector
from reim.ingestion.connectors.nicaragua.worldbank_cpi_inflation import (
    WorldBankNicaraguaCpiInflation,
)
from reim.ingestion.connectors.nicaragua.worldbank_remittances import (
    WorldBankNicaraguaRemittances,
)

RETRIEVED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def _raw(payload: Any, source_key: str, **metadata: Any) -> RawDataset:
    return RawDataset(
        source_key=source_key,
        retrieved_at=RETRIEVED_AT,
        source_url="https://api.worldbank.org/v2/country/NIC/indicator/FP.CPI.TOTL.ZG",
        payload=payload,
        content_type="application/json",
        http_status=200,
        metadata=metadata,
    )


# --------------------------------------------------------------------------
# World Bank
# --------------------------------------------------------------------------
def test_connector_key_must_match_the_catalog(catalog) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match="does not match connector key"):
        WorldBankNicaraguaCpiInflation(catalog.get("worldbank_ni_remittances"))


def test_transform_recorded_payload(cpi_source: SourceEntry, worldbank_cpi_payload) -> None:  # type: ignore[no-untyped-def]
    connector = WorldBankNicaraguaCpiInflation(cpi_source)
    observations = connector.transform(_raw(worldbank_cpi_payload, cpi_source.key))

    assert len(observations) == 10
    assert all(o.indicator_code == "ni_cpi_inflation_annual" for o in observations)
    assert all(o.country_iso3 == "NIC" for o in observations)
    assert all(o.unit == "percent" for o in observations)
    assert all(o.source_key == "worldbank_ni_cpi_inflation" for o in observations)


def test_transform_sorts_chronologically(cpi_source, worldbank_cpi_payload) -> None:  # type: ignore[no-untyped-def]
    observations = WorldBankNicaraguaCpiInflation(cpi_source).transform(
        _raw(worldbank_cpi_payload, cpi_source.key)
    )
    labels = [o.period.label for o in observations]
    assert labels == sorted(labels)
    assert labels[0] == "2015"
    assert labels[-1] == "2024"


def test_transform_preserves_full_precision(cpi_source, worldbank_cpi_payload) -> None:  # type: ignore[no-untyped-def]
    """Values go through Decimal(str(...)), never through float arithmetic."""
    observations = WorldBankNicaraguaCpiInflation(cpi_source).transform(
        _raw(worldbank_cpi_payload, cpi_source.key)
    )
    latest = next(o for o in observations if o.period.label == "2024")
    assert latest.value_numeric == Decimal("4.62473841057141")
    assert isinstance(latest.value_numeric, Decimal)


def test_transform_builds_annual_intervals(cpi_source, worldbank_cpi_payload) -> None:  # type: ignore[no-untyped-def]
    observations = WorldBankNicaraguaCpiInflation(cpi_source).transform(
        _raw(worldbank_cpi_payload, cpi_source.key)
    )
    latest = next(o for o in observations if o.period.label == "2024")
    assert latest.period.start == date(2024, 1, 1)
    assert latest.period.end == date(2024, 12, 31)
    assert latest.period.frequency is Frequency.ANNUAL


def test_transform_records_provenance(cpi_source, worldbank_cpi_payload) -> None:  # type: ignore[no-untyped-def]
    observation = WorldBankNicaraguaCpiInflation(cpi_source).transform(
        _raw(worldbank_cpi_payload, cpi_source.key)
    )[0]
    assert observation.retrieved_at == RETRIEVED_AT
    assert observation.source_url.startswith("https://api.worldbank.org/")
    assert observation.source_record_id.startswith("FP.CPI.TOTL.ZG:")
    assert observation.raw_metadata["worldbank_series"] == "FP.CPI.TOTL.ZG"
    assert observation.published_at == datetime(2026, 7, 13, tzinfo=UTC)


def test_null_values_are_skipped_not_imputed(cpi_source, worldbank_cpi_payload) -> None:  # type: ignore[no-untyped-def]
    """A year the World Bank does not publish simply produces no observation."""
    metadata, rows = worldbank_cpi_payload
    holed = [dict(row) for row in rows]
    holed[0]["value"] = None
    observations = WorldBankNicaraguaCpiInflation(cpi_source).transform(
        _raw([metadata, holed], cpi_source.key)
    )
    assert len(observations) == len(rows) - 1
    assert holed[0]["date"] not in {o.period.label for o in observations}


def test_transform_is_pure(cpi_source, worldbank_cpi_payload) -> None:  # type: ignore[no-untyped-def]
    connector = WorldBankNicaraguaCpiInflation(cpi_source)
    raw = _raw(worldbank_cpi_payload, cpi_source.key)
    first = connector.transform(raw)
    second = connector.transform(raw)
    assert [o.compute_content_hash() for o in first] == [o.compute_content_hash() for o in second]


def test_api_error_envelope_is_a_transformation_error(cpi_source, worldbank_error_payload) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(TransformationError, match="API error"):
        WorldBankNicaraguaCpiInflation(cpi_source).transform(
            _raw(worldbank_error_payload, cpi_source.key)
        )


@pytest.mark.parametrize("payload", [None, {}, [], "text", [[]]])
def test_malformed_envelopes_are_rejected(cpi_source, payload) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(TransformationError):
        WorldBankNicaraguaCpiInflation(cpi_source).transform(_raw(payload, cpi_source.key))


def test_multi_page_response_refuses_to_truncate(cpi_source, worldbank_cpi_payload) -> None:  # type: ignore[no-untyped-def]
    """Silently dropping rows would be worse than failing."""
    metadata, rows = worldbank_cpi_payload
    with pytest.raises(TransformationError, match="pages"):
        WorldBankNicaraguaCpiInflation(cpi_source).transform(
            _raw([{**metadata, "pages": 3}, rows], cpi_source.key)
        )


def test_non_numeric_value_is_rejected(cpi_source, worldbank_cpi_payload) -> None:  # type: ignore[no-untyped-def]
    metadata, rows = worldbank_cpi_payload
    corrupted = [dict(row) for row in rows]
    corrupted[0]["value"] = "n/a"
    with pytest.raises(TransformationError, match="Non-numeric"):
        WorldBankNicaraguaCpiInflation(cpi_source).transform(
            _raw([metadata, corrupted], cpi_source.key)
        )


def test_validate_flags_rows_from_another_country(cpi_source, worldbank_cpi_payload) -> None:  # type: ignore[no-untyped-def]
    connector = WorldBankNicaraguaCpiInflation(cpi_source)
    observations = connector.transform(_raw(worldbank_cpi_payload, cpi_source.key))
    observations[0].country_iso3 = "CRI"
    failures = [r for r in connector.validate(observations) if r.failed]
    assert failures[0].check_name == "worldbank_country_match"
    assert failures[0].severity is CheckSeverity.CRITICAL


def test_validate_passes_for_a_clean_batch(cpi_source, worldbank_cpi_payload) -> None:  # type: ignore[no-untyped-def]
    connector = WorldBankNicaraguaCpiInflation(cpi_source)
    observations = connector.transform(_raw(worldbank_cpi_payload, cpi_source.key))
    assert [r for r in connector.validate(observations) if r.failed] == []


def test_currency_series_carry_their_currency(catalog) -> None:  # type: ignore[no-untyped-def]
    connector = WorldBankNicaraguaRemittances(catalog.get("worldbank_ni_remittances"))
    assert connector.currency_code == "USD"
    assert connector.unit == "current USD"


@respx.mock
async def test_extract_hits_the_documented_url(cpi_source, worldbank_cpi_payload) -> None:  # type: ignore[no-untyped-def]
    route = respx.get("https://api.worldbank.org/v2/country/NIC/indicator/FP.CPI.TOTL.ZG").mock(
        return_value=httpx.Response(200, json=worldbank_cpi_payload)
    )

    raw = await WorldBankNicaraguaCpiInflation(cpi_source).extract()

    assert route.called
    assert raw.http_status == 200
    assert raw.source_key == "worldbank_ni_cpi_inflation"
    assert raw.retrieved_at.tzinfo is not None
    assert dict(route.calls[0].request.url.params)["format"] == "json"


@respx.mock
async def test_extract_sends_the_identifying_user_agent(cpi_source, worldbank_cpi_payload) -> None:  # type: ignore[no-untyped-def]
    route = respx.get("https://api.worldbank.org/v2/country/NIC/indicator/FP.CPI.TOTL.ZG").mock(
        return_value=httpx.Response(200, json=worldbank_cpi_payload)
    )
    await WorldBankNicaraguaCpiInflation(cpi_source).extract()
    assert "REIM" in route.calls[0].request.headers["user-agent"]


@respx.mock
async def test_extract_raises_on_server_error(cpi_source) -> None:  # type: ignore[no-untyped-def]
    respx.get("https://api.worldbank.org/v2/country/NIC/indicator/FP.CPI.TOTL.ZG").mock(
        return_value=httpx.Response(500, text="boom")
    )
    with pytest.raises(ExtractionError):
        await WorldBankNicaraguaCpiInflation(cpi_source).extract()


@respx.mock
async def test_extract_raises_on_html_response(cpi_source) -> None:  # type: ignore[no-untyped-def]
    """A captive portal or error page must not be parsed as data."""
    respx.get("https://api.worldbank.org/v2/country/NIC/indicator/FP.CPI.TOTL.ZG").mock(
        return_value=httpx.Response(200, html="<html>maintenance</html>")
    )
    with pytest.raises(ExtractionError, match="Content-Type"):
        await WorldBankNicaraguaCpiInflation(cpi_source).extract()


@respx.mock
async def test_extract_retries_transient_failures(cpi_source, worldbank_cpi_payload) -> None:  # type: ignore[no-untyped-def]
    route = respx.get("https://api.worldbank.org/v2/country/NIC/indicator/FP.CPI.TOTL.ZG").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json=worldbank_cpi_payload),
        ]
    )
    raw = await WorldBankNicaraguaCpiInflation(cpi_source).extract()
    assert route.call_count == 2
    assert raw.http_status == 200


# --------------------------------------------------------------------------
# BCN (disabled connector, synthetic fixture)
# --------------------------------------------------------------------------
def test_bcn_source_is_disabled_in_the_catalog(bcn_source: SourceEntry) -> None:
    """The blocker is recorded rather than papered over."""
    assert bcn_source.enabled is False
    assert bcn_source.disabled_reason
    assert "TLS" in bcn_source.disabled_reason


def test_bcn_transform_parses_the_result_element(bcn_source, bcn_soap_payload) -> None:  # type: ignore[no-untyped-def]
    connector = BcnExchangeRateConnector(bcn_source)
    raw = RawDataset(
        source_key=bcn_source.key,
        retrieved_at=RETRIEVED_AT,
        source_url=str(bcn_source.base_url),
        payload=bcn_soap_payload,
        content_type="text/xml",
        http_status=200,
        metadata={"reference_date": "2024-07-15"},
    )
    observations = connector.transform(raw)

    assert len(observations) == 1
    assert observations[0].value_numeric == Decimal("36.6243")
    assert observations[0].period.label == "2024-07-15"
    assert observations[0].period.frequency is Frequency.DAILY
    assert observations[0].currency_code == "NIO"
    assert observations[0].raw_metadata["contract_status"] == "unverified"


def test_bcn_transform_rejects_malformed_xml(bcn_source) -> None:  # type: ignore[no-untyped-def]
    raw = RawDataset(
        source_key=bcn_source.key,
        retrieved_at=RETRIEVED_AT,
        source_url=str(bcn_source.base_url),
        payload="<not-closed>",
        metadata={"reference_date": "2024-07-15"},
    )
    with pytest.raises(TransformationError, match="malformed XML"):
        BcnExchangeRateConnector(bcn_source).transform(raw)


def test_bcn_transform_rejects_a_missing_result(bcn_source) -> None:  # type: ignore[no-untyped-def]
    raw = RawDataset(
        source_key=bcn_source.key,
        retrieved_at=RETRIEVED_AT,
        source_url=str(bcn_source.base_url),
        payload="<soap:Envelope xmlns:soap='http://x'><soap:Body/></soap:Envelope>",
        metadata={"reference_date": "2024-07-15"},
    )
    with pytest.raises(TransformationError, match="Result"):
        BcnExchangeRateConnector(bcn_source).transform(raw)


async def test_bcn_refuses_dates_before_documented_coverage(bcn_source) -> None:  # type: ignore[no-untyped-def]
    entry = bcn_source.model_copy(update={"options": {"reference_date": "2005-01-01"}})
    with pytest.raises(ExtractionError, match="outside coverage"):
        await BcnExchangeRateConnector(entry).extract()


def test_bcn_validate_requires_exactly_one_rate(bcn_source, make_observation) -> None:  # type: ignore[no-untyped-def]
    connector = BcnExchangeRateConnector(bcn_source)
    failures = [r for r in connector.validate([]) if r.failed]
    assert failures and failures[0].severity is CheckSeverity.CRITICAL
