"""REIM command line interface.

Run with ``reim <command>`` or ``python -m reim.cli <command>``.

Exit codes:

===  ==========================================================
0    Success.
1    A pipeline failed, or a report contains failing checks.
2    Invalid configuration, catalog or arguments.
===  ==========================================================
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from reim import __version__
from reim.core.config import get_settings
from reim.core.constants import CheckSeverity, CheckStatus, PipelineStatus
from reim.core.exceptions import REIMError
from reim.core.logging import configure_logging, get_logger
from reim.database.session import check_database_connection, session_scope
from reim.domain.pipelines.models import PipelineOutcome
from reim.domain.pipelines.scheduling import DEFAULT_CRON_BY_FREQUENCY
from reim.domain.quality.rules import load_quality_rules
from reim.domain.sources.catalog import load_catalog
from reim.ingestion.registry import ConnectorRegistry
from reim.ingestion.runner import PipelineRunner
from reim.repositories import pipeline_runs as run_repo
from reim.services.seeding import seed_all

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_INVALID = 2

app = typer.Typer(
    name="reim",
    help="Regional Economic Intelligence Monitor — ingestion and operations CLI.",
    no_args_is_help=True,
    add_completion=False,
)
catalog_app = typer.Typer(help="Inspect and validate the source catalog.", no_args_is_help=True)
db_app = typer.Typer(help="Database maintenance commands.", no_args_is_help=True)
pipeline_app = typer.Typer(help="List and execute ingestion pipelines.", no_args_is_help=True)
quality_app = typer.Typer(help="Data-quality reporting.", no_args_is_help=True)

app.add_typer(catalog_app, name="catalog")
app.add_typer(db_app, name="db")
app.add_typer(pipeline_app, name="pipeline")
app.add_typer(quality_app, name="quality")

logger = get_logger(__name__)
err = typer.echo


@app.callback()
def main() -> None:
    """Configure logging before any subcommand runs."""
    configure_logging()


@app.command()
def version() -> None:
    """Print the REIM version."""
    typer.echo(__version__)


# --------------------------------------------------------------------------
# catalog
# --------------------------------------------------------------------------
@catalog_app.command("validate")
def catalog_validate(
    path: Annotated[
        Path | None,
        typer.Option("--path", help="Catalog file to validate. Defaults to REIM_CATALOG_PATH."),
    ] = None,
    check_connectors: Annotated[
        bool,
        typer.Option("--check-connectors/--no-check-connectors", help="Import every connector."),
    ] = True,
) -> None:
    """Validate the source catalog and the quality rules.

    Exits 2 when either file is invalid or a referenced connector cannot load.
    """
    try:
        catalog = load_catalog(path)
        rules = load_quality_rules()
    except REIMError as exc:
        err(f"✗ {exc.message}", err=True)
        raise typer.Exit(EXIT_INVALID) from exc

    typer.echo(
        f"✓ Catalog valid: {len(catalog.sources)} source(s), {len(catalog.enabled_sources)} enabled"
    )
    typer.echo(f"✓ Quality rules valid: {len(rules.indicators)} indicator rule(s)")

    if check_connectors:
        problems = ConnectorRegistry(catalog).validate_all()
        if problems:
            err("✗ Connector problems:", err=True)
            for problem in problems:
                err(f"    {problem}", err=True)
            raise typer.Exit(EXIT_INVALID)
        typer.echo(f"✓ All {len(catalog.sources)} connector(s) import cleanly")

    for entry in catalog.sources:
        mark = "●" if entry.enabled else "○"
        typer.echo(f"  {mark} {entry.key:32} {entry.organization:10} {entry.frequency.value}")
    raise typer.Exit(EXIT_OK)


@catalog_app.command("show")
def catalog_show(source_key: Annotated[str, typer.Argument(help="Catalog key.")]) -> None:
    """Print one catalog entry in full."""
    try:
        entry = load_catalog().get(source_key)
    except REIMError as exc:
        err(f"✗ {exc.message}", err=True)
        raise typer.Exit(EXIT_INVALID) from exc
    typer.echo(entry.model_dump_json(indent=2))


# --------------------------------------------------------------------------
# db
# --------------------------------------------------------------------------
@db_app.command("check")
def db_check() -> None:
    """Verify the database is reachable."""
    if check_database_connection():
        typer.echo(f"✓ Database reachable at {_safe_dsn()}")
        raise typer.Exit(EXIT_OK)
    err(f"✗ Database unreachable at {_safe_dsn()}", err=True)
    raise typer.Exit(EXIT_FAILURE)


@db_app.command("seed")
def db_seed() -> None:
    """Seed countries, organizations, indicators and catalog sources.

    Idempotent: safe to re-run after editing the catalog or a registry.
    """
    try:
        with session_scope() as session:
            report = seed_all(session)
    except REIMError as exc:
        err(f"✗ {exc.message}", err=True)
        raise typer.Exit(EXIT_INVALID) from exc

    typer.echo(f"✓ Seed complete — created {report.total_created}, updated {report.total_updated}")
    typer.echo(
        f"    countries    +{report.countries_created} ~{report.countries_updated}\n"
        f"    organizations+{report.organizations_created} ~{report.organizations_updated}\n"
        f"    indicators   +{report.indicators_created} ~{report.indicators_updated}\n"
        f"    sources      +{report.sources_created} ~{report.sources_updated}"
    )


# --------------------------------------------------------------------------
# pipeline
# --------------------------------------------------------------------------
@pipeline_app.command("list")
def pipeline_list(
    enabled_only: Annotated[
        bool, typer.Option("--enabled-only/--all", help="Restrict to enabled pipelines.")
    ] = False,
) -> None:
    """List registered pipelines and their suggested cron schedule."""
    try:
        registry = ConnectorRegistry(load_catalog())
    except REIMError as exc:
        err(f"✗ {exc.message}", err=True)
        raise typer.Exit(EXIT_INVALID) from exc

    typer.echo(f"{'KEY':32} {'STATUS':9} {'FREQ':10} {'SUGGESTED CRON':20} INDICATORS")
    for entry in registry.catalog.sources:
        if enabled_only and not entry.enabled:
            continue
        status = "enabled" if entry.enabled else "disabled"
        cron = DEFAULT_CRON_BY_FREQUENCY[entry.frequency]
        typer.echo(
            f"{entry.key:32} {status:9} {entry.frequency.value:10} {cron:20} "
            f"{', '.join(entry.indicators)}"
        )


@pipeline_app.command("run")
def pipeline_run(
    pipeline_key: Annotated[str, typer.Argument(help="Catalog key of the pipeline.")],
    force: Annotated[
        bool,
        typer.Option("--force", help="Run even if the catalog marks the source as disabled."),
    ] = False,
) -> None:
    """Run one pipeline. Exits 1 if it fails."""
    try:
        registry = ConnectorRegistry(load_catalog())
        registered = registry.get(pipeline_key)
    except REIMError as exc:
        err(f"✗ {exc.message}", err=True)
        raise typer.Exit(EXIT_INVALID) from exc

    if not registered.enabled and not force:
        reason = registered.entry.disabled_reason or "no reason recorded"
        err(f"✗ Pipeline {pipeline_key!r} is disabled: {reason.strip()}", err=True)
        err("  Re-run with --force to execute it anyway.", err=True)
        raise typer.Exit(EXIT_INVALID)

    outcome = asyncio.run(PipelineRunner(registry).run(pipeline_key))
    _print_outcome(outcome)
    raise typer.Exit(EXIT_OK if outcome.succeeded else EXIT_FAILURE)


@pipeline_app.command("run-all")
def pipeline_run_all(
    include_disabled: Annotated[
        bool, typer.Option("--include-disabled", help="Also run disabled pipelines.")
    ] = False,
) -> None:
    """Run every enabled pipeline. Exits 1 if any of them fails."""
    try:
        registry = ConnectorRegistry(load_catalog())
    except REIMError as exc:
        err(f"✗ {exc.message}", err=True)
        raise typer.Exit(EXIT_INVALID) from exc

    outcomes = asyncio.run(PipelineRunner(registry).run_all(enabled_only=not include_disabled))
    for outcome in outcomes:
        _print_outcome(outcome)

    failed = [outcome for outcome in outcomes if not outcome.succeeded]
    typer.echo(f"\n{len(outcomes) - len(failed)}/{len(outcomes)} pipeline(s) succeeded")
    raise typer.Exit(EXIT_FAILURE if failed else EXIT_OK)


@pipeline_app.command("status")
def pipeline_status(
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 20,
) -> None:
    """Show the most recent pipeline runs."""
    with session_scope() as session:
        runs = run_repo.list_runs(session, limit=limit)
        if not runs:
            typer.echo("No pipeline runs recorded yet.")
            return
        typer.echo(
            f"{'STARTED (UTC)':20} {'KEY':32} {'STATUS':8} {'INS':>5} {'UPD':>5} "
            f"{'REJ':>5} {'MS':>7}"
        )
        for run in runs:
            typer.echo(
                f"{run.started_at.strftime('%Y-%m-%d %H:%M:%S'):20} "
                f"{run.pipeline_key:32} {run.status.value:8} "
                f"{run.records_inserted:5} {run.records_updated:5} "
                f"{run.records_rejected:5} {run.duration_ms or 0:7}"
            )


# --------------------------------------------------------------------------
# quality
# --------------------------------------------------------------------------
@quality_app.command("report")
def quality_report(
    days: Annotated[int, typer.Option("--days", min=1, max=365)] = 30,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 50,
) -> None:
    """Summarise failing quality checks. Exits 1 when errors or worse are present."""
    since = datetime.now(UTC) - timedelta(days=days)
    with session_scope() as session:
        summary = run_repo.summarize_failed_checks(session, since=since)
        failures = run_repo.list_checks(
            session, status=CheckStatus.FAILED, since=since, limit=limit
        )

        typer.echo(f"Quality report — last {days} day(s)")
        if not summary:
            typer.echo("✓ No failing checks recorded.")
            raise typer.Exit(EXIT_OK)

        for severity in (
            CheckSeverity.CRITICAL,
            CheckSeverity.ERROR,
            CheckSeverity.WARNING,
            CheckSeverity.INFO,
        ):
            count = summary.get(severity.value, 0)
            if count:
                typer.echo(f"  {severity.value:9} {count}")

        typer.echo("\nMost recent failures:")
        for check in failures:
            message = str(check.details.get("message", ""))[:80]
            typer.echo(
                f"  [{check.severity.value:8}] {check.check_name:28} "
                f"{check.indicator_code or '-':34} {message}"
            )

        blocking = summary.get(CheckSeverity.CRITICAL.value, 0) + summary.get(
            CheckSeverity.ERROR.value, 0
        )
    raise typer.Exit(EXIT_FAILURE if blocking else EXIT_OK)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _print_outcome(outcome: PipelineOutcome) -> None:
    mark = "✓" if outcome.succeeded else "✗"
    typer.echo(
        f"{mark} {outcome.pipeline_key:32} {outcome.status.value:8} "
        f"extracted={outcome.records_extracted} inserted={outcome.records_inserted} "
        f"updated={outcome.records_updated} unchanged={outcome.records_unchanged} "
        f"rejected={outcome.records_rejected} ({outcome.duration_ms} ms)"
    )
    if outcome.status is PipelineStatus.FAILED and outcome.error_message:
        err(f"    {outcome.error_type}: {outcome.error_message}", err=True)


def _safe_dsn() -> str:
    """Return the database URL with any password removed."""
    url = get_settings().database_url
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    credentials, _, host = rest.rpartition("@")
    user = credentials.split(":", 1)[0] if credentials else ""
    return f"{scheme}://{user}:***@{host}" if user else f"{scheme}://{host}"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
