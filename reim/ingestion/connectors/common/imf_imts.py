"""Merchandise trade from the IMF's SDMX API — shared connector base.

Why the IMF and not the Banco Central de Nicaragua
--------------------------------------------------
The BCN publishes these figures in its monthly bulletins, but
``www.bcn.gob.ni`` redirects every automated request to a Radware bot manager
challenge. Passing it would mean defeating an access control the publisher
installed deliberately, so REIM reads the same indicators from the IMF's
International Merchandise Trade Statistics instead. See ``docs/sources.md``.

The request
-----------
``GET {base_url}/data/IMF.STA,IMTS/NIC..G001.M?startPeriod=1990-01`` with
``Accept: application/vnd.sdmx.data+csv;version=2.0.0``. The key dimensions are
``COUNTRY.INDICATOR.COUNTERPART_COUNTRY.FREQUENCY``.

Three properties of the source shape this connector:

1. **The counterpart is filtered in the key, not after download.** Asking for
   every counterpart returns 103 of them and 62.9 MB; asking for ``G001``
   alone returns the same 1,308 usable rows in 789 KB.
2. **Counterpart groups overlap, so they must never be summed.** Adding all
   103 counterparts for June 2025 gives 1,804 million USD against a real 481
   million, because ``G001`` (world) and the regional groups already contain
   the individual countries.
3. **``SCALE`` is not a multiplier.** Every row reports ``SCALE=6`` while
   carrying full USD. It is recorded for provenance and never applied.

The API also ignores content negotiation — asking for SDMX-JSON returns
SDMX-ML regardless — so the connector pins the CSV media type and refuses a
response that is not CSV.

Licence
-------
Unlike every other source REIM reads, the IMF's data is **not** openly
licensed: it carries "© International Monetary Fund Copyright. All Rights
Reserved." The catalog records this as ``license: imf_terms_of_use`` rather
than ``public_official_data``. See ``docs/sources.md``.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

from reim.core.constants import CheckSeverity, CheckType, Frequency
from reim.core.exceptions import ExtractionError, TransformationError
from reim.domain.countries.registry import COUNTRIES_BY_ISO2
from reim.domain.observations.periods import parse_period
from reim.domain.pipelines.models import (
    NormalizedObservation,
    QualityResult,
    RawDataset,
)
from reim.ingestion.base import BaseConnector
from reim.ingestion.http import ensure_ok, fetch, http_client

#: SDMX agency and dataflow holding merchandise trade.
DATAFLOW = "IMF.STA,IMTS"
#: World aggregate. Counterpart groups overlap, so this is selected in the key
#: rather than reconstructed by summing.
COUNTERPART_WORLD = "G001"
#: SDMX frequency code for monthly.
FREQUENCY_CODE = "M"
#: Earliest month the dataflow holds for Nicaragua.
DEFAULT_START_PERIOD = "1990-01"
#: Media type pinned on the request and required of the response.
CSV_MEDIA_TYPE = "application/vnd.sdmx.data+csv;version=2.0.0"

#: IMF indicator code mapped to the REIM indicator it feeds and its unit.
INDICATORS: dict[str, tuple[str, str]] = {
    "XG_FOB_USD": ("exports_goods_monthly", "current USD"),
    "MG_CIF_USD": ("imports_goods_monthly", "current USD"),
    "TBG_USD": ("trade_balance_goods_monthly", "current USD"),
}

#: Largest accepted gap between the published balance and exports minus
#: imports. The IMF rounds TBG, so 12 of 436 recorded months differ in their
#: last digit; the worst deviation measured is 5e-8 USD.
BALANCE_TOLERANCE = Decimal("0.01")

#: Columns the parser cannot work without.
REQUIRED_COLUMNS = ("INDICATOR", "COUNTERPART_COUNTRY", "TIME_PERIOD", "OBS_VALUE")

_SDMX_MONTH = re.compile(r"^(?P<year>\d{4})-M(?P<month>0[1-9]|1[0-2])$")


class ImfImtsTradeConnector(BaseConnector):
    """Monthly merchandise exports, imports and balance for one country.

    Concrete per-country subclasses live under the country packages and add
    nothing but their catalog key; the country itself comes from the catalog
    entry.
    """

    version = "2.0.0"
    expected_frequency = Frequency.MONTHLY
    currency_code: ClassVar[str] = "USD"

    @property
    def country_iso3(self) -> str:
        """ISO-3 of the country this catalog entry covers.

        Read from the catalog rather than fixed on the class, so one module
        serves every country in the dataflow.

        Raises:
            ExtractionError: The entry declares no country, or one REIM does
                not know. Defaulting to any country would file its data under
                the wrong flag.
        """
        iso2 = self.source.country_iso2
        if iso2 is None:
            msg = f"{self.source.key} must declare a country"
            raise ExtractionError(msg, source_key=self.source.key)
        definition = COUNTRIES_BY_ISO2.get(iso2)
        if definition is None:
            msg = f"{self.source.key} names unknown country {iso2!r}"
            raise ExtractionError(msg, source_key=self.source.key)
        return definition.iso3

    @property
    def start_period(self) -> str:
        """First month requested; overridable through the catalog ``options``."""
        configured = self.source.options.get("start_period")
        return str(configured) if configured else DEFAULT_START_PERIOD

    @property
    def request_url(self) -> str:
        """Full SDMX data URL, counterpart already filtered."""
        base = str(self.source.base_url).rstrip("/")
        key = f"{self.country_iso3}..{COUNTERPART_WORLD}.{FREQUENCY_CODE}"
        return f"{base}/data/{DATAFLOW}/{key}"

    async def extract(self) -> RawDataset:
        """Fetch the whole series as one CSV response.

        Raises:
            ExtractionError: The API was unreachable, returned an error status,
                or answered with something other than CSV.
        """
        params = {"startPeriod": self.start_period}
        retrieved_at = datetime.now(UTC)

        async with http_client() as client:
            response = await fetch(
                client,
                self.request_url,
                params=params,
                headers={"Accept": CSV_MEDIA_TYPE},
            )
            ensure_ok(response, expected_content_type="csv")
            payload = response.text

        self.logger.info(
            "imf_imts.extracted",
            start_period=self.start_period,
            bytes=len(payload),
        )
        return RawDataset(
            source_key=self.source.key,
            retrieved_at=retrieved_at,
            source_url=str(response.request.url),
            payload=payload,
            content_type=response.headers.get("content-type"),
            http_status=response.status_code,
            metadata={
                "dataflow": DATAFLOW,
                "counterpart": COUNTERPART_WORLD,
                "start_period": self.start_period,
            },
        )

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Map the SDMX CSV onto one observation per month and series.

        Pure function of ``raw``. Rows for any counterpart other than
        :data:`COUNTERPART_WORLD` are discarded, and the dataflow metadata row
        — which carries no ``TIME_PERIOD`` — is skipped.

        Raises:
            TransformationError: The payload is not CSV text, a required column
                is absent, a period is unparseable, or a value is non-numeric.
        """
        if not isinstance(raw.payload, str):
            msg = "IMF payload must be the response CSV text"
            raise TransformationError(msg, source_key=self.source.key)

        reader = csv.DictReader(io.StringIO(raw.payload))
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or ())]
        if missing:
            msg = f"IMF CSV is missing column(s): {', '.join(missing)}"
            raise TransformationError(msg, source_key=self.source.key)

        observations: list[NormalizedObservation] = []
        for row in reader:
            period_label = (row.get("TIME_PERIOD") or "").strip()
            if not period_label:
                # Dataflow metadata row: no period, no observation.
                continue
            if (row.get("COUNTERPART_COUNTRY") or "").strip() != COUNTERPART_WORLD:
                continue

            imf_code = (row.get("INDICATOR") or "").strip()
            mapped = INDICATORS.get(imf_code)
            if mapped is None:
                continue
            indicator_code, unit = mapped

            raw_value = (row.get("OBS_VALUE") or "").strip()
            if not raw_value:
                # The IMF publishes no figure for this month. Skip it; never
                # substitute a zero.
                continue

            period = parse_period(self._month_label(period_label), Frequency.MONTHLY)
            observations.append(
                NormalizedObservation(
                    country_iso3=self.country_iso3,
                    indicator_code=indicator_code,
                    source_key=self.source.key,
                    period=period,
                    unit=unit,
                    currency_code=self.currency_code,
                    value_numeric=self._to_decimal(raw_value, period_label),
                    retrieved_at=raw.retrieved_at,
                    source_url=raw.source_url,
                    published_at=self._published_at(row),
                    source_record_id=f"imts:{imf_code}:{period.label}",
                    raw_metadata={
                        "imf_dataflow": (row.get("DATAFLOW") or "").strip(),
                        "imf_indicator": imf_code,
                        "imf_counterpart": COUNTERPART_WORLD,
                        "imf_unit": (row.get("UNIT") or "").strip(),
                        # Reported by the source but deliberately NOT applied:
                        # the values are already full USD.
                        "imf_scale": (row.get("SCALE") or "").strip(),
                    },
                )
            )

        observations.sort(key=lambda obs: (obs.indicator_code, obs.period.start))
        self.logger.info(
            "imf_imts.transformed",
            observations=len(observations),
            months=len({obs.period.label for obs in observations}),
        )
        return observations

    def _month_label(self, sdmx_period: str) -> str:
        """Convert SDMX ``2026-M04`` into REIM's ``2026-04``."""
        match = _SDMX_MONTH.match(sdmx_period)
        if match is None:
            msg = f"Unrecognised IMF monthly period {sdmx_period!r}"
            raise TransformationError(msg, source_key=self.source.key)
        return f"{match['year']}-{match['month']}"

    def _to_decimal(self, value: str, period_label: str) -> Decimal:
        """Build a Decimal from the published string, never through float."""
        try:
            return Decimal(value)
        except InvalidOperation as exc:
            msg = f"IMF returned a non-numeric value {value!r} for {period_label}"
            raise TransformationError(msg, source_key=self.source.key) from exc

    @staticmethod
    def _published_at(row: dict[str, Any]) -> datetime | None:
        """Read the dataset refresh timestamp, when the row carries one."""
        stamp = (row.get("PUBLICATION_DATE") or "").strip()
        if not stamp:
            return None
        try:
            parsed = datetime.fromisoformat(stamp)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert IMF-specific expectations beyond the standard battery."""
        return [
            self._check_world_aggregate_present(observations),
            self._check_all_indicators_present(observations),
            self._check_balance_identity(observations),
            self._check_country_match(observations),
        ]

    def _check_world_aggregate_present(
        self, observations: list[NormalizedObservation]
    ) -> QualityResult:
        """Without the world aggregate there are no totals to publish.

        Critical rather than error: the alternative to having ``G001`` is
        summing 103 overlapping counterpart groups, which double-counts. A run
        without it must not be committed at all.
        """
        kept = [
            obs
            for obs in observations
            if obs.raw_metadata.get("imf_counterpart") == COUNTERPART_WORLD
        ]
        if kept:
            return QualityResult.passed(
                "imf_imts_world_aggregate_present",
                CheckType.COMPLETENESS,
                f"{len(kept)} observation(s) carry the {COUNTERPART_WORLD} world aggregate",
                expected_value=f">0 {COUNTERPART_WORLD} rows",
                actual_value=str(len(kept)),
            )
        return QualityResult.failure(
            "imf_imts_world_aggregate_present",
            CheckType.COMPLETENESS,
            CheckSeverity.CRITICAL,
            f"No {COUNTERPART_WORLD} rows: the response carries no world totals",
            expected_value=f">0 {COUNTERPART_WORLD} rows",
            actual_value="0",
        )

    def _check_all_indicators_present(
        self, observations: list[NormalizedObservation]
    ) -> QualityResult:
        """All three series must arrive, or a column stopped mapping."""
        expected = {code for code, _ in INDICATORS.values()}
        found = {obs.indicator_code for obs in observations}
        missing = sorted(expected - found)

        if not missing:
            return QualityResult.passed(
                "imf_imts_all_indicators_present",
                CheckType.COMPLETENESS,
                f"All {len(expected)} indicators received data",
                expected_value=str(len(expected)),
                actual_value=str(len(found)),
            )
        return QualityResult.failure(
            "imf_imts_all_indicators_present",
            CheckType.COMPLETENESS,
            CheckSeverity.ERROR,
            f"No data parsed for: {', '.join(missing)}",
            expected_value=str(sorted(expected)),
            actual_value=str(sorted(found)),
        )

    def _check_balance_identity(self, observations: list[NormalizedObservation]) -> QualityResult:
        """The published balance must equal exports minus imports.

        Not an exact equality: the IMF publishes ``TBG`` rounded to about 16
        significant digits, so 12 of the 436 recorded months differ from
        ``XG - MG`` in their last digit. The largest deviation measured across
        the whole series is 5e-8 USD. :data:`BALANCE_TOLERANCE` sits four
        orders of magnitude above that noise, so it still catches a real
        misalignment, which would be off by millions rather than fractions of
        a cent.
        """
        by_period: dict[str, dict[str, Decimal]] = {}
        for obs in observations:
            if obs.value_numeric is None:
                continue
            by_period.setdefault(obs.period.label, {})[obs.indicator_code] = obs.value_numeric

        breaks: list[str] = []
        checked = 0
        for label in sorted(by_period):
            series = by_period[label]
            exports = series.get("exports_goods_monthly")
            imports = series.get("imports_goods_monthly")
            balance = series.get("trade_balance_goods_monthly")
            if exports is None or imports is None or balance is None:
                continue
            checked += 1
            if abs(balance - (exports - imports)) > BALANCE_TOLERANCE:
                breaks.append(label)

        if not breaks:
            return QualityResult.passed(
                "imf_imts_balance_identity",
                CheckType.CONSISTENCY,
                f"Balance equals exports minus imports in all {checked} complete month(s)",
                expected_value="0",
                actual_value="0",
            )

        shown = ", ".join(breaks[:5])
        suffix = f" (+{len(breaks) - 5} more)" if len(breaks) > 5 else ""
        return QualityResult.failure(
            "imf_imts_balance_identity",
            CheckType.CONSISTENCY,
            CheckSeverity.ERROR,
            f"{len(breaks)} of {checked} month(s) break TBG = XG - MG: {shown}{suffix}",
            expected_value="0",
            actual_value=str(len(breaks)),
        )

    def _check_country_match(self, observations: list[NormalizedObservation]) -> QualityResult:
        """Every row must belong to the country this entry declares.

        Critical: one module now serves six catalog entries, so a wrong key or
        a wrong response would file one country's trade under another's flag —
        and the counts would look perfectly healthy, because all six countries
        return the same 436 months.
        """
        expected = self.country_iso3
        foreign = sorted({obs.country_iso3 for obs in observations if obs.country_iso3 != expected})

        if not foreign:
            return QualityResult.passed(
                "imf_imts_country_match",
                CheckType.INTEGRITY,
                f"All {len(observations)} observation(s) reported for {expected}",
                expected_value=expected,
                actual_value=expected,
            )
        return QualityResult.failure(
            "imf_imts_country_match",
            CheckType.INTEGRITY,
            CheckSeverity.CRITICAL,
            f"Observations for {', '.join(foreign)} in a {expected} source",
            expected_value=expected,
            actual_value=", ".join(foreign),
        )
