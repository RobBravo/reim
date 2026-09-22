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


def _coordinate_pairs(coordinates: Any) -> list[tuple[float, float]]:
    """Flatten any GeoJSON coordinate nesting down to (lon, lat) pairs."""
    if coordinates and isinstance(coordinates[0], (int, float)):
        return [(coordinates[0], coordinates[1])]
    pairs: list[tuple[float, float]] = []
    for item in coordinates:
        pairs.extend(_coordinate_pairs(item))
    return pairs


def _bounding_box(geometries: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    """Return the combined (min_lon, min_lat, max_lon, max_lat) of several geometries."""
    pairs = [pair for geometry in geometries for pair in _coordinate_pairs(geometry["coordinates"])]
    lons = [lon for lon, _ in pairs]
    lats = [lat for _, lat in pairs]
    return min(lons), min(lats), max(lons), max(lats)


def _part_count(geometry: dict[str, Any]) -> int:
    """Number of polygons in a geometry — 1 for a Polygon, N for a MultiPolygon."""
    return 1 if geometry["type"] == "Polygon" else len(geometry["coordinates"])


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
    for country in COUNTRIES:
        geometry = load_country_geometry(country.iso2)
        assert geometry is not None
        pairs = _coordinate_pairs(geometry["coordinates"])
        assert all(-180 <= lon <= 180 for lon, _ in pairs), country.iso2
        assert all(-90 <= lat <= 90 for lat in (lat for _, lat in pairs)), country.iso2


#: Vertex floor per country outline. Deliberately far below what the asset
#: actually carries (58-227 vertices, measured), so normal source drift never
#: trips it — but far above the 8-27 vertices an over-aggressive
#: ``-simplify 10%`` build once produced, which is the regression this pins.
_MINIMUM_COUNTRY_VERTICES = 40

#: Polygon-count floor for the three countries whose territory is genuinely
#: multipart in the source (BZ 3, HN 3, PA 5 — measured against the pinned
#: Natural Earth commit). Floors, not exact counts, so a marginally different
#: source revision does not fail; but every one of these was silently
#: collapsed to a single polygon by the old build, which dropped Honduras's
#: Islas de la Bahía and Swan Islands, Belize's cayes and atolls and four of
#: Panama's five island groups.
_MINIMUM_COUNTRY_PARTS = {"BZ": 2, "HN": 2, "PA": 3}


def test_country_geometries_retain_their_source_detail() -> None:
    """Guards against a rebuild that simplifies away real national territory.

    Neither the ``type`` check nor the lat/lon bound above notices a country
    that lost half its land: both pass for an 8-vertex triangle. These two
    floors do not.
    """
    for country in COUNTRIES:
        geometry = load_country_geometry(country.iso2)
        assert geometry is not None
        vertices = len(_coordinate_pairs(geometry["coordinates"]))
        assert vertices >= _MINIMUM_COUNTRY_VERTICES, f"{country.iso2} has only {vertices} vertices"
        expected_parts = _MINIMUM_COUNTRY_PARTS.get(country.iso2, 1)
        parts = _part_count(geometry)
        assert parts >= expected_parts, (
            f"{country.iso2} has {parts} polygon part(s), expected at least "
            f"{expected_parts} — island territory was probably dropped "
            f"(mapshaper needs its 'keep-shapes' flag)"
        )


#: How far Panama's province union may fall outside Panama's own country
#: outline, in degrees. Not zero, and it cannot be: the two assets come from
#: different datasets (OpenStreetMap vs Natural Earth 1:50m) whose coastlines
#: disagree by up to 0.033° — measured against a completely *unsimplified*
#: Natural Earth extract, so no simplification setting removes it. This bound
#: sits above that inherent disagreement and well below the 0.112° overhang
#: the old ``-simplify 10%`` build produced, which was a real, visible defect:
#: provinces drawn sticking out past their own country's border.
_PROVINCE_OVERHANG_TOLERANCE_DEGREES = 0.05


def test_panama_provinces_stay_within_panamas_country_outline() -> None:
    """The two assets must agree about where Panama is.

    They are built from different sources at different resolutions, so a
    country outline simplified harder than the province layer beside it
    renders as provinces spilling over their own national border. This pins
    that gap to dataset noise.
    """
    country = load_country_geometry("PA")
    assert country is not None
    provinces = [load_administrative_area_geometry(province.code) for province in PANAMA_PROVINCES]
    assert all(geometry is not None for geometry in provinces)

    country_box = _bounding_box([country])
    province_box = _bounding_box([geometry for geometry in provinces if geometry is not None])
    tolerance = _PROVINCE_OVERHANG_TOLERANCE_DEGREES

    assert province_box[0] >= country_box[0] - tolerance, "provinces reach too far west"
    assert province_box[1] >= country_box[1] - tolerance, "provinces reach too far south"
    assert province_box[2] <= country_box[2] + tolerance, "provinces reach too far east"
    assert province_box[3] <= country_box[3] + tolerance, "provinces reach too far north"
