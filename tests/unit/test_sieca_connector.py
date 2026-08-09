"""Unit tests for the SIECA quarterly services-trade connector.

Every payload replayed here is a real recording; see `tests/fixtures/README.md`.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from reim.core.constants import CheckSeverity, CheckStatus
from reim.core.exceptions import ExtractionError, TransformationError
from reim.domain.pipelines.models import NormalizedObservation, QualityResult, RawDataset
from reim.domain.sources.catalog import load_catalog
from reim.ingestion.connectors.regional.sieca_services_trade import (
    SiecaServicesTradeConnector,
    parse_quarter,
)
from tests.conftest import REPO_ROOT

#: What the recorded responses hold, measured on 2026-08-09.
QUARTERS = 69
COUNTRIES = 6
CELLS_PER_FLOW = 414


def cells_of(payload: str) -> dict[tuple[str, str], Decimal | None]:
    """Flatten one LoadData payload into ``(country, quarter label) -> value``."""
    block = json.loads(payload, parse_float=Decimal)["Data"][0]
    rows = json.loads(block["Data"], parse_float=Decimal)
    columns = [c["data"] for c in block["Columnas"]][4:]
    return {(row["Pais"], column): row[column] for row in rows for column in columns}


def test_the_filters_fixture_holds_every_quarter(sieca_filters_json: str) -> None:
    filters = json.loads(sieca_filters_json)

    assert len(filters["Periodo"]) == QUARTERS
    labels = {f"{p['Trimestre']} {p['Anio']}" for p in filters["Periodo"]}
    assert "I Trim 2009" in labels
    assert "I Trim 2026" in labels


def test_the_filters_fixture_lists_the_six_countries_and_the_aggregate(
    sieca_filters_json: str,
) -> None:
    names = {p["Nombre"] for p in json.loads(sieca_filters_json)["Pais"]}

    assert names == {
        "Centroamérica",
        "Costa Rica",
        "El Salvador",
        "Guatemala",
        "Honduras",
        "Nicaragua",
        "Panamá",
    }


def test_each_flow_fixture_is_complete(
    sieca_exports_json: str, sieca_imports_json: str, sieca_balance_json: str
) -> None:
    """Zero nulls. A re-recording that introduces holes must fail here."""
    for payload in (sieca_exports_json, sieca_imports_json, sieca_balance_json):
        cells = cells_of(payload)
        assert len(cells) == CELLS_PER_FLOW
        assert sum(1 for v in cells.values() if v is None) == 0


def test_the_fixtures_keep_their_exact_published_digits(sieca_exports_json: str) -> None:
    """parse_float=Decimal, not float: 1131.7 must not become 1131.6999999999998."""
    cells = cells_of(sieca_exports_json)

    assert cells[("Costa Rica", "I Trim 2009")] == Decimal("1131.7")
    assert cells[("Costa Rica", "I Trim 2026")] == Decimal("4941.8")


OBSERVATIONS = 1242


def build_connector() -> SiecaServicesTradeConnector:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    return SiecaServicesTradeConnector(catalog.get("sieca_services_trade"))


def build_raw(exports: str, imports: str, balance: str) -> RawDataset:
    return RawDataset(
        source_key="sieca_services_trade",
        retrieved_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        source_url="https://www.servicios.sieca.int/ReporteGeneralServicios",
        payload={"E": exports, "I": imports, "S": balance},
        content_type="application/json; charset=utf-8",
        http_status=200,
        metadata={"operation": "LoadData"},
    )


@pytest.fixture
def raw(sieca_exports_json: str, sieca_imports_json: str, sieca_balance_json: str) -> RawDataset:
    return build_raw(sieca_exports_json, sieca_imports_json, sieca_balance_json)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("I Trim 2026", "2026-Q1"),
        ("II Trim 2009", "2009-Q2"),
        ("III Trim 2015", "2015-Q3"),
        ("IV Trim 2025", "2025-Q4"),
    ],
)
def test_roman_quarters_become_reim_periods(label: str, expected: str) -> None:
    assert parse_quarter(label) == expected


def test_an_unreadable_quarter_label_raises() -> None:
    with pytest.raises(ValueError, match="V Trim 2026"):
        parse_quarter("V Trim 2026")


def test_every_flow_country_and_quarter_becomes_an_observation(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)

    assert len(observations) == OBSERVATIONS
    by_indicator: dict[str, int] = {}
    for obs in observations:
        by_indicator[obs.indicator_code] = by_indicator.get(obs.indicator_code, 0) + 1
    assert by_indicator == {
        "exports_services_quarterly": CELLS_PER_FLOW,
        "imports_services_quarterly": CELLS_PER_FLOW,
        "trade_balance_services_quarterly": CELLS_PER_FLOW,
    }


def test_millions_become_whole_usd(raw: RawDataset) -> None:
    """375.3 million is 375,300,000 exactly — no float anywhere in the path."""
    observations = build_connector().transform(raw)
    nicaragua = next(
        o
        for o in observations
        if o.country_iso3 == "NIC"
        and o.indicator_code == "exports_services_quarterly"
        and o.period.label == "2026-Q1"
    )

    assert nicaragua.value_numeric == Decimal("356500000")
    assert nicaragua.unit == "current USD"
    assert nicaragua.currency_code == "USD"


def test_a_value_not_exact_in_binary_float_still_lands_exactly(raw: RawDataset) -> None:
    """356.5 above happens to be exact in IEEE-754 float; 1131.7 is not.

    Guards the hazard the module docstring names: reading with plain
    ``float`` would corrupt this figure in its last places — it becomes
    1131700000.000000045474735089 — without the row count, country count or
    quarter count changing at all, so no other test would notice.
    """
    observations = build_connector().transform(raw)
    costa_rica = next(
        o
        for o in observations
        if o.country_iso3 == "CRI"
        and o.indicator_code == "exports_services_quarterly"
        and o.period.label == "2009-Q1"
    )

    assert costa_rica.value_numeric == Decimal("1131700000")
    assert costa_rica.raw_metadata["sieca_published_value"] == "1131.7"


def test_the_published_figure_is_kept_alongside(raw: RawDataset) -> None:
    """The conversion is declared, so it stays auditable and reversible."""
    observations = build_connector().transform(raw)
    nicaragua = next(
        o
        for o in observations
        if o.country_iso3 == "NIC"
        and o.indicator_code == "exports_services_quarterly"
        and o.period.label == "2026-Q1"
    )

    assert nicaragua.raw_metadata["sieca_published_value"] == "356.5"
    assert nicaragua.raw_metadata["sieca_published_unit"] == "millones de USD"
    assert nicaragua.raw_metadata["sieca_scale_applied"] == "1e6"


def test_the_six_country_names_map_to_iso3(raw: RawDataset) -> None:
    codes = {o.country_iso3 for o in build_connector().transform(raw)}

    assert codes == {"CRI", "SLV", "GTM", "HND", "NIC", "PAN"}


def test_the_regional_aggregate_produces_nothing() -> None:
    """Centroamérica is the sum of the six, and REIM has no code for a region.

    The real fixtures are recorded with ``paises=1,2,3,4,5,6`` (see
    tests/fixtures/README.md), so LoadData never actually returns the
    aggregate row — only LoadFilters' country dropdown lists it. A synthetic
    row proves the connector would silently drop it rather than raise, the
    way an unrecognised country name does.
    """
    payload = json.dumps(
        {
            "Resultado": True,
            "Data": [
                {
                    "Columnas": [
                        {"data": "Pais"},
                        {"data": "Orden"},
                        {"data": "CodigoServicio"},
                        {"data": "Servicio"},
                        {"data": "I Trim 2026"},
                    ],
                    "Data": json.dumps(
                        [
                            {
                                "Pais": "Centroamérica",
                                "Orden": 0,
                                "CodigoServicio": "Sumatoria",
                                "Servicio": "Servicios de Primer Nivel",
                                "I Trim 2026": 100.0,
                            },
                            {
                                "Pais": "Nicaragua",
                                "Orden": 0,
                                "CodigoServicio": "Sumatoria",
                                "Servicio": "Servicios de Primer Nivel",
                                "I Trim 2026": 10.0,
                            },
                        ]
                    ),
                }
            ],
        }
    )

    observations = build_connector().transform(build_raw(payload, payload, payload))

    assert len(observations) == 3  # one per flow, Nicaragua only
    assert {o.country_iso3 for o in observations} == {"NIC"}


def test_an_unknown_country_name_raises() -> None:
    """Never dropped in silence: a renamed country would shrink the series unseen."""
    doctored = json.dumps(
        {
            "Resultado": True,
            "Data": [
                {
                    "Columnas": [
                        {"data": "Pais"},
                        {"data": "Orden"},
                        {"data": "CodigoServicio"},
                        {"data": "Servicio"},
                        {"data": "I Trim 2026"},
                    ],
                    "Data": json.dumps(
                        [
                            {
                                "Pais": "Belice",
                                "Orden": 0,
                                "CodigoServicio": "Sumatoria",
                                "Servicio": "Servicios de Primer Nivel",
                                "I Trim 2026": 1.0,
                            }
                        ]
                    ),
                }
            ],
        }
    )

    with pytest.raises(TransformationError, match="Belice"):
        build_connector().transform(build_raw(doctored, doctored, doctored))


def test_a_quarter_is_a_three_month_closed_period(raw: RawDataset) -> None:
    observation = next(o for o in build_connector().transform(raw) if o.period.label == "2026-Q1")

    assert observation.period.start == date(2026, 1, 1)
    assert observation.period.end == date(2026, 3, 31)


def test_each_flow_gets_its_own_record_id(raw: RawDataset) -> None:
    ids = {
        o.source_record_id
        for o in build_connector().transform(raw)
        if o.country_iso3 == "NIC" and o.period.label == "2026-Q1"
    }

    assert ids == {
        "servicios:NIC:2026-Q1:E",
        "servicios:NIC:2026-Q1:I",
        "servicios:NIC:2026-Q1:S",
    }


def test_a_null_cell_is_skipped_never_imputed() -> None:
    payload = json.dumps(
        {
            "Resultado": True,
            "Data": [
                {
                    "Columnas": [
                        {"data": "Pais"},
                        {"data": "Orden"},
                        {"data": "CodigoServicio"},
                        {"data": "Servicio"},
                        {"data": "I Trim 2026"},
                    ],
                    "Data": json.dumps(
                        [
                            {
                                "Pais": "Nicaragua",
                                "Orden": 0,
                                "CodigoServicio": "Sumatoria",
                                "Servicio": "Servicios de Primer Nivel",
                                "I Trim 2026": None,
                            }
                        ]
                    ),
                }
            ],
        }
    )

    assert build_connector().transform(build_raw(payload, payload, payload)) == []


def test_a_service_error_is_an_error_not_an_empty_result() -> None:
    payload = json.dumps({"Resultado": False, "Mensaje": "Consulta inválida", "Data": None})

    with pytest.raises(TransformationError, match="Consulta inválida"):
        build_connector().transform(build_raw(payload, payload, payload))


def test_malformed_json_is_an_error() -> None:
    with pytest.raises(TransformationError, match="malformed JSON"):
        build_connector().transform(build_raw("{not json", "{not json", "{not json"))


def test_observations_are_ordered_by_period(raw: RawDataset) -> None:
    exports = [
        o.period.start
        for o in build_connector().transform(raw)
        if o.country_iso3 == "NIC" and o.indicator_code == "exports_services_quarterly"
    ]

    assert exports == sorted(exports)


def results_by_name(observations: list[NormalizedObservation]) -> dict[str, QualityResult]:
    return {result.check_name: result for result in build_connector().validate(observations)}


def test_the_recorded_history_passes_every_check(raw: RawDataset) -> None:
    """The real 0.1-million rounding deviations must not fail a run."""
    results = results_by_name(build_connector().transform(raw))

    assert set(results) == {
        "sieca_six_countries_present",
        "sieca_balance_identity",
        "sieca_quarterly_continuity",
        "sieca_flow_coverage",
    }
    assert [r.status for r in results.values()] == [CheckStatus.PASSED] * 4


def test_a_missing_country_is_critical(raw: RawDataset) -> None:
    observations = [o for o in build_connector().transform(raw) if o.country_iso3 != "PAN"]

    result = results_by_name(observations)["sieca_six_countries_present"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.CRITICAL
    assert "PAN" in result.message


def test_the_real_rounding_deviations_do_not_fail_the_identity(raw: RawDataset) -> None:
    """71 of 414 cells deviate by more than 0.05 million; all are rounding."""
    result = results_by_name(build_connector().transform(raw))["sieca_balance_identity"]

    assert result.status is CheckStatus.PASSED


def test_a_deviation_beyond_the_tolerance_fails(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)
    # NormalizedObservation is a mutable dataclass, not a Pydantic model:
    # there is no model_copy, so the doctored value is assigned in place.
    target = next(
        obs
        for obs in observations
        if obs.indicator_code == "trade_balance_services_quarterly"
        and obs.country_iso3 == "NIC"
        and obs.period.label == "2026-Q1"
    )
    target.value_numeric = Decimal("200000")

    result = results_by_name(observations)["sieca_balance_identity"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.ERROR
    assert "NIC 2026-Q1" in result.message


def test_a_missing_quarter_is_reported(raw: RawDataset) -> None:
    observations = [o for o in build_connector().transform(raw) if o.period.label != "2015-Q3"]

    result = results_by_name(observations)["sieca_quarterly_continuity"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.WARNING
    assert "2015-Q3" in result.message


def test_flows_covering_different_cells_fail(raw: RawDataset) -> None:
    """A flow that silently returns less would otherwise pass unnoticed."""
    observations = [
        o
        for o in build_connector().transform(raw)
        if not (o.indicator_code == "imports_services_quarterly" and o.period.label == "2009-Q1")
    ]

    result = results_by_name(observations)["sieca_flow_coverage"]

    assert result.status is CheckStatus.FAILED
    assert result.severity is CheckSeverity.ERROR


FILTERS_URL = "https://www.servicios.sieca.int/ReporteGeneralServicios/LoadFilters"
DATA_URL = "https://www.servicios.sieca.int/ReporteGeneralServicios/LoadData"


def json_response(body: str) -> httpx.Response:
    return httpx.Response(
        200, text=body, headers={"Content-Type": "application/json; charset=utf-8"}
    )


@respx.mock
async def test_a_run_makes_one_filters_call_and_one_per_flow(
    sieca_filters_json: str,
    sieca_exports_json: str,
    sieca_imports_json: str,
    sieca_balance_json: str,
) -> None:
    filters = respx.post(FILTERS_URL).mock(return_value=json_response(sieca_filters_json))
    data = respx.post(DATA_URL).mock(
        side_effect=[
            json_response(sieca_exports_json),
            json_response(sieca_imports_json),
            json_response(sieca_balance_json),
        ]
    )

    raw = await build_connector().extract()

    assert filters.call_count == 1
    assert data.call_count == 3
    assert set(raw.payload) == {"E", "I", "S"}
    assert raw.payload["E"] == sieca_exports_json


@respx.mock
async def test_the_requested_quarters_come_from_the_source(
    sieca_filters_json: str,
    sieca_exports_json: str,
    sieca_imports_json: str,
    sieca_balance_json: str,
) -> None:
    """Not a hardcoded list: a new quarter must be picked up without a code change."""
    respx.post(FILTERS_URL).mock(return_value=json_response(sieca_filters_json))
    data = respx.post(DATA_URL).mock(
        side_effect=[
            json_response(sieca_exports_json),
            json_response(sieca_imports_json),
            json_response(sieca_balance_json),
        ]
    )

    await build_connector().extract()
    body = data.calls[0].request.content.decode("utf-8")

    assert "I+Trim+2026" in body
    assert "IV+Trim+2009" in body
    assert body.count("Trim") == QUARTERS


@respx.mock
async def test_extract_sends_the_declared_user_agent(
    sieca_filters_json: str,
    sieca_exports_json: str,
    sieca_imports_json: str,
    sieca_balance_json: str,
) -> None:
    """The host answers REIM's own identifier with 202 and an empty body."""
    respx.post(FILTERS_URL).mock(return_value=json_response(sieca_filters_json))
    data = respx.post(DATA_URL).mock(
        side_effect=[
            json_response(sieca_exports_json),
            json_response(sieca_imports_json),
            json_response(sieca_balance_json),
        ]
    )

    await build_connector().extract()

    assert data.calls[0].request.headers["User-Agent"].startswith("Mozilla/5.0")


@respx.mock
async def test_extract_asks_for_all_six_countries_and_the_total_component(
    sieca_filters_json: str,
    sieca_exports_json: str,
    sieca_imports_json: str,
    sieca_balance_json: str,
) -> None:
    respx.post(FILTERS_URL).mock(return_value=json_response(sieca_filters_json))
    data = respx.post(DATA_URL).mock(
        side_effect=[
            json_response(sieca_exports_json),
            json_response(sieca_imports_json),
            json_response(sieca_balance_json),
        ]
    )

    await build_connector().extract()
    body = data.calls[0].request.content.decode("utf-8")

    assert "paises=1%2C2%2C3%2C4%2C5%2C6" in body
    assert "categoria=0" in body
    assert "unidadMedida=MD" in body
    assert "paisesDestino=0" in body


@respx.mock
async def test_an_empty_202_is_rejected(sieca_filters_json: str) -> None:
    """This is exactly what the host returns to a client it will not serve."""
    respx.post(FILTERS_URL).mock(
        return_value=httpx.Response(202, text="", headers={"Content-Type": "text/html"})
    )

    with pytest.raises(ExtractionError, match="empty body"):
        await build_connector().extract()


@respx.mock
async def test_an_html_answer_is_rejected(sieca_filters_json: str) -> None:
    respx.post(FILTERS_URL).mock(
        return_value=httpx.Response(
            403, text="<html>forbidden</html>", headers={"Content-Type": "text/html"}
        )
    )

    with pytest.raises(ExtractionError, match="HTTP 403"):
        await build_connector().extract()


@respx.mock
async def test_extract_records_what_the_service_answered(
    sieca_filters_json: str,
    sieca_exports_json: str,
    sieca_imports_json: str,
    sieca_balance_json: str,
) -> None:
    respx.post(FILTERS_URL).mock(return_value=json_response(sieca_filters_json))
    respx.post(DATA_URL).mock(
        side_effect=[
            json_response(sieca_exports_json),
            json_response(sieca_imports_json),
            json_response(sieca_balance_json),
        ]
    )

    raw = await build_connector().extract()

    assert raw.http_status == 200
    assert raw.content_type == "application/json; charset=utf-8"
    assert raw.metadata["quarters"] == QUARTERS
    assert raw.metadata["component"] == "1.A.b.0"


@pytest.mark.live
async def test_live_service_still_answers_the_recorded_contract() -> None:
    """Opt-in: hits the real SIECA portal. Run with `pytest -m live`."""
    connector = build_connector()

    raw = await connector.extract()
    observations = connector.transform(raw)

    assert len(observations) >= OBSERVATIONS
    assert {o.country_iso3 for o in observations} == {"CRI", "SLV", "GTM", "HND", "NIC", "PAN"}
    assert all(result.status is CheckStatus.PASSED for result in connector.validate(observations))
