"""Nicaragua — daily official exchange rate published by the Banco Central de Nicaragua.

The BCN exposes a free SOAP service at
``https://servicios.bcn.gob.ni/Tc_Servicio/ServicioTC.asmx``, documented at
https://www.bcn.gob.ni/servicio-web-tipo-de-cambio and covering January 2012
onwards. The connector calls ``RecuperaTC_Mes(Ano, Mes)``, which returns every
calendar day of the requested month, rather than the per-day operation.

Two properties of the service shape this connector:

* Rows come back in **arbitrary order**, so they are sorted here.
* The service **answers for months that have not happened yet**, projecting the
  currently frozen rate forward to the end of the calendar year. Those rows are
  discarded: a projection is not an observation.

The host negotiates TLS 1.0 only and signs its key exchange with SHA-1, so the
catalog entry declares ``tls_profile: legacy``. That relaxes the protocol
version and cipher security level for this host alone — certificate and
hostname verification remain enforced. See
:func:`reim.ingestion.http.legacy_tls_context`.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar
from urllib.parse import urlsplit
from xml.etree import ElementTree

from reim.core.constants import CheckSeverity, CheckType, Frequency, TlsProfile
from reim.core.exceptions import ExtractionError, TransformationError
from reim.domain.observations.periods import parse_period
from reim.domain.pipelines.models import (
    NormalizedObservation,
    QualityResult,
    RawDataset,
)
from reim.ingestion.base import BaseConnector
from reim.ingestion.http import ensure_ok, http_client, post

SOAP_NAMESPACE = "http://servicios.bcn.gob.ni/"
SOAP_ACTION = f"{SOAP_NAMESPACE}RecuperaTC_Mes"
SOAP_ENVELOPE_NS = "http://schemas.xmlsoap.org/soap/envelope/"

#: Earliest month the BCN service holds data for; 2011-12 returns nothing.
COVERAGE_START = date(2012, 1, 1)
#: Months requested when the catalog does not say otherwise.
DEFAULT_MONTHS_BACK = 2
#: Ceiling on one run, so a mistyped range cannot launch a thousand requests.
MAX_MONTHS_PER_RUN = 400

_MONTH_OPTION = re.compile(r"^(?P<year>\d{4})-(?P<month>0[1-9]|1[0-2])$")

_SOAP_ENVELOPE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<soap:Envelope xmlns:soap="{envelope_ns}">'
    "<soap:Body>"
    '<RecuperaTC_Mes xmlns="{namespace}"><Ano>{year}</Ano><Mes>{month}</Mes></RecuperaTC_Mes>'
    "</soap:Body></soap:Envelope>"
)


def _utc_today() -> date:
    """Return today's UTC date. Indirected so tests can pin it."""
    return datetime.now(UTC).date()


def _month_of(day: date) -> tuple[int, int]:
    return (day.year, day.month)


def _shift_month(month: tuple[int, int], delta: int) -> tuple[int, int]:
    index = month[0] * 12 + (month[1] - 1) + delta
    return (index // 12, index % 12 + 1)


def _month_span(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    """Return every month from ``start`` to ``end`` inclusive, ascending."""
    count = (end[0] * 12 + end[1]) - (start[0] * 12 + start[1]) + 1
    return [_shift_month(start, offset) for offset in range(count)]


def _days_in_month(month: tuple[int, int]) -> list[date]:
    """Return every calendar day of ``month``."""
    first = date(month[0], month[1], 1)
    following = date(*_shift_month(month, 1), 1)
    return [date.fromordinal(o) for o in range(first.toordinal(), following.toordinal())]


class BcnExchangeRateConnector(BaseConnector):
    """Daily NIO/USD official rate from the BCN SOAP service."""

    connector_key = "bcn_exchange_rate"
    version = "1.0.0"
    expected_frequency = Frequency.DAILY
    indicator_code: ClassVar[str] = "ni_exchange_rate_official_daily"
    unit: ClassVar[str] = "NIO per USD"

    def resolve_months(self, today: date) -> list[tuple[int, int]]:
        """Resolve which ``(year, month)`` pairs to request.

        Pure function of the catalog ``options`` and ``today``, so ``extract``
        and ``validate`` can both call it and agree.

        Args:
            today: The date the run considers "now".

        Raises:
            ExtractionError: The options are malformed, reach before coverage,
                invert the range, or exceed :data:`MAX_MONTHS_PER_RUN`.
        """
        end = self._month_option("end_month") or _month_of(today)
        start = self._month_option("start_month")

        if start is None:
            months_back = self._months_back()
            start = _shift_month(end, -(months_back - 1))

        coverage = _month_of(COVERAGE_START)
        if start < coverage:
            msg = (
                f"BCN coverage starts at {coverage[0]}-{coverage[1]:02d}; "
                f"requested start {start[0]}-{start[1]:02d} is before it"
            )
            raise ExtractionError(msg, source_key=self.source.key)

        if end < start:
            msg = f"end_month {end[0]}-{end[1]:02d} precedes start_month {start[0]}-{start[1]:02d}"
            raise ExtractionError(msg, source_key=self.source.key)

        months = _month_span(start, end)
        if len(months) > MAX_MONTHS_PER_RUN:
            msg = (
                f"Requested {len(months)} months, above the {MAX_MONTHS_PER_RUN} "
                f"allowed in one run; narrow start_month/end_month"
            )
            raise ExtractionError(msg, source_key=self.source.key)
        return months

    def _months_back(self) -> int:
        raw = self.source.options.get("months_back", DEFAULT_MONTHS_BACK)
        try:
            months_back = int(raw)
        except (TypeError, ValueError) as exc:
            msg = f"months_back must be an integer, got {raw!r}"
            raise ExtractionError(msg, source_key=self.source.key) from exc
        if months_back < 1:
            msg = f"months_back must be at least 1, got {months_back}"
            raise ExtractionError(msg, source_key=self.source.key)
        return months_back

    def _month_option(self, name: str) -> tuple[int, int] | None:
        raw = self.source.options.get(name)
        if raw is None:
            return None
        match = _MONTH_OPTION.match(str(raw).strip())
        if match is None:
            msg = f"{name} must be formatted YYYY-MM, got {raw!r}"
            raise ExtractionError(msg, source_key=self.source.key)
        return (int(match["year"]), int(match["month"]))

    async def extract(self) -> RawDataset:
        """Fetch one ``RecuperaTC_Mes`` envelope per resolved month.

        Requests are issued sequentially rather than concurrently: this is an
        official service on a legacy stack, and a backfill can span years.

        Raises:
            ExtractionError: The options are unusable, or the service was
                unreachable or kept failing.
        """
        months = self.resolve_months(_utc_today())
        url = str(self.source.base_url)
        retrieved_at = datetime.now(UTC)

        if self.source.tls_profile is TlsProfile.LEGACY:
            self.logger.warning(
                "bcn.legacy_tls",
                host=urlsplit(url).hostname,
                tls_note=self.source.tls_note,
            )

        payload: list[dict[str, Any]] = []
        status: int | None = None
        content_type: str | None = None

        async with http_client(tls_profile=self.source.tls_profile) as client:
            for year, month in months:
                body = _SOAP_ENVELOPE.format(
                    envelope_ns=SOAP_ENVELOPE_NS,
                    namespace=SOAP_NAMESPACE,
                    year=year,
                    month=month,
                )
                response = await post(
                    client,
                    url,
                    content=body.encode("utf-8"),
                    headers={
                        "Content-Type": "text/xml; charset=utf-8",
                        "SOAPAction": SOAP_ACTION,
                    },
                )
                ensure_ok(response)
                payload.append({"ano": year, "mes": month, "xml": response.text})
                status = response.status_code
                content_type = response.headers.get("content-type")

        return RawDataset(
            source_key=self.source.key,
            retrieved_at=retrieved_at,
            source_url=url,
            payload=payload,
            content_type=content_type,
            http_status=status,
            metadata={
                "operation": "RecuperaTC_Mes",
                "months": [f"{year}-{month:02d}" for year, month in months],
            },
        )

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Normalize the per-month envelopes into one observation per day.

        Pure function of ``raw``. Rows are sorted, deduplicated and truncated
        at ``raw.retrieved_at``: the service answers for future months, and a
        projected rate is not an observation.

        Raises:
            TransformationError: The payload is not the expected shape, an
                envelope is malformed or carries a SOAP fault, a value is not
                numeric, or one day arrives with two different values.
        """
        payload = raw.payload
        if not isinstance(payload, list):
            msg = "BCN payload must be a list of per-month envelopes"
            raise TransformationError(msg, source_key=self.source.key)

        today = raw.retrieved_at.date()
        values: dict[date, Decimal] = {}
        months: dict[date, str] = {}

        for entry in payload:
            month_label = f"{int(entry['ano'])}-{int(entry['mes']):02d}"
            root = self._parse_envelope(str(entry["xml"]), month_label)
            for node in root.iter("Tc"):
                day, value = self._read_row(node, month_label)
                previous = values.get(day)
                if previous is not None and previous != value:
                    msg = (
                        f"BCN returned {day.isoformat()} with two different values: "
                        f"{previous} and {value}"
                    )
                    raise TransformationError(msg, source_key=self.source.key)
                values[day] = value
                months[day] = month_label

        return [
            NormalizedObservation(
                country_iso3="NIC",
                indicator_code=self.indicator_code,
                source_key=self.source.key,
                period=parse_period(day.isoformat(), Frequency.DAILY),
                unit=self.unit,
                currency_code="NIO",
                value_numeric=values[day],
                retrieved_at=raw.retrieved_at,
                source_url=raw.source_url,
                source_record_id=f"tc_dia:{day.isoformat()}",
                raw_metadata={
                    "bcn_operation": "RecuperaTC_Mes",
                    "bcn_requested_month": months[day],
                    "contract_status": "verified",
                },
            )
            for day in sorted(values)
            if day <= today
        ]

    def _parse_envelope(self, xml: str, month_label: str) -> ElementTree.Element:
        """Parse one SOAP envelope, surfacing a fault as a transformation error."""
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError as exc:
            msg = f"BCN returned malformed XML for {month_label}: {exc}"
            raise TransformationError(msg, source_key=self.source.key) from exc

        fault = root.find(f".//{{{SOAP_ENVELOPE_NS}}}Fault")
        if fault is not None:
            detail = (fault.findtext("faultstring") or "no faultstring").strip()
            msg = f"BCN returned a SOAP fault for {month_label}: {detail}"
            raise TransformationError(msg, source_key=self.source.key)
        return root

    def _read_row(self, node: ElementTree.Element, month_label: str) -> tuple[date, Decimal]:
        """Read one ``<Tc>`` element into a date and an exact Decimal."""
        raw_date = (node.findtext("Fecha") or "").strip()
        raw_value = (node.findtext("Valor") or "").strip()

        try:
            day = date.fromisoformat(raw_date[:10])
        except ValueError as exc:
            msg = f"BCN returned an unparseable date {raw_date!r} in {month_label}"
            raise TransformationError(msg, source_key=self.source.key) from exc

        try:
            value = Decimal(raw_value)
        except InvalidOperation as exc:
            msg = f"BCN returned a non-numeric rate {raw_value!r} for {raw_date}"
            raise TransformationError(msg, source_key=self.source.key) from exc

        return day, value

    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert BCN-specific expectations beyond the standard battery.

        The checks re-derive the requested window rather than carrying state
        out of :meth:`transform`, which must stay a pure function of its input.
        """
        today = _utc_today()
        months = self.resolve_months(today)
        days = {obs.period.start for obs in observations}
        return [
            self._check_month_coverage(days, months, today),
            self._check_calendar_continuity(days),
            self._check_future_rows_discarded(months, today),
        ]

    def _check_month_coverage(
        self,
        days: set[date],
        months: list[tuple[int, int]],
        today: date,
    ) -> QualityResult:
        """Every requested month that has already begun must have produced rows."""
        started = [month for month in months if month <= _month_of(today)]
        empty = [
            f"{year}-{month:02d}"
            for year, month in started
            if not any(day.year == year and day.month == month for day in days)
        ]

        if not empty:
            return QualityResult.passed(
                "bcn_month_coverage",
                CheckType.COMPLETENESS,
                f"All {len(started)} requested month(s) returned rates",
                expected_value=str(len(started)),
                actual_value=str(len(started)),
            )
        return QualityResult.failure(
            "bcn_month_coverage",
            CheckType.COMPLETENESS,
            CheckSeverity.ERROR,
            f"No rates returned for {len(empty)} requested month(s): {', '.join(empty)}",
            expected_value=str(len(started)),
            actual_value=", ".join(empty),
        )

    def _check_calendar_continuity(self, days: set[date]) -> QualityResult:
        """The BCN publishes a rate for every calendar day, so gaps are suspect."""
        if len(days) < 2:
            return QualityResult.passed(
                "bcn_calendar_continuity",
                CheckType.CONSISTENCY,
                "Too few days ingested to assess continuity",
                actual_value=str(len(days)),
            )

        first, last = min(days), max(days)
        expected = (last - first).days + 1
        missing = sorted(
            date.fromordinal(ordinal)
            for ordinal in range(first.toordinal(), last.toordinal() + 1)
            if date.fromordinal(ordinal) not in days
        )

        if not missing:
            return QualityResult.passed(
                "bcn_calendar_continuity",
                CheckType.CONSISTENCY,
                f"{expected} consecutive days from {first} to {last}",
                expected_value=str(expected),
                actual_value=str(len(days)),
            )

        shown = ", ".join(day.isoformat() for day in missing[:5])
        suffix = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
        return QualityResult.failure(
            "bcn_calendar_continuity",
            CheckType.CONSISTENCY,
            CheckSeverity.WARNING,
            f"{len(missing)} calendar day(s) missing between {first} and {last}: {shown}{suffix}",
            expected_value=str(expected),
            actual_value=str(len(days)),
        )

    def _check_future_rows_discarded(
        self,
        months: list[tuple[int, int]],
        today: date,
    ) -> QualityResult:
        """Report how many projected rows were dropped, so the discard is visible.

        The service returns a row for every calendar day of a requested month,
        including days that have not happened. This never fails: it records
        what was thrown away.
        """
        discarded = sum(1 for month in months for day in _days_in_month(month) if day > today)
        return QualityResult.passed(
            "bcn_future_rows_discarded",
            CheckType.VALIDITY,
            f"{discarded} projected row(s) after {today.isoformat()} were discarded",
            expected_value="0 ingested",
            actual_value=str(discarded),
        )
