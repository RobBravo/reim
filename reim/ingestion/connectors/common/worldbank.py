"""Shared implementation for World Bank Indicators API v2 connectors.

Endpoint
    ``https://api.worldbank.org/v2/country/{iso3}/indicator/{series}?format=json``

Characteristics (verified 2026-08-04):

* Open access, no API key, no rate limit published for low-volume use.
* Response is a two-element array: ``[metadata, rows]``. An error is returned as
  a one-element array containing a ``message`` object.
* ``value`` is ``null`` for years the World Bank has no figure for. REIM skips
  those rows rather than imputing anything.
* ``date`` is a plain year string for annual series.
* ``lastupdated`` in the metadata block is the database refresh date and is used
  as ``published_at``.

Known limitation: only annual frequency is available for the series REIM uses,
so higher-resolution national data must come from national sources.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

from reim.core.constants import CheckSeverity, CheckType, Frequency
from reim.core.exceptions import ExtractionError, TransformationError
from reim.domain.observations.periods import parse_period
from reim.domain.pipelines.models import (
    NormalizedObservation,
    QualityResult,
    RawDataset,
)
from reim.ingestion.base import BaseConnector
from reim.ingestion.http import ensure_ok, fetch, http_client

#: Rows per page. The MVP series have < 100 points, so one page always suffices,
#: but the connector still verifies it did not silently truncate.
PAGE_SIZE = 500


class WorldBankConnector(BaseConnector):
    """Base class for one World Bank series mapped to one REIM indicator.

    Subclasses set :attr:`series_code`, :attr:`indicator_code`, :attr:`unit` and
    the identity attributes required by :class:`BaseConnector`.
    """

    #: World Bank series identifier, e.g. ``"FP.CPI.TOTL.ZG"``.
    series_code: ClassVar[str]
    #: REIM indicator code the series feeds.
    indicator_code: ClassVar[str]
    #: Unit recorded on each observation.
    unit: ClassVar[str]
    #: ISO-4217 code when the series is denominated in a currency.
    currency_code: ClassVar[str | None] = None
    #: ISO-3166 alpha-3 of the country being requested.
    country_iso3: ClassVar[str] = "NIC"

    expected_frequency = Frequency.ANNUAL
    version = "1.0.0"

    @property
    def request_url(self) -> str:
        """Absolute URL this connector requests."""
        base = str(self.source.base_url).rstrip("/")
        return f"{base}/country/{self.country_iso3}/indicator/{self.series_code}"

    async def extract(self) -> RawDataset:
        """Fetch the full series as JSON."""
        params = {"format": "json", "per_page": str(PAGE_SIZE)}
        retrieved_at = datetime.now(UTC)

        async with http_client() as client:
            response = await fetch(client, self.request_url, params=params)
            ensure_ok(response, expected_content_type="json")
            try:
                payload = response.json()
            except ValueError as exc:
                msg = f"World Bank returned a non-JSON body for {self.series_code}"
                raise ExtractionError(msg, url=self.request_url) from exc

        self.logger.info("worldbank.extracted", series=self.series_code)
        return RawDataset(
            source_key=self.source.key,
            retrieved_at=retrieved_at,
            source_url=str(response.request.url),
            payload=payload,
            content_type=response.headers.get("content-type"),
            http_status=response.status_code,
            metadata={"series_code": self.series_code, "country_iso3": self.country_iso3},
        )

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Normalize the World Bank envelope into observations.

        Rows whose ``value`` is null are skipped: a missing figure is never
        imputed or carried forward.
        """
        metadata, rows = self._unwrap(raw)
        published_at = self._parse_last_updated(metadata.get("lastupdated"))

        observations: list[NormalizedObservation] = []
        for row in rows:
            if not isinstance(row, dict):
                msg = f"Expected an object in the World Bank data array, got {type(row).__name__}"
                raise TransformationError(msg, source_key=self.source.key)
            if row.get("value") is None:
                continue

            year = str(row.get("date", "")).strip()
            value = self._to_decimal(row["value"], year)
            period = parse_period(year, Frequency.ANNUAL)

            observations.append(
                NormalizedObservation(
                    country_iso3=str(row.get("countryiso3code") or self.country_iso3),
                    indicator_code=self.indicator_code,
                    source_key=self.source.key,
                    period=period,
                    unit=self.unit,
                    currency_code=self.currency_code,
                    value_numeric=value,
                    retrieved_at=raw.retrieved_at,
                    source_url=raw.source_url,
                    published_at=published_at,
                    source_record_id=f"{self.series_code}:{year}",
                    raw_metadata={
                        "worldbank_series": self.series_code,
                        "worldbank_indicator_name": (row.get("indicator") or {}).get("value"),
                        "worldbank_decimal": row.get("decimal"),
                        "worldbank_obs_status": row.get("obs_status") or None,
                        "worldbank_last_updated": metadata.get("lastupdated"),
                    },
                )
            )

        observations.sort(key=lambda obs: obs.period.start)
        self.logger.info(
            "worldbank.transformed",
            series=self.series_code,
            rows_received=len(rows),
            observations=len(observations),
        )
        return observations

    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert World-Bank-specific expectations on top of the standard battery."""
        results: list[QualityResult] = []

        wrong_country = [
            obs for obs in observations if obs.country_iso3.upper() != self.country_iso3
        ]
        results.append(
            QualityResult.passed(
                "worldbank_country_match",
                CheckType.INTEGRITY,
                f"All rows reported for {self.country_iso3}",
                expected_value=self.country_iso3,
            )
            if not wrong_country
            else QualityResult.failure(
                "worldbank_country_match",
                CheckType.INTEGRITY,
                CheckSeverity.CRITICAL,
                f"{len(wrong_country)} row(s) attributed to another country",
                expected_value=self.country_iso3,
                actual_value=", ".join(sorted({o.country_iso3 for o in wrong_country})),
            )
        )

        years = [obs.period.start.year for obs in observations]
        if years:
            expected_span = max(years) - min(years) + 1
            gaps = expected_span - len(set(years))
            results.append(
                QualityResult.passed(
                    "worldbank_series_continuity",
                    CheckType.COMPLETENESS,
                    f"Series covers {min(years)}-{max(years)} with no gaps",
                    actual_value="0",
                )
                if gaps == 0
                else QualityResult.failure(
                    "worldbank_series_continuity",
                    CheckType.COMPLETENESS,
                    CheckSeverity.INFO,
                    f"Series covers {min(years)}-{max(years)} with {gaps} year(s) "
                    "the World Bank does not publish",
                    expected_value="0",
                    actual_value=str(gaps),
                )
            )
        return results

    # -- Helpers ----------------------------------------------------------
    def _unwrap(self, raw: RawDataset) -> tuple[dict[str, Any], list[Any]]:
        """Split the World Bank envelope into ``(metadata, rows)``."""
        payload = raw.payload
        if not isinstance(payload, list) or not payload:
            msg = "World Bank response is not the expected [metadata, rows] array"
            raise TransformationError(msg, source_key=self.source.key)

        head = payload[0]
        if len(payload) == 1:
            detail = head[0] if isinstance(head, list) and head else head
            msg = f"World Bank returned an API error for {self.series_code}: {detail}"
            raise TransformationError(msg, source_key=self.source.key)

        if not isinstance(head, dict):
            msg = "World Bank metadata block is not an object"
            raise TransformationError(msg, source_key=self.source.key)

        rows = payload[1]
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            msg = "World Bank data block is not an array"
            raise TransformationError(msg, source_key=self.source.key)

        pages = int(head.get("pages") or 1)
        if pages > 1:
            # PAGE_SIZE is far above every MVP series length; if this ever trips,
            # the connector must learn to paginate rather than silently truncate.
            msg = (
                f"World Bank returned {pages} pages for {self.series_code}; "
                f"the connector only reads the first {PAGE_SIZE} rows"
            )
            raise TransformationError(msg, source_key=self.source.key, pages=pages)

        return head, rows

    def _to_decimal(self, value: Any, year: str) -> Decimal:
        """Convert a JSON number to :class:`~decimal.Decimal` without float loss."""
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            msg = f"Non-numeric value {value!r} for {self.series_code} {year}"
            raise TransformationError(msg, source_key=self.source.key, year=year) from exc

    @staticmethod
    def _parse_last_updated(value: Any) -> datetime | None:
        """Parse the World Bank ``lastupdated`` date into a UTC datetime."""
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            return datetime.fromisoformat(value.strip()).replace(tzinfo=UTC)
        except ValueError:
            return None
