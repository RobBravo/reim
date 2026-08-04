"""Operational status: pipeline health, data freshness and platform totals."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reim import __version__
from reim.core.config import get_settings
from reim.database.models import Country, Indicator, Observation, PipelineRun
from reim.database.session import check_database_connection
from reim.domain.quality.rules import QualityRuleSet, get_quality_rules
from reim.domain.sources.catalog import SourceCatalog, get_catalog
from reim.repositories import pipeline_runs as run_repo
from reim.repositories.observations import latest_period_end
from reim.repositories.reference import get_source_by_key
from reim.schemas.pipelines import PipelineSummary, SystemStatus


def build_pipeline_summaries(
    session: Session,
    catalog: SourceCatalog | None = None,
    rules: QualityRuleSet | None = None,
) -> list[PipelineSummary]:
    """Return an operational summary for every registered pipeline."""
    resolved_catalog = catalog or get_catalog()
    resolved_rules = rules or get_quality_rules()
    today = datetime.now(UTC).date()

    summaries: list[PipelineSummary] = []
    for entry in resolved_catalog.sources:
        last_run = run_repo.latest_run(session, entry.key)
        last_success = run_repo.latest_successful_run(session, entry.key)
        source = get_source_by_key(session, entry.key)

        observation_count = 0
        newest: date | None = None
        if source is not None:
            observation_count = int(
                session.scalar(
                    select(func.count(Observation.id)).where(Observation.source_id == source.id)
                )
                or 0
            )
            newest = latest_period_end(session, source.id)

        age_days: int | None = None
        stale: bool | None = None
        if newest is not None:
            age_days = (today - newest).days
            threshold = resolved_rules.for_indicator(entry.indicators[0]).freshness_max_age_days
            stale = age_days > threshold if threshold is not None else None

        summaries.append(
            PipelineSummary(
                pipeline_key=entry.key,
                source_key=entry.key,
                enabled=entry.enabled,
                disabled_reason=entry.disabled_reason,
                frequency=entry.frequency,
                indicators=list(entry.indicators),
                last_run_at=last_run.started_at if last_run else None,
                last_run_status=last_run.status if last_run else None,
                last_run_duration_ms=last_run.duration_ms if last_run else None,
                last_success_at=last_success.started_at if last_success else None,
                last_error_type=last_run.error_type if last_run else None,
                last_error_message=last_run.error_message if last_run else None,
                records_inserted_last_run=last_run.records_inserted if last_run else None,
                records_updated_last_run=last_run.records_updated if last_run else None,
                records_rejected_last_run=last_run.records_rejected if last_run else None,
                observation_count=observation_count,
                latest_period_end=newest,
                data_age_days=age_days,
                is_stale=stale,
            )
        )
    return summaries


def build_system_status(session: Session, catalog: SourceCatalog | None = None) -> SystemStatus:
    """Return aggregate platform counters and recent quality signal."""
    resolved = catalog or get_catalog()
    since = datetime.now(UTC) - timedelta(days=7)

    return SystemStatus(
        version=__version__,
        environment=get_settings().environment.value,
        database_connected=check_database_connection(),
        countries=int(session.scalar(select(func.count(Country.id))) or 0),
        indicators=int(session.scalar(select(func.count(Indicator.id))) or 0),
        sources_registered=len(resolved.sources),
        sources_enabled=len(resolved.enabled_sources),
        observations=int(session.scalar(select(func.count(Observation.id))) or 0),
        pipeline_runs=int(session.scalar(select(func.count(PipelineRun.id))) or 0),
        last_ingestion_at=session.scalar(select(func.max(Observation.retrieved_at))),
        failed_checks_last_7_days=run_repo.summarize_failed_checks(session, since=since),
        generated_at=datetime.now(UTC),
    )
