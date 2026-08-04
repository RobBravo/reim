"""The shared pipeline runner.

Every ingestion follows exactly the same ten steps, implemented once here:

1. Open a run record (so a crash is still observable).
2. Extract from the source.
3. Validate the response (delegated to the connector's ``extract``).
4. Transform into normalized observations.
5. Run the standard quality battery plus the connector's own checks.
6. Persist inside a single transaction.
7. Record the quality results.
8. Capture errors with their type.
9. Finalise the run record.
10. Emit structured logs throughout.

A connector never persists anything and never handles its own error reporting.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from reim import PIPELINE_VERSION
from reim.core.constants import (
    SEVERITY_ORDER,
    CheckSeverity,
    CheckStatus,
    PipelineStatus,
    ValidationStatus,
)
from reim.core.exceptions import CriticalQualityError, REIMError
from reim.core.logging import get_logger
from reim.database.models import DataQualityCheck, PipelineRun
from reim.database.session import session_scope
from reim.domain.pipelines.models import (
    NormalizedObservation,
    PipelineOutcome,
    QualityResult,
    RawDataset,
)
from reim.domain.quality.checks import run_standard_checks
from reim.domain.quality.rules import IndicatorRule, QualityRuleSet, get_quality_rules
from reim.ingestion.base import BaseConnector
from reim.ingestion.registry import ConnectorRegistry
from reim.repositories.reference import get_source_by_key
from reim.services.observation_writer import write_observations

logger = get_logger(__name__)


class PipelineRunner:
    """Executes connectors and owns all cross-cutting pipeline concerns."""

    def __init__(
        self,
        registry: ConnectorRegistry | None = None,
        rules: QualityRuleSet | None = None,
    ) -> None:
        self.registry = registry or ConnectorRegistry()
        self.rules = rules or get_quality_rules()

    async def run(self, pipeline_key: str, *, session: Session | None = None) -> PipelineOutcome:
        """Run a single pipeline end to end.

        Args:
            pipeline_key: Catalog key of the source to ingest.
            session: Optional session to reuse. When omitted the runner opens
                its own transaction and commits it on success.

        Returns:
            A :class:`PipelineOutcome` describing what happened. Failures are
            reported through the outcome and the run record rather than by
            raising, so ``run-all`` can continue with the next pipeline.
        """
        if session is not None:
            return await self._run_in_session(pipeline_key, session)
        with session_scope() as owned_session:
            return await self._run_in_session(pipeline_key, owned_session)

    async def run_all(
        self, *, enabled_only: bool = True, keys: list[str] | None = None
    ) -> list[PipelineOutcome]:
        """Run several pipelines sequentially, isolating each in its own transaction."""
        targets = keys if keys is not None else self.registry.keys(enabled_only=enabled_only)
        outcomes: list[PipelineOutcome] = []
        for key in targets:
            outcomes.append(await self.run(key))
        succeeded = sum(1 for outcome in outcomes if outcome.succeeded)
        logger.info(
            "pipeline.run_all.finished",
            total=len(outcomes),
            succeeded=succeeded,
            failed=len(outcomes) - succeeded,
        )
        return outcomes

    # -- Internals --------------------------------------------------------
    async def _run_in_session(self, pipeline_key: str, session: Session) -> PipelineOutcome:
        started_at = datetime.now(UTC)
        started_monotonic = time.monotonic()
        registered = self.registry.get(pipeline_key)
        connector = registered.build()

        run = self._open_run(session, connector, started_at)
        run_id = run.id
        log = logger.bind(
            pipeline_key=pipeline_key,
            run_id=str(run_id),
            source_key=connector.source.key,
            country=connector.country_iso2,
        )
        log.info("pipeline.started")

        extracted = 0
        results: list[QualityResult] = []
        error_type: str | None = None
        error_message: str | None = None
        status = PipelineStatus.SUCCESS
        inserted = updated = unchanged = rejected = 0

        try:
            raw = await connector.extract()
            observations = connector.transform(raw)
            extracted = len(observations)
            log.info("pipeline.transformed", records_extracted=extracted)

            results = self._evaluate_quality(connector, observations)
            self._abort_on_critical(results)

            rejected_indices = self._rejected_indices(results)
            statuses = self._validation_statuses(observations, results, rejected_indices)

            report = write_observations(
                session,
                observations,
                connector_version=connector.version,
                validation_status_by_index=statuses,
                rejected_indices=rejected_indices,
                pipeline_run_id=run_id,
            )
            inserted, updated = report.inserted, report.updated
            unchanged, rejected = report.unchanged, report.rejected
            # A dataset-level `error` check cannot point at a single row, so it
            # rejects nothing — but it still means something an operator must
            # look at went wrong, so the run is not a clean success.
            status = (
                PipelineStatus.PARTIAL
                if rejected or self._has_dataset_error(results)
                else PipelineStatus.SUCCESS
            )
            self._record_extraction_metadata(run, raw)

        except CriticalQualityError as exc:
            session.rollback()
            run = self._reopen_run(session, connector, started_at, run_id)
            status, error_type, error_message = PipelineStatus.FAILED, exc.code, exc.message
            log.error("pipeline.critical_quality_failure", failed_checks=exc.failed_checks)
        except REIMError as exc:
            session.rollback()
            run = self._reopen_run(session, connector, started_at, run_id)
            status, error_type, error_message = PipelineStatus.FAILED, exc.code, exc.message
            log.error("pipeline.failed", error_type=exc.code, error=exc.message)
        except Exception as exc:
            session.rollback()
            run = self._reopen_run(session, connector, started_at, run_id)
            status = PipelineStatus.FAILED
            error_type, error_message = type(exc).__name__, str(exc)
            log.exception("pipeline.unexpected_error", error_type=error_type)

        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        finished_at = datetime.now(UTC)

        self._finalise_run(
            session,
            run,
            status=status,
            finished_at=finished_at,
            duration_ms=duration_ms,
            extracted=extracted,
            inserted=inserted,
            updated=updated,
            unchanged=unchanged,
            rejected=rejected,
            error_type=error_type,
            error_message=error_message,
            results=results,
        )

        outcome = PipelineOutcome(
            pipeline_key=pipeline_key,
            run_id=str(run_id),
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            records_extracted=extracted,
            records_inserted=inserted,
            records_updated=updated,
            records_unchanged=unchanged,
            records_rejected=rejected,
            quality_results=results,
            error_type=error_type,
            error_message=error_message,
        )
        log.info("pipeline.finished", **outcome.log_fields())
        return outcome

    def _open_run(
        self, session: Session, connector: BaseConnector, started_at: datetime
    ) -> PipelineRun:
        source = get_source_by_key(session, connector.source.key)
        run = PipelineRun(
            id=uuid.uuid4(),
            pipeline_key=connector.connector_key,
            source_id=source.id if source else None,
            connector_version=connector.version,
            pipeline_version=PIPELINE_VERSION,
            started_at=started_at,
            status=PipelineStatus.RUNNING,
            run_metadata=dict(connector.describe()),
            created_at=started_at,
        )
        session.add(run)
        session.flush()
        return run

    def _reopen_run(
        self,
        session: Session,
        connector: BaseConnector,
        started_at: datetime,
        run_id: uuid.UUID,
    ) -> PipelineRun:
        """Recreate the run record after a rollback discarded it.

        The rollback that protects the data also discards the run row inserted
        at the start, so it is written again with the same id to keep the
        identifier reported in logs valid.
        """
        source = get_source_by_key(session, connector.source.key)
        run = PipelineRun(
            id=run_id,
            pipeline_key=connector.connector_key,
            source_id=source.id if source else None,
            connector_version=connector.version,
            pipeline_version=PIPELINE_VERSION,
            started_at=started_at,
            status=PipelineStatus.RUNNING,
            run_metadata=dict(connector.describe()),
            created_at=started_at,
        )
        session.add(run)
        session.flush()
        return run

    def _rule_for(self, connector: BaseConnector) -> IndicatorRule:
        """Return the quality rule governing this connector's primary indicator."""
        return self.rules.for_indicator(connector.source.indicators[0])

    def _evaluate_quality(
        self, connector: BaseConnector, observations: list[NormalizedObservation]
    ) -> list[QualityResult]:
        """Run the standard battery per indicator plus the connector's own checks."""
        results: list[QualityResult] = []
        grouped: dict[str, list[NormalizedObservation]] = defaultdict(list)
        for observation in observations:
            grouped[observation.indicator_code].append(observation)

        if not observations:
            results += run_standard_checks(
                [], self._rule_for(connector), connector.expected_frequency
            )

        for indicator_code, group in grouped.items():
            rule = self.rules.for_indicator(indicator_code)
            group_results = run_standard_checks(group, rule, connector.expected_frequency)
            # Re-map indices from the per-indicator group back to the full batch.
            for result in group_results:
                if result.observation_index is not None:
                    result.observation_index = observations.index(group[result.observation_index])
                result.indicator_code = result.indicator_code or indicator_code
            results += group_results

        results += connector.validate(observations)
        return results

    @staticmethod
    def _abort_on_critical(results: list[QualityResult]) -> None:
        """Raise when any check failed at ``critical`` severity."""
        critical = [
            result.check_name
            for result in results
            if result.failed and result.severity is CheckSeverity.CRITICAL
        ]
        if critical:
            msg = (
                f"{len(critical)} critical quality check(s) failed: "
                f"{', '.join(sorted(set(critical)))}"
            )
            raise CriticalQualityError(msg, failed_checks=sorted(set(critical)))

    @staticmethod
    def _has_dataset_error(results: list[QualityResult]) -> bool:
        """True when an ``error``-severity check failed without naming a row."""
        return any(
            result.failed
            and result.severity is CheckSeverity.ERROR
            and result.observation_index is None
            for result in results
        )

    @staticmethod
    def _rejected_indices(results: list[QualityResult]) -> set[int]:
        """Return indices of observations that failed an ``error``-level check."""
        return {
            result.observation_index
            for result in results
            if result.failed
            and result.severity is CheckSeverity.ERROR
            and result.observation_index is not None
        }

    @staticmethod
    def _validation_statuses(
        observations: list[NormalizedObservation],
        results: list[QualityResult],
        rejected: set[int],
    ) -> dict[int, ValidationStatus]:
        """Map each surviving observation to its validation status."""
        warned = {
            result.observation_index
            for result in results
            if result.failed
            and result.severity is CheckSeverity.WARNING
            and result.observation_index is not None
        }
        statuses: dict[int, ValidationStatus] = {}
        for index in range(len(observations)):
            if index in rejected:
                statuses[index] = ValidationStatus.REJECTED
            elif index in warned:
                statuses[index] = ValidationStatus.PASSED_WITH_WARNINGS
            else:
                statuses[index] = ValidationStatus.PASSED
        return statuses

    @staticmethod
    def _record_extraction_metadata(run: PipelineRun, raw: RawDataset) -> None:
        """Attach non-sensitive provenance from the raw response to the run.

        Only small scalars are stored — never the payload itself.
        """
        metadata: dict[str, Any] = dict(run.run_metadata)
        metadata.update(
            {
                "source_url": raw.source_url,
                "http_status": raw.http_status,
                "content_type": raw.content_type,
                "retrieved_at": raw.retrieved_at.isoformat(),
            }
        )
        metadata.update({k: v for k, v in raw.metadata.items() if isinstance(v, str | int | float)})
        run.run_metadata = metadata

    def _finalise_run(
        self,
        session: Session,
        run: PipelineRun,
        *,
        status: PipelineStatus,
        finished_at: datetime,
        duration_ms: int,
        extracted: int,
        inserted: int,
        updated: int,
        unchanged: int,
        rejected: int,
        error_type: str | None,
        error_message: str | None,
        results: list[QualityResult],
    ) -> None:
        """Write the terminal state of the run and its quality checks."""
        run.status = status
        run.finished_at = finished_at
        run.duration_ms = duration_ms
        run.records_extracted = extracted
        run.records_inserted = inserted
        run.records_updated = updated
        run.records_unchanged = unchanged
        run.records_rejected = rejected
        run.error_type = error_type
        run.error_message = (error_message or None) and error_message[:4000]

        worst = max(
            (SEVERITY_ORDER[r.severity] for r in results if r.failed),
            default=None,
        )
        if worst is not None:
            run.run_metadata = {**run.run_metadata, "worst_failed_severity": worst}

        for result in results:
            session.add(
                DataQualityCheck(
                    pipeline_run_id=run.id,
                    check_name=result.check_name,
                    check_type=result.check_type,
                    status=result.status,
                    severity=result.severity,
                    indicator_code=result.indicator_code,
                    period_label=result.period_label,
                    expected_value=_truncate(result.expected_value),
                    actual_value=_truncate(result.actual_value),
                    details={"message": result.message, **result.details},
                    created_at=finished_at,
                )
            )
        session.flush()

        failed = sum(1 for result in results if result.status is CheckStatus.FAILED)
        if failed:
            logger.warning("pipeline.quality_failures", run_id=str(run.id), failed_checks=failed)


def _truncate(value: str | None, limit: int = 200) -> str | None:
    """Trim a value to the column width, preserving ``None``."""
    return value[:limit] if value else value
