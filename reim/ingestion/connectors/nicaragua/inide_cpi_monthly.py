"""Nicaragua — monthly consumer price index published by INIDE.

INIDE (Instituto Nacional de Información de Desarrollo) is Nicaragua's national
statistics office and the official producer of the IPC. This is REIM's first
national primary source and its first monthly series.

How the source works
--------------------
INIDE publishes one Excel workbook per month at
https://www.inide.gob.ni/Home/ipc. Each release contains the **complete
historical series**, not just the new month, so a single download yields the
whole dataset.

Two properties of the source shape this connector:

1. **File URLs are not derivable.** Directory and file naming drift between
   releases — ``ipc_2025/ipc_abr25/``, ``ipc_2024/ipc_abril24/``,
   ``ipc_2023/ipc_Ene2023/``, and March 2026 is
   ``Estadisticas_del_IPC_a_marzo_de_2026.xls`` rather than the usual
   ``Cuadros_Estadisticas_IPC_marzo_2026.xls``. The connector therefore reads
   the index page and *discovers* the newest workbook instead of guessing a URL.
   This is HTML parsing, but only to locate a document — every actual value
   comes from the structured spreadsheet.

2. **The workbook layout is stable.** Sheet ``2-1-06`` ("Cuadro II-1-06") has
   carried the same title, base-year note and column headers across the 2023,
   2025 and 2026 releases that were checked. The connector asserts all three
   before reading a single value, so a layout change fails loudly rather than
   producing silently wrong numbers.

Layout of sheet ``2-1-06``
--------------------------
Column 0 holds either a year (an annual summary row) or a Spanish month name
belonging to the most recent year above it. Columns 2-5 are the national series:

===  ==========================================
Col  Content
===  ==========================================
2    IPC nacional, index, base 2006 = 100
3    Variación % mensual (month on month)
4    Variación % acumulada (year to date)
5    Variación % interanual (year on year)
===  ==========================================

Columns 6-9 repeat the block for Managua and 10-13 for the rest of the country.
Only the **national** series is ingested in this version; the regional
breakdowns are a documented future extension.

Deliberate omissions
--------------------
* **Annual rows are not ingested.** INIDE's yearly figure is the arithmetic mean
  of that year's monthly indices, so for the current year it is a partial-year
  average that changes every month. Storing it would manufacture a stream of
  spurious "revisions" for a number that is not yet final.
* **The year-to-date column is not ingested.** It is a running total that is
  fully reconstructible from the monthly series.
* **Missing values are skipped.** Every month of 2007 carries ``-`` in the
  month-on-month column because there is no December 2006 in the rebased series.
  Those observations are simply not produced — never zero-filled.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Any, ClassVar, NamedTuple

import xlrd

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

#: Page listing every published IPC workbook.
INDEX_PATH = "/Home/ipc"

#: Worksheet holding the national index and its variations.
SHEET_NAME = "2-1-06"

#: First year from which INIDE publishes an unbroken run of monthly figures.
#: Earlier history is genuinely sparse in the source — annual rows only for
#: 2001-2006 and 2008-2010 — so continuity is only enforced from here on.
CONTIGUOUS_FROM_YEAR = 2011

#: Index base declared in cell A2. If INIDE rebases the series this stops
#: matching and the connector refuses to mix incompatible bases.
EXPECTED_BASE_NOTE = "2006 = 100"

#: Column headers asserted in row 3 before any value is read.
EXPECTED_HEADERS: dict[int, str] = {
    2: "nacional",
    3: "mensual",
    4: "acumulada",
    5: "interanual",
}

#: INIDE stores the index to six decimal places and displays it to one; the
#: variation columns are spreadsheet formula results carrying full binary
#: precision. Values are quantised to six decimals, which preserves the whole
#: published precision of the index while discarding IEEE-754 storage noise
#: (Excel returns 321.00426699999997 for a stored 321.004267).
VALUE_DECIMALS = 6

MONTH_NUMBERS: dict[str, int] = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,  # occasional alternative spelling
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_HREF = re.compile(r'href\s*=\s*"([^"]+\.xlsx?)"', re.IGNORECASE)
_YEAR = re.compile(r"(20\d{2})")
_MONTH_NAME = re.compile("|".join(sorted(MONTH_NUMBERS, key=len, reverse=True)), re.IGNORECASE)

#: Columns mapped to the REIM indicator they feed.
COLUMN_INDICATORS: dict[int, tuple[str, str]] = {
    2: ("ni_cpi_index_monthly", "index (2006=100)"),
    3: ("ni_cpi_inflation_monthly", "percent"),
    5: ("ni_cpi_inflation_yoy", "percent"),
}


class Release(NamedTuple):
    """One published workbook, identified by the month it reports on."""

    year: int
    month: int
    url: str

    @property
    def label(self) -> str:
        """Period label of the month this release reports on."""
        return f"{self.year}-{self.month:02d}"


class InideCpiMonthly(BaseConnector):
    """Monthly national CPI (index, month-on-month and year-on-year) from INIDE."""

    connector_key = "inide_cpi_monthly"
    version = "1.0.0"
    expected_frequency = Frequency.MONTHLY
    country_iso3: ClassVar[str] = "NIC"

    @property
    def index_url(self) -> str:
        """URL of the page listing the published workbooks."""
        return f"{str(self.source.base_url).rstrip('/')}{INDEX_PATH}"

    # -- Extract ----------------------------------------------------------
    async def extract(self) -> RawDataset:
        """Discover the newest workbook from the index page and download it."""
        retrieved_at = datetime.now(UTC)

        async with http_client() as client:
            listing = await fetch(client, self.index_url)
            ensure_ok(listing, expected_content_type="html")
            release = self._select_latest_release(listing.text)

            self.logger.info("inide.release_selected", release=release.label, url=release.url)

            workbook = await fetch(client, release.url)
            ensure_ok(workbook)
            content = workbook.content
            published_at = self._parse_last_modified(workbook.headers.get("last-modified"))

        if not content.startswith(b"\xd0\xcf\x11\xe0"):
            # OLE2 compound-document magic. Anything else (an HTML error page,
            # a redirect body) must not reach the parser.
            msg = f"Expected a legacy .xls workbook at {release.url}, got {content[:16]!r}"
            raise ExtractionError(msg, url=release.url, source_key=self.source.key)

        return RawDataset(
            source_key=self.source.key,
            retrieved_at=retrieved_at,
            source_url=release.url,
            payload=content,
            content_type=workbook.headers.get("content-type"),
            http_status=workbook.status_code,
            metadata={
                "release_label": release.label,
                "release_year": release.year,
                "release_month": release.month,
                "index_url": self.index_url,
                "bytes": len(content),
                "published_at": published_at.isoformat() if published_at else "",
            },
        )

    def _select_latest_release(self, html: str) -> Release:
        """Return the most recent workbook linked from the index page.

        Raises:
            ExtractionError: No spreadsheet link on the page could be resolved
                to a year and month.
        """
        base = str(self.source.base_url).rstrip("/")
        releases: list[Release] = []

        for href in _HREF.findall(html):
            if "/ipc" not in href.lower():
                continue
            resolved = self._resolve(base, href)
            dated = self._infer_period(resolved)
            if dated is not None:
                releases.append(Release(dated[0], dated[1], resolved))

        if not releases:
            msg = (
                f"No dated IPC workbook link found on {self.index_url}; "
                "the page layout may have changed"
            )
            raise ExtractionError(msg, url=self.index_url, source_key=self.source.key)

        latest = max(releases, key=lambda item: (item.year, item.month))
        self.logger.info("inide.index_parsed", candidates=len(releases), latest=latest.label)
        return latest

    @staticmethod
    def _resolve(base: str, href: str) -> str:
        """Turn a possibly relative href into an absolute URL."""
        if href.startswith("http://") or href.startswith("https://"):
            return href
        return f"{base}/{href.lstrip('/')}"

    @staticmethod
    def _infer_period(url: str) -> tuple[int, int] | None:
        """Infer ``(year, month)`` from a workbook URL.

        The file name is preferred; the directory is the fallback for older
        releases whose file name omits the year.
        """
        path = url.split("?", 1)[0]
        directory, _, filename = path.rpartition("/")

        month_match = _MONTH_NAME.search(filename) or _MONTH_NAME.search(directory)
        if month_match is None:
            return None
        month = MONTH_NUMBERS[month_match.group(0).lower()]

        year_match = _YEAR.search(filename) or _YEAR.search(directory)
        if year_match is None:
            return None
        return int(year_match.group(1)), month

    @staticmethod
    def _parse_last_modified(header: str | None) -> datetime | None:
        """Parse the HTTP ``Last-Modified`` header, used as ``published_at``.

        INIDE publishes no machine-readable publication date inside the
        workbook, so the server's own timestamp is the best available signal.
        """
        if not header:
            return None
        try:
            parsed = parsedate_to_datetime(header)
        except (TypeError, ValueError):
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    # -- Transform --------------------------------------------------------
    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Parse sheet ``2-1-06`` into monthly observations for three indicators."""
        if not isinstance(raw.payload, bytes):
            msg = "INIDE payload must be the raw .xls bytes"
            raise TransformationError(msg, source_key=self.source.key)

        try:
            book = xlrd.open_workbook(file_contents=raw.payload)
        except Exception as exc:
            msg = f"Could not open the INIDE workbook: {type(exc).__name__}: {exc}"
            raise TransformationError(msg, source_key=self.source.key) from exc

        if SHEET_NAME not in book.sheet_names():
            msg = (
                f"Worksheet {SHEET_NAME!r} not found in the INIDE workbook; "
                f"available: {', '.join(book.sheet_names())}"
            )
            raise TransformationError(msg, source_key=self.source.key)

        sheet = book.sheet_by_name(SHEET_NAME)
        self._assert_layout(sheet)

        published_at = self._published_at(raw)
        observations: list[NormalizedObservation] = []
        current_year: int | None = None

        for row in range(sheet.nrows):
            label = sheet.cell_value(row, 0)

            if isinstance(label, float) and 1990 < label < 2100:
                # Annual summary row: it sets the year for the months below it
                # but is not ingested (see the module docstring).
                current_year = int(label)
                continue

            month = MONTH_NUMBERS.get(str(label).strip().lower())
            if month is None or current_year is None:
                continue

            period = parse_period(f"{current_year}-{month:02d}", Frequency.MONTHLY)
            for column, (indicator_code, unit) in COLUMN_INDICATORS.items():
                value = self._decimal_at(sheet, row, column)
                if value is None:
                    # "-" or blank: the source does not publish this figure for
                    # this month. Skip it; never substitute a zero.
                    continue
                observations.append(
                    NormalizedObservation(
                        country_iso3=self.country_iso3,
                        indicator_code=indicator_code,
                        source_key=self.source.key,
                        period=period,
                        unit=unit,
                        value_numeric=value,
                        retrieved_at=raw.retrieved_at,
                        source_url=raw.source_url,
                        published_at=published_at,
                        source_record_id=f"{SHEET_NAME}:{period.label}:c{column}",
                        raw_metadata={
                            "inide_sheet": SHEET_NAME,
                            "inide_column": column,
                            "inide_series": "nacional",
                            "inide_base_year": 2006,
                            "inide_release": str(raw.metadata.get("release_label", "")),
                        },
                    )
                )

        observations.sort(key=lambda obs: (obs.indicator_code, obs.period.start))
        self.logger.info(
            "inide.transformed",
            observations=len(observations),
            months=len({obs.period.label for obs in observations}),
        )
        return observations

    def _assert_layout(self, sheet: Any) -> None:
        """Fail loudly if the workbook is not the layout this connector expects.

        Guards against two silent-corruption modes: INIDE rebasing the index
        (which would make old and new values incomparable) and the columns being
        reordered.
        """
        base_note = " ".join(str(sheet.cell_value(1, 0)).split())
        if EXPECTED_BASE_NOTE not in base_note:
            msg = (
                f"INIDE workbook declares base {base_note!r}, expected "
                f"{EXPECTED_BASE_NOTE!r}. The index may have been rebased; "
                "values from different bases must not be mixed."
            )
            raise TransformationError(msg, source_key=self.source.key, base_note=base_note)

        for column, expected in EXPECTED_HEADERS.items():
            actual = str(sheet.cell_value(3, column)).strip().lower()
            if actual != expected:
                msg = (
                    f"Unexpected header in sheet {SHEET_NAME} column {column}: "
                    f"got {actual!r}, expected {expected!r}"
                )
                raise TransformationError(msg, source_key=self.source.key, column=column)

    @staticmethod
    def _decimal_at(sheet: Any, row: int, column: int) -> Decimal | None:
        """Read a numeric cell, or return ``None`` when the source has no figure."""
        if column >= sheet.ncols:
            return None
        value = sheet.cell_value(row, column)
        if not isinstance(value, float):
            # "-", "..." or an empty cell.
            return None
        return Decimal(str(round(value, VALUE_DECIMALS)))

    @staticmethod
    def _published_at(raw: RawDataset) -> datetime | None:
        """Recover the publication timestamp captured during extraction."""
        stamp = str(raw.metadata.get("published_at") or "")
        if not stamp:
            return None
        try:
            return datetime.fromisoformat(stamp)
        except ValueError:
            return None

    # -- Validate ---------------------------------------------------------
    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert INIDE-specific expectations beyond the standard battery."""
        results: list[QualityResult] = []
        results.append(self._check_all_indicators_present(observations))
        results.append(self._check_index_series_complete(observations))
        return results

    def _check_all_indicators_present(
        self, observations: list[NormalizedObservation]
    ) -> QualityResult:
        """Every catalog indicator must receive data, or a column stopped parsing."""
        expected = {code for code, _ in COLUMN_INDICATORS.values()}
        found = {obs.indicator_code for obs in observations}
        missing = sorted(expected - found)

        if not missing:
            return QualityResult.passed(
                "inide_all_indicators_present",
                CheckType.COMPLETENESS,
                f"All {len(expected)} indicators received data",
                expected_value=str(len(expected)),
                actual_value=str(len(found)),
            )
        return QualityResult.failure(
            "inide_all_indicators_present",
            CheckType.COMPLETENESS,
            CheckSeverity.CRITICAL,
            f"No data parsed for: {', '.join(missing)}",
            expected_value=str(sorted(expected)),
            actual_value=str(sorted(found)),
        )

    def _check_index_series_complete(
        self, observations: list[NormalizedObservation]
    ) -> QualityResult:
        """The index must be unbroken from :data:`CONTIGUOUS_FROM_YEAR` onward.

        INIDE's own table is sparse before that: sheet ``2-1-06`` carries annual
        rows only for 2001-2006 and 2008-2010, with monthly detail for 2007 and
        then continuously from 2011. That history is a property of the source,
        not a parsing fault, so it is not treated as a failure. The modern
        stretch, however, must never develop a hole — one there would mean the
        workbook was truncated or the row scan broke.
        """
        months = sorted(
            obs.period.start for obs in observations if obs.indicator_code == "ni_cpi_index_monthly"
        )
        if not months:
            return QualityResult.skipped(
                "inide_index_continuity",
                CheckType.COMPLETENESS,
                "No index observations to assess",
            )

        modern = [month for month in months if month.year >= CONTIGUOUS_FROM_YEAR]
        if not modern:
            return QualityResult.failure(
                "inide_index_continuity",
                CheckType.COMPLETENESS,
                CheckSeverity.ERROR,
                f"No monthly index at or after {CONTIGUOUS_FROM_YEAR}",
                expected_value=f">= 1 month from {CONTIGUOUS_FROM_YEAR}",
                actual_value="0",
            )

        span = (modern[-1].year - modern[0].year) * 12 + modern[-1].month - modern[0].month + 1
        gaps = span - len(modern)
        legacy = len(months) - len(modern)

        if gaps == 0:
            return QualityResult.passed(
                "inide_index_continuity",
                CheckType.COMPLETENESS,
                f"Index unbroken {modern[0]:%Y-%m}..{modern[-1]:%Y-%m} "
                f"({len(modern)} months), plus {legacy} sparse pre-"
                f"{CONTIGUOUS_FROM_YEAR} month(s) the source publishes",
                expected_value="0",
                actual_value="0",
            )
        return QualityResult.failure(
            "inide_index_continuity",
            CheckType.COMPLETENESS,
            CheckSeverity.ERROR,
            f"Index has {gaps} missing month(s) between {modern[0]:%Y-%m} and "
            f"{modern[-1]:%Y-%m}, where the source publishes continuously",
            expected_value="0",
            actual_value=str(gaps),
        )
