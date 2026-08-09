"""Unit tests for the Banguat daily exchange-rate connector.

The SOAP payload replayed here is Banguat's real, complete response; see
`tests/fixtures/README.md`.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from reim.core.constants import CheckSeverity, CheckStatus, CheckType
from reim.core.exceptions import ExtractionError, TransformationError
from reim.domain.pipelines.models import QualityResult, RawDataset
from reim.domain.sources.catalog import SourceEntry
from reim.ingestion.connectors.guatemala import banguat_exchange_rate
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


# --------------------------------------------------------------------------
# validate
# --------------------------------------------------------------------------
def results_by_name(observations: list) -> dict[str, QualityResult]:  # type: ignore[type-arg]
    return {result.check_name: result for result in build_connector().validate(observations)}


def test_the_recorded_history_passes_every_check(banguat_rango_xml: str) -> None:
    """The 84 rows where the buy rate sat above the sell rate must not fail a run."""
    observations = build_connector().transform(build_raw(banguat_rango_xml))

    results = results_by_name(observations)

    assert [r.status for r in results.values()] == [CheckStatus.PASSED] * 3


def test_both_sides_present_passes_when_every_day_carries_the_pair() -> None:
    observations = build_connector().transform(
        build_raw(envelope(var("01/07/2026", "7.62415", "7.62415")))
    )

    result = results_by_name(observations)["banguat_both_sides_present"]

    assert result.status is CheckStatus.PASSED
    assert result.check_type is CheckType.COMPLETENESS


def test_a_side_missing_altogether_is_critical() -> None:
    """A parse bug that drops one tag would otherwise ingest half a series."""
    observations = [
        obs
        for obs in build_connector().transform(
            build_raw(envelope(var("01/07/2026", "7.62415", "7.62415")))
        )
        if obs.indicator_code != "gt_exchange_rate_official_daily_buy"
    ]

    result = results_by_name(observations)["banguat_both_sides_present"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.CRITICAL


def test_one_day_missing_a_side_is_critical() -> None:
    observations = build_connector().transform(
        build_raw(
            envelope(
                var("01/07/2026", "7.62415", "7.62415"),
                var("02/07/2026", "7.62500", "7.62500"),
            )
        )
    )
    trimmed = [
        obs
        for obs in observations
        if not (
            obs.period.start == date(2026, 7, 2)
            and obs.indicator_code == "gt_exchange_rate_official_daily_sell"
        )
    ]

    result = results_by_name(trimmed)["banguat_both_sides_present"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.CRITICAL
    assert "1 day(s) buy-only" in result.message


def test_the_1990_inversions_do_not_fail_the_spread_check() -> None:
    """Real history: the buy rate was fixed at 5.15 while the sell rate floated."""
    observations = build_connector().transform(
        build_raw(envelope(var("08/11/1990", "4.62181", "5.15")))
    )

    result = results_by_name(observations)["banguat_sell_not_below_buy"]

    assert result.status is CheckStatus.PASSED


def test_an_inversion_from_1992_onwards_fails() -> None:
    observations = build_connector().transform(
        build_raw(envelope(var("02/01/1992", "4.62181", "5.15")))
    )

    result = results_by_name(observations)["banguat_sell_not_below_buy"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.ERROR
    assert "1992-01-02 sell 4.62181 < buy 5.15" in result.message


def test_a_recent_inversion_fails(banguat_rango_xml: str) -> None:
    """Doctored into the real history, so the check is proven to reach the whole run."""
    doctored = banguat_rango_xml.replace(
        "<fecha>01/07/2026</fecha><venta>7.62415</venta><compra>7.62415</compra>",
        "<fecha>01/07/2026</fecha><venta>7.00000</venta><compra>7.62415</compra>",
    )
    assert doctored != banguat_rango_xml
    observations = build_connector().transform(build_raw(doctored))

    result = results_by_name(observations)["banguat_sell_not_below_buy"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.ERROR


def test_the_spread_check_counts_the_days_it_assessed() -> None:
    observations = build_connector().transform(
        build_raw(envelope(var("01/07/2026", "7.62415", "7.62415")))
    )

    result = results_by_name(observations)["banguat_sell_not_below_buy"]

    assert "1 day(s) from 1992" in result.message


def test_the_gap_check_counts_the_days_the_source_skips(banguat_rango_xml: str) -> None:
    observations = build_connector().transform(build_raw(banguat_rango_xml))

    result = results_by_name(observations)["banguat_calendar_gaps"]

    assert result.status is CheckStatus.PASSED
    assert f"{len(MISSING_DAYS)} not published" in result.message
    assert result.actual_value == str(PUBLISHED_DAYS)


def test_the_gap_check_never_fails() -> None:
    """Five days are genuinely absent; a failing check would cry wolf on every run."""
    observations = build_connector().transform(
        build_raw(
            envelope(
                var("01/07/2026", "7.62415", "7.62415"),
                var("31/07/2026", "7.62500", "7.62500"),
            )
        )
    )

    result = results_by_name(observations)["banguat_calendar_gaps"]

    assert result.status is CheckStatus.PASSED
    assert "29 not published" in result.message


def test_the_gap_check_is_quiet_on_a_single_day() -> None:
    observations = build_connector().transform(
        build_raw(envelope(var("01/07/2026", "7.62415", "7.62415")))
    )

    result = results_by_name(observations)["banguat_calendar_gaps"]

    assert result.status is CheckStatus.PASSED
    assert "Too few days" in result.message


def test_validate_reports_all_three_checks(banguat_rango_xml: str) -> None:
    observations = build_connector().transform(build_raw(banguat_rango_xml))

    assert set(results_by_name(observations)) == {
        "banguat_both_sides_present",
        "banguat_sell_not_below_buy",
        "banguat_calendar_gaps",
    }


# --------------------------------------------------------------------------
# extract
# --------------------------------------------------------------------------
@pytest.fixture
def pinned_today(monkeypatch: pytest.MonkeyPatch) -> date:
    """Pin the connector's notion of today so the requested range is deterministic."""
    today = date(2026, 8, 9)
    monkeypatch.setattr(banguat_exchange_rate, "_utc_today", lambda: today)
    return today


def xml_response(body: str) -> httpx.Response:
    return httpx.Response(200, text=body, headers={"Content-Type": "text/xml; charset=utf-8"})


@respx.mock
async def test_the_whole_history_costs_one_request(
    pinned_today: date, banguat_rango_xml: str
) -> None:
    """No windowing and no separate backfill: a rebuild is complete by default."""
    route = respx.post(SOAP_URL).mock(return_value=xml_response(banguat_rango_xml))

    raw = await build_connector().extract()

    assert route.call_count == 1
    assert raw.http_status == 200
    assert raw.payload == banguat_rango_xml
    assert raw.metadata["range"] == "1990-01-01/2026-08-09"


@respx.mock
async def test_extract_asks_for_1990_to_today_day_first(pinned_today: date) -> None:
    route = respx.post(SOAP_URL).mock(return_value=xml_response(envelope()))

    await build_connector().extract()
    body = route.calls.last.request.content.decode("utf-8")

    assert '<TipoCambioRango xmlns="http://www.banguat.gob.gt/variables/ws/">' in body
    assert "<fechainit>01/01/1990</fechainit>" in body
    assert "<fechafin>09/08/2026</fechafin>" in body


@respx.mock
async def test_the_soap_action_is_quoted(pinned_today: date) -> None:
    """Banguat's IIS host answers an unquoted action with a 500."""
    route = respx.post(SOAP_URL).mock(return_value=xml_response(envelope()))

    await build_connector().extract()

    assert route.calls.last.request.headers["SOAPAction"] == (
        '"http://www.banguat.gob.gt/variables/ws/TipoCambioRango"'
    )


@respx.mock
async def test_extract_sends_the_soap_content_type(pinned_today: date) -> None:
    route = respx.post(SOAP_URL).mock(return_value=xml_response(envelope()))

    await build_connector().extract()

    assert route.calls.last.request.headers["Content-Type"] == "text/xml; charset=utf-8"


@respx.mock
async def test_extract_records_what_the_service_answered(pinned_today: date) -> None:
    respx.post(SOAP_URL).mock(return_value=xml_response(envelope()))

    raw = await build_connector().extract()

    assert raw.content_type == "text/xml; charset=utf-8"
    assert raw.source_url == SOAP_URL
    assert raw.metadata["operation"] == "TipoCambioRango"


@respx.mock
async def test_an_html_answer_is_rejected(pinned_today: date) -> None:
    """A captive portal or an error page must not reach transform as data."""
    respx.post(SOAP_URL).mock(
        return_value=httpx.Response(
            200, text="<html>maintenance</html>", headers={"Content-Type": "text/html"}
        )
    )

    with pytest.raises(ExtractionError, match="xml"):
        await build_connector().extract()


@respx.mock
async def test_extract_raises_when_the_service_errors(pinned_today: date) -> None:
    # 404 rather than 500: a real answer, so ensure_ok raises immediately
    # instead of burning four attempts of exponential backoff.
    respx.post(SOAP_URL).mock(return_value=httpx.Response(404, text="not found"))

    with pytest.raises(ExtractionError, match="HTTP 404"):
        await build_connector().extract()


@respx.mock
async def test_an_empty_body_is_rejected(pinned_today: date) -> None:
    respx.post(SOAP_URL).mock(
        return_value=httpx.Response(200, text="", headers={"Content-Type": "text/xml"})
    )

    with pytest.raises(ExtractionError, match="empty body"):
        await build_connector().extract()


@pytest.mark.live
async def test_live_service_still_answers_the_recorded_contract() -> None:
    """Opt-in: hits the real Banguat service. Run with `pytest -m live`."""
    connector = build_connector()

    raw = await connector.extract()
    observations = connector.transform(raw)

    days = {obs.period.start for obs in observations}
    assert min(days) == date(1990, 1, 1)
    assert len(days) >= PUBLISHED_DAYS
    assert len(observations) == 2 * len(days)
    assert all(obs.value_numeric is not None and obs.value_numeric > 0 for obs in observations)
    assert all(result.status is CheckStatus.PASSED for result in connector.validate(observations))
