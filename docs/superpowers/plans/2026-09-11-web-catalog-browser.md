# REIM's first web page — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve a catalog browser at `/` — what REIM holds, how fresh it is,
and what is disabled and why — plus the server-rendered skeleton the
pipeline-observability page and the time-series dashboard will reuse.

**Architecture:** `apps/web/` beside `apps/api/`, mounted by the same
`create_app()`. Jinja2 templates, one hand-written stylesheet, no build step.
Views call `build_pipeline_summaries(session)` and `get_catalog()` directly —
never the application's own HTTP API.

**Tech Stack:** Python 3.13, FastAPI, Jinja2 (**the one new dependency**),
pytest with `TestClient`, ruff, mypy. Run tools as `.venv/bin/<tool>` — there
is no `pip` in the venv, so a new dependency needs `uv pip install` or the
project's own install path.

**Spec:** `docs/superpowers/specs/2026-09-11-web-catalog-browser-design.md`

## Global Constraints

* **Views call repositories and services, never the app's own HTTP API**
  (spec D3). A page that fetches `http://localhost:8000/api/v1/...` from inside
  the process is wrong, and a test enforces it.
* **Exactly one new dependency: `jinja2`.** No CDN, no bundler, no
  `node_modules`, no build step (spec D2).
* **The API surface does not change.** Every existing route keeps its path,
  its response and its tests. `/api/v1` is untouched; the pages take `/`.
* **Tests assert content, not markup** (spec D7). Asserting tag structure makes
  every styling change a test change.
* **Nothing is disabled today** — 23 sources, 23 enabled — so the disabled
  block states its emptiness in words rather than rendering an empty table
  (spec D5).
* **The verification gate is CI's, over the whole repository:**
  `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest`.
* Measured facts this plan asserts, all from 2026-09-11: 23 catalog sources,
  all enabled; 63 indicators; `jinja2` neither declared nor installed;
  `build_pipeline_summaries` at `reim/services/status.py:22` already resolves
  the catalog itself via the `lru_cache`-backed `get_catalog()`; `create_app()`
  at `apps/api/main.py:100-138` registers eight routers and returns.

---

### Task 1: Add Jinja2 and mount an empty web surface

The smallest end-to-end slice: a route, a template, a stylesheet, and a test
that the page renders. No content yet — this proves the wiring before any
data touches it.

**Files:**
- Modify: `pyproject.toml`
- Create: `apps/web/__init__.py`, `apps/web/routes.py`
- Create: `apps/web/templates/base.html`
- Create: `apps/web/static/reim.css`
- Modify: `apps/api/main.py`
- Create: `tests/integration/test_web.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `apps/web.routes.router` — an `APIRouter` with no prefix;
  `create_app()` mounting it and `/static`.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, add `"jinja2>=3.1"` to the `dependencies` list (not to
`dev`: the pages are part of the running application). Then install it:

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/bin/python -m pip install 'jinja2>=3.1' 2>/dev/null || uv pip install --python .venv/bin/python 'jinja2>=3.1'
.venv/bin/python -c "import jinja2; print('jinja2', jinja2.__version__)"
```

There is no `pip` in this venv, so the first form is expected to fail and the
`uv` form to succeed. If neither works, **stop and report** — do not vendor the
package or work around the absence.

- [ ] **Step 2: Write the failing test**

Create `tests/integration/test_web.py`. Copy the client fixture from
`tests/integration/test_api.py` (it is at lines 23-51 there) rather than
inventing one — the seeded session and `TestClient` setup are identical.

```python
def test_the_catalog_page_renders(client: TestClient) -> None:
    """The skeleton serves HTML at the site root, beside the API."""
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "REIM" in response.text


def test_the_api_is_unchanged_by_the_web_surface(client: TestClient) -> None:
    """Mounting pages at / must not move or shadow any API route."""
    assert client.get("/api/v1/system/health").status_code == 200
    assert client.get("/api/v1/indicators").status_code == 200


def test_the_stylesheet_is_served(client: TestClient) -> None:
    """No CDN: the one stylesheet ships with the application."""
    response = client.get("/static/reim.css")

    assert response.status_code == 200
    assert "css" in response.headers["content-type"]
```

- [ ] **Step 3: Run it and watch it fail**

```bash
.venv/bin/pytest tests/integration/test_web.py -q 2>&1 | tail -5
```

Expected: FAIL — `404` on `/`, because no such route exists.

- [ ] **Step 4: Write the route module**

`apps/web/routes.py`. Note `Jinja2Templates` needs the templates directory as
an absolute path, resolved from this file rather than the working directory —
the application must render the same whichever directory it is started from.

```python
"""REIM's web pages, served from the same application as the API.

Server-rendered rather than a client application, so the project keeps one
language, one linter, one type checker and one test runner, and its deployment
stays the container it already is. See the design document for why that was
chosen over a SPA.

These views call the same service and repository functions the API routers
call. They do **not** issue HTTP requests to the application's own API: a
process requesting from itself adds a network hop that can fail on its own, a
second serialisation of data already in memory, and an ordering problem at
startup — for nothing. The Pydantic schemas are still the shape handed to the
templates, which is what keeps the two surfaces from drifting apart.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

TEMPLATES_DIRECTORY = Path(__file__).resolve().parent / "templates"
STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIRECTORY))

router = APIRouter(tags=["web"], include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
def catalog(request: Request) -> HTMLResponse:
    """The catalog browser: what REIM holds, how fresh it is, what is disabled."""
    return templates.TemplateResponse(request, "catalog.html", {})
```

`include_in_schema=False` keeps the pages out of the OpenAPI document, which
describes the API contract and should not grow HTML routes.

- [ ] **Step 5: Write `base.html` and `catalog.html`**

`base.html` carries the layout: `<!doctype html>`, a `<title>` block, a link to
`/static/reim.css`, a header naming the project, a `{% block content %}`, and a
footer. `catalog.html` extends it and, for now, holds only a heading.

Keep the markup plain and semantic — `<table>`, `<section>`, `<h2>`. No
framework classes. The stylesheet is the only styling.

- [ ] **Step 6: Write `reim.css`**

One hand-written file. A readable measure, a system font stack, enough table
styling to make columns legible, and a muted colour for secondary text. It does
not need to be elaborate; it needs to make a dense table readable.

- [ ] **Step 7: Mount both in `create_app()`**

In `apps/api/main.py`, after the eight `include_router` calls:

```text
    app.include_router(web_routes.router)
    app.mount("/static", StaticFiles(directory=str(web_routes.STATIC_DIRECTORY)), name="static")
```

with `from fastapi.staticfiles import StaticFiles` and
`from apps.web import routes as web_routes` at the top. **Mount the router
last**, so no page path can shadow an API route.

- [ ] **Step 8: Verify and commit**

```bash
.venv/bin/pytest tests/integration/test_web.py -q 2>&1 | tail -3
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q 2>&1 | tail -2
git add pyproject.toml apps/web apps/api/main.py tests/integration/test_web.py
git commit -m "feat(web): serve an empty page at the site root"
```

---

### Task 2: Show what REIM holds

**Files:**
- Modify: `apps/web/routes.py`, `apps/web/templates/catalog.html`
- Modify: `tests/integration/test_web.py`

**Interfaces:**
- Consumes: `build_pipeline_summaries` from `reim.services.status`,
  `get_catalog` from `reim.domain.sources.catalog`.
- Produces: a `rows` sequence handed to the template, each entry pairing a
  `PipelineSummary` with its `SourceEntry`.

- [ ] **Step 1: Write the failing tests**

```python
def test_every_catalog_source_appears(client: TestClient) -> None:
    """All 23, not a page of them: this is a catalog, not a feed."""
    body = client.get("/").text

    catalog = get_catalog()
    assert len(catalog.sources) == 23
    for entry in catalog.sources:
        assert entry.key in body, f"{entry.key} is missing from the page"


def test_each_source_shows_its_organization_and_frequency(client: TestClient) -> None:
    """The two facts that say what a row actually is."""
    body = client.get("/").text

    assert "CEPAL" in body
    assert "BANGUAT" in body
    assert "quarterly" in body.lower()
    assert "daily" in body.lower()


def test_a_source_links_to_its_documentation(client: TestClient) -> None:
    """Every figure links back — the rule the project applies to charts."""
    body = client.get("/").text

    entry = get_catalog().get("cepalstat_bop_quarterly")
    assert entry.documentation_url is not None
    assert str(entry.documentation_url) in body
```

- [ ] **Step 2: Run them and watch them fail**

```bash
.venv/bin/pytest tests/integration/test_web.py -q -k "catalog_source or organization or documentation" 2>&1 | tail -5
```

- [ ] **Step 3: Join the two sources in the view**

`build_pipeline_summaries(session)` returns one `PipelineSummary` per catalog
entry, keyed by `source_key`. `get_catalog()` is `lru_cache`-backed, so reading
it in a view costs nothing after the first call.

```text
summaries = build_pipeline_summaries(session)
catalog = get_catalog()
rows = [(summary, catalog.get(summary.source_key)) for summary in summaries]
```

Hand `rows` to the template. **Do not flatten the pair into a dict** — keeping
the two Pydantic objects intact is what the spec's D4 protects: a field added
to either shows up on the page and in the API together.

`SourceCatalog.get()` **raises `CatalogError`** for an unknown key rather than
returning `None` — verified at `reim/domain/sources/catalog.py:140-148`. Since
`build_pipeline_summaries` builds its summaries *by iterating the same
catalog*, every `source_key` it returns is present by construction, so the
lookup cannot raise in practice. Do not add a defensive branch for a case the
data shape rules out; if it ever raises, that is a real inconsistency and
should surface.

- [ ] **Step 4: Render the table**

Columns: source name, organization, frequency, indicator count, licence. The
source name links to `documentation_url`. Keep it one `<table>`; sort by
organization then key so related sources sit together.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/pytest tests/integration/test_web.py -q 2>&1 | tail -3
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps
git add apps/web tests/integration/test_web.py
git commit -m "feat(web): list every source REIM reads, with its organization and licence"
```

---

### Task 3: Show how fresh it is, and mark the licences

**Files:**
- Modify: `apps/web/templates/catalog.html`, `apps/web/static/reim.css`
- Modify: `tests/integration/test_web.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_freshness_is_shown_per_source(client: TestClient) -> None:
    """A catalog that does not say how old its data is, is a list of promises."""
    body = client.get("/").text

    assert "Last success" in body or "last success" in body.lower()


def test_a_source_that_never_ran_says_so(client: TestClient) -> None:
    """Never-run and ran-and-failed are different states and must read that way."""
    body = client.get("/").text

    # The seeded fixture runs no pipelines, so every source is in this state.
    assert "Never" in body or "never" in body


def test_non_open_licences_are_marked(client: TestClient) -> None:
    """Three of REIM's sources forbid redistribution; the page says which."""
    body = client.get("/").text

    imf = get_catalog().get("imf_imts_nicaragua")
    assert imf.license in body
```

`imf_imts_nicaragua` is a real catalog key — verified. Its licence is the
IMF's, one of the three non-open ones.

- [ ] **Step 2: Run them and watch them fail**

- [ ] **Step 3: Add the freshness columns**

From `PipelineSummary`: `last_success_at`, `last_run_status`, and the three
record counts. A source with `last_success_at is None` renders **"Never run"**,
not an empty cell — an empty cell is indistinguishable from a rendering bug.

Format timestamps as dates with the age beside them (`2026-09-09 · 2 days
ago`), since "how fresh" is the question the column answers and a raw timestamp
makes the reader do the arithmetic.

- [ ] **Step 4: Mark the non-open licences**

Three of REIM's sources are not openly licensed — the IMF, SIECA and CEPAL.
Show every source's licence, and mark those three visually (a class, not an
emoji) so a reader scanning for what is redistributable can find it.

Take the list from the catalog's `license` field rather than hard-coding the
three keys: if a fourth arrives, the page should mark it without an edit.
Determine from `sources/catalog.yml` which licence slugs are the non-open ones
and record the rule in the template's comment.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/pytest tests/integration/test_web.py -q 2>&1 | tail -3
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps
git add apps/web tests/integration/test_web.py
git commit -m "feat(web): show freshness per source and mark the non-open licences"
```

---

### Task 4: The disabled block, which has nothing to show

**Files:**
- Modify: `apps/web/templates/catalog.html`
- Modify: `tests/integration/test_web.py`

This task is short and is the one most likely to be done carelessly, because
the correct output today is an absence.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_disabled_block_states_its_own_emptiness(client: TestClient) -> None:
    """Nothing is disabled today: 23 sources, 23 enabled.

    An empty section reads as a failed load. The page must say the absence out
    loud, so a reader can tell "none" from "did not render".
    """
    body = client.get("/").text

    assert all(entry.enabled for entry in get_catalog().sources)
    assert "No source is disabled" in body


def test_a_disabled_source_renders_its_reason(client: TestClient) -> None:
    """`disabled_reason` has never run against real data — so construct it.

    v0.1.0 shipped the BCN connector disabled and v0.2.0 unblocked it, leaving
    the field in the schema with nothing exercising it. This is the only test
    that proves the block works when there is something to put in it.
    """
    entry = ...  # a catalog entry with enabled=False and a disabled_reason
    # Render the page with that entry present and assert both the source key
    # and its reason appear, and that the "No source is disabled" line does not.
```

The second test needs a disabled entry. Decide how to introduce one and say
which you chose: overriding `get_catalog` through FastAPI's dependency system
is not available here because the view calls it directly, so the options are
monkeypatching `get_catalog` (remember `reset_catalog_cache()`), or building a
`SourceCatalog` in the test and passing it through a parameter the view
accepts. **If you add a parameter to the view for testability alone, say so** —
that is a design change and needs to be visible, not smuggled in.

- [ ] **Step 2: Run them and watch them fail**

- [ ] **Step 3: Render the block**

A `<section>` with its heading always present. Inside: the disabled sources with
their reasons, or the sentence **"No source is disabled."** The heading never
disappears — a missing heading is as ambiguous as an empty table.

- [ ] **Step 4: Verify and commit**

```bash
.venv/bin/pytest tests/integration/test_web.py -q 2>&1 | tail -3
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps
git add apps/web tests/integration/test_web.py
git commit -m "feat(web): state that nothing is disabled, and prove the block works when something is"
```

---

### Task 5: Pin the architecture, look at the page, and document it

**Files:**
- Modify: `tests/integration/test_web.py`
- Modify: `README.md`, `ROADMAP.md`

- [ ] **Step 1: Pin the no-outbound-HTTP rule**

The spec's D3 is an architectural decision that nothing currently enforces. A
later contributor adding a page by calling the app's own API would not be
caught by any existing test.

```python
@respx.mock
def test_the_pages_make_no_outbound_http_requests(client: TestClient) -> None:
    """Views call services directly; a page fetching the app's own API is wrong.

    respx is mounted with no routes, so any outbound request raises rather than
    escaping to the network.
    """
    assert client.get("/").status_code == 200
```

Confirm this actually fails when the rule is broken: temporarily make the view
issue `httpx.get("https://example.invalid")`, watch the test fail, then revert.
**Say that you did this** — a guard test that has never been seen to fail is
not known to guard anything.

- [ ] **Step 2: Look at the page**

```bash
.venv/bin/uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!
sleep 3
curl -s http://localhost:8000/ | head -40
kill $API_PID
```

Read the rendered HTML. The tests assert content, not layout, so this is the
only step that catches a table with its columns misaligned or a heading that
reads badly. Report what it looks like — including anything you would change
but did not.

If a database is available (`make db-up CONTAINER_ENGINE=podman`, then
`.venv/bin/alembic upgrade head` and `db seed`), run a pipeline first so the
freshness column shows real values rather than "Never run" everywhere. Say
which you did.

- [ ] **Step 3: Update `README.md` and `ROADMAP.md`**

`README.md`: a short section saying the web pages exist, what the catalog
browser answers, and how to reach them (`make run-api`, then `/`). Note that
the API is unchanged at `/api/v1`.

`ROADMAP.md`, in v0.4.0:
- **Mark the `methodology_varies_by_country` bullet done** — it was completed
  on 2026-09-11 and is still listed as pending.
- Mark the data catalog browser done, in the established voice, noting it is
  REIM's first web page and that the skeleton is what the remaining two pages
  reuse.
- Leave the dashboard and observability bullets, noting the charting decision
  is still open.

- [ ] **Step 4: Run the gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . \
  && .venv/bin/mypy reim apps && .venv/bin/pytest -q 2>&1 | tail -2
git add tests/integration/test_web.py README.md ROADMAP.md
git commit -m "docs(web): the catalog browser, and what it looks like"
```

`ruff format` reaches Python fenced in Markdown. If it rewrites a block in
`README.md`, that block is not a valid standalone module — fence it as
```text and re-run until the check is clean.

---

## Self-review

**Spec coverage.** §2.1 structure → Task 1. §2.2 one dependency, no build →
Task 1. §2.3 no self-HTTP → Tasks 1 and 5. §3 the join → Task 2. §3.1 disabled
emptiness → Task 4. §3.2 licences → Task 3. §3.3 links back → Task 2. §4
testing → every task. §5 D1-D8 all land in a task. §6 out-of-scope introduces
no work. No gaps.

**Known soft spots, flagged rather than papered over.** Two that were open when
this plan was drafted are now settled and written into the tasks:
`SourceCatalog.get()` raises `CatalogError` rather than returning `None`
(`catalog.py:140-148`), and the lookup cannot raise here because
`build_pipeline_summaries` iterates that same catalog; and
`imf_imts_nicaragua` is a real key. One remains: Task 4's second test needs a
disabled catalog entry
and the plan deliberately does not prescribe how, because the options differ in
whether they change the view's signature — and that is a decision worth seeing
rather than assuming. Task 5 step 2 is the only step that looks at the output;
everything else asserts content, which cannot catch a page that reads badly.
