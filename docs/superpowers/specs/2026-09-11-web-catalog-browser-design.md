# REIM's first web page — design

The catalog browser, and with it the skeleton every later page will reuse:
server-rendered HTML inside the existing FastAPI application, answering *what
REIM holds, how fresh it is, and what is disabled and why*.

This is v0.4.0's first increment and the project's first piece of work that is
not a connector. Everything measured below was checked against the repository
on 2026-09-11.

## 1. What exists, and what this adds

REIM has **no front end at all**: eight API routers, no templates, no static
files, no `package.json`. Its data is reachable only by someone who already
knows how to construct an HTTP request and read JSON.

The API is not the gap. Measured, it already serves everything this page needs:

| Endpoint | What it gives |
|---|---|
| `GET /api/v1/pipelines` | Every pipeline with its last run, volumes and freshness |
| `GET /api/v1/sources` | The catalog entries, paginated, with detail |
| `GET /api/v1/indicators` | The 63 indicator definitions |
| `GET /api/v1/system/stats` | Aggregate counters and last ingestion time |

So this increment is front end, not back end. It adds one page and the
skeleton — templates, layout, static assets, routing, a test approach — that
the pipeline-observability page and the time-series dashboard will reuse.

**One roadmap correction rides along.** v0.4.0's first bullet, making
`methodology_varies_by_country` machine-readable, was completed on 2026-09-11
and is still listed as pending. It is marked done as part of this work.

## 2. Architecture

### 2.1 One application, two surfaces

`apps/web/` beside `apps/api/`, mounted by the same `create_app()` in
`apps/api/main.py:103-138`. The API keeps its `/api/v1` prefix untouched; the
web pages take `/`.

```text
apps/web/
    __init__.py
    routes.py          # the view functions
    templates/
        base.html      # layout, nav, footer
        catalog.html   # this increment's page
    static/
        reim.css
```

### 2.2 Server-rendered, and the dependency budget is one package

Jinja2 templates rendered by FastAPI's `Jinja2Templates`. **`jinja2` is not
currently a dependency and is not installed** — it is the one package this
increment adds, and the only one.

No CDN, no bundler, no `node_modules`, no build step. The deployment artefact
stays the container that already exists, and `make run-api` still serves
everything. This matters for a project whose stated goal is to be
self-hostable: a page that needs a network fetch to render is a page that does
not render on a restricted network.

CSS is one hand-written file. No framework.

### 2.3 Views call repositories, not the API over HTTP

The decision most likely to be made wrongly, so it is stated plainly: the view
functions call the same repository and service functions the API routers call —
`build_pipeline_summaries(session)` for this page — **not** `httpx.get` against
the application's own `/api/v1`.

A process issuing HTTP requests to itself buys nothing and costs three things:
a network hop that can fail independently, a second serialisation of data it
already holds, and an ordering problem at startup. The API routers are thin
wrappers over those same functions (`apps/api/routers/pipelines.py:31-33` is
three lines), so calling the function is calling the endpoint minus the
transport.

**The Pydantic schemas are still used** as the shape handed to templates. That
is what stops the two surfaces drifting: if `PipelineSummary` gains a field, the
page and the endpoint see it together.

## 3. The page

Three blocks, built by **joining two sources on the source key**. Neither alone
is enough, and which field comes from where was measured rather than assumed:

| Source | Carries |
|---|---|
| `build_pipeline_summaries(session)` → `PipelineSummary` (`reim/schemas/pipelines.py:68-87`) | `source_key`, `pipeline_key`, `enabled`, `disabled_reason`, `frequency`, `indicators`, and every freshness field |
| `load_catalog(...)` → `SourceEntry` | `organization`, `license`, `documentation_url`, `name`, `description`, `official` |

**`PipelineSummary` carries no organization and no licence** — it is a run-health
view, not a catalog view. The page therefore reads the catalog too and joins
`PipelineSummary.source_key` to `SourceEntry.key`. `DataSourceRead` holds the
same catalog fields from the database, but as `organization_id`, a foreign key
the page would then have to resolve; the YAML entry names the organization
directly and is the authority anyway.

| Block | Fields |
|---|---|
| **What REIM holds** | `name`, `organization`, `frequency`, `indicators`, `license` |
| **How fresh it is** | `last_success_at`, `last_run_at`, `last_run_status`, `records_inserted_last_run`, `records_updated_last_run`, `records_rejected_last_run` |
| **What is disabled** | `enabled`, `disabled_reason` |

### 3.1 Nothing is disabled today, and the page must say so

Measured on 2026-09-11: `catalog validate` reports **23 sources, 23 enabled**.
`grep "enabled: false" sources/catalog.yml` returns nothing. The BCN
exchange-rate connector, which v0.1.0 shipped disabled, was unblocked in
v0.2.0.

So the third block has **no rows**, and that is the point worth designing for.
An empty section reads as a failed load. The page states the absence in words —
*"No source is disabled."* — rather than rendering an empty table or omitting
the heading.

`disabled_reason` is in the schema and has therefore **never been exercised
against real data**. A test constructs a disabled pipeline to prove the block
renders the reason when there is one, so the absence today is a fact about the
catalog and not an untested path.

### 3.2 Licences are shown, because three of them are not open

REIM reads three sources whose terms are not open — the IMF, SIECA and CEPAL —
and `docs/sources.md` records each one's real terms. A catalog browser that
listed what REIM holds without saying what may be redistributed would undo
that. Each source shows its licence, and the non-open ones are marked as such
rather than left for the reader to infer from a slug.

### 3.3 Every figure links back

The project's rule for charts — *every chart links back to the source URL for
the underlying figure* — applies to tables too. Each source links to its
`documentation_url`, and to its section in `docs/sources.md` where one exists.

## 4. Testing

The same `TestClient` the API routes use (`tests/integration/test_api.py:11,51`)
with the seeded session. HTML routes need no new harness.

**Tests assert content, not markup.** That the 23 sources appear; that a
non-open licence is visible on the sources carrying one; that the disabled block
states its emptiness; that a constructed disabled pipeline renders its reason;
that `200` is returned and the response is `text/html`. Asserting tag structure
would make every styling change a test change, which is how front-end tests come
to be deleted.

One test pins the architectural decision of §2.3: the web routes must not issue
outbound HTTP. It runs a page render under `respx` with no routes mounted, so
any outbound request raises.

## 5. Decisions

| | Decision | Rationale |
|---|---|---|
| **D1** | Server-rendered Jinja2, not a SPA | Keeps one language, one linter, one type checker and one test runner; adds no build step to a self-hostable deployment (§2.2) |
| **D2** | One new dependency, `jinja2` | No CDN and no bundler; a page that needs the network to render does not render on a restricted one |
| **D3** | Views call repositories, not the app's own HTTP API | A process requesting from itself adds a failure mode and a serialisation for nothing (§2.3) |
| **D4** | Pydantic schemas remain the shape handed to templates | Keeps the page and the endpoint from drifting apart |
| **D8** | The page joins `PipelineSummary` with the catalog's `SourceEntry` | Freshness and catalog metadata live in different objects; `PipelineSummary` carries no organization or licence, and `DataSourceRead` carries the organization only as a foreign key (§3) |
| **D5** | The disabled block states its emptiness in words | Nothing is disabled today; an empty section reads as a broken page (§3.1) |
| **D6** | Licences shown, non-open ones marked | Three of REIM's sources forbid redistribution; a catalog that hid that would undo `docs/sources.md` (§3.2) |
| **D7** | Tests assert content, not markup | Markup assertions make every styling change a test change |

## 6. Out of scope

* **Charts and time series.** This increment proves the skeleton without
  mixing in the charting decision, which is the hardest one and deserves its
  own discussion — server-rendered SVG, a vendored library, or reconsidering
  the SPA question for that page alone.
* **The pipeline-observability page**, which reuses this skeleton and the same
  `PipelineSummary` data with run history behind it.
* **Any write path.** REIM's API is read-only and so is this.
* **Authentication.** v0.5.0's concern, along with rate limiting.
