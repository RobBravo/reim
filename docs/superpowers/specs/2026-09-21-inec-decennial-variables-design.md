# INEC Panama's decennial variables — a deferred mini-spec

**Status: not ready to implement.** This records what was measured
investigating whether `inec_pa_provincial` should be extended to the two
`Decenal`-frequency variable groups `docs/sources.md` already lists as
excluded. Both need a real product/design decision this note does not make —
it exists so a future session picks up from a measurement, not from
scratch. Everything below was checked against the live API on 2026-09-21.

## Why this exists

The `inec_pa_provincial` connector just gained four new variables (202–205,
construction area and value) in the same row shape as its original three —
a genuinely simple extension. The two remaining excluded items looked, from
`docs/sources.md`'s one-line description ("`Decenal` — not a series"), like
the same kind of simple extension blocked only by `Frequency` having no
value for "once a decade." **That assumption was wrong on inspection**, and
this document is the correction, not a design.

## Investigation 1: `Empresas según naturaleza jurídica` (id 66, and its
percentage twin, id 171)

**Measured:** `GET /data/choropleth?nivel_geografico=Provincia&id_variable=66&anio=2022`
returns **71 rows**, not the clean 11 (10 provinces + 1 national) every
other variable this connector reads produces. Each province is crossed with
**eight legal business types** — `Sociedad anónima`, `Individual/Natural`,
`Cooperativas`, `Sin fines de lucro`, `Sociedad civil`, `Sociedad limitada`,
`Sociedad colectiva`, `Otra` — and each type also carries its own national
total (8 of the 71 rows have `is_total: true`, one per type, not one for the
whole variable).

**The open question this raises, not answers:** modelled at the same
fidelity as everything else REIM stores, this is **eight new indicator
codes**, not one or two — `pa_businesses_corporation_count_provincial_decennial`
and seven siblings. Before writing any of them:

* Is "count of registered businesses by legal type" the kind of statistic
  REIM's catalogue should carry at all? Every other REIM indicator is
  macroeconomic (trade, prices, banking, GDP, now construction activity);
  this is closer to a business-registry statistic. That is a scope
  question for whoever picks this up, not an engineering one.
* If yes: does `Sociedad limitada` (5 provincial rows, not 10 — some
  provinces report none) get stored with the missing provinces simply
  absent, the same "gap is a gap, never filled" rule REIM applies
  everywhere else? Almost certainly yes, but it is worth stating rather
  than assuming when the connector is actually written.
* id 171 is the same eight-way breakdown as a percentage. REIM's existing
  practice (e.g. the automobiles-per-1000 indicator already stores a
  published rate, not a REIM-computed one) suggests storing id 66's raw
  counts and leaving id 171 out — REIM does not need to store both a count
  and its own percentage of the same total — but that too is a decision
  for the implementer, not fixed here.

**Cost of doing nothing:** zero. The item stays in `docs/sources.md`'s
excluded table, which is where the vast majority of measured-but-unused
INEC variables already sit.

## Investigation 2: `Gastos`/`Ingresos de los municipios` (id 210/209)

**Measured:** `GET /data/choropleth?nivel_geografico=Provincia&id_variable=209&anio=2022`
returns **12 area rows plus one national total** — not 10 plus one. The
`id_provincia` values are `01`–`11` then `13`.
`reim/domain/geography/registry.py`'s own `PANAMA_PROVINCES` comment already
names codes `10`–`12` as Panama's three indigenous comarcas, a different
administrative category, and the ten real provinces as `01`–`09` plus `13`.
This response therefore includes **two of the three comarcas** (`10`, `11`)
alongside the ten real provinces, and omits the third (`12`) — not a clean
"comarcas always included" or "always excluded" pattern, an inconsistent
one.

**The existing safety net already works.** The connector's own
`_check_eleven_rows_per_variable` guard — CRITICAL severity, per
`inec_provincial.py` — would reject a 13-row batch outright rather than
silently writing a comarca's spending figure against a province's code, or
dropping it silently. Nothing here is at risk of mis-storing data; the gap
is that nothing here *stores* this data at all yet.

**The open question this raises, not answers:** does REIM want to model
comarcas as their own `AdministrativeArea.level` (the field is already a
free string — `PANAMA_PROVINCES`'s own comment states the schema needs no
change) — or does it continue treating any source whose `Provincia`
response mixes in comarcas as one to filter or exclude, the way every
existing use of this API already does? Modelling comarcas properly also
means deciding how `GET /api/v1/compare` and `/api/v1/observations`'
`administrative_area` filter should treat a third geography level
alongside "province" — untested territory, since only one level exists
today.

**Cost of doing nothing:** zero, same as investigation 1.

## Not decided here, on purpose

* Whether either variable group is worth building at all, given REIM's
  stated macroeconomic focus.
* Whether `Frequency.IRREGULAR` (defined, `FREQUENCY_DAYS` = 3650, never
  yet used by a real connector) is the right tag for either — plausible,
  but moot until the shape questions above are settled.
* Any schema migration, indicator registration, or connector code. None of
  that should be written from this document alone.

## Picking this up later

Start with a fresh brainstorming pass on whichever investigation looks
worth pursuing — each is closer to its own small design decision than to
"add two more dict entries," and conflating them with a future bounded
extension is the mistake this document exists to prevent. Re-verify
`anio_referencia` is still `2022` before trusting anything above unchanged;
a decade is a long time for a census-derived figure to sit still, but it is
not guaranteed to.
