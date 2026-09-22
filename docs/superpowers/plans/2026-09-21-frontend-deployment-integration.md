# Frontend Deployment Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve the Next.js static export (`frontend/`) at the production domain — both the generic `deploy/docker-compose.prod.yml` deployment and the real, already-running panda deployment — by adding a small containerized frontend image and moving `apps/web` to `/legacy` so the new frontend can take the root path.

**Architecture:** A new multi-stage image (`node:20-alpine` build → `caddy:2.11.4-alpine` runtime) bakes the static export and serves it internally via `file_server` on `:8080`. The outer proxy (generic `deploy/Caddyfile` or panda's host Caddy) stays `reverse_proxy`-only and splits by path: `/api/*`, `/legacy*`, `/static/*`, `/health`, `/ready` go to the existing api upstream; everything else goes to the new frontend upstream. `apps/web`'s router gets `prefix="/legacy"` so the path split needs no proxy-side rewriting.

**Tech Stack:** Next.js static export, Caddy 2.11.4, Podman (compose + Quadlets), FastAPI/Jinja2 (`apps/web`).

**Spec:** `docs/superpowers/specs/2026-09-21-frontend-deployment-integration-design.md`

## Global Constraints

- Frontend image build stage: `node:20-alpine`. Runtime stage: `caddy:2.11.4-alpine` — same pin already used by `deploy/Caddyfile`'s own measured build, and by the compose `caddy` service.
- No `file_server` directive outside the frontend image's own internal Caddyfile. Every outer Caddy config (generic and panda) stays `reverse_proxy`-only, matching the existing pattern with zero exceptions.
- `apps/web`'s `APIRouter` gets `prefix="/legacy"` in Python code, not via `handle_path` at the proxy — the URL structure's source of truth stays in the application.
- `/static/*` routing is unchanged everywhere — it keeps its own top-level path in every Caddy config regardless of where `apps/web`'s pages live.
- The "Catálogo" nav link stays pointed at `/catalog/` (unchanged) — that page has never existed, so there's nothing to preserve there.
- Any change to panda's live `/etc/caddy/sites/reim.caddy` is validated with `caddy validate --adapter caddyfile` against a copy first, and applied with `systemctl reload caddy`, never `restart` — this process serves 4 other unrelated sites (`git`, `grafana`, `n8n`, `cockpit`).

---

### Task 1: Move `apps/web` under `/legacy`

**Files:**
- Modify: `apps/web/routes.py:132`
- Modify: `apps/web/templates/base.html`, `runs.html`, `run_detail.html`, `run_not_found.html`, `series.html`, `series_not_found.html`
- Test: `tests/integration/test_web.py`, `tests/integration/test_web_runs.py`, `tests/integration/test_web_series.py`

**Interfaces:**
- Produces: `apps/web/routes.py`'s `router` now serves `/legacy`, `/legacy/runs`, `/legacy/runs/{run_id}`, `/legacy/series` instead of `/`, `/runs`, `/runs/{run_id}`, `/series`. `app.mount("/static", ...)` in `apps/api/main.py:165` is unchanged and untouched by this task.

- [ ] **Step 1: Update the three test files to expect the `/legacy` prefix**

Two targeted multi-line edits first (these check rendered nav `href` attributes, not just request paths, so a blanket find/replace would miss the assertions).

In `tests/integration/test_web_runs.py`, replace:
```python
    for path in ("/", "/runs"):
        body = client.get(path).text
        assert 'href="/runs"' in body
        assert 'href="/"' in body
```
with:
```python
    for path in ("/legacy/", "/legacy/runs"):
        body = client.get(path).text
        assert 'href="/legacy/runs"' in body
        assert 'href="/legacy/"' in body
```

In `tests/integration/test_web_series.py`, replace:
```python
    for path in ("/", "/runs", "/series"):
        body = client.get(path).text
        assert 'href="/series"' in body, f"{path} is missing the Series nav link"
```
with:
```python
    for path in ("/legacy/", "/legacy/runs", "/legacy/series"):
        body = client.get(path).text
        assert 'href="/legacy/series"' in body, f"{path} is missing the Series nav link"
```

Then the mechanical request-path replacements, run from the repo root:
```bash
sed -i 's/client\.get("\/")/client.get("\/legacy\/")/g' tests/integration/test_web.py
sed -i 's/client\.get("\/runs/client.get("\/legacy\/runs/g' tests/integration/test_web.py
sed -i 's/client\.get(f"\/runs\//client.get(f"\/legacy\/runs\//g' tests/integration/test_web.py
sed -i 's/client\.get("\/series/client.get("\/legacy\/series/g' tests/integration/test_web.py

sed -i 's/client\.get("\/runs/client.get("\/legacy\/runs/g' tests/integration/test_web_runs.py
sed -i 's/client\.get(f"\/runs\//client.get(f"\/legacy\/runs\//g' tests/integration/test_web_runs.py

sed -i 's/client\.get("\/series/client.get("\/legacy\/series/g' tests/integration/test_web_series.py
```

`tests/integration/test_web.py`'s `client.get("/health")` and `client.get("/metrics")` (unprefixed system routes, not part of `apps/web`) and `client.get("/static/reim.css")` must NOT change — none of the patterns above touch them.

Verify no bare references remain (each command should print nothing):
```bash
grep -n 'client\.get("/")\|client\.get("/runs\|client\.get(f"/runs\|client\.get("/series' tests/integration/test_web.py tests/integration/test_web_runs.py tests/integration/test_web_series.py
```

- [ ] **Step 2: Run the tests and confirm they fail against the unmodified app**

```bash
REIM_TEST_DATABASE_URL=${REIM_TEST_DATABASE_URL:-postgresql+psycopg://reim:reim@localhost:55432/reim} \
  .venv/bin/python -m pytest tests/integration/test_web.py tests/integration/test_web_runs.py tests/integration/test_web_series.py -v
```
Expected: multiple FAILs — 404s on `/legacy/...` (the router doesn't have the prefix yet) and `AssertionError`s on the `href="/legacy/..."` checks (the templates still render unprefixed links).

- [ ] **Step 3: Add the `/legacy` prefix to the router**

In `apps/web/routes.py:132`, change:
```python
router = APIRouter(tags=["web"], include_in_schema=False)
```
to:
```python
router = APIRouter(prefix="/legacy", tags=["web"], include_in_schema=False)
```

- [ ] **Step 4: Update the 6 templates' hardcoded links**

In `apps/web/templates/base.html`, replace:
```html
    <nav class="site-nav">
      <a href="/">Catalog</a>
      <a href="/runs">Runs</a>
      <a href="/series">Series</a>
    </nav>
```
with:
```html
    <nav class="site-nav">
      <a href="/legacy/">Catalog</a>
      <a href="/legacy/runs">Runs</a>
      <a href="/legacy/series">Series</a>
    </nav>
```
(the `<link rel="stylesheet" href="/static/reim.css" />` line above it is unchanged).

In `apps/web/templates/runs.html`, replace:
```html
          <td><a href="/runs/{{ run.id }}">{{ run.started_at | freshness }}</a></td>
```
with:
```html
          <td><a href="/legacy/runs/{{ run.id }}">{{ run.started_at | freshness }}</a></td>
```

In `apps/web/templates/run_detail.html`, replace:
```html
  <p><a href="/runs">Back to the run history</a></p>
```
with:
```html
  <p><a href="/legacy/runs">Back to the run history</a></p>
```

In `apps/web/templates/run_not_found.html`, replace:
```html
  <p><a href="/runs">Back to the run history</a></p>
```
with:
```html
  <p><a href="/legacy/runs">Back to the run history</a></p>
```

In `apps/web/templates/series.html`, replace:
```html
  <form class="series-form" method="get" action="/series">
```
with:
```html
  <form class="series-form" method="get" action="/legacy/series">
```

In `apps/web/templates/series_not_found.html`, replace:
```html
  <p><a href="/series">Back to the series picker</a></p>
```
with:
```html
  <p><a href="/legacy/series">Back to the series picker</a></p>
```

- [ ] **Step 5: Run the tests and confirm they pass**

```bash
REIM_TEST_DATABASE_URL=${REIM_TEST_DATABASE_URL:-postgresql+psycopg://reim:reim@localhost:55432/reim} \
  .venv/bin/python -m pytest tests/integration/test_web.py tests/integration/test_web_runs.py tests/integration/test_web_series.py -v
```
Expected: all PASS.

- [ ] **Step 6: Run the full backend gate**

```bash
make check
```
Expected: exit code 0 (ruff, mypy, catalog validate, full pytest suite — confirms nothing outside the three web test files depended on the old paths).

- [ ] **Step 7: Commit**

```bash
git add apps/web/routes.py apps/web/templates/base.html apps/web/templates/runs.html \
  apps/web/templates/run_detail.html apps/web/templates/run_not_found.html \
  apps/web/templates/series.html apps/web/templates/series_not_found.html \
  tests/integration/test_web.py tests/integration/test_web_runs.py tests/integration/test_web_series.py
git commit -m "refactor(web): move apps/web routes under /legacy prefix"
```

---

### Task 2: Frontend header — interim nav links for Series and Operaciones

**Files:**
- Modify: `frontend/src/components/Header.tsx`
- Test: `frontend/src/components/__tests__/Header.test.tsx`

**Interfaces:**
- Consumes: nothing from Task 1 directly (independent codebase), but relies on the `/legacy/...` paths Task 1 establishes being live before this is deployed.
- Produces: `Header.tsx`'s `NAV_LINKS` — "Series" now points at `/legacy/series/`, "Operaciones" at `/legacy/runs/`. "Inicio" (`/`), "Mapa" (`/map/`), and "Catálogo" (`/catalog/`) are unchanged.

- [ ] **Step 1: Write the failing test**

Replace the full contents of `frontend/src/components/__tests__/Header.test.tsx` with:
```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { Header } from "../Header";

vi.mock("next/navigation", () => ({
  usePathname: () => "/map/",
}));

describe("Header", () => {
  it("renders brand and navigation links", () => {
    render(<Header />);
    expect(screen.getByText("REIM")).toBeInTheDocument();
    expect(screen.getByText("Mapa")).toBeInTheDocument();
    expect(screen.getByText("Series")).toBeInTheDocument();
    expect(screen.getByText("Catálogo")).toBeInTheDocument();
  });

  it("points Series and Operaciones at the interim /legacy pages", () => {
    render(<Header />);
    expect(screen.getByText("Series").closest("a")).toHaveAttribute("href", "/legacy/series/");
    expect(screen.getByText("Operaciones").closest("a")).toHaveAttribute("href", "/legacy/runs/");
  });

  it("leaves Catálogo pointed at the not-yet-built page", () => {
    render(<Header />);
    expect(screen.getByText("Catálogo").closest("a")).toHaveAttribute("href", "/catalog/");
  });
});
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
cd frontend && npm run test -- Header
```
Expected: FAIL on the "interim /legacy pages" assertion — `NAV_LINKS` still has `/series/` and `/runs/`.

- [ ] **Step 3: Update `NAV_LINKS`**

In `frontend/src/components/Header.tsx`, replace:
```tsx
const NAV_LINKS = [
  { href: "/", label: "Inicio" },
  { href: "/map/", label: "Mapa" },
  { href: "/series/", label: "Series" },
  { href: "/catalog/", label: "Catálogo" },
  { href: "/runs/", label: "Operaciones" },
];
```
with:
```tsx
const NAV_LINKS = [
  { href: "/", label: "Inicio" },
  { href: "/map/", label: "Mapa" },
  // Interim: apps/web hasn't been rewritten as a Next page yet, so this
  // points at its relocated /legacy route until the downstream
  // catalog/observability plan replaces it.
  { href: "/legacy/series/", label: "Series" },
  { href: "/catalog/", label: "Catálogo" },
  // Interim: same as Series above.
  { href: "/legacy/runs/", label: "Operaciones" },
];
```

- [ ] **Step 4: Run the test and confirm it passes**

```bash
cd frontend && npm run test -- Header
```
Expected: all PASS.

- [ ] **Step 5: Run the full frontend gate**

```bash
make frontend-check
```
Expected: exit code 0.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Header.tsx frontend/src/components/__tests__/Header.test.tsx
git commit -m "feat(frontend): point Series/Operaciones nav at interim /legacy pages"
```

---

### Task 3: Frontend container image

**Files:**
- Create: `deploy/Caddyfile.frontend`
- Create: `deploy/Dockerfile.frontend`

**Interfaces:**
- Produces: image tag `localhost/reim-frontend:prod` (panda) / build target for the `frontend` compose service (Task 4), listening on `:8080` internally, serving `frontend/out` via `file_server`.

- [ ] **Step 1: Create `deploy/Caddyfile.frontend`**

```caddyfile
# Internal Caddyfile baked into the frontend image. No TLS, no domain
# matcher — this only ever receives traffic from the outer proxy (the
# compose caddy service, or panda's host Caddy), over the container
# network. See deploy/Caddyfile / /etc/caddy/sites/reim.caddy for the
# outer routing that sends non-API, non-/legacy traffic here.
:8080 {
	root * /srv/frontend
	file_server
}
```

- [ ] **Step 2: Create `deploy/Dockerfile.frontend`**

```dockerfile
# syntax=docker/dockerfile:1
#
# Multi-stage build for the REIM static frontend. The runtime stage is
# just Caddy plus the built static export — no Node.js in the final image.

FROM node:20-alpine AS builder

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# caddy:2.11.4-alpine — the same pinned build deploy/Caddyfile's own
# comment already measured for X-Forwarded-For behaviour, and the compose
# caddy service uses. No new Caddy version to reason about.
FROM caddy:2.11.4-alpine AS runtime

COPY deploy/Caddyfile.frontend /etc/caddy/Caddyfile
COPY --from=builder /build/out /srv/frontend

EXPOSE 8080
```

- [ ] **Step 3: Build the image**

```bash
podman build -t localhost/reim-frontend:prod -f deploy/Dockerfile.frontend .
```
Expected: `Successfully tagged localhost/reim-frontend:prod` (run from the repo root — the build context is `.`, matching how `Dockerfile` for the api image is already built from the repo root, since both Dockerfiles need to `COPY` from `frontend/` / `apps/`, `reim/` respectively).

- [ ] **Step 4: Run the image standalone and verify it serves the export**

```bash
podman run -d --rm -p 18080:8080 --name reim-frontend-test localhost/reim-frontend:prod
sleep 1
curl -sf http://localhost:18080/ | grep -o '<title>[^<]*</title>'
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:18080/map/
podman rm -f reim-frontend-test
```
Expected: a `<title>` line (whatever `frontend/src/app/layout.tsx` sets) and `200` for `/map/`.

- [ ] **Step 5: Commit**

```bash
git add deploy/Caddyfile.frontend deploy/Dockerfile.frontend
git commit -m "feat(deploy): add containerized static frontend image"
```

---

### Task 4: Generic production compose + Caddyfile

**Files:**
- Modify: `deploy/docker-compose.prod.yml`
- Modify: `deploy/Caddyfile`

**Interfaces:**
- Consumes: `deploy/Dockerfile.frontend` and `deploy/Caddyfile.frontend` from Task 3 (build context/dockerfile reference); `/legacy` prefix from Task 1 (the `/legacy*` handle block assumes `apps/web` already answers there).
- Produces: a `frontend` service reachable inside the `reim` network at `frontend:8080`, referenced by `deploy/Caddyfile`'s default `handle` block.

- [ ] **Step 1: Add the `frontend` service to `deploy/docker-compose.prod.yml`**

Insert immediately before the `caddy:` service block (which currently starts the line after the `api:` service's `networks: [reim]`):
```yaml
  frontend:
    build:
      context: ..
      dockerfile: deploy/Dockerfile.frontend
    restart: unless-stopped
    # No published port: same reasoning as api — caddy is the only door in.
    networks:
      - reim

```
And add `frontend` to the `caddy` service's `depends_on`, changing:
```yaml
    depends_on:
      api:
        condition: service_healthy
```
(the `caddy` service's `depends_on`, not `api`'s own) to:
```yaml
    depends_on:
      api:
        condition: service_healthy
      frontend:
        condition: service_started
```

- [ ] **Step 2: Update `deploy/Caddyfile`'s routing**

In `deploy/Caddyfile`, inside the `{$REIM_DOMAIN} { ... }` block, replace the final `handle { ... }` (everything from `handle {` on line 42 through its closing `}` on line 60):
```caddyfile
	handle {
		# A cap on request bodies clients SEND, shipped commented out. Caddy
		# does not add it by default, and it is not the byte budget anyone
		# comes looking for: max_size bounds a body before Caddy forwards it
		# upstream, never a response Caddy returns. export.csv is fetched
		# with a bodiless GET, so uncommenting this caps nothing about that
		# endpoint at any value. Nor does anything else here — `caddy
		# list-modules` against this pinned build
		# (docker.io/library/caddy:2.11.4-alpine) matches exactly one
		# body- or size-related handler, http.handlers.request_body, which is
		# this one. Uncomment and pick a size if you start accepting uploads;
		# otherwise leave it, and see docs/deployment.md's "limit counts
		# requests, not bytes" for the lever that does exist.
		# request_body {
		# 	max_size 10MB
		# }
		header Strict-Transport-Security "max-age=31536000; includeSubDomains"
		reverse_proxy api:8000
	}
```
with:
```caddyfile
	handle /api/* {
		reverse_proxy api:8000
	}

	handle /legacy* {
		reverse_proxy api:8000
	}

	handle /static/* {
		reverse_proxy api:8000
	}

	handle /health {
		reverse_proxy api:8000
	}

	handle /ready {
		reverse_proxy api:8000
	}

	handle {
		# A cap on request bodies clients SEND, shipped commented out. Caddy
		# does not add it by default, and it is not the byte budget anyone
		# comes looking for: max_size bounds a body before Caddy forwards it
		# upstream, never a response Caddy returns. export.csv is fetched
		# with a bodiless GET, so uncommenting this caps nothing about that
		# endpoint at any value. Nor does anything else here — `caddy
		# list-modules` against this pinned build
		# (docker.io/library/caddy:2.11.4-alpine) matches exactly one
		# body- or size-related handler, http.handlers.request_body, which is
		# this one. Uncomment and pick a size if you start accepting uploads;
		# otherwise leave it, and see docs/deployment.md's "limit counts
		# requests, not bytes" for the lever that does exist.
		# request_body {
		# 	max_size 10MB
		# }
		header Strict-Transport-Security "max-age=31536000; includeSubDomains"
		reverse_proxy frontend:8080
	}
```
The `max_size`/`request_body` comment documents the general-traffic case, not API-specific behaviour, so it moves down into the new default `handle` unchanged.

- [ ] **Step 3: Validate the compose file merges cleanly**

```bash
podman compose -f deploy/docker-compose.prod.yml config >/dev/null
echo "exit: $?"
```
Expected: `exit: 0`, no YAML/schema errors. Do **not** run `up -d` on this host — ports 80/443 are already owned by the live system `caddy.service` (see Task 5); a full integration run belongs in a disposable environment.

- [ ] **Step 4: Validate the Caddyfile syntax**

```bash
REIM_DOMAIN=example.test REIM_ACME_EMAIL= caddy validate --config deploy/Caddyfile --adapter caddyfile
```
Expected: `Valid configuration`.

- [ ] **Step 5: Commit**

```bash
git add deploy/docker-compose.prod.yml deploy/Caddyfile
git commit -m "feat(deploy): route the generic production stack through the new frontend"
```

---

### Task 5: Deploy to panda

**Files:**
- Create (host, outside git): `~/.config/containers/systemd/reim-frontend.container`
- Modify (host, outside git): `/etc/caddy/sites/reim.caddy`
- Modify: `docs/deployment-panda.md`

**Interfaces:**
- Consumes: `deploy/Dockerfile.frontend` (Task 3), `/legacy` prefix (Task 1).
- Produces: `https://reim.panda.home.arpa/` serving the new frontend; `/legacy/*` serving `apps/web`; `/api/*` unchanged.

- [ ] **Step 1: Build the frontend image on panda**

```bash
podman build -t localhost/reim-frontend:prod -f deploy/Dockerfile.frontend .
```
Expected: `Successfully tagged localhost/reim-frontend:prod`.

- [ ] **Step 2: Create the Quadlet unit**

Write `~/.config/containers/systemd/reim-frontend.container`:
```ini
[Unit]
Description=Panda REIM Frontend
After=network-online.target
Wants=network-online.target

[Container]
Image=localhost/reim-frontend:prod
ContainerName=panda-reim-frontend
Network=panda-net
PublishPort=127.0.0.1:8080:8080

[Service]
Restart=always
TimeoutStartSec=120

[Install]
WantedBy=default.target
```

- [ ] **Step 3: Start the service**

```bash
systemctl --user daemon-reload
systemctl --user start reim-frontend.service
systemctl --user status reim-frontend.service
curl -s http://127.0.0.1:8080/ | grep -o '<title>[^<]*</title>'
```
Expected: `active (running)`, and a `<title>` line from the export.

- [ ] **Step 4: Prepare and validate a candidate Caddy site file**

```bash
mkdir -p /tmp/reim-caddy-candidate
cp /etc/caddy/sites/reim.caddy /tmp/reim-caddy-candidate/reim.caddy
```
Edit `/tmp/reim-caddy-candidate/reim.caddy` to:
```caddyfile
reim.panda.home.arpa {
	tls internal

	handle /metrics {
		respond 404
	}

	handle /metrics/ {
		respond 404
	}

	handle /api/* {
		reverse_proxy 127.0.0.1:8000
	}

	handle /legacy* {
		reverse_proxy 127.0.0.1:8000
	}

	handle /static/* {
		reverse_proxy 127.0.0.1:8000
	}

	handle /health {
		reverse_proxy 127.0.0.1:8000
	}

	handle /ready {
		reverse_proxy 127.0.0.1:8000
	}

	handle {
		header Strict-Transport-Security "max-age=31536000; includeSubDomains"
		reverse_proxy 127.0.0.1:8080
	}
}
```
Then:
```bash
caddy validate --config /tmp/reim-caddy-candidate/reim.caddy --adapter caddyfile
```
Expected: `Valid configuration`.

- [ ] **Step 5: Apply the live Caddy config change — CONFIRM WITH THE USER FIRST**

This touches a process serving 4 other live sites (`git`, `grafana`, `n8n`, `cockpit`). Do not run this step without explicit go-ahead in the moment, even though it was approved as part of this plan — confirm again right before running it.

```bash
sudo cp /tmp/reim-caddy-candidate/reim.caddy /etc/caddy/sites/reim.caddy
sudo systemctl reload caddy
systemctl status caddy | head -5
```
Expected: `caddy.service` stays `active (running)` with its original start time (a reload, not a restart).

- [ ] **Step 6: Verify**

```bash
curl -sk https://reim.panda.home.arpa/                     # new frontend index
curl -sk https://reim.panda.home.arpa/map/                  # new frontend map page
curl -sk https://reim.panda.home.arpa/legacy/                # apps/web catalog page
curl -sk https://reim.panda.home.arpa/legacy/runs             # apps/web run history
curl -sk https://reim.panda.home.arpa/legacy/series             # apps/web series picker
curl -sk https://reim.panda.home.arpa/api/v1/countries            # API JSON
curl -sk https://reim.panda.home.arpa/static/reim.css               # apps/web stylesheet
curl -sk https://reim.panda.home.arpa/health                          # {"status":"ok",...}
curl -sk -w '%{http_code}' https://reim.panda.home.arpa/metrics -o /dev/null   # 404
```
Expected: each returns the content named in its comment; the last prints `404`.

Re-confirm the proxy-identity measurement still holds (same method `docs/deployment-panda.md` already used):
```bash
for i in $(seq 1 61); do curl -sk -o /dev/null -w '%{http_code}\n' https://reim.panda.home.arpa/api/v1/countries; done | tail -3
curl -sk -o /dev/null -w '%{http_code}\n' https://reim.panda.home.arpa/api/v1/countries -H 'X-Forwarded-For: 1.2.3.4'
```
Expected: `429` in all three — the forged header buys no fresh allowance.

- [ ] **Step 7: Update `docs/deployment-panda.md`**

Add the `reim-frontend.container` Quadlet unit (Step 2's content) alongside the existing `reim-api.container` in the "Architecture" table and its own subsection. Replace the `/etc/caddy/sites/reim.caddy` code block with the new version from Step 4. Add a "Redeploying the frontend" bullet to "Operating this deployment", mirroring the existing "Redeploying a code change" bullet, with this text and inner code block:

> - **Redeploying the frontend:** same shape as the api container —
>   ```text
>   podman build -t localhost/reim-frontend:prod -f deploy/Dockerfile.frontend .
>   systemctl --user restart reim-frontend.service
>   ```

Add the new verification block (Step 6's curls) to the "Verified" section.

- [ ] **Step 8: Commit the docs update**

```bash
git add docs/deployment-panda.md
git commit -m "docs: record the frontend deployment on panda"
```

---

## Done when

- `apps/web` answers at `/legacy/*`; `tests/integration/test_web*.py` pass against the new paths.
- `frontend/`'s Header nav for Series/Operaciones points at `/legacy/series/` / `/legacy/runs/` and has a test locking that in.
- `deploy/Dockerfile.frontend` builds a working image serving the static export on `:8080`.
- `deploy/docker-compose.prod.yml` and `deploy/Caddyfile` route traffic between `api` and the new `frontend` service; both validate cleanly.
- `reim.panda.home.arpa/` serves the new frontend, `/legacy/*` serves `apps/web`, `/api/*` is unchanged, and `docs/deployment-panda.md` matches what's actually running.
- `make check` and `make frontend-check` both exit 0 throughout.
