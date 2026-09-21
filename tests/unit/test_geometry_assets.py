"""Structural checks on the checked-in boundary geometry assets.

These do not touch a database — they load the files directly, the same way
reim.domain.geography.geometry does, and check the assets are internally
consistent with the registries they are meant to match.
"""

from __future__ import annotations

from typing import Any

from reim.domain.countries.registry import COUNTRIES
from reim.domain.geography.geometry import load_administrative_area_geometry, load_country_geometry
from reim.domain.geography.registry import PANAMA_PROVINCES


def test_every_registered_country_has_a_geometry() -> None:
    for country in COUNTRIES:
        geometry = load_country_geometry(country.iso2)
        assert geometry is not None, f"{country.iso2} has no boundary geometry"
        assert geometry["type"] in ("Polygon", "MultiPolygon")


def test_every_panama_province_has_a_geometry() -> None:
    for province in PANAMA_PROVINCES:
        geometry = load_administrative_area_geometry(province.code)
        assert geometry is not None, f"{province.code} ({province.name}) has no geometry"
        assert geometry["type"] in ("Polygon", "MultiPolygon")


def test_an_unregistered_code_returns_none_not_a_raise() -> None:
    """The loader is a lookup, not a validator — Task 3's seeding step is
    where a missing geometry becomes a caught, asserted condition."""
    assert load_country_geometry("ZZ") is None
    assert load_administrative_area_geometry("99") is None


def test_country_geometry_coordinates_are_plausible_lat_lon() -> None:
    """A loose sanity bound, not a precise bbox check: catches a geometry
    accidentally built in projected (non-degree) coordinates, which would
    have values far outside [-180, 180] / [-90, 90]."""

    def _flatten(coords: Any) -> list[float]:
        if isinstance(coords, (int, float)):
            return [coords]
        flat: list[float] = []
        for item in coords:
            flat.extend(_flatten(item))
        return flat

    for country in COUNTRIES:
        geometry = load_country_geometry(country.iso2)
        assert geometry is not None
        flat = _flatten(geometry["coordinates"])
        lons = flat[0::2]
        lats = flat[1::2]
        assert all(-180 <= lon <= 180 for lon in lons), country.iso2
        assert all(-90 <= lat <= 90 for lat in lats), country.iso2
