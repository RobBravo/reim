"""Guatemala — daily official exchange rate published by the Banco de Guatemala.

Banguat exposes a free SOAP service at
``https://www.banguat.gob.gt/variables/ws/TipoCambio.asmx``, no authentication
and modern TLS. The connector calls ``TipoCambioRango(fechainit, fechafin)``
over the whole published history on every run: 1990-01-01 to today is one
request of about 1.3 MB, so there is no windowed mode and no separate backfill.
A rebuild from an empty database is therefore complete by default — the two-mode
design the BCN needs, because its history costs 176 requests, is what let a
rebuild there produce 40 rows instead of 5,334.

The service publishes **two rates for each day**, and they differ on 6,174 of
the 13,365 days published so far, so each side gets its own indicator. "Compra"
and "venta" are stated from the bank's side: `compra` is what it pays for a US
dollar, `venta` what it charges for one.

Dates cross the wire as ``dd/mm/yyyy`` in both directions.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import ClassVar
from xml.etree import ElementTree

from reim.core.constants import CheckSeverity, CheckType, Frequency
from reim.core.exceptions import TransformationError
from reim.domain.observations.periods import parse_period
from reim.domain.pipelines.models import (
    NormalizedObservation,
    QualityResult,
    RawDataset,
)
from reim.ingestion.base import BaseConnector
from reim.ingestion.http import ensure_ok, http_client, post

SOAP_NAMESPACE = "http://www.banguat.gob.gt/variables/ws/"
SOAP_ACTION = f"{SOAP_NAMESPACE}TipoCambioRango"
SOAP_ENVELOPE_NS = "http://schemas.xmlsoap.org/soap/envelope/"

#: First day Banguat publishes. Requesting earlier simply returns from here.
START_DATE = date(1990, 1, 1)

#: The sell rate sits at or above the buy rate only from 1992 onwards. Through
#: the quetzal's liberalisation the buy rate was fixed at 5.15 while the sell
#: rate floated below it, as low as 4.62 — 84 days in 1990 and 1991. That is
#: real history, so the invariant is enforced only where the source holds it.
SPREAD_ENFORCED_FROM_YEAR = 1992

#: ``(xml tag, indicator code, record-id suffix)`` for each published side.
SIDES: tuple[tuple[str, str, str], ...] = (
    ("compra", "gt_exchange_rate_official_daily_buy", "buy"),
    ("venta", "gt_exchange_rate_official_daily_sell", "sell"),
)

_DDMMYYYY = re.compile(r"^(?P<day>\d{2})/(?P<month>\d{2})/(?P<year>\d{4})$")

_SOAP_ENVELOPE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<soap:Envelope xmlns:soap="{envelope_ns}">'
    "<soap:Body>"
    '<TipoCambioRango xmlns="{namespace}">'
    "<fechainit>{start}</fechainit><fechafin>{end}</fechafin>"
    "</TipoCambioRango>"
    "</soap:Body></soap:Envelope>"
)


def _utc_today() -> date:
    """Return today's UTC date. Indirected so tests can pin it."""
    return datetime.now(UTC).date()


class BanguatExchangeRateConnector(BaseConnector):
    """Daily GTQ/USD official buy and sell rates from the Banguat SOAP service."""

    connector_key = "banguat_exchange_rate"
    version = "1.0.0"
    expected_frequency = Frequency.DAILY
    unit: ClassVar[str] = "GTQ per USD"
    currency_code: ClassVar[str] = "GTQ"
    country_iso3: ClassVar[str] = "GTM"

    async def extract(self) -> RawDataset:
        """Fetch the whole published history in one ``TipoCambioRango`` call.

        Raises:
            ExtractionError: The service was unreachable, kept failing, or
                answered with something other than XML.
        """
        url = str(self.source.base_url)
        retrieved_at = datetime.now(UTC)
        end = _utc_today()
        body = _SOAP_ENVELOPE.format(
            envelope_ns=SOAP_ENVELOPE_NS,
            namespace=SOAP_NAMESPACE,
            start=f"{START_DATE:%d/%m/%Y}",
            end=f"{end:%d/%m/%Y}",
        )

        async with http_client(tls_profile=self.source.tls_profile) as client:
            response = await post(
                client,
                url,
                content=body.encode("utf-8"),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    # Quoted, as SOAP 1.1 requires. Banguat's IIS host answers
                    # an unquoted action with a 500.
                    "SOAPAction": f'"{SOAP_ACTION}"',
                },
            )
            ensure_ok(response, expected_content_type="xml")

        return RawDataset(
            source_key=self.source.key,
            retrieved_at=retrieved_at,
            source_url=url,
            payload=response.text,
            content_type=response.headers.get("content-type"),
            http_status=response.status_code,
            metadata={
                "operation": "TipoCambioRango",
                "range": f"{START_DATE.isoformat()}/{end.isoformat()}",
            },
        )

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Normalize the envelope into two observations per published day.

        Pure function of ``raw``.

        Raises:
            TransformationError: The payload is not XML text, the envelope is
                malformed or carries a SOAP fault, a date or rate is
                unreadable, or one day arrives with two different values.
        """
        if not isinstance(raw.payload, str):
            msg = "Banguat payload must be the response XML text"
            raise TransformationError(msg, source_key=self.source.key)

        root = self._parse_envelope(raw.payload)
        rates: dict[date, dict[str, Decimal]] = {}

        for node in root.iter(f"{{{SOAP_NAMESPACE}}}Var"):
            day = self._read_date(node)
            row = {tag: self._read_rate(node, tag, day) for tag, _, _ in SIDES}
            previous = rates.get(day)
            if previous is not None and previous != row:
                msg = (
                    f"Banguat returned {day.isoformat()} with two different values: "
                    f"{previous} and {row}"
                )
                raise TransformationError(msg, source_key=self.source.key)
            rates[day] = row

        return [
            NormalizedObservation(
                country_iso3=self.country_iso3,
                indicator_code=indicator_code,
                source_key=self.source.key,
                period=parse_period(day.isoformat(), Frequency.DAILY),
                unit=self.unit,
                currency_code=self.currency_code,
                value_numeric=rates[day][tag],
                retrieved_at=raw.retrieved_at,
                source_url=raw.source_url,
                source_record_id=f"tc_rango:{day.isoformat()}:{suffix}",
                raw_metadata={
                    "banguat_operation": "TipoCambioRango",
                    "banguat_side": tag,
                    "banguat_currency_code": "2",
                    "contract_status": "verified",
                },
            )
            for day in sorted(rates)
            for tag, indicator_code, suffix in SIDES
        ]

    def _parse_envelope(self, xml: str) -> ElementTree.Element:
        """Parse the SOAP envelope, surfacing a fault as a transformation error."""
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError as exc:
            msg = f"Banguat returned malformed XML: {exc}"
            raise TransformationError(msg, source_key=self.source.key) from exc

        fault = root.find(f".//{{{SOAP_ENVELOPE_NS}}}Fault")
        if fault is not None:
            detail = (fault.findtext("faultstring") or "no faultstring").strip()
            msg = f"Banguat returned a SOAP fault: {detail}"
            raise TransformationError(msg, source_key=self.source.key)
        return root

    def _read_date(self, node: ElementTree.Element) -> date:
        """Read one ``<fecha>``, which is day-first — ``08/11/1990`` is 8 November."""
        raw_date = (node.findtext(f"{{{SOAP_NAMESPACE}}}fecha") or "").strip()
        match = _DDMMYYYY.match(raw_date)
        if match is None:
            msg = f"Banguat returned an unparseable date {raw_date!r}"
            raise TransformationError(msg, source_key=self.source.key)
        try:
            return date(int(match["year"]), int(match["month"]), int(match["day"]))
        except ValueError as exc:
            msg = f"Banguat returned an unparseable date {raw_date!r}: {exc}"
            raise TransformationError(msg, source_key=self.source.key) from exc

    def _read_rate(self, node: ElementTree.Element, tag: str, day: date) -> Decimal:
        """Read one side of a row into an exact Decimal."""
        raw_value = (node.findtext(f"{{{SOAP_NAMESPACE}}}{tag}") or "").strip()
        try:
            return Decimal(raw_value)
        except InvalidOperation as exc:
            msg = f"Banguat returned a non-numeric {tag} rate {raw_value!r} for {day.isoformat()}"
            raise TransformationError(msg, source_key=self.source.key) from exc

    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert Banguat-specific expectations beyond the standard battery."""
        by_side: dict[str, dict[date, Decimal]] = {
            indicator_code: {
                obs.period.start: obs.value_numeric
                for obs in observations
                if obs.indicator_code == indicator_code and obs.value_numeric is not None
            }
            for _, indicator_code, _ in SIDES
        }
        buy = by_side["gt_exchange_rate_official_daily_buy"]
        sell = by_side["gt_exchange_rate_official_daily_sell"]

        return [
            self._check_both_sides_present(buy, sell),
            self._check_sell_not_below_buy(buy, sell),
            self._check_calendar_gaps(set(buy) | set(sell)),
        ]

    def _check_both_sides_present(
        self,
        buy: dict[date, Decimal],
        sell: dict[date, Decimal],
    ) -> QualityResult:
        """Every published day carries both rates; one side alone means a parse bug."""
        if buy and sell and set(buy) == set(sell):
            return QualityResult.passed(
                "banguat_both_sides_present",
                CheckType.COMPLETENESS,
                f"Both rates present for all {len(buy)} day(s)",
                expected_value=str(len(buy)),
                actual_value=str(len(sell)),
            )

        only_buy = sorted(set(buy) - set(sell))
        only_sell = sorted(set(sell) - set(buy))
        if not buy or not sell:
            detail = f"buy has {len(buy)} day(s), sell has {len(sell)}"
        else:
            detail = f"{len(only_buy)} day(s) buy-only, {len(only_sell)} sell-only"
        return QualityResult.failure(
            "banguat_both_sides_present",
            CheckType.COMPLETENESS,
            CheckSeverity.CRITICAL,
            f"Banguat publishes a buy and a sell rate for every day, but {detail}",
            expected_value=str(max(len(buy), len(sell))),
            actual_value=str(min(len(buy), len(sell))),
        )

    def _check_sell_not_below_buy(
        self,
        buy: dict[date, Decimal],
        sell: dict[date, Decimal],
    ) -> QualityResult:
        """From 1992 the bank sells at or above what it buys. See ``SPREAD_ENFORCED_FROM_YEAR``."""
        assessed = [
            day for day in sorted(set(buy) & set(sell)) if day.year >= SPREAD_ENFORCED_FROM_YEAR
        ]
        inverted = [day for day in assessed if sell[day] < buy[day]]

        if not inverted:
            return QualityResult.passed(
                "banguat_sell_not_below_buy",
                CheckType.CONSISTENCY,
                f"Sell rate at or above buy on all {len(assessed)} day(s) "
                f"from {SPREAD_ENFORCED_FROM_YEAR}",
                expected_value="0 inverted",
                actual_value="0",
            )

        shown = ", ".join(
            f"{day.isoformat()} sell {sell[day]} < buy {buy[day]}" for day in inverted[:5]
        )
        suffix = f" (+{len(inverted) - 5} more)" if len(inverted) > 5 else ""
        return QualityResult.failure(
            "banguat_sell_not_below_buy",
            CheckType.CONSISTENCY,
            CheckSeverity.ERROR,
            f"{len(inverted)} day(s) from {SPREAD_ENFORCED_FROM_YEAR} onwards have the "
            f"sell rate below the buy rate: {shown}{suffix}",
            expected_value="0 inverted",
            actual_value=str(len(inverted)),
        )

    def _check_calendar_gaps(self, days: set[date]) -> QualityResult:
        """Report missing calendar days. Never fails: five are genuinely absent.

        Banguat skipped 2000-04-02, 2000-05-01, 2001-09-02, 2004-03-06 and
        2004-03-07 and publishes every other day since 1990. The count is worth
        seeing when it moves, but the source's own history is not a defect.
        """
        if len(days) < 2:
            return QualityResult.passed(
                "banguat_calendar_gaps",
                CheckType.COMPLETENESS,
                "Too few days ingested to assess gaps",
                actual_value=str(len(days)),
            )

        first, last = min(days), max(days)
        expected = (last - first).days + 1
        missing = expected - len(days)
        return QualityResult.passed(
            "banguat_calendar_gaps",
            CheckType.COMPLETENESS,
            f"{len(days)} of {expected} calendar day(s) from {first} to {last}; "
            f"{missing} not published",
            expected_value=str(expected),
            actual_value=str(len(days)),
        )
