"""INIDE monthly CPI connector, replayed against recorded fixtures.

No test here performs a real network call.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from reim.core.constants import CheckSeverity, Frequency
from reim.core.exceptions import ExtractionError, TransformationError
from reim.domain.pipelines.models import RawDataset
from reim.domain.sources.catalog import SourceEntry
from reim.ingestion.connectors.nicaragua.inide_cpi_monthly import (
    SHEET_NAME,
    InideCpiMonthly,
    Release,
)

RETRIEVED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
INDEX_URL = "https://www.inide.gob.ni/Home/ipc"
WORKBOOK_URL = (
    "https://www.inide.gob.ni/docs/ipc/ipc_2026/ipc_jun26/Cuadros_Estadisticas_IPC_junio_2026.xls"
)


def _raw(payload: object, **metadata: object) -> RawDataset:
    return RawDataset(
        source_key="inide_cpi_monthly",
        retrieved_at=RETRIEVED_AT,
        source_url=WORKBOOK_URL,
        payload=payload,
        content_type="application/vnd.ms-excel",
        http_status=200,
        metadata={"release_label": "2026-06", **metadata},
    )


@pytest.fixture
def connector(inide_source: SourceEntry) -> InideCpiMonthly:
    return InideCpiMonthly(inide_source)


# --------------------------------------------------------------------------
# Release discovery
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # Current convention.
        ("/docs/ipc/ipc_2026/ipc_jun26/Cuadros_Estadisticas_IPC_junio_2026.xls", (2026, 6)),
        # June 2026's neighbour that breaks the file-name convention entirely.
        ("/docs/ipc/ipc_2026/ipc_mar26/Estadisticas_del_IPC_a_marzo_de_2026.xls", (2026, 3)),
        # Older directory conventions: full month name, capitalised, abbreviated.
        ("/docs/ipc/ipc_2024/ipc_abril24/Cuadros_Estadisticas_IPC_abril_2024.xls", (2024, 4)),
        ("/docs/ipc/ipc_2023/ipc_Ene2023/Cuadros_Estadisticas_IPC_enero_2023.xls", (2023, 1)),
        ("/docs/ipc/ipc_2024/ipc_Dic24/Cuadros_Estadisticas_IPC_diciembre_2024.xls", (2024, 12)),
        # File name carries no year: fall back to the directory.
        ("/docs/ipc/T22020/Cuadros_de_Estadisticas_del_IPC_abril.xls", (2020, 4)),
        ("/docs/ipc/dic2020/Cuadros_de_Estadisticas_del_IPC_diciembre2020.xlsx", (2020, 12)),
    ],
)
def test_period_inferred_from_irregular_urls(url: str, expected: tuple[int, int]) -> None:
    """URL naming drifts between releases; discovery must survive all of it."""
    assert InideCpiMonthly._infer_period(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "/docs/ipc/whatever/Cuadros_Estadisticas_IPC_2026.xls",  # no month
        "/docs/ipc/whatever/Cuadros_de_Estadisticas.xls",  # no month, no year
    ],
)
def test_undatable_urls_are_ignored(url: str) -> None:
    assert InideCpiMonthly._infer_period(url) is None


def test_latest_release_selected_from_real_index(
    connector: InideCpiMonthly, inide_index_html: str
) -> None:
    release = connector._select_latest_release(inide_index_html)
    assert (release.year, release.month) == (2026, 6)
    assert release.url == WORKBOOK_URL
    assert release.label == "2026-06"


def test_selection_prefers_the_newest_not_the_first_listed(
    connector: InideCpiMonthly,
) -> None:
    """The page is not ordered by date, so discovery must compare, not take [0]."""
    html = """
      <a href="/docs/ipc/ipc_2023/ipc_ene2023/Cuadros_Estadisticas_IPC_enero_2023.xls">a</a>
      <a href="/docs/ipc/ipc_2026/ipc_jun26/Cuadros_Estadisticas_IPC_junio_2026.xls">b</a>
      <a href="/docs/ipc/ipc_2025/ipc_dic25/Cuadros_Estadisticas_IPC_diciembre_2025.xls">c</a>
    """
    assert connector._select_latest_release(html).label == "2026-06"


def test_relative_and_absolute_hrefs_both_resolve(connector: InideCpiMonthly) -> None:
    html = (
        '<a href="https://www.inide.gob.ni/docs/ipc/ipc_2026/ipc_jun26/'
        'Cuadros_Estadisticas_IPC_junio_2026.xls">x</a>'
    )
    assert connector._select_latest_release(html).url == WORKBOOK_URL


def test_page_without_workbook_links_raises(connector: InideCpiMonthly) -> None:
    with pytest.raises(ExtractionError, match="No dated IPC workbook"):
        connector._select_latest_release("<html><body>site redesigned</body></html>")


def test_non_ipc_spreadsheets_are_ignored(connector: InideCpiMonthly) -> None:
    """The page links other publications; only IPC workbooks are candidates."""
    html = (
        '<a href="/docs/enif/Encuesta_enero_2027.xls">other</a>'
        '<a href="/docs/ipc/ipc_2026/ipc_jun26/Cuadros_Estadisticas_IPC_junio_2026.xls">ipc</a>'
    )
    assert connector._select_latest_release(html).label == "2026-06"


def test_release_label_formats_month() -> None:
    assert Release(2026, 3, "u").label == "2026-03"


# --------------------------------------------------------------------------
# Transform
# --------------------------------------------------------------------------
def test_transform_parses_the_real_workbook(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    observations = connector.transform(_raw(inide_workbook_bytes))

    by_indicator: dict[str, int] = {}
    for obs in observations:
        by_indicator[obs.indicator_code] = by_indicator.get(obs.indicator_code, 0) + 1

    # 198 months of index and year-on-year; 2007 has no month-on-month figure.
    assert by_indicator == {
        "ni_cpi_index_monthly": 198,
        "ni_cpi_inflation_yoy": 198,
        "ni_cpi_inflation_monthly": 186,
    }
    assert len(observations) == 582


def test_transform_produces_monthly_periods(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    observations = connector.transform(_raw(inide_workbook_bytes))
    assert all(obs.period.frequency is Frequency.MONTHLY for obs in observations)

    june = next(
        obs
        for obs in observations
        if obs.indicator_code == "ni_cpi_index_monthly" and obs.period.label == "2026-06"
    )
    assert june.period.start == date(2026, 6, 1)
    assert june.period.end == date(2026, 6, 30)


def test_transform_reads_the_published_values(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    """Values cross-checked by hand against the workbook's June 2026 row."""
    observations = connector.transform(_raw(inide_workbook_bytes))
    june = {
        obs.indicator_code: obs.value_numeric
        for obs in observations
        if obs.period.label == "2026-06"
    }
    assert june["ni_cpi_index_monthly"] == Decimal("326.390947")
    assert june["ni_cpi_inflation_monthly"] == Decimal("0.125374")
    assert june["ni_cpi_inflation_yoy"] == Decimal("3.983389")


def test_values_are_quantised_without_float_noise(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    """Excel returns 321.00426699999997 for a stored 321.004267."""
    observations = connector.transform(_raw(inide_workbook_bytes))
    january = next(
        obs
        for obs in observations
        if obs.indicator_code == "ni_cpi_index_monthly" and obs.period.label == "2026-01"
    )
    assert january.value_numeric == Decimal("321.004267")
    assert str(january.value_numeric) == "321.004267"


def test_annual_summary_rows_are_not_ingested(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    """INIDE's yearly figure is a year average, partial for the current year."""
    observations = connector.transform(_raw(inide_workbook_bytes))
    assert all(obs.period.frequency is Frequency.MONTHLY for obs in observations)
    assert not any(obs.period.days > 31 for obs in observations)


def test_months_without_a_figure_are_skipped_not_zeroed(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    """2007 carries '-' for month-on-month; those rows must simply not exist."""
    observations = connector.transform(_raw(inide_workbook_bytes))
    monthly_2007 = [
        obs
        for obs in observations
        if obs.indicator_code == "ni_cpi_inflation_monthly" and obs.period.start.year == 2007
    ]
    assert monthly_2007 == []
    assert all(obs.value_numeric is not None for obs in observations)


def test_documented_source_gap_is_preserved(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    """INIDE publishes no monthly detail for 2008-2010; REIM must not invent it."""
    observations = connector.transform(_raw(inide_workbook_bytes))
    years = {
        obs.period.start.year
        for obs in observations
        if obs.indicator_code == "ni_cpi_index_monthly"
    }
    assert {2008, 2009, 2010}.isdisjoint(years)
    assert 2007 in years
    assert 2011 in years


def test_transform_records_provenance(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    observations = connector.transform(
        _raw(inide_workbook_bytes, published_at="2026-07-10T19:17:18+00:00")
    )
    obs = observations[0]
    assert obs.country_iso3 == "NIC"
    assert obs.source_key == "inide_cpi_monthly"
    assert obs.source_url == WORKBOOK_URL
    assert obs.retrieved_at == RETRIEVED_AT
    assert obs.published_at == datetime(2026, 7, 10, 19, 17, 18, tzinfo=UTC)
    assert obs.raw_metadata["inide_sheet"] == SHEET_NAME
    assert obs.raw_metadata["inide_base_year"] == 2006
    assert obs.raw_metadata["inide_release"] == "2026-06"
    assert obs.source_record_id.startswith(f"{SHEET_NAME}:")


def test_transform_is_pure(connector: InideCpiMonthly, inide_workbook_bytes: bytes) -> None:
    raw = _raw(inide_workbook_bytes)
    first = [obs.compute_content_hash() for obs in connector.transform(raw)]
    second = [obs.compute_content_hash() for obs in connector.transform(raw)]
    assert first == second


def test_index_units_are_labelled_with_the_base_year(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    observations = connector.transform(_raw(inide_workbook_bytes))
    units = {obs.indicator_code: obs.unit for obs in observations}
    assert units["ni_cpi_index_monthly"] == "index (2006=100)"
    assert units["ni_cpi_inflation_monthly"] == "percent"
    assert units["ni_cpi_inflation_yoy"] == "percent"


def test_missing_published_at_is_tolerated(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    observations = connector.transform(_raw(inide_workbook_bytes, published_at=""))
    assert observations[0].published_at is None


# -- Transform failure modes ------------------------------------------------
def test_non_bytes_payload_is_rejected(connector: InideCpiMonthly) -> None:
    with pytest.raises(TransformationError, match=r"raw \.xls bytes"):
        connector.transform(_raw("not bytes"))


def test_unopenable_workbook_is_rejected(connector: InideCpiMonthly) -> None:
    with pytest.raises(TransformationError, match="Could not open"):
        connector.transform(_raw(b"\xd0\xcf\x11\xe0 truncated garbage"))


def test_rebased_index_is_refused(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes, monkeypatch
) -> None:
    """If INIDE rebases the series, mixing bases would corrupt the history."""
    import xlrd

    real_open = xlrd.open_workbook

    def fake_open(**kwargs: object):  # type: ignore[no-untyped-def]
        book = real_open(**kwargs)
        sheet = book.sheet_by_name(SHEET_NAME)
        sheet._cell_values[1][0] = "(Año base, 2024 = 100)"
        return book

    monkeypatch.setattr(
        "reim.ingestion.connectors.nicaragua.inide_cpi_monthly.xlrd.open_workbook", fake_open
    )
    with pytest.raises(TransformationError, match="rebased"):
        connector.transform(_raw(inide_workbook_bytes))


def test_reordered_columns_are_refused(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes, monkeypatch
) -> None:
    import xlrd

    real_open = xlrd.open_workbook

    def fake_open(**kwargs: object):  # type: ignore[no-untyped-def]
        book = real_open(**kwargs)
        book.sheet_by_name(SHEET_NAME)._cell_values[3][3] = "Trimestral"
        return book

    monkeypatch.setattr(
        "reim.ingestion.connectors.nicaragua.inide_cpi_monthly.xlrd.open_workbook", fake_open
    )
    with pytest.raises(TransformationError, match="Unexpected header"):
        connector.transform(_raw(inide_workbook_bytes))


# --------------------------------------------------------------------------
# Validate
# --------------------------------------------------------------------------
def test_validate_passes_on_the_real_workbook(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    observations = connector.transform(_raw(inide_workbook_bytes))
    assert [r for r in connector.validate(observations) if r.failed] == []


def test_validate_reports_the_documented_sparse_history(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    observations = connector.transform(_raw(inide_workbook_bytes))
    continuity = next(
        r for r in connector.validate(observations) if r.check_name == "inide_index_continuity"
    )
    assert not continuity.failed
    assert "2011-01..2026-06" in continuity.message
    assert "sparse pre-2011" in continuity.message


def test_validate_flags_a_hole_in_the_modern_series(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    observations = [
        obs
        for obs in connector.transform(_raw(inide_workbook_bytes))
        if obs.period.label != "2015-05"
    ]
    continuity = next(
        r for r in connector.validate(observations) if r.check_name == "inide_index_continuity"
    )
    assert continuity.failed
    assert continuity.severity is CheckSeverity.ERROR
    assert continuity.actual_value == "1"


def test_validate_fails_when_an_indicator_produced_nothing(
    connector: InideCpiMonthly, inide_workbook_bytes: bytes
) -> None:
    observations = [
        obs
        for obs in connector.transform(_raw(inide_workbook_bytes))
        if obs.indicator_code != "ni_cpi_inflation_yoy"
    ]
    result = next(
        r
        for r in connector.validate(observations)
        if r.check_name == "inide_all_indicators_present"
    )
    assert result.failed
    assert result.severity is CheckSeverity.CRITICAL
    assert "ni_cpi_inflation_yoy" in result.message


# --------------------------------------------------------------------------
# Extract (mocked HTTP)
# --------------------------------------------------------------------------
@respx.mock
async def test_extract_discovers_then_downloads(
    connector: InideCpiMonthly, inide_index_html: str, inide_workbook_bytes: bytes
) -> None:
    index = respx.get(INDEX_URL).mock(return_value=httpx.Response(200, html=inide_index_html))
    workbook = respx.get(WORKBOOK_URL).mock(
        return_value=httpx.Response(
            200,
            content=inide_workbook_bytes,
            headers={
                "content-type": "application/vnd.ms-excel",
                "last-modified": "Fri, 10 Jul 2026 19:17:18 GMT",
            },
        )
    )

    raw = await connector.extract()

    assert index.called and workbook.called
    assert raw.source_url == WORKBOOK_URL
    assert raw.metadata["release_label"] == "2026-06"
    assert raw.metadata["published_at"] == "2026-07-10T19:17:18+00:00"
    assert isinstance(raw.payload, bytes)
    assert raw.payload.startswith(b"\xd0\xcf\x11\xe0")


@respx.mock
async def test_extract_rejects_a_non_workbook_body(
    connector: InideCpiMonthly, inide_index_html: str
) -> None:
    """A redirect to an HTML error page must never reach the parser."""
    respx.get(INDEX_URL).mock(return_value=httpx.Response(200, html=inide_index_html))
    respx.get(WORKBOOK_URL).mock(
        return_value=httpx.Response(200, html="<html>404 - File not found</html>")
    )
    with pytest.raises(ExtractionError, match=r"legacy \.xls workbook"):
        await connector.extract()


@respx.mock
async def test_extract_fails_when_the_index_is_unreachable(
    connector: InideCpiMonthly,
) -> None:
    respx.get(INDEX_URL).mock(side_effect=httpx.ConnectError("no route"))
    with pytest.raises(ExtractionError):
        await connector.extract()


@respx.mock
async def test_extract_sends_the_identifying_user_agent(
    connector: InideCpiMonthly, inide_index_html: str, inide_workbook_bytes: bytes
) -> None:
    index = respx.get(INDEX_URL).mock(return_value=httpx.Response(200, html=inide_index_html))
    respx.get(WORKBOOK_URL).mock(
        return_value=httpx.Response(
            200, content=inide_workbook_bytes, headers={"content-type": "application/vnd.ms-excel"}
        )
    )
    await connector.extract()
    assert "REIM" in index.calls[0].request.headers["user-agent"]
