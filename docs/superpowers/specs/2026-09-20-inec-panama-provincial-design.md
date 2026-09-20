# REIM's first subnational data — design

Provincial-level economic figures from INEC Panama, and with them REIM's first
geographic dimension below the country. This is v0.6.0's geospatial line,
narrowed to the one route already measured: `docs/sources.md`'s "INEC Panama"
entry (probed 2026-09-11).

Everything measured below was re-verified against the live API on 2026-09-20,
fetched at least twice per endpoint and confirmed identical.

## 1. What exists, and what this adds

REIM's `Observation` table has exactly one geographic dimension:
`country_id`. No table anywhere in the schema models anything below a
country. `docs/sources.md` recorded INEC Panama as "reachable and open, not
ingested" for exactly this reason — its data is provincial, not national, and
`anio=2023` is the only populated year for most variables (a cross-section,
not a series).

This increment adds:

- A new reference table, `administrative_areas`, and a nullable FK from
  `Observation` onto it — REIM's first geography below `Country`.
- One connector reading three INEC variables at provincial level.
- The `/compare` fix this makes necessary (§4).

**Not in this increment:** district (`Corregimiento`) level, the Decenal
(census-derived) variables, and any country besides Panama. See §7.

## 2. Scope: three variables, ten provinces, one country

### 2.1 Why these three variables

INEC's catalogue (`GET /meta/estructura-completa`, 218 variables) has 25 under
its `Económica` theme. Most of those are `frecuencia_actualizacion: Decenal`
— tied to the population census, next due ~2033. A `Decenal` variable is not
meaningfully a series REIM can track; it is one more cross-section, the same
defect that keeps the rest of the catalogue out.

A `Provincia`-level, genuinely `Anual` cluster exists under `Industriales` and
`Transporte`:

| id | Name | Unit | Category |
|---|---|---|---|
| 232 | Automóviles en circulación por cada 1000 habitantes | automóviles | Transporte |
| 206 | Cantidad de edificaciones residenciales | unidades | Industriales |
| 207 | Cantidad de edificaciones no residenciales | unidades | Industriales |

All three: `GET /data/choropleth?nivel_geografico=Provincia&id_variable={id}&anio=2023`,
verified `200`, 11 rows, identical on a repeat fetch. None duplicates data
REIM already holds (Panama's GDP is already stored nationally from CEPALSTAT;
these are not GDP).

**Excluded, and recorded in `docs/sources.md` rather than silently dropped:**
`Empresas según naturaleza jurídica` (id 66/171) and municipal revenue/expense
(`Gastos`/`Ingresos de los municipios`, id 210/209) — the variables closest to
the sources doc's original "businesses" and "municipal revenue and spending"
language, both genuinely `Decenal`. Construction *area* and *value* (id
202–205) are also `Anual` and `Provincia`-level and are reasonable second-cut
candidates, left out here to keep the first connector to three variables.

### 2.2 The response shape already separates national from provincial

Each `/data/choropleth` response for a given variable and year is **11 rows**:
10 carry a real `id_provincia` (`"01"`–`"09"`, then `"13"` — not a contiguous
1–10 sequence) and `is_total: false`; the 11th carries `id_provincia: null`
and `is_total: true`, holding Panama's national figure for that variable and
year.

This is the connector's natural split: the `is_total` row becomes the
national observation (`administrative_area_id = NULL`, the same as every
observation REIM stores today); the ten `is_total: false` rows become
provincial observations. One request therefore yields both a national and a
provincial figure — the national one is new data too (REIM's existing GDP
aside, it holds no other Panama figure from INEC).

The exact `id_provincia → province name` mapping is not resolved by this
design and is deferred to implementation, where it will be pinned against a
verified fixture (rule 7 of `docs/sources.md`'s "Rules for adding a source"),
the same way every other connector's mapping has been. What matters for this
spec is the shape: a closed set of 10 codes, stable across variables (the
same 10 codes appear for all three variables probed), which is what
`AdministrativeArea` and its guard test (§6) depend on.

## 3. Data model

### 3.1 `AdministrativeArea`

A new reference table, following the shape of every other reference entity in
`reim/database/models/reference.py` (`Country`, `Organization`, `DataSource`):

```python
class AdministrativeArea(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A geographic subdivision below the country level.

    REIM's first geography below ``Country``. ``level`` names the kind of
    subdivision ("province" today); ``code`` is the publisher's own
    identifier, kept verbatim rather than re-derived, so a connector's fixture
    and REIM's stored row are traceably the same thing.
    """

    __tablename__ = "administrative_areas"

    country_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("countries.id", ondelete="RESTRICT"), nullable=False
    )
    level: Mapped[str] = mapped_column(String(40), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    country: Mapped[Country] = relationship(back_populates="administrative_areas")
    observations: Mapped[list[Observation]] = relationship(back_populates="administrative_area")

    __table_args__ = (
        UniqueConstraint("country_id", "level", "code", name="uq_administrative_area_natural_key"),
        Index("ix_administrative_areas_country_id", "country_id"),
    )
```

### 3.2 `Observation` gains one nullable column

```python
administrative_area_id: Mapped[uuid.UUID | None] = mapped_column(
    UUID(as_uuid=True), ForeignKey("administrative_areas.id", ondelete="RESTRICT")
)
```

`NATURAL_KEY_COLUMNS` (`reim/database/models/observation.py:33`) extends to
`(country_id, indicator_id, source_id, period_start, period_end,
administrative_area_id)`. `NULL` keeps meaning "national" — every existing
row and every existing source is unaffected, since `NULL` sorts as a single
value for uniqueness purposes and no current source ever sets this column.

`Country` gains the matching `administrative_areas: Mapped[list[AdministrativeArea]]`
relationship, and `Observation` gains
`administrative_area: Mapped[AdministrativeArea | None] = relationship(back_populates="observations")`
alongside its existing `country`/`indicator`/`source` relationships.

One Alembic migration carries all of it.

### 3.3 The pipeline runner and `NormalizedObservation`

`NormalizedObservation` (`reim/domain/pipelines/models.py:48`) currently
resolves geography through `country_iso3` alone. It gains one optional field:

```python
administrative_area_code: str | None = None
```

**Correction (this spec's own self-review caught a contradiction here — the
first draft said the runner creates an `AdministrativeArea` on first sight,
while §6 already specified a guard test that *rejects* an unrecognized code.
The static-registry approach below is the one that actually holds, and
matches how `Country` and `Organization` are already done — see D7a.)**

`AdministrativeArea` is a static reference table, seeded the same way
`Country` and `Organization` are: a frozen-dataclass registry
(`reim/domain/geography/registry.py`, new — `AdministrativeAreaDefinition`,
mirroring `CountryDefinition` in `reim/domain/countries/registry.py`),
materialised by `reim db seed`. The ten rows for Panama's provinces are data
written once during implementation (§2.2's still-to-be-confirmed code→name
mapping lands here), not created at ingestion time.

`reim/repositories/reference.py` gains `require_administrative_area_by_code(session, country_id, level, code)`,
matching the shape of `require_country_by_iso3` / `require_indicator_by_code`
/ `require_source_by_key` it sits beside — raises if the code is not seeded,
exactly like its siblings. `reim/services/observation_writer.py`'s
`_ReferenceCache` (`reim/services/observation_writer.py:74`) gains an
`administrative_areas` cache dict and an `administrative_area()` lookup
method following the existing `country()` / `indicator()` / `source()`
pattern exactly, called from `write_observations()` only when
`incoming.administrative_area_code is not None`. An unrecognized code raises
the same way a source publishing for an unregistered country already does —
this *is* §6's "closed set" guard test, not a separate mechanism.

**Only `NormalizedObservation.natural_key`** (`reim/domain/pipelines/models.py:83`,
and its module-level counterpart `reim.domain.observations.hashing.natural_key`)
folds in `administrative_area_code`. This is what
`reim/domain/quality/checks.py:100`'s in-batch duplicate check
(`Counter(obs.natural_key for obs in observations)`) uses to catch
accidental duplicates *within one connector run* — without the change, ten
provincial rows sharing a country/indicator/source/period would count as
ten duplicates of the same key and the standard quality battery would flag
the whole batch. `compute_content_hash`/`content_hash()` need **no
change**: it is only ever compared against a single already-identified row
returned by `get_by_natural_key` (§3.3 below, extended with
`administrative_area_id`), so which row that is is the lookup's job, not
the hash's — folding identity into a value hash would blur the distinction
this module's own docstring draws between the two.

`reim/repositories/observations.py:168`'s `get_by_natural_key` gains an
`administrative_area_id: uuid.UUID | None = None` parameter, added to its
`where(...)` clause, and `observation_writer.py`'s `_build_observation`
(`reim/services/observation_writer.py:207`) sets
`administrative_area_id=area.id if area else None` on the row it builds.

## 4. `/compare` must not see subnational rows

`fetch_comparison_cells` (`reim/repositories/comparison.py:113`) selects one
`value_numeric` per `(country, period)` for the requested indicator, with no
aggregation and no deduplication — it assumes that pair is unique. It is,
today, because nothing sets `administrative_area_id`. The moment an indicator
carries provincial rows, the same country and period appear once per
province, and the query silently returns however many rows collide into
whatever the consuming code does with them — the exact class of defect this
project's guard tests exist to catch before it ships.

There is no fix on the indicator-naming side: giving provincial and national
observations different indicator codes would work, but then a province's
figure could never share an indicator code with another province's, which
defeats storing them as the same concept at different geographic
resolutions. The fix is in `/compare` itself, since `/compare` is
inherently a national concept — there is no single "Panama" figure to place
beside another country's when the indicator is genuinely provincial, so a
subnational row has nothing correct to do there regardless.

**Fix:** every query in `reim/repositories/comparison.py` that reads
`Observation` gains `Observation.administrative_area_id.is_(None)`. A
provincial observation is invisible to `/compare`, and always was for every
indicator that has none — this is a no-op change for the entire existing
catalog.

**Guard test:** plant a provincial `Observation` for a country/indicator pair
already exercised by an existing `/compare` test, confirm the comparison
response is unchanged (same cell count, same value) and does not error or
silently duplicate.

`/api/v1/observations` needs no equivalent restriction — it is a general
filtered listing, not a per-country matrix, and returning provincial rows
alongside national ones is correct there. It gains:

- `ObservationRead` (`reim/schemas/observations.py`): an optional
  `administrative_area` field (`code` + `name`), null for national rows.
- `observation_filters()` (`apps/api/routers/observations.py:28`): an
  optional `administrative_area` query parameter (matches `code`), and a
  documented default — unset returns both national and provincial rows,
  matching this endpoint's existing "no implicit narrowing" behaviour for
  every other filter.

Nothing in the web dashboard (`/series`) or catalog browser changes; neither
reads these new indicators unless a later increment points them there.

## 5. Connector

`reim/ingestion/connectors/panama/inec_provincial.py`, one `BaseConnector`
covering all three variables (§2.1) — the same "one source, several
indicators" shape as most existing connectors (e.g. the CEPALSTAT family).

`extract()`: **four requests**, corrected from an earlier draft of this
section that said three and did not account for discovering the year. One
`GET {base_url}/meta/estructura-completa` (the catalogue, 94 KB, needs no
parameters) to read each of the three variables' current `anio_referencia`
— not hardcoded to 2023 past this point, so a future INEC republication is
picked up without a code change, the same principle SIECA's connector
already applies to its quarter window. Then one
`GET {base_url}/data/choropleth?nivel_geografico=Provincia&id_variable={id}&anio={year}`
per variable, using that variable's own discovered year (they are not
guaranteed to move together, though they do today).

`transform()`: for each response row, the `is_total: true` row becomes a
`NormalizedObservation` with `administrative_area_code=None`; each
`is_total: false` row becomes one with `administrative_area_code=id_provincia`.
The row's own province name is carried in `raw_metadata` for provenance —
resolution against the seeded `AdministrativeArea` registry (§3.3) is by
code, not by this name, and an unrecognized code is what makes
`require_administrative_area_by_code` raise. `unidad_medida` from the row
maps to `unit` directly — INEC's own unit strings, not re-derived.

`validate()`: `min_observations` per variable is 11 (10 provinces + 1
national) per run — a run that returns fewer is either a partial response or
a province the closed set (§2.2) doesn't recognize, and either should reject
rather than silently store a partial picture.

### 5.1 Catalog and registry entries

- `reim/domain/geography/registry.py` (new module): `AdministrativeAreaDefinition`
  (mirrors `CountryDefinition` — `country_iso2`, `level`, `code`, `name`) and
  a `PANAMA_PROVINCES` tuple of ten entries, seeded by `reim db seed`
  alongside `COUNTRIES` and `ORGANIZATIONS` (§3.3).
- `reim/domain/sources/organizations.py`: one new `OrganizationDefinition`,
  `code="INEC_PA"`, `organization_type=OrganizationType.STATISTICS_OFFICE` —
  the same type already used for INIDE
  (`reim/domain/sources/organizations.py:48`), REIM's other national
  statistics office — `country_iso2="PA"`.
- `sources/catalog.yml`: one new entry, `country: PA`, `organization:
  INEC_PA`, `frequency: annual`, `format: json`, the three indicator codes.
- `reim/domain/indicators/registry.py`: three new `IndicatorDefinition`s,
  codes following the existing `{country_iso2_lower}_{concept}_{qualifier}`
  convention (e.g. `pa_automobiles_per_1000_provincial_annual`),
  `currency_convertible=False` for the vehicle-count and building-count
  indicators (none are currency amounts).

## 6. Testing

Per `docs/sources.md`'s "Rules for adding a source" (rule 7): real fixtures.
The three `/data/choropleth` responses fetched for this design (§2.1) are
verified, reproducible, and become the connector's transform-test fixtures
directly — no synthetic data.

New guard tests, beyond the connector's own transform tests:

- **`/compare` excludes subnational rows** (§4) — the load-bearing new test.
- **The extended natural key actually prevents a duplicate**: the same
  indicator, period and province landing twice is one row with a revision,
  not two rows.
- **A national and a provincial observation for the same indicator and
  period coexist**: `administrative_area_id IS NULL` and a real UUID for the
  same `(country, indicator, source, period)` are different rows, not a
  collision.
- **The province code set is closed**: `require_administrative_area_by_code`
  (§3.3) raises for a code that was not seeded, the same way an observation
  for an unregistered country already fails loudly rather than silently
  minting one — the same "reject the unrecognized shape" instinct as
  `test_only_a_real_assignment_line_counts_as_documentation` and similar
  guard tests elsewhere in this codebase.

### 6.1 Freshness

`sources/quality_rules.yml` gets a `freshness_max_age_days` for the three new
indicators set loose and the reasoning documented inline — INEC's own
declared cadence is `Anual` but the actual republication interval is
unconfirmed (only one year has ever been observed). This is a disclosure, not
a new mechanism: the field already exists and every other source's threshold
is already tuned by hand.

## 7. Decisions

| | Decision | Rationale |
|---|---|---|
| **D1** | New `AdministrativeArea` table + nullable FK, not a denormalized string column on `Observation` | Matches every other reference entity's shape in this schema (`Country`, `Organization`, `DataSource`); a free-text region field has no canonical list and cannot be validated (§3.1) |
| **D2** | `NULL` `administrative_area_id` means "national", unchanged for every existing row | Zero migration cost for the existing catalog; no source today sets this column |
| **D3** | `/compare` filters `administrative_area_id IS NULL` rather than giving provincial data separate indicator codes | `/compare` has no correct behaviour for a provincial row regardless of naming — there is no single national figure to place beside another country's; separate codes would also stop a province and the nation sharing one concept (§4) |
| **D4** | Province-level only, no district (`Corregimiento`) this increment | Keeps the geography question to one new table and one level; district is a strict refinement of the same design, not a different one, and can be added by widening `level` later |
| **D5** | Three `Anual` variables (vehicles, residential/non-residential building counts), not the `Decenal` "businesses"/"municipal finance" ones the sources doc originally named | A `Decenal` variable is a cross-section republished roughly once a decade — not meaningfully a series REIM tracks — while the chosen three are genuinely annual and provably exercise the new shape end-to-end (§2.1) |
| **D6** | The connector reads both the `is_total` and provincial rows from one request | The response already carries both; skipping the national row would throw away data the same request already paid for (§2.2) |
| **D7** | Exact `id_provincia → name` mapping resolved during implementation, not in this spec | The code set (10 values) is confirmed stable across all three variables probed; the specific mapping is an implementation fixture question, not a design one (§2.2) |
| **D7a** | `AdministrativeArea` is a seeded static registry (`require_*`, raises on an unknown code), not created on first sight during ingestion | Matches `Country`/`Organization`'s existing pattern exactly, and is the only reading consistent with §6's own "closed set" guard test — the first draft of §3.3 said "create on first sight," which directly contradicted that test; caught in this spec's self-review (§3.3) |

## 8. Out of scope

- **District (`Corregimiento`) level.** `AdministrativeArea.level` is
  designed to carry it later without a schema change beyond a new row shape,
  but no district data is ingested here.
- **The `Decenal` variables** (business counts, municipal revenue/spending,
  legal-nature breakdown). Recorded in `docs/sources.md` as measured but not
  stored, with the reason (§2.1).
- **Construction area/value** (id 202–205). Same shape as the chosen three,
  reasonable second-cut candidates, left out to keep this connector to three
  variables.
- **Any other country's subnational data.** No second source is known; the
  `AdministrativeArea` design does not assume one, but does not require
  Panama-specific code either (`country_id` is a real FK).
- **Web dashboard or catalog-browser changes.** Neither surface points at
  these indicators; a later increment that wants to visualize provincial
  data (e.g. a choropleth on `/series`) is its own design.
- **INEC's `Corregimiento`-level socio-demographic variables** (radio/phone
  ownership, income, etc.) — not economic data, out of REIM's scope
  regardless of geographic level.
