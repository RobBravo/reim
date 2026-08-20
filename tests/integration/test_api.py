"""API behaviour against a live schema (requires PostgreSQL)."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.api.dependencies import get_db
from apps.api.main import create_app
from reim.schemas.observations import CSV_COLUMNS
from tests.conftest import requires_db

pytestmark = [requires_db, pytest.mark.integration]


@pytest.fixture
def client(seeded_session: Session, make_observation) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    """A test client backed by the seeded test schema, with sample observations."""
    from reim.services.observation_writer import write_observations

    write_observations(
        seeded_session,
        [make_observation(str(year), str(4 + year % 5)) for year in range(2015, 2025)],
        connector_version="1.0.0",
    )
    write_observations(
        seeded_session,
        [
            make_observation(
                str(year),
                str(3000000000 + year),
                indicator_code="ni_remittances_received",
                source_key="worldbank_ni_remittances",
                unit="current USD",
                currency_code="USD",
            )
            for year in range(2020, 2025)
        ],
        connector_version="1.0.0",
    )
    seeded_session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: seeded_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------
# System
# --------------------------------------------------------------------------
def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["database"] is True


def test_status_reports_coverage(client: TestClient) -> None:
    body = client.get("/api/v1/status").json()
    assert body["observations"] == 15
    assert body["countries"] == 7
    assert body["sources_registered"] >= 3
    assert body["sources_enabled"] >= 3
    assert body["last_ingestion_at"]


def test_openapi_schema_is_served(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"]
    assert "/api/v1/observations" in schema["paths"]
    assert "/api/v1/observations/export.csv" in schema["paths"]


def test_no_public_pipeline_trigger_endpoint(client: TestClient) -> None:
    """The MVP must not expose HTTP-triggered ingestion."""
    schema = client.get("/openapi.json").json()
    for path, operations in schema["paths"].items():
        assert set(operations) <= {"get", "parameters"}, f"{path} exposes a write method"


# --------------------------------------------------------------------------
# Reference resources
# --------------------------------------------------------------------------
def test_list_countries(client: TestClient) -> None:
    body = client.get("/api/v1/countries").json()
    assert body["meta"]["total"] == 7
    assert {c["iso2"] for c in body["data"]} >= {"NI", "CR", "GT"}


def test_active_only_filter(client: TestClient) -> None:
    """Belize was the one inactive country; CEPALSTAT's GDP activated it.

    All seven are active now, so the filter no longer removes anyone. What it
    must still do is return only rows that say they are active.
    """
    body = client.get("/api/v1/countries", params={"active_only": True}).json()

    assert {c["iso2"] for c in body["data"]} == {"NI", "GT", "SV", "HN", "CR", "PA", "BZ"}
    assert all(country["is_active"] for country in body["data"])


def test_get_country(client: TestClient) -> None:
    body = client.get("/api/v1/countries/ni").json()
    assert body["iso3"] == "NIC"
    assert body["currency_code"] == "NIO"


def test_unknown_country_returns_the_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/countries/ZZ")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["message"]
    assert error["details"]["iso2"] == "ZZ"


def test_list_organizations(client: TestClient) -> None:
    body = client.get("/api/v1/organizations").json()
    assert {o["code"] for o in body["data"]} >= {"BCN", "INIDE", "WORLDBANK"}


def test_list_sources_exposes_activation_state(client: TestClient) -> None:
    """A disabled source must never appear active without saying why."""
    body = client.get("/api/v1/sources").json()

    assert body["data"]
    for source in body["data"]:
        assert "is_active" in source
        assert "disabled_reason" in source
        if not source["is_active"]:
            assert source["disabled_reason"], f"{source['source_key']} is off without a reason"


def test_bcn_source_is_active_over_a_declared_legacy_tls_profile(client: TestClient) -> None:
    body = client.get("/api/v1/sources").json()
    bcn = next(s for s in body["data"] if s["source_key"] == "bcn_exchange_rate")

    assert bcn["is_active"] is True
    assert bcn["disabled_reason"] is None


def test_sources_active_only_filter(client: TestClient) -> None:
    body = client.get("/api/v1/sources", params={"active_only": True}).json()
    assert all(s["is_active"] for s in body["data"])


def test_get_source(client: TestClient) -> None:
    body = client.get("/api/v1/sources/worldbank_ni_cpi_inflation").json()
    assert body["is_official"] is True
    assert body["connector_path"].startswith("reim.ingestion.connectors")


def test_list_indicators(client: TestClient) -> None:
    body = client.get("/api/v1/indicators").json()
    assert body["meta"]["total"] >= 6


def test_filter_indicators_by_category(client: TestClient) -> None:
    body = client.get("/api/v1/indicators", params={"category": "external_sector"}).json()
    assert body["data"]
    assert all(i["category"] == "external_sector" for i in body["data"])


def test_filter_indicators_by_frequency(client: TestClient) -> None:
    body = client.get("/api/v1/indicators", params={"frequency": "annual"}).json()
    assert all(i["frequency"] == "annual" for i in body["data"])


def test_filter_indicators_by_country_uses_stored_data(client: TestClient) -> None:
    body = client.get("/api/v1/indicators", params={"country": "NI"}).json()
    codes = {i["code"] for i in body["data"]}
    assert codes == {"ni_cpi_inflation_annual", "ni_remittances_received"}


def test_get_indicator(client: TestClient) -> None:
    body = client.get("/api/v1/indicators/ni_cpi_inflation_annual").json()
    assert body["unit"] == "percent"
    assert body["value_type"] == "percent_change"


def test_unknown_indicator_returns_404(client: TestClient) -> None:
    assert client.get("/api/v1/indicators/nope").status_code == 404


# --------------------------------------------------------------------------
# Observations
# --------------------------------------------------------------------------
def test_list_observations(client: TestClient) -> None:
    body = client.get("/api/v1/observations").json()
    assert body["meta"]["total"] == 15


def test_observation_carries_full_provenance(client: TestClient) -> None:
    row = client.get("/api/v1/observations", params={"limit": 1}).json()["data"][0]
    for field in (
        "country_iso3",
        "indicator_code",
        "source_key",
        "period_start",
        "period_end",
        "period_label",
        "unit",
        "retrieved_at",
        "source_url",
        "content_hash",
        "validation_status",
        "connector_version",
        "pipeline_version",
        "raw_metadata",
    ):
        assert field in row, f"missing provenance field {field}"


def test_filter_by_country(client: TestClient) -> None:
    assert (
        client.get("/api/v1/observations", params={"country": "NIC"}).json()["meta"]["total"] == 15
    )
    assert client.get("/api/v1/observations", params={"country": "CR"}).json()["meta"]["total"] == 0


def test_filter_by_indicator(client: TestClient) -> None:
    body = client.get(
        "/api/v1/observations", params={"indicator": "ni_cpi_inflation_annual"}
    ).json()
    assert body["meta"]["total"] == 10


def test_filter_by_source(client: TestClient) -> None:
    body = client.get("/api/v1/observations", params={"source": "worldbank_ni_remittances"}).json()
    assert body["meta"]["total"] == 5


def test_filter_by_category(client: TestClient) -> None:
    body = client.get("/api/v1/observations", params={"category": "prices"}).json()
    assert body["meta"]["total"] == 10


def test_filter_by_date_range(client: TestClient) -> None:
    body = client.get(
        "/api/v1/observations",
        params={
            "indicator": "ni_cpi_inflation_annual",
            "date_from": "2020-01-01",
            "date_to": "2022-12-31",
        },
    ).json()
    assert body["meta"]["total"] == 3
    assert {row["period_label"] for row in body["data"]} == {"2020", "2021", "2022"}


def test_filter_by_validation_status(client: TestClient) -> None:
    body = client.get("/api/v1/observations", params={"validation_status": "passed"}).json()
    assert body["meta"]["total"] == 15
    body = client.get("/api/v1/observations", params={"validation_status": "rejected"}).json()
    assert body["meta"]["total"] == 0


def test_inverted_date_range_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/v1/observations", params={"date_from": "2024-01-01", "date_to": "2020-01-01"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_pagination(client: TestClient) -> None:
    first = client.get("/api/v1/observations", params={"limit": 4, "offset": 0}).json()
    second = client.get("/api/v1/observations", params={"limit": 4, "offset": 4}).json()

    assert first["meta"]["returned"] == 4
    assert first["meta"]["has_more"] is True
    assert second["meta"]["offset"] == 4
    assert {r["id"] for r in first["data"]}.isdisjoint({r["id"] for r in second["data"]})


def test_last_page_reports_no_more(client: TestClient) -> None:
    body = client.get("/api/v1/observations", params={"limit": 100}).json()
    assert body["meta"]["has_more"] is False


def test_page_size_is_capped(client: TestClient) -> None:
    body = client.get("/api/v1/observations", params={"limit": 999999}).json()
    assert body["meta"]["limit"] <= 1000


def test_invalid_limit_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/observations", params={"limit": 0})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_sorting(client: TestClient) -> None:
    ascending = client.get(
        "/api/v1/observations",
        params={"indicator": "ni_cpi_inflation_annual", "sort_by": "period_start", "order": "asc"},
    ).json()
    labels = [row["period_label"] for row in ascending["data"]]
    assert labels == sorted(labels)


def test_invalid_sort_column_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/observations", params={"sort_by": "; DROP TABLE"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_latest_returns_one_row_per_series(client: TestClient) -> None:
    rows = client.get("/api/v1/observations/latest").json()
    assert len(rows) == 2
    assert {row["period_label"] for row in rows} == {"2024"}


def test_latest_respects_filters(client: TestClient) -> None:
    rows = client.get(
        "/api/v1/observations/latest", params={"indicator": "ni_cpi_inflation_annual"}
    ).json()
    assert len(rows) == 1
    assert rows[0]["indicator_code"] == "ni_cpi_inflation_annual"


# --------------------------------------------------------------------------
# CSV export
# --------------------------------------------------------------------------
def _rows(response) -> list[dict[str, str]]:  # type: ignore[no-untyped-def]
    return list(csv.DictReader(io.StringIO(response.text)))


def test_csv_export_content_type_and_filename(client: TestClient) -> None:
    response = client.get("/api/v1/observations/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert ".csv" in response.headers["content-disposition"]


def test_csv_export_has_the_documented_columns(client: TestClient) -> None:
    rows = _rows(client.get("/api/v1/observations/export.csv"))
    assert list(rows[0]) == list(CSV_COLUMNS)


def test_csv_export_row_count_matches_filters(client: TestClient) -> None:
    rows = _rows(
        client.get(
            "/api/v1/observations/export.csv",
            params={"indicator": "ni_cpi_inflation_annual"},
        )
    )
    assert len(rows) == 10
    assert all(row["indicator_code"] == "ni_cpi_inflation_annual" for row in rows)


def test_csv_export_preserves_decimal_precision(
    client: TestClient, seeded_session: Session, make_observation
) -> None:  # type: ignore[no-untyped-def]
    from reim.services.observation_writer import write_observations

    write_observations(
        seeded_session,
        [make_observation("2010", "4.62473841057141")],
        connector_version="1.0.0",
    )
    seeded_session.commit()

    rows = _rows(
        client.get(
            "/api/v1/observations/export.csv",
            params={"date_from": "2010-01-01", "date_to": "2010-12-31"},
        )
    )
    assert rows[0]["value_numeric"] == "4.62473841057141"
    assert Decimal(rows[0]["value_numeric"]) == Decimal("4.62473841057141")


def test_csv_export_respects_the_row_limit(client: TestClient) -> None:
    rows = _rows(client.get("/api/v1/observations/export.csv", params={"limit": 3}))
    assert len(rows) == 3


def test_csv_export_of_an_empty_result_still_has_a_header(client: TestClient) -> None:
    response = client.get("/api/v1/observations/export.csv", params={"country": "CR"})
    assert response.text.strip() == ",".join(CSV_COLUMNS)


# --------------------------------------------------------------------------
# Pipelines
# --------------------------------------------------------------------------
def test_pipeline_overview(client: TestClient) -> None:
    rows = client.get("/api/v1/pipelines").json()
    assert len(rows) >= 3
    keys = {row["pipeline_key"] for row in rows}
    assert "worldbank_ni_cpi_inflation" in keys


def test_pipeline_overview_reports_freshness(client: TestClient) -> None:
    rows = client.get("/api/v1/pipelines").json()
    cpi = next(r for r in rows if r["pipeline_key"] == "worldbank_ni_cpi_inflation")
    assert cpi["observation_count"] == 10
    assert cpi["latest_period_end"] == "2024-12-31"
    assert cpi["data_age_days"] is not None


def test_pipeline_overview_surfaces_activation_state(client: TestClient) -> None:
    """A disabled pipeline must carry its reason into the overview."""
    rows = client.get("/api/v1/pipelines").json()

    assert rows
    for row in rows:
        if not row["enabled"]:
            assert row["disabled_reason"], f"{row['pipeline_key']} is off without a reason"

    bcn = next(r for r in rows if r["pipeline_key"] == "bcn_exchange_rate")
    assert bcn["enabled"] is True


def test_list_runs_when_empty(client: TestClient) -> None:
    body = client.get("/api/v1/pipelines/runs").json()
    assert body["meta"]["total"] == 0
    assert body["data"] == []


def test_unknown_run_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/pipelines/runs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_malformed_run_id_returns_422(client: TestClient) -> None:
    response = client.get("/api/v1/pipelines/runs/not-a-uuid")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_runs_are_listed_after_a_pipeline_executes(
    client: TestClient, seeded_session: Session
) -> None:
    from datetime import UTC, datetime

    from reim.core.constants import PipelineStatus
    from reim.database.models import PipelineRun

    now = datetime.now(UTC)
    seeded_session.add(
        PipelineRun(
            pipeline_key="worldbank_ni_cpi_inflation",
            started_at=now,
            finished_at=now,
            duration_ms=1234,
            status=PipelineStatus.SUCCESS,
            records_extracted=10,
            records_inserted=10,
            run_metadata={},
            created_at=now,
        )
    )
    seeded_session.commit()

    body = client.get("/api/v1/pipelines/runs").json()
    assert body["meta"]["total"] == 1
    run = body["data"][0]
    assert run["status"] == "success"
    assert run["duration_ms"] == 1234

    detail = client.get(f"/api/v1/pipelines/runs/{run['id']}").json()
    assert detail["id"] == run["id"]
    assert detail["quality_checks"] == []


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------
@pytest.fixture
def compare_client(seeded_session: Session, make_observation) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    """A client with one indicator held by two countries, Guatemala missing a month."""
    from reim.services.observation_writer import write_observations

    write_observations(
        seeded_session,
        [
            make_observation(
                period,
                value,
                indicator_code="exports_goods_monthly",
                source_key=source,
                country_iso3=iso3,
                unit="current USD",
                currency_code="USD",
            )
            for period, value, iso3, source in (
                ("2024-01", "100", "NIC", "imf_imts_nicaragua"),
                ("2024-02", "110", "NIC", "imf_imts_nicaragua"),
                ("2024-03", "120", "NIC", "imf_imts_nicaragua"),
                ("2024-01", "500", "GTM", "imf_imts_guatemala"),
                ("2024-03", "520", "GTM", "imf_imts_guatemala"),
            )
        ],
        connector_version="1.0.0",
    )
    seeded_session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: seeded_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_compare_aligns_periods(compare_client: TestClient) -> None:
    body = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "exports_goods_monthly", "country": ["NI", "GT"]},
    ).json()

    assert body["meta"]["total"] == 3
    assert [row["period_label"] for row in body["data"]] == ["2024-01", "2024-02", "2024-03"]


def test_compare_reports_a_gap_as_an_explicit_null(compare_client: TestClient) -> None:
    """Guatemala has no February. The key must be present and null."""
    body = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "exports_goods_monthly", "country": ["NI", "GT"]},
    ).json()
    february = next(row for row in body["data"] if row["period_label"] == "2024-02")

    assert "GTM" in february["values"]
    assert february["values"]["GTM"] is None
    assert february["values"]["NIC"] == "110"


def test_compare_matches_the_observations_endpoint(compare_client: TestClient) -> None:
    """The comparison must not transform anything."""
    observations = compare_client.get(
        "/api/v1/observations",
        params={"country": "GT", "indicator": "exports_goods_monthly", "limit": 100},
    ).json()["data"]
    expected = {o["period_label"]: o["value_numeric"] for o in observations}

    body = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "exports_goods_monthly", "country": ["NI", "GT"]},
    ).json()
    got = {
        row["period_label"]: row["values"]["GTM"]
        for row in body["data"]
        if row["values"]["GTM"] is not None
    }

    assert got == expected


def test_compare_reports_series_metadata(compare_client: TestClient) -> None:
    body = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "exports_goods_monthly", "country": ["NI", "GT"]},
    ).json()
    series = {s["country_iso3"]: s for s in body["series"]}

    assert body["comparable"] is True
    assert series["NIC"]["observations"] == 3
    assert series["GTM"]["observations"] == 2
    assert series["NIC"]["units"] == ["current USD"]
    assert series["NIC"]["organization_codes"] == ["IMF"]
    assert series["NIC"]["first_period"] == "2024-01"
    assert body["comparability_notes"] == []


def test_compare_names_a_country_holding_nothing(compare_client: TestClient) -> None:
    body = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "exports_goods_monthly", "country": ["NI", "HN"]},
    ).json()
    series = {s["country_iso3"]: s for s in body["series"]}

    assert series["HND"]["observations"] == 0
    assert all(row["values"]["HND"] is None for row in body["data"])
    assert any("HND" in note for note in body["comparability_notes"])


def test_compare_flags_differing_units(
    seeded_session: Session,
    compare_client: TestClient,
    make_observation,  # type: ignore[no-untyped-def]
) -> None:
    """Not reachable from ingested data yet, but storable and served honestly."""
    from reim.services.observation_writer import write_observations

    write_observations(
        seeded_session,
        [
            make_observation(
                "2024-01",
                "9",
                indicator_code="exports_goods_monthly",
                source_key="imf_imts_honduras",
                country_iso3="HND",
                unit="lempiras",
                currency_code="HNL",
            )
        ],
        connector_version="1.0.0",
    )
    seeded_session.commit()

    body = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "exports_goods_monthly", "country": ["NI", "HN"]},
    ).json()

    assert body["comparable"] is False
    assert any("nit" in note for note in body["comparability_notes"])


def test_compare_paginates_periods(compare_client: TestClient) -> None:
    body = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "exports_goods_monthly", "country": ["NI", "GT"], "limit": 1},
    ).json()

    assert body["meta"]["total"] == 3
    assert body["meta"]["has_more"] is True
    assert len(body["data"]) == 1
    assert body["data"][0]["period_label"] == "2024-01"


def test_compare_orders_descending(compare_client: TestClient) -> None:
    body = compare_client.get(
        "/api/v1/compare",
        params={
            "indicator": "exports_goods_monthly",
            "country": ["NI", "GT"],
            "order": "desc",
        },
    ).json()

    assert body["data"][0]["period_label"] == "2024-03"


def test_compare_requires_at_least_two_countries(compare_client: TestClient) -> None:
    response = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "exports_goods_monthly", "country": ["NI"]},
    )

    assert response.status_code == 422


def test_compare_rejects_more_than_twenty_countries(compare_client: TestClient) -> None:
    response = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "exports_goods_monthly", "country": ["NI"] * 21},
    )

    assert response.status_code == 422


def test_compare_rejects_an_unknown_indicator(compare_client: TestClient) -> None:
    response = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "not_an_indicator", "country": ["NI", "GT"]},
    )

    assert response.status_code == 404


def test_compare_rejects_an_unknown_country(compare_client: TestClient) -> None:
    response = compare_client.get(
        "/api/v1/compare",
        params={"indicator": "exports_goods_monthly", "country": ["NI", "ZZ"]},
    )

    assert response.status_code == 404
