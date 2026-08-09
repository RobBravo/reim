"""Unit tests for the Banguat daily exchange-rate connector.

The SOAP payload replayed here is Banguat's real, complete response; see
`tests/fixtures/README.md`.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from reim.core.exceptions import TransformationError
from reim.domain.pipelines.models import RawDataset
from reim.domain.sources.catalog import SourceEntry
from reim.ingestion.connectors.guatemala.banguat_exchange_rate import (
    BanguatExchangeRateConnector,
)

SOAP_URL = "https://www.banguat.gob.gt/variables/ws/TipoCambio.asmx"

_VAR = re.compile(r"<Var>.*?</Var>", re.S)

#: What the recorded response holds, measured on 2026-08-09.
PUBLISHED_DAYS = 13365
DIFFERING_DAYS = 6174
MISSING_DAYS = (
    date(2000, 4, 2),
    date(2000, 5, 1),
    date(2001, 9, 2),
    date(2004, 3, 6),
    date(2004, 3, 7),
)


def build_connector() -> BanguatExchangeRateConnector:
    entry = SourceEntry.model_validate(
        {
            "key": "banguat_exchange_rate",
            "name": "Guatemala official exchange rate (daily)",
            "organization": "BANGUAT",
            "country": "GT",
            "category": "exchange_rate",
            "access_type": "soap",
            "frequency": "daily",
            "format": "xml",
            "base_url": SOAP_URL,
            "connector": "reim.ingestion.connectors.guatemala.banguat_exchange_rate",
            "indicators": [
                "gt_exchange_rate_official_daily_buy",
                "gt_exchange_rate_official_daily_sell",
            ],
        }
    )
    return BanguatExchangeRateConnector(entry)


def build_raw(xml: str, *, retrieved_at: datetime | None = None) -> RawDataset:
    return RawDataset(
        source_key="banguat_exchange_rate",
        retrieved_at=retrieved_at or datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        source_url=SOAP_URL,
        payload=xml,
        content_type="text/xml; charset=utf-8",
        http_status=200,
        metadata={"operation": "TipoCambioRango"},
    )


def envelope(*rows: str) -> str:
    """Wrap ``<Var>`` fragments in the service's own response envelope."""
    body = "".join(rows)
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        "<soap:Body>"
        '<TipoCambioRangoResponse xmlns="http://www.banguat.gob.gt/variables/ws/">'
        f"<TipoCambioRangoResult><Vars>{body}</Vars></TipoCambioRangoResult>"
        "</TipoCambioRangoResponse>"
        "</soap:Body></soap:Envelope>"
    )


def var(fecha: str, venta: str, compra: str, moneda: str = "2") -> str:
    return (
        f"<Var><moneda>{moneda}</moneda><fecha>{fecha}</fecha>"
        f"<venta>{venta}</venta><compra>{compra}</compra></Var>"
    )


# --------------------------------------------------------------------------
# The recording itself
# --------------------------------------------------------------------------
def test_the_fixture_holds_the_whole_published_history(banguat_rango_xml: str) -> None:
    """A regrab that silently narrows the window would break every count below."""
    assert len(_VAR.findall(banguat_rango_xml)) == PUBLISHED_DAYS
    assert "<fecha>01/01/1990</fecha>" in banguat_rango_xml
    assert "<fecha>09/08/2026</fecha>" in banguat_rango_xml


def test_the_fixture_keeps_the_liberalisation_rows(banguat_rango_xml: str) -> None:
    """1990-11-08: the buy rate fixed at 5.15 while the sell rate floated below."""
    flat = banguat_rango_xml.replace("\r\n", "").replace("\n", "")

    assert "<fecha>08/11/1990</fecha><venta>4.62181</venta><compra>5.15</compra>" in flat


def test_the_fixture_skips_the_days_the_source_skips(banguat_rango_xml: str) -> None:
    """Five days are absent in 36 years; they are the source's history, not a fault."""
    for missing in MISSING_DAYS:
        assert f"<fecha>{missing:%d/%m/%Y}</fecha>" not in banguat_rango_xml


# --------------------------------------------------------------------------
# transform
# --------------------------------------------------------------------------
def test_every_published_day_yields_both_sides(banguat_rango_xml: str) -> None:
    observations = build_connector().transform(build_raw(banguat_rango_xml))

    by_indicator: dict[str, int] = {}
    for obs in observations:
        by_indicator[obs.indicator_code] = by_indicator.get(obs.indicator_code, 0) + 1
    assert by_indicator == {
        "gt_exchange_rate_official_daily_buy": PUBLISHED_DAYS,
        "gt_exchange_rate_official_daily_sell": PUBLISHED_DAYS,
    }


def test_the_two_sides_carry_the_values_the_source_gives_them() -> None:
    """The hazard this guards: reading one tag into both indicators.

    Counts would still match, so only asserting the values catches it.
    """
    raw = build_raw(envelope(var("01/01/1990", "3.41332", "3.4081")))

    observations = {o.indicator_code: o.value_numeric for o in build_connector().transform(raw)}

    assert observations["gt_exchange_rate_official_daily_sell"] == Decimal("3.41332")
    assert observations["gt_exchange_rate_official_daily_buy"] == Decimal("3.4081")


def test_the_recorded_history_keeps_its_exact_decimals(banguat_rango_xml: str) -> None:
    observations = build_connector().transform(build_raw(banguat_rango_xml))
    first_day = {
        o.indicator_code: o.value_numeric
        for o in observations
        if o.period.start == date(1990, 1, 1)
    }

    assert first_day["gt_exchange_rate_official_daily_sell"] == Decimal("3.41332")
    assert first_day["gt_exchange_rate_official_daily_buy"] == Decimal("3.4081")


def test_dates_are_read_day_first() -> None:
    """`08/11/1990` is 8 November, not 11 August — and the wrong reading is silent.

    The row is pinned by its values: only November's carries a 5.15 buy rate.
    """
    raw = build_raw(envelope(var("08/11/1990", "4.62181", "5.15")))

    observation = build_connector().transform(raw)[0]

    assert observation.period.start == date(1990, 11, 8)


def test_a_day_becomes_a_single_day_closed_period() -> None:
    raw = build_raw(envelope(var("01/07/2026", "7.62415", "7.62415")))

    period = build_connector().transform(raw)[0].period

    assert period.start == date(2026, 7, 1)
    assert period.end == date(2026, 7, 1)
    assert period.label == "2026-07-01"


def test_the_sides_differ_exactly_where_the_source_says_they_do(
    banguat_rango_xml: str,
) -> None:
    observations = build_connector().transform(build_raw(banguat_rango_xml))
    pairs: dict[date, dict[str, Decimal | None]] = {}
    for obs in observations:
        pairs.setdefault(obs.period.start, {})[obs.indicator_code] = obs.value_numeric

    differing = sum(
        1
        for sides in pairs.values()
        if sides["gt_exchange_rate_official_daily_buy"]
        != sides["gt_exchange_rate_official_daily_sell"]
    )
    assert differing == DIFFERING_DAYS


def test_each_side_gets_its_own_record_id() -> None:
    raw = build_raw(envelope(var("01/07/2026", "7.62415", "7.62415")))

    ids = {o.source_record_id for o in build_connector().transform(raw)}

    assert ids == {"tc_rango:2026-07-01:sell", "tc_rango:2026-07-01:buy"}


def test_observations_are_labelled_with_guatemala_and_the_quetzal() -> None:
    raw = build_raw(envelope(var("01/07/2026", "7.62415", "7.62415")))

    observation = build_connector().transform(raw)[0]

    assert observation.country_iso3 == "GTM"
    assert observation.currency_code == "GTQ"
    assert observation.unit == "GTQ per USD"


def test_rows_come_back_in_date_order(banguat_rango_xml: str) -> None:
    days = [o.period.start for o in build_connector().transform(build_raw(banguat_rango_xml))]

    assert days == sorted(days)


def test_a_soap_fault_is_an_error_not_an_empty_result() -> None:
    fault = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        "<soap:Body><soap:Fault><faultcode>soap:Server</faultcode>"
        "<faultstring>Server was unable to process request.</faultstring>"
        "</soap:Fault></soap:Body></soap:Envelope>"
    )

    with pytest.raises(TransformationError, match="SOAP fault"):
        build_connector().transform(build_raw(fault))


def test_malformed_xml_is_an_error() -> None:
    with pytest.raises(TransformationError, match="malformed XML"):
        build_connector().transform(build_raw("<soap:Envelope><unclosed>"))


def test_a_non_numeric_rate_is_an_error() -> None:
    raw = build_raw(envelope(var("01/07/2026", "n/d", "7.62415")))

    with pytest.raises(TransformationError, match="non-numeric"):
        build_connector().transform(raw)


def test_an_unparseable_date_is_an_error() -> None:
    raw = build_raw(envelope(var("2026-07-01", "7.62415", "7.62415")))

    with pytest.raises(TransformationError, match="unparseable date"):
        build_connector().transform(raw)


def test_a_day_repeated_with_different_values_is_an_error() -> None:
    """Picking a winner would make the ingested figure depend on row order."""
    raw = build_raw(
        envelope(
            var("01/07/2026", "7.62415", "7.62415"),
            var("01/07/2026", "7.70000", "7.62415"),
        )
    )

    with pytest.raises(TransformationError, match="two different"):
        build_connector().transform(raw)


def test_a_day_repeated_identically_is_accepted() -> None:
    raw = build_raw(
        envelope(
            var("01/07/2026", "7.62415", "7.62415"),
            var("01/07/2026", "7.62415", "7.62415"),
        )
    )

    assert len(build_connector().transform(raw)) == 2


def test_a_payload_that_is_not_text_is_an_error() -> None:
    with pytest.raises(TransformationError, match="XML text"):
        build_connector().transform(build_raw({"not": "xml"}))  # type: ignore[arg-type]
