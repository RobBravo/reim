"""End-to-end pipeline runs against mocked HTTP (requires PostgreSQL)."""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reim.core.constants import (
    CheckSeverity,
    CheckStatus,
    PipelineStatus,
    ValidationStatus,
)
from reim.database.models import DataQualityCheck, Observation, PipelineRun
from reim.domain.quality.rules import IndicatorRule, QualityRuleSet
from reim.ingestion.registry import ConnectorRegistry
from reim.ingestion.runner import PipelineRunner
from tests.conftest import requires_db

pytestmark = [requires_db, pytest.mark.integration]

CPI_URL = "https://api.worldbank.org/v2/country/NIC/indicator/FP.CPI.TOTL.ZG"
PIPELINE = "worldbank_ni_cpi_inflation"


@pytest.fixture
def runner(catalog, quality_rules) -> PipelineRunner:  # type: ignore[no-untyped-def]
    return PipelineRunner(ConnectorRegistry(catalog), quality_rules)


def _observations(session: Session) -> int:
    return int(session.scalar(select(func.count(Observation.id))) or 0)


# --------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------
@respx.mock
async def test_full_run_persists_observations(
    seeded_session: Session, runner: PipelineRunner, worldbank_cpi_payload
) -> None:  # type: ignore[no-untyped-def]
    respx.get(CPI_URL).mock(return_value=httpx.Response(200, json=worldbank_cpi_payload))

    outcome = await runner.run(PIPELINE, session=seeded_session)

    assert outcome.status is PipelineStatus.SUCCESS
    assert outcome.records_extracted == 10
    assert outcome.records_inserted == 10
    assert _observations(seeded_session) == 10


@respx.mock
async def test_run_records_a_pipeline_run(
    seeded_session: Session, runner: PipelineRunner, worldbank_cpi_payload
) -> None:  # type: ignore[no-untyped-def]
    respx.get(CPI_URL).mock(return_value=httpx.Response(200, json=worldbank_cpi_payload))
    await runner.run(PIPELINE, session=seeded_session)

    run = seeded_session.scalar(select(PipelineRun))
    assert run is not None
    assert run.pipeline_key == PIPELINE
    assert run.status is PipelineStatus.SUCCESS
    assert run.finished_at is not None
    assert run.duration_ms is not None and run.duration_ms >= 0
    assert run.records_extracted == 10
    assert run.records_inserted == 10
    assert run.source_id is not None
    assert run.connector_version and run.pipeline_version
    assert run.run_metadata["source_url"].startswith("https://api.worldbank.org/")


@respx.mock
async def test_run_records_quality_checks(
    seeded_session: Session, runner: PipelineRunner, worldbank_cpi_payload
) -> None:  # type: ignore[no-untyped-def]
    respx.get(CPI_URL).mock(return_value=httpx.Response(200, json=worldbank_cpi_payload))
    await runner.run(PIPELINE, session=seeded_session)

    checks = list(seeded_session.scalars(select(DataQualityCheck)))
    assert checks
    names = {check.check_name for check in checks}
    assert "dataset_not_empty" in names
    assert "no_duplicate_periods" in names
    assert "worldbank_country_match" in names
    assert all(check.pipeline_run_id for check in checks)


@respx.mock
async def test_observations_are_linked_to_all_three_dimensions(
    seeded_session: Session, runner: PipelineRunner, worldbank_cpi_payload
) -> None:  # type: ignore[no-untyped-def]
    respx.get(CPI_URL).mock(return_value=httpx.Response(200, json=worldbank_cpi_payload))
    await runner.run(PIPELINE, session=seeded_session)

    for row in seeded_session.scalars(select(Observation)):
        assert row.country.iso3 == "NIC"
        assert row.indicator.code == "ni_cpi_inflation_annual"
        assert row.source.source_key == PIPELINE
        assert row.validation_status is ValidationStatus.PASSED


@respx.mock
async def test_values_keep_full_precision_end_to_end(
    seeded_session: Session, runner: PipelineRunner, worldbank_cpi_payload
) -> None:  # type: ignore[no-untyped-def]
    respx.get(CPI_URL).mock(return_value=httpx.Response(200, json=worldbank_cpi_payload))
    await runner.run(PIPELINE, session=seeded_session)
    seeded_session.expire_all()

    row = seeded_session.scalar(select(Observation).where(Observation.period_label == "2024"))
    assert row.value_numeric == Decimal("4.62473841057141")


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------
@respx.mock
async def test_second_run_is_a_no_op(
    seeded_session: Session, runner: PipelineRunner, worldbank_cpi_payload
) -> None:  # type: ignore[no-untyped-def]
    respx.get(CPI_URL).mock(return_value=httpx.Response(200, json=worldbank_cpi_payload))

    await runner.run(PIPELINE, session=seeded_session)
    second = await runner.run(PIPELINE, session=seeded_session)

    assert second.records_inserted == 0
    assert second.records_unchanged == 10
    assert _observations(seeded_session) == 10


@respx.mock
async def test_upstream_revision_is_detected(
    seeded_session: Session, runner: PipelineRunner, worldbank_cpi_payload
) -> None:  # type: ignore[no-untyped-def]
    metadata, rows = worldbank_cpi_payload
    respx.get(CPI_URL).mock(return_value=httpx.Response(200, json=worldbank_cpi_payload))
    await runner.run(PIPELINE, session=seeded_session)

    revised = [dict(row) for row in rows]
    revised[0]["value"] = 9.99
    respx.get(CPI_URL).mock(return_value=httpx.Response(200, json=[metadata, revised]))
    outcome = await runner.run(PIPELINE, session=seeded_session)

    assert outcome.records_updated == 1
    assert outcome.records_unchanged == 9
    assert _observations(seeded_session) == 10


# --------------------------------------------------------------------------
# Failure handling
# --------------------------------------------------------------------------
@respx.mock
async def test_unreachable_source_is_recorded_not_raised(
    seeded_session: Session, runner: PipelineRunner
) -> None:
    respx.get(CPI_URL).mock(side_effect=httpx.ConnectError("no route"))

    outcome = await runner.run(PIPELINE, session=seeded_session)

    assert outcome.status is PipelineStatus.FAILED
    assert outcome.error_type == "extraction_error"
    assert _observations(seeded_session) == 0


@respx.mock
async def test_failed_run_is_still_persisted(
    seeded_session: Session, runner: PipelineRunner
) -> None:
    """Evidence of the failure survives the rollback that protects the data."""
    respx.get(CPI_URL).mock(return_value=httpx.Response(500, text="boom"))
    await runner.run(PIPELINE, session=seeded_session)
    seeded_session.commit()

    run = seeded_session.scalar(select(PipelineRun))
    assert run is not None
    assert run.status is PipelineStatus.FAILED
    assert run.error_type == "extraction_error"
    assert run.error_message
    assert run.finished_at is not None


@respx.mock
async def test_critical_check_rolls_the_load_back(
    seeded_session: Session, catalog, worldbank_cpi_payload
) -> None:  # type: ignore[no-untyped-def]
    """A critical failure must prevent invalid data from being committed."""
    strict = QualityRuleSet(
        defaults=IndicatorRule(min_observations=999),
        indicators={"ni_cpi_inflation_annual": IndicatorRule(min_observations=999)},
    )
    respx.get(CPI_URL).mock(return_value=httpx.Response(200, json=worldbank_cpi_payload))

    outcome = await PipelineRunner(ConnectorRegistry(catalog), strict).run(
        PIPELINE, session=seeded_session
    )

    assert outcome.status is PipelineStatus.FAILED
    assert outcome.error_type == "critical_quality_failure"
    assert _observations(seeded_session) == 0


@respx.mock
async def test_rollback_does_not_lose_previously_committed_data(
    seeded_session: Session, catalog, quality_rules, worldbank_cpi_payload
) -> None:  # type: ignore[no-untyped-def]
    respx.get(CPI_URL).mock(return_value=httpx.Response(200, json=worldbank_cpi_payload))
    await PipelineRunner(ConnectorRegistry(catalog), quality_rules).run(
        PIPELINE, session=seeded_session
    )
    seeded_session.commit()
    assert _observations(seeded_session) == 10

    strict = QualityRuleSet(
        defaults=IndicatorRule(min_observations=999),
        indicators={"ni_cpi_inflation_annual": IndicatorRule(min_observations=999)},
    )
    await PipelineRunner(ConnectorRegistry(catalog), strict).run(PIPELINE, session=seeded_session)

    assert _observations(seeded_session) == 10


@respx.mock
async def test_error_level_check_rejects_only_the_offending_row(
    seeded_session: Session, catalog, worldbank_cpi_payload
) -> None:  # type: ignore[no-untyped-def]
    metadata, rows = worldbank_cpi_payload
    poisoned = [dict(row) for row in rows]
    poisoned[0]["value"] = -999  # below the configured minimum
    respx.get(CPI_URL).mock(return_value=httpx.Response(200, json=[metadata, poisoned]))

    rules = QualityRuleSet(
        indicators={
            "ni_cpi_inflation_annual": IndicatorRule(
                min_value=Decimal("-30"), range_severity=CheckSeverity.ERROR
            )
        }
    )
    outcome = await PipelineRunner(ConnectorRegistry(catalog), rules).run(
        PIPELINE, session=seeded_session
    )

    assert outcome.status is PipelineStatus.PARTIAL
    assert outcome.records_rejected == 1
    assert outcome.records_inserted == 9
    assert _observations(seeded_session) == 9


@respx.mock
async def test_warning_stores_data_and_marks_it(
    seeded_session: Session, catalog, worldbank_cpi_payload
) -> None:  # type: ignore[no-untyped-def]
    rules = QualityRuleSet(
        indicators={
            "ni_cpi_inflation_annual": IndicatorRule(max_period_change_pct=Decimal("0.0001"))
        }
    )
    respx.get(CPI_URL).mock(return_value=httpx.Response(200, json=worldbank_cpi_payload))

    outcome = await PipelineRunner(ConnectorRegistry(catalog), rules).run(
        PIPELINE, session=seeded_session
    )

    assert outcome.status is PipelineStatus.SUCCESS
    assert outcome.records_inserted == 10
    warned = seeded_session.scalars(
        select(Observation).where(
            Observation.validation_status == ValidationStatus.PASSED_WITH_WARNINGS
        )
    ).all()
    assert warned


@respx.mock
async def test_failed_checks_are_recorded_with_severity(
    seeded_session: Session, catalog, worldbank_cpi_payload
) -> None:  # type: ignore[no-untyped-def]
    strict = QualityRuleSet(
        defaults=IndicatorRule(min_observations=999),
        indicators={"ni_cpi_inflation_annual": IndicatorRule(min_observations=999)},
    )
    respx.get(CPI_URL).mock(return_value=httpx.Response(200, json=worldbank_cpi_payload))
    await PipelineRunner(ConnectorRegistry(catalog), strict).run(PIPELINE, session=seeded_session)
    seeded_session.commit()

    critical = seeded_session.scalars(
        select(DataQualityCheck).where(
            DataQualityCheck.status == CheckStatus.FAILED,
            DataQualityCheck.severity == CheckSeverity.CRITICAL,
        )
    ).all()
    assert critical
    assert any(check.check_name == "dataset_not_empty" for check in critical)


# --------------------------------------------------------------------------
# run_all
# --------------------------------------------------------------------------
@respx.mock
async def test_run_all_isolates_failures(
    seeded_session: Session, catalog, quality_rules, worldbank_cpi_payload, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """One broken source must not stop the others."""

    @contextmanager
    def _test_scope():  # type: ignore[no-untyped-def]
        yield seeded_session
        seeded_session.commit()

    monkeypatch.setattr("reim.ingestion.runner.session_scope", _test_scope)

    respx.get(CPI_URL).mock(return_value=httpx.Response(200, json=worldbank_cpi_payload))
    respx.get(url__startswith="https://api.worldbank.org/v2/country/NIC/indicator/").mock(
        return_value=httpx.Response(503)
    )

    runner = PipelineRunner(ConnectorRegistry(catalog), quality_rules)
    outcomes = await runner.run_all(keys=[PIPELINE, "worldbank_ni_remittances"])

    assert len(outcomes) == 2
    assert outcomes[0].status is PipelineStatus.SUCCESS
    assert outcomes[1].status is PipelineStatus.FAILED
    # The successful pipeline's data survived the other one's failure.
    assert _observations(seeded_session) == 10


async def test_unknown_pipeline_key_raises(catalog, quality_rules) -> None:  # type: ignore[no-untyped-def]
    from reim.core.exceptions import ConnectorNotFoundError

    runner = PipelineRunner(ConnectorRegistry(catalog), quality_rules)
    with pytest.raises(ConnectorNotFoundError):
        await runner.run("not_a_pipeline")
