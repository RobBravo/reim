r"""Nicaragua — daily official exchange rate published by the Banco Central de Nicaragua.

.. warning::
   **This connector ships disabled and its response contract is unverified.**

   The BCN exposes a free SOAP service at
   ``https://servicios.bcn.gob.ni/Tc_Servicio/ServicioTC.asmx`` documented at
   https://www.bcn.gob.ni/servicio-web-tipo-de-cambio, covering January 2012
   onwards. During development the endpoint could not be reached: the host only
   negotiates a pre-TLS 1.2 handshake, which OpenSSL 3.x under the default
   Fedora ``DEFAULT`` crypto policy rejects with
   ``error:0A000102:SSL routines::unsupported protocol``.

   The request construction below follows the published service description, but
   because no live response was ever observed, the *parsing* is written
   defensively and **must be verified against the real service before this
   source is enabled**. In line with the project's transparency principle, no
   fabricated response was used to "confirm" it works, and the catalog entry
   carries ``enabled: false`` with the blocker recorded.

   To verify and enable it, from a host that can complete the handshake::

       curl -sv --tlsv1.0 \\
         "https://servicios.bcn.gob.ni/Tc_Servicio/ServicioTC.asmx?WSDL"

   then confirm the operation name and the shape of the ``*Result`` element,
   adjust :meth:`BcnExchangeRateConnector.transform` if needed, add a recorded
   fixture, and flip ``enabled: true`` in ``sources/catalog.yml``.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import ClassVar
from xml.etree import ElementTree

from reim.core.constants import CheckSeverity, CheckType, Frequency
from reim.core.exceptions import ExtractionError, TransformationError
from reim.domain.observations.periods import parse_period
from reim.domain.pipelines.models import (
    NormalizedObservation,
    QualityResult,
    RawDataset,
)
from reim.ingestion.base import BaseConnector
from reim.ingestion.http import ensure_ok, http_client

SOAP_NAMESPACE = "http://tempuri.org/"
SOAP_ACTION = f"{SOAP_NAMESPACE}RecuperaTC_Dia"
#: Earliest date the BCN service documents coverage for.
COVERAGE_START = date(2012, 1, 1)

_SOAP_ENVELOPE = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <RecuperaTC_Dia xmlns="{namespace}">
      <strfecha>{reference_date}</strfecha>
    </RecuperaTC_Dia>
  </soap:Body>
</soap:Envelope>
"""

_RESULT_TAG = re.compile(r"Result$")


class BcnExchangeRateConnector(BaseConnector):
    """Daily NIO/USD official rate from the BCN SOAP service.

    The connector requests a single reference date — by default today, or the
    date supplied through the catalog ``options.reference_date`` — because the
    service is documented as a per-day lookup rather than a bulk series export.
    """

    connector_key = "bcn_exchange_rate"
    version = "0.1.0-unverified"
    expected_frequency = Frequency.DAILY
    indicator_code: ClassVar[str] = "ni_exchange_rate_official_daily"
    unit: ClassVar[str] = "NIO per USD"

    @property
    def reference_date(self) -> date:
        """Date to query; overridable through the catalog ``options`` block."""
        configured = self.source.options.get("reference_date")
        if isinstance(configured, str):
            return date.fromisoformat(configured)
        if isinstance(configured, date):
            return configured
        return datetime.now(UTC).date()

    async def extract(self) -> RawDataset:
        """POST the SOAP request for :attr:`reference_date`."""
        reference = self.reference_date
        if reference < COVERAGE_START:
            msg = (
                f"BCN publishes exchange rates from {COVERAGE_START.isoformat()} onwards; "
                f"{reference.isoformat()} is outside coverage"
            )
            raise ExtractionError(msg, source_key=self.source.key)

        url = str(self.source.base_url)
        body = _SOAP_ENVELOPE.format(namespace=SOAP_NAMESPACE, reference_date=reference.isoformat())
        retrieved_at = datetime.now(UTC)

        async with http_client() as client:
            try:
                response = await client.post(
                    url,
                    content=body.encode("utf-8"),
                    headers={
                        "Content-Type": "text/xml; charset=utf-8",
                        "SOAPAction": SOAP_ACTION,
                    },
                )
            except Exception as exc:
                msg = f"Could not reach the BCN SOAP service at {url}: {type(exc).__name__}: {exc}"
                raise ExtractionError(msg, url=url, source_key=self.source.key) from exc
            ensure_ok(response)
            text = response.text

        return RawDataset(
            source_key=self.source.key,
            retrieved_at=retrieved_at,
            source_url=url,
            payload=text,
            content_type=response.headers.get("content-type"),
            http_status=response.status_code,
            metadata={"reference_date": reference.isoformat()},
        )

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Extract the rate from the SOAP envelope.

        Parses the first element whose tag ends in ``Result`` rather than
        hard-coding a path, because the exact envelope has not been observed
        against the live service.
        """
        if not isinstance(raw.payload, str):
            msg = "BCN payload must be the raw SOAP XML string"
            raise TransformationError(msg, source_key=self.source.key)

        try:
            root = ElementTree.fromstring(raw.payload)
        except ElementTree.ParseError as exc:
            msg = f"BCN returned malformed XML: {exc}"
            raise TransformationError(msg, source_key=self.source.key) from exc

        result_text: str | None = None
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1]
            if _RESULT_TAG.search(tag) and element.text and element.text.strip():
                result_text = element.text.strip()
                break

        if result_text is None:
            msg = "No '*Result' element with a value found in the BCN SOAP response"
            raise TransformationError(msg, source_key=self.source.key)

        try:
            value = Decimal(result_text.replace(",", "."))
        except (InvalidOperation, ValueError) as exc:
            msg = f"BCN returned a non-numeric exchange rate {result_text!r}"
            raise TransformationError(msg, source_key=self.source.key) from exc

        reference = str(raw.metadata.get("reference_date", ""))
        period = parse_period(reference, Frequency.DAILY)

        return [
            NormalizedObservation(
                country_iso3="NIC",
                indicator_code=self.indicator_code,
                source_key=self.source.key,
                period=period,
                unit=self.unit,
                currency_code="NIO",
                value_numeric=value,
                retrieved_at=raw.retrieved_at,
                source_url=raw.source_url,
                source_record_id=f"tc_dia:{reference}",
                raw_metadata={
                    "bcn_operation": "RecuperaTC_Dia",
                    "bcn_reference_date": reference,
                    "contract_status": "unverified",
                },
            )
        ]

    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert the day lookup returned exactly one rate."""
        count = len(observations)
        if count == 1:
            return [
                QualityResult.passed(
                    "bcn_single_daily_rate",
                    CheckType.COMPLETENESS,
                    "Exactly one daily rate returned",
                    expected_value="1",
                    actual_value="1",
                )
            ]
        return [
            QualityResult.failure(
                "bcn_single_daily_rate",
                CheckType.COMPLETENESS,
                CheckSeverity.CRITICAL,
                f"Expected exactly one daily rate, got {count}",
                expected_value="1",
                actual_value=str(count),
            )
        ]
