"""Pipeline observability endpoints.

Read-only by design: this MVP deliberately exposes no HTTP trigger for running a
pipeline. Ingestion is a CLI/scheduler concern.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from apps.api.dependencies import PaginationDep, SessionDep
from reim.core.constants import PipelineStatus
from reim.core.exceptions import ResourceNotFoundError
from reim.repositories import pipeline_runs as run_repo
from reim.schemas.common import Page
from reim.schemas.pipelines import (
    PipelineRunDetail,
    PipelineRunRead,
    PipelineSummary,
    QualityCheckRead,
)
from reim.services.status import build_pipeline_summaries

router = APIRouter(prefix="/api/v1/pipelines", tags=["pipelines"])


@router.get("", response_model=list[PipelineSummary], summary="Pipeline health overview")
def list_pipelines(session: SessionDep) -> list[PipelineSummary]:
    """Return every registered pipeline with its last run, volumes and freshness."""
    return build_pipeline_summaries(session)


@router.get("/runs", response_model=Page[PipelineRunRead], summary="List pipeline runs")
def list_runs(
    session: SessionDep,
    pagination: PaginationDep,
    pipeline_key: Annotated[str | None, Query(description="Filter by pipeline key.")] = None,
    status: Annotated[PipelineStatus | None, Query()] = None,
) -> Page[PipelineRunRead]:
    """Return recorded pipeline runs, newest first."""
    total = run_repo.count_runs(session, pipeline_key=pipeline_key, status=status)
    runs = run_repo.list_runs(
        session,
        pipeline_key=pipeline_key,
        status=status,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return Page.build(
        [PipelineRunRead.model_validate(run) for run in runs],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get(
    "/runs/{run_id}",
    response_model=PipelineRunDetail,
    summary="Get one pipeline run with its quality checks",
    responses={404: {"description": "Run not found"}},
)
def get_run(session: SessionDep, run_id: uuid.UUID) -> PipelineRunDetail:
    """Return a single run, including every quality check it produced."""
    run = run_repo.get_run(session, run_id)
    if run is None:
        msg = f"Pipeline run {run_id} not found"
        raise ResourceNotFoundError(msg, run_id=str(run_id))
    detail = PipelineRunDetail.model_validate(run)
    detail.quality_checks = [QualityCheckRead.model_validate(check) for check in run.quality_checks]
    return detail
