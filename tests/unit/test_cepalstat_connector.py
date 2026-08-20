"""Unit tests for the CEPALSTAT annual GDP connector.

Every payload replayed here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from reim.core.constants import CheckSeverity, CheckStatus, Frequency
from reim.core.exceptions import TransformationError
from reim.domain.pipelines.models import NormalizedObservation, QualityResult, RawDataset
from reim.domain.sources.catalog import load_catalog
from reim.ingestion.connectors.regional.cepalstat_gdp import (
    CENTRAL_AMERICA,
    CepalstatGdpConnector,
)
from tests.conftest import REPO_ROOT

#: What the recorded responses hold, measured on 2026-08-18.
YEARS_DIMENSION = 29117
COUNTRY_DIMENSION = 208
CELLS_PER_INDICATOR = 252


def cells_of(payload: str) -> dict[tuple[str, str], Decimal]:
    """Flatten one response into ``(iso3, year label) -> value`` for the seven."""
    body = json.loads(payload, parse_float=Decimal)["body"]
    years = next(d for d in body["dimensions"] if d["id"] == YEARS_DIMENSION)
    labels = {member["id"]: member["name"] for member in years["members"]}
    return {
        (row["iso3"], labels[row[f"dim_{YEARS_DIMENSION}"]]): Decimal(str(row["value"]))
        for row in body["data"]
        if row.get("iso3") in CENTRAL_AMERICA
    }


def test_each_fixture_covers_the_seven_countries_completely(
    cepalstat_gdp_2203_json: str,
    cepalstat_gdp_2204_json: str,
    cepalstat_gdp_2205_json: str,
    cepalstat_gdp_2206_json: str,
) -> None:
    """252 cells, 36 years each, no holes. A re-recording with gaps fails here."""
    for payload in (
        cepalstat_gdp_2203_json,
        cepalstat_gdp_2204_json,
        cepalstat_gdp_2205_json,
        cepalstat_gdp_2206_json,
    ):
        cells = cells_of(payload)
        assert len(cells) == CELLS_PER_INDICATOR
        assert {iso3 for iso3, _ in cells} == CENTRAL_AMERICA
        for iso3 in CENTRAL_AMERICA:
            assert sum(1 for c, _ in cells if c == iso3) == 36


#: 33 countries + 3 regional aggregates ("Caribbean", "Latin America", and
#: "Latin America and the Caribbean"), counted directly from a complete
#: recording of indicator 2203 on 2026-08-18 (`in == 1` members of the
#: country dimension, id 208).
INCLUDED_COUNTRY_DIMENSION_MEMBERS = 36


def test_the_fixtures_hold_the_other_countries_and_the_aggregates(
    cepalstat_gdp_2203_json: str,
    cepalstat_gdp_2204_json: str,
    cepalstat_gdp_2205_json: str,
    cepalstat_gdp_2206_json: str,
) -> None:
    """Not trimmed to seven: the filter has to have something to filter.

    Checked on all four fixtures independently — a re-recording of just one
    of 2204, 2205 or 2206 trimmed to the seven would otherwise pass unnoticed,
    since `test_each_fixture_covers_the_seven_countries_completely` pre-filters
    to Central America and cannot see whether the other countries survived.
    """
    for payload in (
        cepalstat_gdp_2203_json,
        cepalstat_gdp_2204_json,
        cepalstat_gdp_2205_json,
        cepalstat_gdp_2206_json,
    ):
        body = json.loads(payload)["body"]
        countries = next(d for d in body["dimensions"] if d["id"] == COUNTRY_DIMENSION)
        included = [m["name"] for m in countries["members"] if m["in"] == 1]

        assert len(included) == INCLUDED_COUNTRY_DIMENSION_MEMBERS
        assert "Mexico" in included
        assert "Brazil" in included
        assert "Latin America" in included
        assert any(row.get("iso3") is None for row in body["data"])


def test_the_fixtures_keep_their_exact_published_digits(
    cepalstat_gdp_2203_json: str, cepalstat_gdp_2206_json: str
) -> None:
    """parse_float=Decimal, not float, all the way through."""
    assert cells_of(cepalstat_gdp_2203_json)[("NIC", "2024")] == Decimal("19696.31184918235")
    assert cells_of(cepalstat_gdp_2206_json)[("NIC", "2024")] == Decimal("2142.334639853647")
    assert cells_of(cepalstat_gdp_2203_json)[("BLZ", "1990")] == Decimal("546.75091228848")


def test_the_constant_price_fixtures_carry_the_base_year_footnote(
    cepalstat_gdp_2204_json: str, cepalstat_gdp_2206_json: str, cepalstat_gdp_2203_json: str
) -> None:
    """The base year is in a footnote, not the unit. That is why it is checked."""
    for payload in (cepalstat_gdp_2204_json, cepalstat_gdp_2206_json):
        footnotes = json.loads(payload)["body"]["footnotes"]
        assert [f["description"] for f in footnotes] == ["At prices 2018"]

    assert json.loads(cepalstat_gdp_2203_json)["body"]["footnotes"] == []


OBSERVATIONS = 1008


def build_connector() -> CepalstatGdpConnector:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    return CepalstatGdpConnector(catalog.get("cepalstat_gdp_annual"))


def build_raw(payloads: dict[int, str]) -> RawDataset:
    return RawDataset(
        source_key="cepalstat_gdp_annual",
        retrieved_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
        source_url="https://api-cepalstat.cepal.org/cepalstat/api/v1",
        payload=payloads,
        content_type="application/json",
        http_status=200,
        metadata={"indicator_ids": sorted(payloads)},
    )


@pytest.fixture
def raw(
    cepalstat_gdp_2203_json: str,
    cepalstat_gdp_2204_json: str,
    cepalstat_gdp_2205_json: str,
    cepalstat_gdp_2206_json: str,
) -> RawDataset:
    return build_raw(
        {
            2203: cepalstat_gdp_2203_json,
            2204: cepalstat_gdp_2204_json,
            2205: cepalstat_gdp_2205_json,
            2206: cepalstat_gdp_2206_json,
        }
    )


def test_transform_produces_every_cell(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)

    assert len(observations) == OBSERVATIONS
    per_indicator = Counter(obs.indicator_code for obs in observations)
    assert set(per_indicator) == {
        "gdp_current_usd_annual",
        "gdp_constant_usd_annual",
        "gdp_per_capita_current_usd_annual",
        "gdp_per_capita_constant_usd_annual",
    }
    assert set(per_indicator.values()) == {CELLS_PER_INDICATOR}


def test_only_the_seven_countries_survive(raw: RawDataset) -> None:
    """26 other countries and 3 aggregates are in the payload and must not land."""
    observations = build_connector().transform(raw)

    assert {obs.country_iso3 for obs in observations} == CENTRAL_AMERICA


def test_belize_gets_its_first_data(raw: RawDataset) -> None:
    belize = [obs for obs in build_connector().transform(raw) if obs.country_iso3 == "BLZ"]

    assert len(belize) == 144
    assert {obs.period.label for obs in belize} == {str(y) for y in range(1990, 2026)}


def test_the_totals_are_scaled_and_the_per_capita_series_are_not(raw: RawDataset) -> None:
    """Nicaragua 2024, verified by hand against the source."""
    by_key = {
        (obs.indicator_code, obs.country_iso3, obs.period.label): obs
        for obs in build_connector().transform(raw)
    }

    total = by_key[("gdp_current_usd_annual", "NIC", "2024")]
    assert total.value_numeric == Decimal("19696311849.18235")
    assert total.unit == "current USD"
    assert total.currency_code == "USD"

    per_capita = by_key[("gdp_per_capita_current_usd_annual", "NIC", "2024")]
    assert per_capita.value_numeric == Decimal("2757.621539962527")
    assert per_capita.unit == "current USD per person"


def test_the_published_figure_is_kept_alongside(raw: RawDataset) -> None:
    by_key = {
        (obs.indicator_code, obs.country_iso3, obs.period.label): obs
        for obs in build_connector().transform(raw)
    }
    metadata = by_key[("gdp_constant_usd_annual", "NIC", "2024")].raw_metadata

    assert metadata["cepalstat_indicator_id"] == 2204
    assert metadata["cepalstat_published_value"] == "15301.62516515467"
    assert metadata["cepalstat_published_unit"] == "Millions of dollars"
    assert metadata["cepalstat_scale_applied"] == "1e6"
    assert metadata["cepalstat_source"] == "Own estimates based on national sources"
    assert metadata["cepalstat_footnotes"] == ["At prices 2018"]


def test_the_fetch_date_is_not_stored(raw: RawDataset) -> None:
    """credits[0] is CEPAL's own fetch date and changes between runs."""
    metadata = build_connector().transform(raw)[0].raw_metadata

    assert metadata["cepalstat_credits"] == [
        "CEPALSTAT",
        "Economic Commission for Latin America and the Caribbean – ECLAC",  # noqa: RUF001
        "United Nations",
    ]


def test_periods_are_annual_and_span_the_calendar_year(raw: RawDataset) -> None:
    observation = next(
        obs for obs in build_connector().transform(raw) if obs.period.label == "1990"
    )

    assert observation.period.frequency is Frequency.ANNUAL
    assert observation.period.start == date(1990, 1, 1)
    assert observation.period.end == date(1990, 12, 31)


def test_source_record_ids_are_unique_and_readable(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)
    ids = [obs.source_record_id for obs in observations]

    assert len(set(ids)) == OBSERVATIONS
    assert "cepalstat:2203:NIC:2024" in ids


def test_a_missing_years_dimension_raises(raw: RawDataset) -> None:
    broken = json.loads(raw.payload[2203])
    broken["body"]["dimensions"] = [
        d for d in broken["body"]["dimensions"] if d["id"] != YEARS_DIMENSION
    ]
    payloads = dict(raw.payload) | {2203: json.dumps(broken)}

    with pytest.raises(TransformationError, match="years dimension"):
        build_connector().transform(build_raw(payloads))


def test_an_unmapped_year_member_raises(raw: RawDataset) -> None:
    """A year id with no member is a contract change, not a row to skip."""
    broken = json.loads(raw.payload[2203])
    # data[0] is Argentina, which transform filters out before it ever looks
    # at the year; the mutated row has to belong to one of the seven or the
    # broken value is discarded unnoticed.
    row = next(r for r in broken["body"]["data"] if r.get("iso3") in CENTRAL_AMERICA)
    row[f"dim_{YEARS_DIMENSION}"] = 999999
    payloads = dict(raw.payload) | {2203: json.dumps(broken)}

    with pytest.raises(TransformationError, match="unknown year member"):
        build_connector().transform(build_raw(payloads))


def results_of(observations: list[NormalizedObservation]) -> dict[str, QualityResult]:
    return {result.check_name: result for result in build_connector().validate(observations)}


def test_all_four_checks_pass_on_the_real_recordings(raw: RawDataset) -> None:
    results = results_of(build_connector().transform(raw))

    assert set(results) == {
        "cepalstat_seven_countries_present",
        "cepalstat_population_identity",
        "cepalstat_constant_price_base_year",
        "cepalstat_annual_continuity",
    }
    assert all(result.status is CheckStatus.PASSED for result in results.values())


def test_a_missing_country_fails_critically(raw: RawDataset) -> None:
    """Belize vanishing is the failure this connector exists not to commit."""
    observations = [obs for obs in build_connector().transform(raw) if obs.country_iso3 != "BLZ"]

    result = results_of(observations)["cepalstat_seven_countries_present"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.CRITICAL
    assert "BLZ" in result.message


def test_the_population_identity_holds_on_the_real_data(raw: RawDataset) -> None:
    result = results_of(build_connector().transform(raw))["cepalstat_population_identity"]

    assert result.status is CheckStatus.PASSED
    assert "252" in result.message


def test_a_broken_population_identity_fails(raw: RawDataset) -> None:
    """Move one per-capita figure by 1%: far above noise, far below a typo."""
    observations = build_connector().transform(raw)
    for index, obs in enumerate(observations):
        if (
            obs.indicator_code == "gdp_per_capita_constant_usd_annual"
            and obs.country_iso3 == "NIC"
            and obs.period.label == "2024"
        ):
            assert obs.value_numeric is not None
            observations[index] = replace(obs, value_numeric=obs.value_numeric * Decimal("1.01"))

    result = results_of(observations)["cepalstat_population_identity"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.ERROR
    assert "NIC 2024" in result.message


def test_a_rebasing_fails_the_base_year_check(raw: RawDataset) -> None:
    """A CEPAL rebasing changes every constant value and no unit string."""
    observations = build_connector().transform(raw)
    for index, obs in enumerate(observations):
        if obs.indicator_code == "gdp_constant_usd_annual":
            observations[index] = replace(
                obs, raw_metadata={**obs.raw_metadata, "cepalstat_footnotes": ["At prices 2020"]}
            )

    result = results_of(observations)["cepalstat_constant_price_base_year"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.ERROR
    assert "2018" in result.message


def test_a_missing_year_is_reported_as_a_warning(raw: RawDataset) -> None:
    observations = [obs for obs in build_connector().transform(raw) if obs.period.label != "2008"]

    result = results_of(observations)["cepalstat_annual_continuity"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.WARNING
    assert "2008" in result.message


def test_every_check_is_dataset_level(raw: RawDataset) -> None:
    """No check names a row: a broken identity has no single guilty cell."""
    results = build_connector().validate(build_connector().transform(raw))

    assert all(result.observation_index is None for result in results)
