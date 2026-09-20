"""Structural checks on the administrative-area registry."""

from __future__ import annotations

from reim.domain.geography.registry import ADMINISTRATIVE_AREAS, PANAMA_PROVINCES


def test_panama_has_exactly_ten_provinces() -> None:
    assert len(PANAMA_PROVINCES) == 10


def test_every_province_code_is_unique() -> None:
    codes = [p.code for p in PANAMA_PROVINCES]
    assert len(codes) == len(set(codes))


def test_every_province_belongs_to_panama_at_province_level() -> None:
    for province in PANAMA_PROVINCES:
        assert province.country_iso2 == "PA"
        assert province.level == "province"


def test_administrative_areas_is_the_registry_of_record() -> None:
    assert ADMINISTRATIVE_AREAS == PANAMA_PROVINCES
