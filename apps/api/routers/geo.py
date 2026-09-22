"""Boundary geometry endpoints for the map view.

Serves the checked-in geometries Task 2/3 attached to Country and
AdministrativeArea rows at seed time — this router never computes or
fetches a geometry itself.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Response

from apps.api.dependencies import SessionDep
from reim.repositories.reference import list_administrative_areas, list_countries

router = APIRouter(prefix="/api/v1/geo", tags=["geo"])

#: One year, matching this data's own practical update cadence (never, in
#: practice — a country's or a province's outline does not move). Far
#: longer than any indicator response's cache policy, deliberately: this is
#: the one REIM response whose content is not expected to change between
#: requests at all.
_CACHE_CONTROL = "public, max-age=31536000, immutable"


@router.get("/boundaries", summary="Boundary geometries for the map view")
def boundaries(
    session: SessionDep,
    response: Response,
    level: Annotated[
        Literal["country", "administrative_area"],
        Query(description="Which geometry level to return."),
    ],
) -> dict[str, Any]:
    """Return a GeoJSON FeatureCollection of boundary geometries.

    Each Feature carries only its geometry and the join key a caller needs
    to match it to indicator data (``iso2`` for countries, ``code`` for
    administrative areas) — never the full metadata ``/countries`` or a
    future administrative-area listing endpoint already provides.

    At ``administrative_area`` level, ``code`` alone is a safe join key only
    because every administrative area REIM tracks today is one of Panama's
    ten provinces; a second country's subnational areas would need this
    response to carry a country qualifier too (see
    ``reim.domain.geography.geometry.load_administrative_area_geometry``).
    """
    response.headers["Cache-Control"] = _CACHE_CONTROL

    if level == "country":
        features = [
            {
                "type": "Feature",
                "properties": {"iso2": country.iso2},
                "geometry": country.geometry_geojson,
            }
            for country in list_countries(session)
            if country.geometry_geojson is not None
        ]
    else:
        features = [
            {
                "type": "Feature",
                "properties": {"code": area.code},
                "geometry": area.geometry_geojson,
            }
            for area in list_administrative_areas(session)
            if area.geometry_geojson is not None
        ]

    return {"type": "FeatureCollection", "features": features}
