"""Model-level checks that don't need seeded reference data."""

from __future__ import annotations

from reim.database.models import NATURAL_KEY_COLUMNS, AdministrativeArea, Observation


def test_natural_key_columns_includes_administrative_area() -> None:
    assert NATURAL_KEY_COLUMNS == (
        "country_id",
        "indicator_id",
        "source_id",
        "period_start",
        "period_end",
        "administrative_area_id",
    )


def test_administrative_area_id_is_nullable_on_observation() -> None:
    column = Observation.__table__.columns["administrative_area_id"]
    assert column.nullable is True


def test_administrative_area_table_has_the_expected_columns() -> None:
    columns = set(AdministrativeArea.__table__.columns.keys())
    assert columns == {"id", "country_id", "level", "code", "name", "created_at", "updated_at"}
