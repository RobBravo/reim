# REIM's modern web frontend — design

Replaces every server-rendered page REIM has shipped (`apps/web`) with a
statically-exported React application: an interactive map, polished
time-series charts, and the same catalog/observability views, none of it
server-rendered. `apps/api` — the JSON contract, the rate limiter, the
provenance guarantees — is untouched.

This reopens a decision this project made twice before and is explicit about
what that costs. Everything measured below was checked against the repository
on 2026-09-21.

## 1. Why this exists, and what it costs

The web-catalog-browser design's **D1** ("server-rendered, no build step, no
JavaScript") and the time-series-dashboard design's **D1** ("server-rendered
SVG, no JavaScript, no charting library") both gave the same rationale: a
vendored charting or mapping library sits oddly in a self-hostable project,
and a build step is a dependency an operator on a restricted network cannot
satisfy.

Both decisions are reopened here, on purpose, because the actual product goal
changed: a smooth, WebGL-panned map with a choropleth REIM colors by
indicator, and interactive charts, are not achievable by drawing more SVG on
the server — the interactivity itself is the point, not a rendering detail
server-side cleverness can supply. [`osirisai.live`](https://osirisai.live)
(repo: `github.com/simplifaisoul/osiris`) is the reference for the *quality*
of that interaction, not for its OSINT subject matter — Osiris tracks live
flights, ships and cameras over WebSocket; REIM publishes periodic official
statistics and has no real-time data at all. What actually transfers from its
`package.json` is three libraries, not the product: `maplibre-gl` (WebGL
vector maps), `lightweight-charts` (TradingView's charting library), and
`tailwindcss` for styling. `hls.js`, `satellite.js`, `react-force-graph-2d`
and `ws` — all genuinely load-bearing for Osiris's live feeds — have no REIM
use and are not adopted.

**What this actually costs:** REIM's web pages will no longer render on a
browser with JavaScript disabled, and a first-time visitor's browser now
executes third-party code (React, MapLibre) it did not before. **What is not
lost:** the deployment stays self-hostable and free of a third-party runtime
dependency — §3 keeps Next.js entirely out of production (no Node process to
run), and §4 keeps the map's own basemap self-hosted rather than pulled from
a paid tiles API at request time. Self-hostability is preserved in a
different shape, not abandoned.

`apps/api` is not part of either reopened decision and does not change its
JSON contract, its rate limiting, or its provenance guarantees for this work
— see §7 for the one addition to it.

## 2. What is removed, what is added

| Removed | Kept unchanged |
|---|---|
| `apps/web/routes.py` (5 routes: `/`, `/runs`, `/runs/{run_id}`, `/series`, catalog at `/`) | `apps/api/*` — every `/api/v1/...` endpoint, its schemas, its rate limiter |
| `apps/web/templates/*.html` (7 Jinja2 templates) | `reim/*` — ingestion, domain, quality, repositories |
| `apps/web/charts.py` (server-side SVG geometry) | `deploy/docker-compose.prod.yml`'s `postgres` and `api` services |

| Added | Purpose |
|---|---|
| `frontend/` — a new top-level Next.js project | The replacement UI, §5 |
| `Country.geometry_geojson`, `AdministrativeArea.geometry_geojson` — two new nullable columns | Map boundaries, §4 |
| `GET /api/v1/geo/boundaries` | Serves those boundaries, §4 |
| A self-hosted PMTiles basemap asset | The map's background, §4 |

`apps/web`'s dependency on Jinja2 templating (`fastapi.templating`,
`Jinja2Templates`) is removed from `apps/api/main.py` — no other route uses
it, confirmed by grep across `apps/`.

## 3. Architecture

```
                    Caddy (unchanged site: reim.panda.home.arpa)
  /api/*, /health, /ready  ──────────►  apps/api (FastAPI — unchanged)
  /metrics                 ──────────►  404 (unchanged)
  everything else          ──────────►  file_server, root = the Next.js
                                          static export
```

Next.js runs `next build` with static export **only at image-build time**.
No Node process exists in the running deployment — Caddy serves the output
directory the same way it already serves any static file, and the browser
makes ordinary `fetch()` calls to `apps/api` for every piece of data: the
map's boundaries and indicator values, the series charts, the catalog, the
run history. There is no server-side rendering per request and no API
proxying through Next.js.

This changes both deployment shapes REIM documents:

* **`deploy/docker-compose.prod.yml`** (the generic guide): its `caddy`
  service's image gains a build stage that also runs the frontend build and
  `COPY`s the static output in; `deploy/Caddyfile`'s catch-all `handle` block
  gains a `root` + `file_server` alongside its existing `reverse_proxy
  api:8000` (only for paths the API does not own — the exact split needs a
  `handle` per prefix, detailed in the implementation plan, not invented
  here).
* **panda** (`docs/deployment-panda.md`): simpler, since Caddy there is
  native. The static export lands in a new directory under
  `/srv/containers/reim/` (e.g. `frontend-dist/`), and
  `/etc/caddy/sites/reim.caddy` gains a `root` + `file_server` block beside
  its existing `reverse_proxy 127.0.0.1:8000`. Redeploying the frontend means
  rebuilding and replacing that directory's contents, no container restart
  required for the frontend half.

## 4. Geographic boundaries

**Data model.** One nullable column, `geometry_geojson` (`JSONB`), added to
`Country` (`reim/database/models/reference.py:29`) and to
`AdministrativeArea` (`:51`). It stores a GeoJSON `Geometry` object
(`Polygon`/`MultiPolygon`) only — not a `Feature` — because every other field
a `Feature`'s `properties` would carry (name, ISO code, region) already lives
on the row. This is the first `JSONB` column in the schema; every existing
custom type (`EconomicNumeric`, the value-persisting enum in
`reim/database/types.py`) exists for a numeric or enumerated value, none for
a document. No PostGIS: nothing here issues a spatial query (REIM never asks
"which country contains this point"), only serves a stored shape for the
frontend to draw — the extension would add operational surface for zero
query benefit.

**Sourcing — one settled, one to measure, not assume.** Countries: [Natural
Earth](https://www.naturalearthdata.com) admin-0 boundaries, public domain,
no attribution required — the same openness bar REIM already holds every
connector to. Panama's ten provinces: **not decided here.** Two candidates —
Natural Earth's own admin-1 layer (if its Panama coverage and precision hold
up) and Panama's official geoportal (Instituto Geográfico Nacional Tommy
Guardia) — get compared for actual coverage and licence before either is
picked, the same measure-before-trusting discipline every REIM connector
already gets. This is implementation-plan work, not a spec decision.

**Simplification is offline, once, not a runtime concern.** Raw admin-0
boundaries run into megabytes; a 17-shape choropleth (7 countries visible
today, plus Panama's provinces) does not need that precision. Simplified with
a tool such as `mapshaper`, the output is checked into the repository as a
versioned asset — the same treatment a connector's test fixture gets, not
something computed by the running application.

**Serving.** `GET /api/v1/geo/boundaries?level=country|administrative_area`
returns a GeoJSON `FeatureCollection`. Each `Feature`'s `properties` carries
only the join key the frontend needs to match a shape to indicator data —
`iso2`/`iso3` for countries, the area's `id` for administrative areas — never
the full metadata `GET /api/v1/countries` already provides. It sits under
`/api/v1`, so `LIMITED_PREFIX` (`apps/api/middleware.py:48`) already covers
it under the existing rate limiter with no special case, and it ships with a
long `Cache-Control` — boundaries do not change between requests the way an
indicator value can.

**Guard test.** Every `Country` and every `AdministrativeArea` that carries
at least one real observation must have a stored geometry — so the map never
silently renders a gap where REIM actually holds data.

**Sourcing the basemap, not just the boundaries.** The map's visual
background (coastlines, other countries, ocean, labels — everything that
makes it look like a map rather than 17 floating shapes) is a separate
concern from the boundaries above, and does not belong to REIM's own data at
all. A live third-party tile API (Mapbox, MapTiler) would reintroduce exactly
the third-party runtime dependency §1 argues self-hostability survives
without. Instead: a single self-hosted [PMTiles](https://protomaps.com)
basemap asset, served as a static file beside the frontend build, read
directly by MapLibre with no server component and no API key. Same
self-hosted, no-third-party-at-runtime property as the boundaries endpoint,
applied to the basemap instead.

## 5. The frontend

**Location.** `frontend/`, a new top-level directory, `package.json` and
`tsconfig.json` at its root.

**Stack.** Next.js (static export output), React, TypeScript, Tailwind CSS,
`maplibre-gl` + `react-map-gl`, `lightweight-charts`, `framer-motion`, and
one addition not present in Osiris's own dependency list: **TanStack Query**
(or SWR), to give every page the same loading/error/cache handling around
`fetch()` rather than five hand-rolled copies of it — the same
justification-per-dependency bar `maplibre-gl` and `lightweight-charts`
already clear, applied to a fourth library that does one concrete job.

**Pages (v1 is full parity with today's five routes, plus the map):**

| Route | Replaces | Content |
|---|---|---|
| `/` | catalog's root (`apps/web/routes.py:161`) | Landing: what REIM holds, entry points into the other views |
| `/map` | — (new) | Choropleth: countries and Panama's provinces, coloured by a chosen indicator and period, MapLibre-rendered over the self-hosted basemap (§4) |
| `/series` | `/series` (`:437`) | One indicator over time, multiple countries, `lightweight-charts` instead of server-drawn SVG |
| `/catalog` | catalog (`:161`) | Sources, organizations, frequency, licence — same content, new rendering |
| `/runs`, `/runs/{run_id}` | `/runs`, `/runs/{run_id}` (`:256`, `:281`) | Pipeline observability — lower visual priority than the other four, still in scope |

**Data fetching is entirely client-side.** No server component fetches data
at build time or per-request; static export means there is no server at
request time to do so. Every page is a client component that calls
`apps/api` directly through TanStack Query, the browser's normal same-origin
`fetch()` (Caddy serves both the static site and, under `/api`, the API — no
CORS configuration is needed for this because both share one origin).

**Two rules this frontend inherits rather than re-derives, both already
settled by the time-series-dashboard design:**

* **Overlay only when `comparable` and `levels_comparable` are both true**
  (`assess_comparability`, `reim/schemas/comparison.py:45`, and
  `levels_comparable`, `:23`); small multiples otherwise. This is `/compare`
  and `/series`'s own existing logic, unchanged — the new frontend calls the
  same API and must draw the same conclusion the old page did, not invent a
  new rule because the chart library changed.
* **A country whose own series crosses a unit change is not charted at
  all** — its own axis cannot rescue a line that lies within a single
  country, the reasoning the dashboard design already recorded.

**Empty and error states are not optional polish.** The current dashboard
distinguishes nine distinct states on `/series` alone (database unreachable,
indicator not found, country not found, valid selection with no data, mixed
data availability, non-comparable data, a unit-changing country, an
over-large range, first visit with no selection yet) — see the time-series
dashboard design §6. Every page in the new frontend needs its own explicit
loading, empty, and error states; "the API call failed" rendering as a blank
screen is a regression this spec explicitly rules out.

**Testing.** Vitest and React Testing Library for components (the MapLibre
wrapper, the chart wrapper, anything that reimplements the two rules above on
the client); `tsc --noEmit` and `eslint` as the equivalent gate to
`mypy`/`ruff` on the Python side.

## 6. Visual design

**Theme:** an institutional dark palette — deep navy-black backgrounds
(`#0f1720`/`#132234`), a gold/amber accent (`#e8b84b`) for interactive and
active-data elements, humanist (not monospaced) typography. Chosen over a
literal "tactical/OSINT" cyan-on-black reskin of Osiris and over a light
"public portal" theme — closer to Osiris's interaction quality, but reads as
an official statistics platform rather than a monitoring console.

**`/map`'s layout:** the map fills the viewport; the indicator/period
selector and the selected country's mini chart are floating, collapsible
panels over it, not a fixed side panel or a stacked layout. Chosen for the
immersive, map-first feel over always-visible-panel alternatives that were
also mocked up and rejected.

**Navigation:** one consistent top bar across all five pages/routes, same
theme, linking `/`, `/map`, `/series`, `/catalog`, `/runs`. The two more
tabular pages (`/catalog`, `/runs`) keep the same palette with less
floating/overlaid chrome — they are read, not explored.

## 7. Build and CI changes

**`Dockerfile`** gains a frontend build stage (a pinned `node:<LTS>-slim`
image — the exact tag is an implementation-time choice, pinned the same way
`caddy:2.11.4-alpine` is pinned rather than floated, not decided here) whose
`npm ci && npm run build` output is the static export directory; the runtime
stage's `apps/api` image is otherwise unchanged (still no Node in the image
that actually runs `uvicorn`). Where that static output lands for Caddy to
serve is a deployment-shape decision, not a spec decision — §3 covers both
shapes this repository documents.

**CI** gains one job, parallel to the existing `quality` and `test` jobs, not
gating either: `npm ci && tsc --noEmit && eslint && vitest run && next
build`. The existing `docker` job (`.github/workflows/ci.yml`) already
exercises the full multi-stage `Dockerfile` build, so it structurally
includes the frontend build once §7's Dockerfile change lands; the new job
exists to fail fast and cheaply before that heavier build runs, the same
relationship `quality` already has to `test` and `docker`.

## 8. Decisions

| | Decision | Rationale |
|---|---|---|
| **D1** | Reopen the catalog-browser and dashboard designs' own D1 ("no JavaScript, no build step") | The interactivity goal (WebGL map, polished charts) cannot be delivered by more server-rendered SVG; §1 states plainly what this costs and what is deliberately preserved instead |
| **D2** | Next.js runs only at build time; static export, no Node process in production | Keeps the no-third-party-runtime-dependency property alive in a different shape — Caddy serves static files the same way it serves anything else (§3) |
| **D3** | The map's basemap is a self-hosted PMTiles asset, not a live third-party tiles API | A paid or free-tier tile service at request time reintroduces exactly the runtime dependency D2 avoids; PMTiles is a static file MapLibre reads directly (§4) |
| **D4** | REIM stores and serves its own country/administrative-area boundary geometries, separately from the basemap | The actual data REIM visualizes (17 shapes) is tiny, needs to be tied to REIM's own primary keys for coloring, and matches how REIM already curates its own reference data (§4) |
| **D5** | Geometry is a plain `JSONB` column, no PostGIS | Nothing in REIM issues a spatial query; PostGIS would add an extension for a capability nothing here uses (§4) |
| **D6** | Panama's provincial boundary source is measured during implementation, not chosen here | The same measure-before-trusting discipline every REIM connector already gets — Natural Earth admin-1 vs. Panama's official geoportal, decided on actual coverage and licence (§4) |
| **D7** | `apps/web` is deleted outright, not kept behind a flag or as a fallback | The brainstorming session's own explicit choice: full replacement, not an additional interface alongside the old one |
| **D8** | Full parity with today's five routes plus the new map, for v1 | The brainstorming session's own explicit scope choice — not a narrower "map-only" proof of concept |
| **D9** | Data fetching is entirely client-side against the existing `apps/api`; no SSR, no Next.js API routes | Every genuinely interactive view (the map, `/compare`'s combinatorial country selection) needs client-side JavaScript regardless, so SSR would add an operational process for no benefit not already available statically (§3, §5) |
| **D10** | The comparability rule (`comparable` and `levels_comparable`) and the unit-change exclusion rule carry over from the time-series-dashboard design unchanged | Two already-settled, carefully-reasoned decisions about what a shared axis is allowed to imply — a new chart library is not a reason to re-derive them (§5) |

## 9. Out of scope

* **Any real-time feature** — websockets, live feeds, anything Osiris does
  that depends on data REIM does not have. REIM's data is periodic official
  statistics; nothing here pretends otherwise.
* **Server-side rendering / a Next.js server process in production** (D9).
* **New geospatial data.** This spec visualizes whatever `AdministrativeArea`
  and `Country` rows already exist or are separately added by the geospatial
  roadmap item (district-level Panama, INEC's other variables) — it does not
  ingest new indicators itself.
* **A design-system package, Storybook, or component library** beyond what
  these five pages need directly.
* **Any change to `apps/api`'s existing endpoints** beyond the new
  `/api/v1/geo/boundaries` (§4). Rate limiting, authentication, and every
  existing response shape are untouched.
* **A native mobile app.** The static export is a responsive web app, not a
  packaged app of any kind.
* **Currency conversion on the new `/series`.** Out of scope for the same
  reason the time-series dashboard design gave it (D8 there): differing
  currencies already route to small multiples, which is the honest
  rendering; adding it back in is a separate increment, not a side effect of
  a redesign.
