"""Persistence, idempotency and the revision audit trail (requires PostgreSQL)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reim.core.constants import ValidationStatus
from reim.core.exceptions import UnknownReferenceError
from reim.database.models import Country, DataSource, Indicator, Observation, ObservationRevision
from reim.domain.sources.catalog import SourceCatalog
from reim.services.observation_writer import write_observations
from reim.services.seeding import seed_all
from tests.conftest import requires_db

pytestmark = [requires_db, pytest.mark.integration]

CONNECTOR_VERSION = "1.0.0"


def _write(session: Session, observations, **kwargs):  # type: ignore[no-untyped-def]
    return write_observations(session, observations, connector_version=CONNECTOR_VERSION, **kwargs)


def _count(session: Session) -> int:
    return int(session.scalar(select(func.count(Observation.id))) or 0)


# --------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------
def test_seed_creates_reference_data(seeded_session: Session) -> None:
    assert seeded_session.scalar(select(func.count(Country.id))) == 7
    assert seeded_session.scalar(select(func.count(Indicator.id))) >= 6
    assert seeded_session.scalar(select(func.count(DataSource.id))) >= 3


def test_seed_is_idempotent(seeded_session: Session, catalog) -> None:  # type: ignore[no-untyped-def]
    from reim.services.seeding import seed_all

    before = seeded_session.scalar(select(func.count(Country.id)))
    report = seed_all(seeded_session, catalog)
    assert report.total_created == 0
    assert seeded_session.scalar(select(func.count(Country.id))) == before


def test_disabled_source_is_marked_inactive(session: Session) -> None:
    """Seeding carries a catalog entry's disabled state and reason into the table.

    Seeded from a catalog built here rather than the repository's own, which
    currently has no disabled source — the mechanism is what is under test, not
    which entry happens to be off today.
    """
    catalog = SourceCatalog.model_validate(
        {
            "version": 1,
            "sources": [
                {
                    "key": "disabled_probe_source",
                    "name": "A source with no automatable endpoint yet",
                    "country": "NI",
                    "organization": "MHCP",
                    "category": "fiscal",
                    "access_type": "manual",
                    "frequency": "annual",
                    "format": "pdf",
                    "base_url": "https://www.mhcp.gob.ni",
                    "connector": "reim.ingestion.connectors.nicaragua.worldbank_exports",
                    "indicators": ["ni_exports_goods_services"],
                    "enabled": False,
                    "disabled_reason": "Published only as PDF; no stable machine-readable export.",
                }
            ],
        }
    )
    seed_all(session, catalog)
    session.commit()

    source = session.scalar(
        select(DataSource).where(DataSource.source_key == "disabled_probe_source")
    )

    assert source is not None
    assert source.is_active is False
    assert source.disabled_reason == "Published only as PDF; no stable machine-readable export."


def test_enabled_source_carries_no_disabled_reason(seeded_session: Session) -> None:
    """Every source in the repository catalog is currently enabled."""
    sources = seeded_session.scalars(select(DataSource)).all()

    assert sources
    for source in sources:
        assert source.is_active is True
        assert source.disabled_reason is None


# --------------------------------------------------------------------------
# Insert
# --------------------------------------------------------------------------
def test_insert_new_observations(seeded_session: Session, make_observation) -> None:  # type: ignore[no-untyped-def]
    report = _write(
        seeded_session, [make_observation("2023", "5.1"), make_observation("2024", "4.6")]
    )
    assert (report.inserted, report.updated, report.unchanged) == (2, 0, 0)
    assert _count(seeded_session) == 2


def test_stored_row_carries_full_provenance(seeded_session: Session, make_observation) -> None:  # type: ignore[no-untyped-def]
    _write(seeded_session, [make_observation("2024", "4.62473841057141")])
    row = seeded_session.scalar(select(Observation))
    assert row is not None
    assert row.country_id and row.indicator_id and row.source_id
    assert row.source_url
    assert row.retrieved_at.tzinfo is not None
    assert row.content_hash and len(row.content_hash) == 64
    assert row.connector_version == CONNECTOR_VERSION
    assert row.pipeline_version
    assert row.validation_status is ValidationStatus.PASSED


def test_decimal_precision_survives_the_round_trip(
    seeded_session: Session, make_observation
) -> None:  # type: ignore[no-untyped-def]
    """Economic values must never lose precision to float."""
    _write(seeded_session, [make_observation("2024", "4.62473841057141")])
    seeded_session.expire_all()
    row = seeded_session.scalar(select(Observation))
    assert isinstance(row.value_numeric, Decimal)
    assert row.value_numeric == Decimal("4.62473841057141")


def test_tiny_values_survive_the_round_trip(seeded_session: Session, make_observation) -> None:  # type: ignore[no-untyped-def]
    observation = make_observation(
        "1975",
        "2.06064418965517E-9",
        indicator_code="ni_exchange_rate_official_annual_avg",
        source_key="worldbank_ni_exchange_rate",
        unit="NIO per USD",
    )
    _write(seeded_session, [observation])
    seeded_session.expire_all()
    row = seeded_session.scalar(select(Observation))
    assert row.value_numeric == Decimal("2.06064418965517E-9")


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------
def test_rerunning_the_same_batch_inserts_nothing(
    seeded_session: Session, make_observation
) -> None:  # type: ignore[no-untyped-def]
    batch = [make_observation("2023", "5.1"), make_observation("2024", "4.6")]
    _write(seeded_session, batch)
    second = _write(seeded_session, batch)

    assert (second.inserted, second.updated, second.unchanged) == (0, 0, 2)
    assert _count(seeded_session) == 2


def test_idempotent_across_three_runs(seeded_session: Session, make_observation) -> None:  # type: ignore[no-untyped-def]
    batch = [make_observation(str(year), "1.5") for year in range(2015, 2025)]
    for _ in range(3):
        _write(seeded_session, batch)
    assert _count(seeded_session) == 10


def test_later_retrieval_time_alone_is_not_a_revision(
    seeded_session: Session, make_observation
) -> None:  # type: ignore[no-untyped-def]
    _write(seeded_session, [make_observation("2024", "4.6")])
    report = _write(
        seeded_session,
        [make_observation("2024", "4.6", retrieved_at=datetime(2026, 12, 1, tzinfo=UTC))],
    )
    assert report.unchanged == 1
    assert report.updated == 0


def test_trailing_zeros_are_not_a_revision(seeded_session: Session, make_observation) -> None:  # type: ignore[no-untyped-def]
    _write(seeded_session, [make_observation("2024", "4.60")])
    report = _write(seeded_session, [make_observation("2024", "4.6")])
    assert report.unchanged == 1


def test_unchanged_rows_keep_their_timestamps(seeded_session: Session, make_observation) -> None:  # type: ignore[no-untyped-def]
    _write(seeded_session, [make_observation("2024", "4.6")])
    seeded_session.commit()
    original = seeded_session.scalar(select(Observation))
    created_at, updated_at = original.created_at, original.updated_at

    _write(seeded_session, [make_observation("2024", "4.6")])
    seeded_session.commit()
    seeded_session.expire_all()
    row = seeded_session.scalar(select(Observation))
    assert row.created_at == created_at
    assert row.updated_at == updated_at


def test_database_constraint_blocks_duplicate_natural_keys(
    seeded_session: Session, make_observation
) -> None:
    """Idempotency does not rely on the hash alone; the DB enforces it too."""
    _write(seeded_session, [make_observation("2024", "4.6")])
    seeded_session.commit()

    row = seeded_session.scalar(select(Observation))
    seeded_session.add(
        Observation(
            country_id=row.country_id,
            indicator_id=row.indicator_id,
            source_id=row.source_id,
            period_start=row.period_start,
            period_end=row.period_end,
            period_label=row.period_label,
            value_numeric=Decimal("99"),
            unit=row.unit,
            retrieved_at=row.retrieved_at,
            source_url=row.source_url,
            content_hash="0" * 64,
            connector_version="1.0.0",
            pipeline_version="1.0.0",
            raw_metadata={},
        )
    )
    with pytest.raises(IntegrityError):
        seeded_session.flush()


# --------------------------------------------------------------------------
# Revisions
# --------------------------------------------------------------------------
def test_changed_value_is_recorded_as_a_revision(seeded_session: Session, make_observation) -> None:  # type: ignore[no-untyped-def]
    _write(seeded_session, [make_observation("2024", "4.6")])
    report = _write(seeded_session, [make_observation("2024", "4.8")])

    assert (report.inserted, report.updated, report.unchanged) == (0, 1, 0)
    assert _count(seeded_session) == 1


def test_revision_snapshots_the_previous_value(seeded_session: Session, make_observation) -> None:  # type: ignore[no-untyped-def]
    """Nothing is deleted: the old figure stays recoverable."""
    _write(seeded_session, [make_observation("2024", "4.6")])
    _write(seeded_session, [make_observation("2024", "4.8")])

    revision = seeded_session.scalar(select(ObservationRevision))
    assert revision is not None
    assert revision.previous_value_numeric == Decimal("4.6")
    assert revision.new_value_numeric == Decimal("4.8")
    assert revision.revision_number == 1
    assert revision.previous_content_hash != revision.new_content_hash
    assert revision.change_reason


def test_current_row_holds_the_latest_value(seeded_session: Session, make_observation) -> None:  # type: ignore[no-untyped-def]
    _write(seeded_session, [make_observation("2024", "4.6")])
    _write(seeded_session, [make_observation("2024", "4.8")])

    row = seeded_session.scalar(select(Observation))
    assert row.value_numeric == Decimal("4.8")
    assert row.revision_count == 1


def test_multiple_revisions_are_numbered_sequentially(
    seeded_session: Session, make_observation
) -> None:  # type: ignore[no-untyped-def]
    for value in ("4.6", "4.8", "5.0"):
        _write(seeded_session, [make_observation("2024", value)])

    revisions = list(
        seeded_session.scalars(
            select(ObservationRevision).order_by(ObservationRevision.revision_number)
        )
    )
    assert [r.revision_number for r in revisions] == [1, 2]
    assert [r.previous_value_numeric for r in revisions] == [Decimal("4.6"), Decimal("4.8")]
    assert seeded_session.scalar(select(Observation)).revision_count == 2


def test_revision_preserves_created_at(seeded_session: Session, make_observation) -> None:  # type: ignore[no-untyped-def]
    _write(seeded_session, [make_observation("2024", "4.6")])
    seeded_session.commit()
    created_at = seeded_session.scalar(select(Observation)).created_at

    _write(seeded_session, [make_observation("2024", "4.8")])
    seeded_session.commit()
    seeded_session.expire_all()
    assert seeded_session.scalar(select(Observation)).created_at == created_at


def test_revision_links_to_the_pipeline_run(
    seeded_session: Session, make_observation, run_id
) -> None:  # type: ignore[no-untyped-def]
    from reim.core.constants import PipelineStatus
    from reim.database.models import PipelineRun

    now = datetime.now(UTC)
    seeded_session.add(
        PipelineRun(
            id=run_id,
            pipeline_key="worldbank_ni_cpi_inflation",
            started_at=now,
            status=PipelineStatus.RUNNING,
            run_metadata={},
            created_at=now,
        )
    )
    seeded_session.flush()

    _write(seeded_session, [make_observation("2024", "4.6")])
    _write(seeded_session, [make_observation("2024", "4.8")], pipeline_run_id=run_id)

    assert seeded_session.scalar(select(ObservationRevision)).pipeline_run_id == run_id


# --------------------------------------------------------------------------
# Rejection and referential integrity
# --------------------------------------------------------------------------
def test_rejected_observations_are_not_persisted(seeded_session: Session, make_observation) -> None:  # type: ignore[no-untyped-def]
    batch = [make_observation("2023", "5.1"), make_observation("2024", "4.6")]
    report = _write(seeded_session, batch, rejected_indices={1})

    assert (report.inserted, report.rejected) == (1, 1)
    assert _count(seeded_session) == 1
    assert seeded_session.scalar(select(Observation)).period_label == "2023"


def test_validation_status_is_stored_per_observation(
    seeded_session: Session, make_observation
) -> None:  # type: ignore[no-untyped-def]
    batch = [make_observation("2023", "5.1"), make_observation("2024", "4.6")]
    _write(
        seeded_session,
        batch,
        validation_status_by_index={
            0: ValidationStatus.PASSED,
            1: ValidationStatus.PASSED_WITH_WARNINGS,
        },
    )
    statuses = {
        row.period_label: row.validation_status
        for row in seeded_session.scalars(select(Observation))
    }
    assert statuses["2023"] is ValidationStatus.PASSED
    assert statuses["2024"] is ValidationStatus.PASSED_WITH_WARNINGS


def test_unknown_indicator_raises_a_typed_error(seeded_session: Session, make_observation) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(UnknownReferenceError, match="not registered"):
        _write(seeded_session, [make_observation("2024", "1", indicator_code="ni_not_real")])


def test_unknown_source_raises_a_typed_error(seeded_session: Session, make_observation) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(UnknownReferenceError, match="not registered"):
        _write(seeded_session, [make_observation("2024", "1", source_key="not_a_source")])


def test_rollback_discards_the_whole_batch(seeded_session: Session, make_observation) -> None:  # type: ignore[no-untyped-def]
    """A failure mid-load must leave no partial data behind."""
    _write(seeded_session, [make_observation("2023", "5.1")])
    assert _count(seeded_session) == 1

    seeded_session.rollback()
    assert _count(seeded_session) == 0
