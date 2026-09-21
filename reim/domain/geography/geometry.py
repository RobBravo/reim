"""Loads the pre-built boundary geometries under boundaries/.

Both files are static, offline-built assets — see boundaries/README.md for
their exact source, licence and how they were produced. Nothing here
fetches or computes a geometry at runtime.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_BOUNDARIES_DIR = Path(__file__).parent / "boundaries"


@lru_cache(maxsize=1)
def _country_geometries() -> dict[str, dict[str, Any]]:
    payload = json.loads((_BOUNDARIES_DIR / "countries.geojson").read_text(encoding="utf-8"))
    return {feature["properties"]["iso2"]: feature["geometry"] for feature in payload["features"]}


@lru_cache(maxsize=1)
def _panama_province_geometries() -> dict[str, dict[str, Any]]:
    payload = json.loads((_BOUNDARIES_DIR / "panama_provinces.geojson").read_text(encoding="utf-8"))
    return {feature["properties"]["code"]: feature["geometry"] for feature in payload["features"]}


def load_country_geometry(iso2: str) -> dict[str, Any] | None:
    """Return the GeoJSON geometry for a country, or None if not recorded."""
    return _country_geometries().get(iso2)


def load_administrative_area_geometry(code: str) -> dict[str, Any] | None:
    """Return the GeoJSON geometry for an administrative area, or None if not recorded.

    Keyed by code alone: every administrative area REIM tracks today is one
    of Panama's ten provinces, so no country qualifier is needed yet. A
    second country's subnational geometries would need this function (and
    panama_provinces.geojson's own shape) to also key on country, at the
    same time that country's own AdministrativeAreaDefinition entries are
    added to the registry.
    """
    return _panama_province_geometries().get(code)
