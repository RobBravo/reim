# Geometry Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give REIM's `Country` and `AdministrativeArea` rows real boundary
geometries, and one endpoint to serve them — the backend half of the modern
web frontend's `/map` view, buildable and testable with no frontend at all.

**Architecture:** Two nullable `JSONB` columns store each row's GeoJSON
geometry. The geometries themselves are pre-simplified, offline-built static
assets checked into the repository (not fetched or computed at runtime), a
small loader module reads them by key, `seed_countries`/
`seed_administrative_areas` attach them the same idempotent way every other
reference field is seeded, and one new endpoint,
`GET /api/v1/geo/boundaries`, serves them as GeoJSON `FeatureCollection`s.

**Tech Stack:** Python 3.12, SQLAlchemy/Alembic, PostgreSQL `JSONB`, FastAPI.
One transient tool used only to build the checked-in assets, never a runtime
dependency: `npx mapshaper` (Node is already on any machine with `npm`/`npx`
available — this does not add a Python or Node dependency to the project
itself).

**Spec:** `docs/superpowers/specs/2026-09-21-modern-web-frontend-design.md`,
§4 ("Geographic boundaries"). This plan implements that section only — no
frontend code, no Next.js, nothing under `frontend/`.

## Global Constraints

- The gate, from the repository root, is
  `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q`.
  Integration tests need `REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim`
  (start it with `make db-up CONTAINER_ENGINE=podman` if not already running).
- No Docker daemon; use `podman`. No `pip` in `.venv`; use `.venv/bin/<tool>`.
- Geometries are `JSONB` GeoJSON **geometry** objects only (`Polygon` /
  `MultiPolygon`) — never a `Feature`, and never include the name/ISO
  metadata a `Feature`'s `properties` would carry, since every existing
  column already has that (spec §4, decision D4/D5).
- No PostGIS. Nothing in this plan issues a spatial query — see spec D5.
- The two boundary asset files are built **once, offline**, with the exact
  commands this plan gives, and checked in as static files — never
  regenerated or fetched at application runtime (spec §4).
- Country geometries: [Natural Earth](https://www.naturalearthdata.com)
  admin-0, public domain, no attribution required. Panama's ten province
  geometries: [geoBoundaries.org](https://www.geoboundaries.org) (ODbL,
  sourced from OpenStreetMap) — **this one needs attribution**, which
  Task 2 records in a checked-in `README.md` beside the asset. Both sources
  and this choice are the spec's own deferred decision D6, resolved here
  with live measurements (§ Task 2 below), not assumed.
- Follow this codebase's existing patterns exactly: `reim/database/models/reference.py`
  for the two model changes, `reim/repositories/reference.py` for lookups,
  `apps/api/routers/countries.py` for the router shape, and
  `reim/services/seeding.py` for how a reference field gets attached
  idempotently.

---

### Task 1: The migration

**Files:**
- Modify: `reim/database/models/reference.py`
- Create: one new file under `alembic/versions/`
- Test: `tests/unit/test_database_models.py`

**Interfaces:**
- Produces: `Country.geometry_geojson: dict[str, Any] | None`,
  `AdministrativeArea.geometry_geojson: dict[str, Any] | None` — both read
  directly as ORM attributes by Task 3 (seeding) and Task 4 (the API).

- [ ] **Step 1: Add the two columns to the models**

In `reim/database/models/reference.py`, add `Any` to the existing
`from typing import TYPE_CHECKING` line (`from typing import TYPE_CHECKING, Any`)
and add `JSONB` to the existing postgres dialect import (currently
`from sqlalchemy.dialects.postgresql import UUID` — change to
`from sqlalchemy.dialects.postgresql import JSONB, UUID`).

In the `Country` class (currently lines 29-48), add one column, immediately
after `is_active`:

```python
    #: GeoJSON Geometry (Polygon/MultiPolygon) for this country's outline, or
    #: None if not yet recorded. Never a Feature — every other field a
    #: Feature's properties would carry already exists on this row. Built
    #: offline; see reim/domain/geography/boundaries/README.md.
    geometry_geojson: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
```

In the `AdministrativeArea` class (currently lines 51-75), add the same
column, immediately after `name`:

```python
    #: GeoJSON Geometry (Polygon/MultiPolygon) for this area's outline, or
    #: None if not yet recorded. Same shape and provenance as
    #: Country.geometry_geojson.
    geometry_geojson: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
```

- [ ] **Step 2: Write a failing structural test**

In `tests/unit/test_database_models.py`, add:

```python
def test_country_and_administrative_area_carry_a_nullable_geometry_column() -> None:
    """A model-level guard: the column exists, is JSONB, and defaults to nullable.

    Catches a future migration or model edit that silently drops or narrows
    this column, before any database round-trip test would.
    """
    from sqlalchemy.dialects.postgresql import JSONB

    from reim.database.models import AdministrativeArea, Country

    for model in (Country, AdministrativeArea):
        column = model.__table__.columns["geometry_geojson"]
        assert isinstance(column.type, JSONB)
        assert column.nullable is True
```

Read the existing tests in this file first for the exact import shape this
project uses for `Country`/`AdministrativeArea` (both come from
`reim.database.models`, the package `__init__.py`, not the `reference`
submodule directly) before adding this test alongside them.

**This file also already has an exact-columns guard test that the new
column breaks** — confirmed by actually running it, not assumed:
`test_administrative_area_table_has_the_expected_columns` asserts the
literal set of `AdministrativeArea.__table__.columns.keys()`. Update it in
the same step, or Step 3 below will show one unrelated-looking failure
alongside the expected one:

```python
def test_administrative_area_table_has_the_expected_columns() -> None:
    columns = set(AdministrativeArea.__table__.columns.keys())
    assert columns == {
        "id",
        "country_id",
        "level",
        "code",
        "name",
        "geometry_geojson",
        "created_at",
        "updated_at",
    }
```

(There is no equivalent exact-columns test for `Country` in this file —
confirmed by grepping `has_the_expected_columns` and
`__table__.columns.keys()` across it — so `Country`'s side of Step 1 needs
no matching update here.)

- [ ] **Step 3: Run the tests to verify the new one fails**

```bash
.venv/bin/pytest tests/unit/test_database_models.py -v
```

Expected: the new test `FAIL`s with `AttributeError` or `KeyError` — the
column does not exist yet on the actual table metadata until Step 1's model
change is picked up. The updated `test_administrative_area_table_has_the_expected_columns`
also fails at this point, for the same reason — both failures are expected
together. (If Step 1 is already done by the time you reach this step, skip
ahead — this is written TDD-ordered for a fresh implementer, not a hard
requirement to break something first.)

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_database_models.py -v
```

Expected: every test in the file passes, including both touched above.

- [ ] **Step 5: Generate and edit the Alembic migration**

```bash
.venv/bin/alembic revision --autogenerate -m "add geometry_geojson"
```

This creates a new file under `alembic/versions/`. Open it and confirm the
generated `upgrade()` adds exactly two columns (`countries.geometry_geojson`,
`administrative_areas.geometry_geojson`), both `postgresql.JSONB`, both
`nullable=True`, and nothing else. It should look like:

```python
def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        "administrative_areas",
        sa.Column("geometry_geojson", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "countries",
        sa.Column("geometry_geojson", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("countries", "geometry_geojson")
    op.drop_column("administrative_areas", "geometry_geojson")
    # ### end Alembic commands ###
```

If autogenerate produced anything else (a type change, an index, a
different table), stop and re-check Step 1 before proceeding — it means the
model change did not match what this step expects.

- [ ] **Step 6: Verify the migration round-trips against a real database**

```bash
make db-up CONTAINER_ENGINE=podman   # if not already running
REIM_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/alembic upgrade head
REIM_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/alembic downgrade -1
REIM_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/alembic upgrade head
```

Expected: all three commands exit 0, no errors. (This uses the dev database
on port 55432, not the ephemeral `reim_test` schema the test suite creates
and drops on its own — running this does not affect `pytest`.)

- [ ] **Step 7: Full gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps
REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
```

```bash
git add reim/database/models/reference.py alembic/versions/*_add_geometry_geojson.py \
  tests/unit/test_database_models.py
git commit -m "feat(schema): add geometry_geojson to Country and AdministrativeArea"
```

---

### Task 2: The boundary assets

**Files:**
- Create: `reim/domain/geography/boundaries/countries.geojson`
- Create: `reim/domain/geography/boundaries/panama_provinces.geojson`
- Create: `reim/domain/geography/boundaries/README.md`
- Create: `reim/domain/geography/geometry.py`
- Test: `tests/unit/test_geometry_assets.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `load_country_geometry(iso2: str) -> dict[str, Any] | None` and
  `load_administrative_area_geometry(code: str) -> dict[str, Any] | None`,
  both in `reim.domain.geography.geometry` — Task 3 calls these directly.

This task builds two small, real, already-measured assets. Every command
below was run for real while writing this plan; the exact byte counts and
feature names are what were actually produced, not estimates.

- [ ] **Step 1: Build `countries.geojson`**

```bash
mkdir -p reim/domain/geography/boundaries
curl -sL --max-time 60 \
  "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/ca96624a56bd078437bca8184e78163e5039ad19/geojson/ne_50m_admin_0_countries.geojson" \
  -o /tmp/ne_countries_50m.geojson
```

Verify it downloaded (world file, all countries):

```bash
python3 -c "import json; print(len(json.load(open('/tmp/ne_countries_50m.geojson'))['features']))"
```

Expected: `177`.

Filter to REIM's seven countries and strip every property except `iso2`:

```bash
python3 -c "
import json
d = json.load(open('/tmp/ne_countries_50m.geojson'))
by_admin = {f['properties']['ADMIN']: f for f in d['features']}
wanted = {
    'Nicaragua': 'NI', 'Guatemala': 'GT', 'El Salvador': 'SV',
    'Honduras': 'HN', 'Costa Rica': 'CR', 'Panama': 'PA', 'Belize': 'BZ',
}
out = {'type': 'FeatureCollection', 'features': []}
for admin_name, iso2 in wanted.items():
    f = by_admin[admin_name]
    out['features'].append({
        'type': 'Feature',
        'properties': {'iso2': iso2},
        'geometry': f['geometry'],
    })
assert len(out['features']) == 7
json.dump(out, open('/tmp/ca7_bare.geojson', 'w'))
print('wrote', len(out['features']), 'features')
"
```

Expected: `wrote 7 features`.

Simplify with `mapshaper` (pinned version — this is a one-time build tool,
never a project dependency):

```bash
npx --yes mapshaper@0.6.117 -i /tmp/ca7_bare.geojson -simplify 10% -o reim/domain/geography/boundaries/countries.geojson format=geojson
```

Verify the result:

```bash
wc -c reim/domain/geography/boundaries/countries.geojson
python3 -c "
import json
d = json.load(open('reim/domain/geography/boundaries/countries.geojson'))
print(sorted(f['properties']['iso2'] for f in d['features']))
"
```

Expected: file size close to `3449` bytes (mapshaper's simplification is
deterministic for a given input and version, so this should match closely,
not necessarily to the byte — if it differs by more than a few percent,
re-check the input file matches the pinned commit above before trusting the
output). Second command expected: `['BZ', 'CR', 'GT', 'HN', 'NI', 'PA', 'SV']`.

- [ ] **Step 2: Build `panama_provinces.geojson`**

```bash
curl -sL --max-time 30 \
  "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/PAN/ADM1/geoBoundaries-PAN-ADM1_simplified.geojson" \
  -o /tmp/pan_adm1.geojson
python3 -c "import json; print(len(json.load(open('/tmp/pan_adm1.geojson'))['features']))"
```

Expected: `13` (Panama's ten provinces plus three indigenous comarcas —
`reim/domain/geography/registry.py`'s own `PANAMA_PROVINCES` comment already
documents that comarcas share this "Provincia"/`ADM1` level in third-party
data and must be filtered out).

Exclude the three comarcas by name and map each remaining province's
`shapeName` to REIM's own province code (`reim/domain/geography/registry.py`'s
`PANAMA_PROVINCES` — read that file now to confirm these ten codes/names
have not changed since this plan was written):

```bash
python3 -c "
import json
d = json.load(open('/tmp/pan_adm1.geojson'))
comarcas = {'Comarca Emberá-Wounaan', 'Comarca Guna Yala', 'Comarca Ngäbe-Buglé'}
name_to_code = {
    'Provincia de Bocas del Toro': '01',
    'Provincia de Coclé': '02',
    'Colón Province': '03',
    'Provincia de Chiriquí': '04',
    'Provincia de Darién': '05',
    'Provincia de Herrera': '06',
    'Provincia de Los Santos': '07',
    'Provincia de Panamá': '08',
    'Provincia de Veraguas': '09',
    'Provincia de Panamá Oeste': '13',
}
out = {'type': 'FeatureCollection', 'features': []}
seen = set()
for f in d['features']:
    name = f['properties']['shapeName']
    if name in comarcas:
        continue
    code = name_to_code[name]  # raises KeyError if geoBoundaries renamed something
    seen.add(code)
    out['features'].append({
        'type': 'Feature',
        'properties': {'code': code},
        'geometry': f['geometry'],
    })
assert seen == {'01', '02', '03', '04', '05', '06', '07', '08', '09', '13'}, seen
json.dump(out, open('/tmp/pan_provinces_bare.geojson', 'w'))
print('wrote', len(out['features']), 'features')
"
```

Expected: `wrote 10 features`. If this raises `KeyError`, geoBoundaries
changed a `shapeName` since this plan was written — fetch the raw file and
compare names before editing the mapping blind.

Simplify (a higher reduction than the countries file — Panama's provinces
came in far more detailed, and a choropleth at this scale does not need
that density):

```bash
npx --yes mapshaper@0.6.117 -i /tmp/pan_provinces_bare.geojson -simplify 5% -o reim/domain/geography/boundaries/panama_provinces.geojson format=geojson
```

Verify:

```bash
wc -c reim/domain/geography/boundaries/panama_provinces.geojson
python3 -c "
import json
d = json.load(open('reim/domain/geography/boundaries/panama_provinces.geojson'))
print(sorted(f['properties']['code'] for f in d['features']))
"
npx --yes mapshaper@0.6.117 -i reim/domain/geography/boundaries/panama_provinces.geojson -info
```

Expected: file size close to `19377` bytes; codes
`['01', '02', '03', '04', '05', '06', '07', '08', '09', '13']`; the `-info`
command reports `Records: 10`, `Type: polygon`, and a bounding box roughly
`-83.05, 7.20` to `-77.17, 9.63` (Panama's real extent) with no error or
warning lines. A bounding box far outside that range, or an error/warning
from `-info`, means something went wrong upstream — do not proceed to the
next step with a suspect file.

- [ ] **Step 3: Write the provenance README**

Create `reim/domain/geography/boundaries/README.md`:

```markdown
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
```

- [ ] **Step 4: Write the geometry loader**

Create `reim/domain/geography/geometry.py`:

```python
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
```

- [ ] **Step 5: Write the structural tests**

Create `tests/unit/test_geometry_assets.py`:

```python
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
```

- [ ] **Step 6: Run the tests**

```bash
.venv/bin/pytest tests/unit/test_geometry_assets.py -v
```

Expected: all pass. If `test_every_registered_country_has_a_geometry` or
`test_every_panama_province_has_a_geometry` fails, Step 1 or Step 2's build
produced a file missing an entry — re-check the filter/mapping step, not
the loader or the test.

- [ ] **Step 7: Full gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps
REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
```

```bash
git add reim/domain/geography/boundaries/countries.geojson \
  reim/domain/geography/boundaries/panama_provinces.geojson \
  reim/domain/geography/boundaries/README.md \
  reim/domain/geography/geometry.py \
  tests/unit/test_geometry_assets.py
git commit -m "feat(geography): add checked-in boundary geometry assets and loader"
```

---

### Task 3: Seeding

**Files:**
- Modify: `reim/services/seeding.py`
- Modify: `tests/integration/test_persistence.py`

**Interfaces:**
- Consumes: `load_country_geometry`, `load_administrative_area_geometry`
  from Task 2.
- Produces: nothing new — `Country.geometry_geojson` and
  `AdministrativeArea.geometry_geojson` become populated as a side effect of
  `reim db seed` / `seed_all`, which Task 4's API endpoint then reads.

- [ ] **Step 1: Write the failing tests**

In `tests/integration/test_persistence.py`, add these two tests near
`test_seed_creates_administrative_areas` (read that test and
`test_seed_creates_reference_data` first — this follows their exact
`seeded_session` fixture pattern):

```python
def test_seeded_countries_carry_a_geometry(seeded_session: Session) -> None:
    countries = seeded_session.scalars(select(Country)).all()
    assert countries
    for country in countries:
        assert country.geometry_geojson is not None, country.iso2
        assert country.geometry_geojson["type"] in ("Polygon", "MultiPolygon")


def test_seeded_administrative_areas_carry_a_geometry(seeded_session: Session) -> None:
    from reim.database.models import AdministrativeArea

    areas = seeded_session.scalars(select(AdministrativeArea)).all()
    assert areas
    for area in areas:
        assert area.geometry_geojson is not None, area.code
        assert area.geometry_geojson["type"] in ("Polygon", "MultiPolygon")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim \
  .venv/bin/pytest tests/integration/test_persistence.py -k geometry -v
```

Expected: both `FAIL`, `geometry_geojson is None` — seeding does not attach
it yet.

- [ ] **Step 3: Wire the loader into seeding**

In `reim/services/seeding.py`, add the import:

```python
from reim.domain.geography.geometry import load_administrative_area_geometry, load_country_geometry
```

In `seed_countries` (currently lines 76-95), add `geometry_geojson` to the
`values` dict, immediately after `is_active`:

```python
        values = {
            "iso3": definition.iso3,
            "name": definition.name,
            "name_local": definition.name_local,
            "region": definition.region,
            "currency_code": definition.currency_code,
            "currency_name": definition.currency_name,
            "is_active": definition.is_active,
            "geometry_geojson": load_country_geometry(definition.iso2),
        }
```

In `seed_administrative_areas` (currently lines 132-161), add
`geometry_geojson` to its `values` dict, alongside `name`:

```python
        values = {
            "name": definition.name,
            "geometry_geojson": load_administrative_area_geometry(definition.code),
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim \
  .venv/bin/pytest tests/integration/test_persistence.py -k geometry -v
```

Expected: both `PASS`.

- [ ] **Step 5: Run the full persistence suite to confirm nothing else broke**

```bash
REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim \
  .venv/bin/pytest tests/integration/test_persistence.py -v
```

Expected: every test passes, including
`test_seed_is_idempotent`/`test_administrative_area_seeding_is_idempotent` —
`_sync`'s field-by-field comparison already handles a dict-valued field with
no changes needed, but this confirms it rather than assuming it.

- [ ] **Step 6: Full gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps
REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
```

```bash
git add reim/services/seeding.py tests/integration/test_persistence.py
git commit -m "feat(geography): attach boundary geometries during seeding"
```

---

### Task 4: The API endpoint

**Files:**
- Create: `apps/api/routers/geo.py`
- Modify: `apps/api/main.py`, `reim/repositories/reference.py`
- Test: `tests/integration/test_api.py`

**Interfaces:**
- Consumes: `Country.geometry_geojson`, `AdministrativeArea.geometry_geojson`
  (Task 1/3), `reim.repositories.reference.list_countries` (existing).
- Produces: `GET /api/v1/geo/boundaries?level=country|administrative_area` —
  the exact endpoint the frontend's `/map` view (a separate, future plan)
  will call.

- [ ] **Step 1: Add a repository lookup for administrative areas with geometry**

`reim/repositories/reference.py` already has `list_countries`
(lines 66-71). Add, near it:

```python
def list_administrative_areas(session: Session) -> list[AdministrativeArea]:
    """Return every administrative area, ordered by name."""
    return list(session.scalars(select(AdministrativeArea).order_by(AdministrativeArea.name)))
```

(`AdministrativeArea` is already imported at the top of this file — check
before adding a duplicate import.)

- [ ] **Step 2: Write the failing router tests**

Confirmed before writing this plan: no file in `tests/integration/` imports
the `client` fixture across module boundaries — every test file that needs
it defines its own copy. Follow that same convention: add these four tests
directly into `tests/integration/test_api.py`, near `test_list_countries`
(currently around line 97), using the `client` fixture already defined in
that file (around line 23) — do not create a new test module or a
cross-module fixture import for this.

```python
def test_country_level_returns_a_feature_per_registered_country(client: TestClient) -> None:
    body = client.get("/api/v1/geo/boundaries", params={"level": "country"}).json()

    assert body["type"] == "FeatureCollection"
    iso2_codes = {feature["properties"]["iso2"] for feature in body["features"]}
    assert iso2_codes == {"NI", "GT", "SV", "HN", "CR", "PA", "BZ"}
    for feature in body["features"]:
        assert feature["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_administrative_area_level_returns_panamas_ten_provinces(client: TestClient) -> None:
    body = client.get("/api/v1/geo/boundaries", params={"level": "administrative_area"}).json()

    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 10
    codes = {feature["properties"]["code"] for feature in body["features"]}
    assert codes == {"01", "02", "03", "04", "05", "06", "07", "08", "09", "13"}


def test_an_unsupported_level_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/geo/boundaries", params={"level": "district"})
    assert response.status_code == 422


def test_the_response_carries_a_long_cache_control_header(client: TestClient) -> None:
    response = client.get("/api/v1/geo/boundaries", params={"level": "country"})
    assert "max-age=" in response.headers["cache-control"]
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim \
  .venv/bin/pytest tests/integration/test_api.py -v
```

Expected: every pre-existing test in the file still passes; the four new
ones from Step 2 `FAIL` with a `404` — the route does not exist yet.

- [ ] **Step 4: Write the router**

Create `apps/api/routers/geo.py`:

```python
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
```

- [ ] **Step 5: Register the router**

In `apps/api/main.py`, the router imports are one multi-line, alphabetically
ordered statement (currently lines 19-28):

```text
from apps.api.routers import (
    comparison,
    countries,
    indicators,
    observations,
    organizations,
    pipelines,
    sources,
    system,
)
```

Add `geo` to that same statement, keeping alphabetical order (it sorts
before `indicators`):

```text
from apps.api.routers import (
    comparison,
    countries,
    geo,
    indicators,
    observations,
    organizations,
    pipelines,
    sources,
    system,
)
```

Add the registration, alongside the existing `app.include_router(...)`
calls (currently lines 143-150):

```python
    app.include_router(geo.router)
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim \
  .venv/bin/pytest tests/integration/test_api.py -v
```

Expected: every test in the file passes, including the four new ones.

- [ ] **Step 7: Confirm this endpoint is covered by the existing rate-limit guard**

`LIMITED_PREFIX = "/api/v1"` in `apps/api/middleware.py:48` already covers
any route under that prefix, with no special case needed — verify this
holds rather than assuming it:

```bash
REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim \
  .venv/bin/pytest tests/unit/test_ratelimit.py tests/integration/test_rate_limiting.py -v
```

Expected: all pass, unchanged — this step adds no new test, it confirms the
existing rate-limit test suite still passes with a new `/api/v1` route
present, since some of those tests may enumerate real routes.

- [ ] **Step 8: Full gate**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps
REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
```

Expected: everything clean, full suite passed count up by exactly 11 tests
over this plan's own additions (1 in Task 1, 4 in Task 2, 2 in Task 3, 4 in
Task 4).

- [ ] **Step 9: Commit**

```bash
git add reim/repositories/reference.py apps/api/routers/geo.py apps/api/main.py \
  tests/integration/test_api.py
git commit -m "feat(api): serve country and administrative-area boundary geometries"
```

## Deliberately not in this plan

* **The frontend that consumes this endpoint.** `/map`'s own plan, separate
  and downstream of this one — see the spec's §5 page table.
* **The self-hosted PMTiles basemap** (spec §4, D3). A separate, unrelated
  asset (the visual background, not REIM's own data) — its own small task
  inside the frontend scaffold plan, not this backend one.
* **District (`Corregimiento`)-level geometries.** No REIM data exists at
  that level (see `docs/sources.md`'s INEC Panama section, "measured, not
  merely unexplored") — nothing to draw yet.
* **A second country's subnational geometries.** Only Panama has
  administrative areas today; `load_administrative_area_geometry`'s own
  docstring already states what a second country's addition would need.
* **Caching this endpoint's response in Redis, a CDN, or anywhere beyond
  the `Cache-Control` header.** The header alone is the whole mechanism —
  optimizing further has no measurement asking for it yet.

## Done when

* `Country` and `AdministrativeArea` both carry a nullable `geometry_geojson`
  `JSONB` column, migrated and round-tripped.
* Every one of REIM's seven countries and Panama's ten provinces has a real,
  plausible-coordinate geometry after `reim db seed`, pinned by a guard test
  that fails loudly on a gap rather than shipping a silent one.
* `GET /api/v1/geo/boundaries?level=country` and `?level=administrative_area`
  both return valid GeoJSON `FeatureCollection`s, cached long, under the
  existing rate limiter, with no new special case.
* `reim/domain/geography/boundaries/README.md` states each asset's exact
  source, licence and build command — including the ODbL attribution
  Panama's provinces require, which this plan's own ingestion did not
  previously need for anything REIM stores.
* The full gate passes: `ruff check`, `ruff format --check`, `mypy reim apps`,
  `pytest -q`.
