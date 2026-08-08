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
from typing import ClassVar

from reim.core.constants import Frequency
from reim.core.exceptions import ExtractionError
from reim.domain.pipelines.models import (
    NormalizedObservation,
    QualityResult,
    RawDataset,
)
from reim.ingestion.base import BaseConnector

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
        """Not yet implemented; see Task 8 of the implementation plan."""
        raise NotImplementedError

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Not yet implemented; see Task 6 of the implementation plan."""
        raise NotImplementedError

    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Not yet implemented; see Task 7 of the implementation plan."""
        raise NotImplementedError
