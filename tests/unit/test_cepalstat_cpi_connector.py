"""Unit tests for the CEPALSTAT regional consumer price index connector.

Every payload replayed here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from reim.core.constants import CheckSeverity, CheckStatus, Frequency
from reim.core.exceptions import ExtractionError
from reim.domain.pipelines.models import NormalizedObservation, RawDataset
from reim.domain.sources.catalog import load_catalog
from reim.ingestion.connectors.regional.cepalstat_cpi import (
    CENTRAL_AMERICA,
    CepalstatCpiConnector,
)
from tests.conftest import REPO_ROOT

BASE_URL = "https://api-cepalstat.cepal.org/cepalstat/api/v1"

#: What the recording holds, measured on 2026-09-06.
ROWS_FOR_THE_SEVEN = 3451
SPANS = {
    "BLZ": ("1990-11", "2026-06", 266),
    "CRI": ("1980-01", "2026-06", 558),
    "GTM": ("1980-01", "2026-07", 559),
    "HND": ("1994-01", "2026-07", 391),
    "NIC": ("1980-01", "2026-07", 559),
    "PAN": ("1980-01", "2026-07", 559),
    "SLV": ("1980-01", "2026-07", 559),
}


@pytest.fixture
def connector() -> CepalstatCpiConnector:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    source = next(s for s in catalog.sources if s.key == "cepalstat_cpi_monthly")
    return CepalstatCpiConnector(source)


@pytest.fixture
def raw(cepalstat_cpi_365_json: str) -> RawDataset:
    return RawDataset(
        source_key="cepalstat_cpi_monthly",
        retrieved_at=datetime(2026, 9, 6, tzinfo=UTC),
        source_url=BASE_URL,
        payload={"data": cepalstat_cpi_365_json},
        content_type="application/json",
        http_status=200,
        metadata={"indicator_id": 365, "lang": "en"},
    )


def by_key(
    observations: list[NormalizedObservation],
) -> dict[tuple[str, str], Decimal | None]:
    return {(o.country_iso3, o.period.label): o.value_numeric for o in observations}


def test_stores_only_the_seven_countries(connector: CepalstatCpiConnector, raw: RawDataset) -> None:
    """The matrix carries 40 countries; REIM keeps seven."""
    observations = connector.transform(raw)

    assert len(observations) == ROWS_FOR_THE_SEVEN
    assert {o.country_iso3 for o in observations} == set(CENTRAL_AMERICA)


def test_each_country_span_matches_the_recording(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    observations = connector.transform(raw)

    for iso3, (first, last, count) in SPANS.items():
        labels = sorted(o.period.label for o in observations if o.country_iso3 == iso3)
        assert (labels[0], labels[-1], len(labels)) == (first, last, count)


def test_guatemalas_splice_is_stored_as_published(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    """A 42.6% fall that is a change of base, not deflation.

    Stored exactly as CEPAL published it. This test is the fact; the connector
    check is what stops a *new* one going unnoticed.
    """
    values = by_key(connector.transform(raw))

    assert values[("GTM", "2009-12")] == Decimal("94.882")
    assert values[("GTM", "2010-01")] == Decimal("54.4831537")


def test_el_salvadors_corrupt_cell_is_stored_as_published(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    """One bad value the series steps around — September over July is 1.0397."""
    values = by_key(connector.transform(raw))

    assert values[("SLV", "1985-07")] == Decimal("11.473")
    assert values[("SLV", "1985-08")] == Decimal("7.157")
    assert values[("SLV", "1985-09")] == Decimal("11.928")


def test_nicaraguas_redenominated_history_parses_exactly(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    """Scientific notation, down to 2E-9, held exactly by Decimal."""
    values = by_key(connector.transform(raw))
    nicaraguan = [v for (iso3, _), v in values.items() if iso3 == "NIC" and v is not None]

    assert min(nicaraguan) == Decimal("2E-9")
    assert max(nicaraguan) > Decimal("300")


def test_full_published_precision_is_kept(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    """CEPAL declares two decimals and publishes up to eight. Neither is rounded."""
    observations = connector.transform(raw)
    published = [o.raw_metadata["cepalstat_published_value"] for o in observations]
    decimals = {len(p.split(".")[1]) for p in published if "." in p}

    assert max(decimals) == 8


def test_the_unit_carries_no_base_year(connector: CepalstatCpiConnector, raw: RawDataset) -> None:
    """CEPAL's declared bases are wrong for three of five, so REIM states none."""
    observations = connector.transform(raw)

    assert {o.unit for o in observations} == {"index"}
    assert all(o.currency_code is None for o in observations)


def test_a_row_without_a_cited_source_stores_an_empty_string(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    """The freshest rows carry no source_id; REIM does not invent one."""
    observations = connector.transform(raw)
    recent = [o for o in observations if o.period.label >= "2024-01"]

    assert recent
    assert any(o.raw_metadata["cepalstat_source"] == "" for o in recent)
    assert all(o.raw_metadata["cepalstat_source"] != "None" for o in observations)


def test_the_published_data_features_string_is_stored_verbatim(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    """CEPAL's own trailing whitespace and CRLF, kept rather than tidied.

    Storing what the publisher published means not cleaning it up: a later
    change to this string is a change in the source, and trimming it here
    would hide that.
    """
    observations = connector.transform(raw)

    assert {o.raw_metadata["cepalstat_data_features"] for o in observations} == {
        "Official country figures \r\n"
    }


@respx.mock
async def test_extract_makes_one_request(
    connector: CepalstatCpiConnector, cepalstat_cpi_365_json: str
) -> None:
    route = respx.get(f"{BASE_URL}/indicator/365/data").mock(
        return_value=httpx.Response(
            200, text=cepalstat_cpi_365_json, headers={"content-type": "application/json"}
        )
    )
    dims = respx.get(f"{BASE_URL}/indicator/365/dimensions").mock(
        return_value=httpx.Response(200, json={})
    )

    result = await connector.extract()

    assert route.call_count == 1
    assert dims.call_count == 0
    assert route.calls[0].request.url.params["lang"] == "en"
    assert len(connector.transform(result)) == ROWS_FOR_THE_SEVEN


@respx.mock
async def test_a_failing_envelope_raises(connector: CepalstatCpiConnector) -> None:
    respx.get(f"{BASE_URL}/indicator/365/data").mock(
        return_value=httpx.Response(
            200,
            text=(
                '{"header": {"success": false, "code": 500, "message": "no data"}, '
                '"body": {"data": []}}'
            ),
            headers={"content-type": "application/json"},
        )
    )

    with pytest.raises(ExtractionError, match="500"):
        await connector.extract()


def test_periods_are_monthly(connector: CepalstatCpiConnector, raw: RawDataset) -> None:
    observations = connector.transform(raw)

    assert {o.period.frequency for o in observations} == {Frequency.MONTHLY}


def test_the_expected_countries_and_splice_checks_pass_on_the_recording(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    results = {r.check_name: r for r in connector.validate(connector.transform(raw))}

    assert list(results) == [
        "cepalstat_cpi_expected_countries",
        "cepalstat_cpi_known_splices",
        "cepalstat_monthly_continuity",
    ]
    assert results["cepalstat_cpi_expected_countries"].status is CheckStatus.PASSED
    assert results["cepalstat_cpi_known_splices"].status is CheckStatus.PASSED


def test_continuity_warns_about_belize_on_every_run(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    """Belize published quarterly until 2011. The warning is the correct output.

    Asserted as an expected warning rather than glossed over, so that if it
    ever stops firing someone notices the coverage changed.
    """
    results = {r.check_name: r for r in connector.validate(connector.transform(raw))}
    continuity = results["cepalstat_monthly_continuity"]

    assert continuity.status is CheckStatus.FAILED
    assert continuity.severity is CheckSeverity.WARNING
    assert "BLZ" in continuity.message


def test_a_missing_country_is_critical(connector: CepalstatCpiConnector, raw: RawDataset) -> None:
    observations = [o for o in connector.transform(raw) if o.country_iso3 != "CRI"]

    result = next(
        r
        for r in connector.validate(observations)
        if r.check_name == "cepalstat_cpi_expected_countries"
    )

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.CRITICAL
    assert "CRI" in result.message


def test_a_new_splice_fails(connector: CepalstatCpiConnector, raw: RawDataset) -> None:
    """Halving one Panamanian month is the shape of an unannounced rebase."""
    observations = connector.transform(raw)
    index = next(
        i
        for i, o in enumerate(observations)
        if o.country_iso3 == "PAN" and o.period.label == "2015-06"
    )
    halved = observations[index].value_numeric
    assert halved is not None
    observations[index] = replace(observations[index], value_numeric=halved / 2)

    result = next(
        r for r in connector.validate(observations) if r.check_name == "cepalstat_cpi_known_splices"
    )

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.ERROR
    assert "PAN 2015-06" in result.message


def test_the_measured_splices_do_not_fail_the_check(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    """Guatemala 2010-01 and El Salvador's 1985 pair are on the allow-list.

    Without all three entries this check would fail on real data every run —
    El Salvador's one corrupt cell produces two moves, not one.
    """
    result = next(
        r
        for r in connector.validate(connector.transform(raw))
        if r.check_name == "cepalstat_cpi_known_splices"
    )

    assert result.status is CheckStatus.PASSED
    assert "3 of the 3 known breaks" in result.message


def test_nicaraguan_hyperinflation_does_not_fail_the_check(
    connector: CepalstatCpiConnector, raw: RawDataset
) -> None:
    """58 real moves beyond 15%, excluded by date rather than enumerated."""
    observations = [
        o
        for o in connector.transform(raw)
        if o.country_iso3 == "NIC" and o.period.label < "1992-01"
    ]

    result = next(
        r for r in connector.validate(observations) if r.check_name == "cepalstat_cpi_known_splices"
    )

    assert result.status is CheckStatus.PASSED


def test_the_two_nicaraguan_indices_differ_by_a_stable_ratio(
    connector: CepalstatCpiConnector, raw: RawDataset, inide_workbook_bytes: bytes
) -> None:
    """REIM holds two official Nicaraguan CPIs and they disagree.

    CEPAL cites the Banco Central de Nicaragua; REIM reads INIDE directly.
    Both declare base 2006. Across the 198 months they share, not one agrees to
    the digit, but the ratio stays inside a narrow band — the signature of a
    rebasing difference between two compilers rather than a data disagreement.

    This is the regression test for that explanation. If a future CEPAL
    revision makes the two converge or diverge, the explanation has stopped
    being true and someone must look rather than assume.
    """
    from reim.ingestion.connectors.nicaragua.inide_cpi_monthly import InideCpiMonthly

    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    inide_source = next(s for s in catalog.sources if s.key == "inide_cpi_monthly")
    inide_raw = RawDataset(
        source_key="inide_cpi_monthly",
        retrieved_at=datetime(2026, 9, 6, tzinfo=UTC),
        source_url="https://www.inide.gob.ni",
        payload=inide_workbook_bytes,
        content_type="application/vnd.ms-excel",
        http_status=200,
        metadata={},
    )
    inide = {
        o.period.label: o.value_numeric
        for o in InideCpiMonthly(inide_source).transform(inide_raw)
        if o.indicator_code == "ni_cpi_index_monthly"
    }
    cepal = {
        o.period.label: o.value_numeric for o in connector.transform(raw) if o.country_iso3 == "NIC"
    }

    shared = sorted(set(inide) & set(cepal))
    assert len(shared) == 198

    ratios = []
    for label in shared:
        national, regional = inide[label], cepal[label]
        assert national is not None and regional is not None
        assert national != regional
        ratios.append(regional / national)

    assert Decimal("1.02") < min(ratios) < max(ratios) < Decimal("1.05")
