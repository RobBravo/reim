# Boundary geometry assets

Static, offline-built GeoJSON assets. Never fetched or regenerated at
application runtime — loaded by `reim/domain/geography/geometry.py` and
attached to `Country`/`AdministrativeArea` rows at seed time.

## `countries.geojson`

Seven of REIM's countries, one `Feature` each, `properties: {"iso2": ...}`,
geometry only (no name, no other metadata — every other field already
exists on the `Country` row).

- **Source:** Natural Earth admin-0 countries, 1:50m resolution, via
  <https://github.com/nvkelso/natural-earth-vector>, commit
  `ca96624a56bd078437bca8184e78163e5039ad19`.
- **Licence:** Public domain. No attribution required.
- **Built:** 2026-09-21. Filtered to REIM's seven countries by `ADMIN` name,
  stripped to `iso2` + geometry, simplified with
  `npx mapshaper@0.6.117 -simplify 10%`.

## `panama_provinces.geojson`

Panama's ten provinces (REIM's own province set — see
`reim/domain/geography/registry.py`'s `PANAMA_PROVINCES`), one `Feature`
each, `properties: {"code": ...}` matching REIM's own province codes.

- **Source:** [geoBoundaries.org](https://www.geoboundaries.org),
  boundary ID `PAN-ADM1-82927092`, sourced from OpenStreetMap
  (`wambachers-osm.website/boundaries/`).
- **Licence:** Open Data Commons Open Database License 1.0 (ODbL) —
  **attribution required.** Map or page using this data:
  "Contains data from geoBoundaries.org and OpenStreetMap contributors,
  ODbL 1.0."
- **Built:** 2026-09-21. The raw file carries 13 areas (ten provinces plus
  three indigenous comarcas); the three comarcas
  (`Comarca Emberá-Wounaan`, `Comarca Guna Yala`, `Comarca Ngäbe-Buglé`) were
  excluded and the remaining ten `shapeName`s mapped to REIM's own province
  codes by name, then simplified with
  `npx mapshaper@0.6.117 -simplify 5%`.

## Regenerating either file

Both were built with the exact commands recorded in
`docs/superpowers/plans/2026-09-21-geometry-backend.md`, Task 2. Re-run them
against a fresh source fetch only if REIM's country set or Panama's province
codes change — not on a schedule, since neither source publishes updates on
one.
