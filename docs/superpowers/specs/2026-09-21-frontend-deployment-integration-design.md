# Frontend deployment integration — design

`frontend/` (Next.js, `output: 'export'`) has three commits of real work —
scaffold, API client, PMTiles map — and as of `0a97046` a green
`make frontend-check`. None of it is reachable from `reim.panda.home.arpa`:
neither `deploy/docker-compose.prod.yml` nor the live panda deployment knows
`frontend/` exists. This increment wires the static export into both the
generic production compose file and panda's real, already-running
deployment, and moves `apps/web` out of the way so the new frontend can take
the root path.

Everything measured below was checked against the repository at `0a97046`
and the live `panda-reim-api` / host Caddy on 2026-09-21.

## 1. What exists, and what this adds

| Piece | State |
|---|---|
| `frontend/` | Builds a static export (`output: 'export'`, `trailingSlash: true`) to `frontend/out`. `NEXT_PUBLIC_API_BASE_URL` defaults to `""`, so the API client fetches same-origin relative paths (`/api/v1/...`) — the frontend assumes it is served from the same domain as the API |
| `deploy/docker-compose.prod.yml` | `postgres`, `api`, `caddy` only. No `frontend` service |
| `deploy/Caddyfile` | One `reverse_proxy api:8000` for everything except `/metrics` (404) |
| panda (real deployment) | Rootless Podman Quadlets, not compose. `reim-api.container` publishes `127.0.0.1:8000`. Host-level `caddy.service` owns 80/443 for 5 sites total (`git`, `grafana`, `n8n`, `cockpit`, `reim`), one file per site under `/etc/caddy/sites/`, **every existing site file uses `reverse_proxy` only — zero `file_server` anywhere** |
| `apps/web` | `APIRouter(tags=["web"], include_in_schema=False)` with no prefix, owns `/`, `/runs`, `/runs/{id}`, `/series` (`apps/web/routes.py:132`). 6 templates hardcode absolute links to those same paths plus `/static/reim.css` |
| `frontend/src/components/Header.tsx` | Nav already links `/series/`, `/catalog/`, `/runs/` — pages that don't exist in the Next app yet (only `/` and `/map/` are built) |
| `/catalog` | Does not exist anywhere in the codebase yet — the nav link is a forward-reference to a future page, not a regression this increment causes |

The addition is **one new container image, changes to both deployment
paths' routing config, and a small prefix move for `apps/web`**. No new
runtime dependency beyond what's already pinned (Caddy `2.11.4-alpine`,
already used twice in this repository).

## 2. What ships

### 2.1 `deploy/Dockerfile.frontend`

Multi-stage, mirroring the existing `Dockerfile`'s shape (dependency layer
first, then source, builder stage discarded at runtime):

```dockerfile
FROM node:20-alpine AS builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM caddy:2.11.4-alpine AS runtime
COPY --from=builder /build/out /srv/frontend
COPY deploy/Caddyfile.frontend /etc/caddy/Caddyfile
EXPOSE 8080
```

`caddy:2.11.4-alpine` — the same pinned build `deploy/Caddyfile`'s own
comment already measured for `X-Forwarded-For` behaviour (D1). No new image
version to reason about.

### 2.2 `deploy/Caddyfile.frontend`

The internal Caddyfile baked into the frontend image. No TLS, no domain
matcher — it only ever receives traffic from the outer proxy, over the
compose/Quadlet network:

```caddyfile
:8080 {
	root * /srv/frontend
	file_server
}
```

This is the **only** `file_server` this increment introduces, and it is
internal to the frontend image — the outer Caddy (generic or panda) never
gets a `file_server` directive of its own, keeping every outer site file
`reverse_proxy`-only (D2).

### 2.3 `deploy/docker-compose.prod.yml`

New `frontend` service:

```yaml
  frontend:
    build:
      context: ..
      dockerfile: deploy/Dockerfile.frontend
    restart: unless-stopped
    networks:
      - reim
```

No published port — same reasoning as `api`: the outer `caddy` service is
the only door in. `caddy`'s `depends_on` gains `frontend` alongside `api`.

### 2.4 `deploy/Caddyfile`

Routing splits by path instead of forwarding everything to `api`:

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
	reverse_proxy frontend:8080
}
```

placed inside the existing `{$REIM_DOMAIN} { ... }` block, alongside the
`/metrics` 404 handlers already there.

### 2.5 panda: new Quadlet + real Caddy site update

`~/.config/containers/systemd/reim-frontend.container`, same shape as the
existing `reim-api.container`:

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

No `Requires=postgres.service` — the frontend container has no database
dependency, unlike `reim-api.container`.

`/etc/caddy/sites/reim.caddy` gets the same path split as §2.4, targeting
loopback ports instead of compose service names:

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

Validated with `caddy validate --config <candidate-copy>/Caddyfile --adapter
caddyfile` against a copy before touching the live file, then
`sudo systemctl reload caddy` (not restart) — the same care
`docs/deployment-panda.md` already documents, because this Caddy serves four
other sites (D3).

`docs/deployment-panda.md` gets the same updates: the new Quadlet unit, the
updated site file, a "Redeploying the frontend" entry alongside the
existing "Redeploying a code change" section, and the new verification
curls (§4).

### 2.6 `apps/web`: move under `/legacy`

`apps/web/routes.py:132`:

```python
router = APIRouter(prefix="/legacy", tags=["web"], include_in_schema=False)
```

One line. FastAPI now owns `/legacy`, `/legacy/runs`, `/legacy/runs/{id}`,
`/legacy/series` natively — no path-stripping needed at the proxy, so the
Caddy config in §2.4/§2.5 is a plain `reverse_proxy`, not `handle_path`
(D4).

`app.mount("/static", ...)` in `apps/api/main.py:165` is **unchanged** —
`/static/*` keeps its own top-level route in both Caddyfiles regardless of
where `apps/web`'s pages live, since nothing in the new frontend's static
export uses that path (Next assets live under `/_next/*`).

Six templates get the same prefix added to their hardcoded absolute links:

| File | Link(s) |
|---|---|
| `base.html` | nav: `/` → `/legacy/`, `/runs` → `/legacy/runs`, `/series` → `/legacy/series` (`/static/reim.css` unchanged) |
| `runs.html` | `/runs/{{ run.id }}` → `/legacy/runs/{{ run.id }}` |
| `run_detail.html` | `/runs` → `/legacy/runs` |
| `run_not_found.html` | `/runs` → `/legacy/runs` |
| `series.html` | form `action="/series"` → `action="/legacy/series"` |
| `series_not_found.html` | `/series` → `/legacy/series` |

### 2.7 `frontend/src/components/Header.tsx`: interim nav fix

`NAV_LINKS` for "Series" and "Operaciones" point at `/legacy/series/` and
`/legacy/runs/` instead of the not-yet-built `/series/`/`/runs/` Next pages,
so those nav items keep showing real content (the `apps/web` views) instead
of 404ing the moment this ships. "Catálogo" stays at `/catalog/` — that page
has never existed anywhere, so there is no regression to avoid there (D5).
This is explicitly interim: the downstream catalog/observability plan
replaces both with native Next pages and these two links move back.

## 3. Decisions

| | Decision | Rationale |
|---|---|---|
| **D1** | Frontend image's runtime stage is `caddy:2.11.4-alpine`, not nginx or a bare static server | Already the pinned, measured build used twice in this repo (`deploy/Caddyfile`, the compose `caddy` service) — no new version or tool to reason about |
| **D2** | `file_server` lives only inside the frontend image's internal Caddyfile; every outer Caddy config (generic and panda) stays `reverse_proxy`-only | Matches the existing pattern with zero exceptions — panda's other 4 sites, and REIM's own current config, never use `file_server`. Keeps "redeploy" symmetric with the api container: build an image, restart a unit |
| **D3** | panda's live Caddy config is changed with `caddy validate` on a copy, then `reload` not `restart` | `docs/deployment-panda.md` already establishes this discipline because the process serves 4 unrelated sites; a syntax error taken live would break all of them |
| **D4** | `apps/web`'s own `APIRouter` gets `prefix="/legacy"` rather than stripping the prefix at the proxy (`handle_path`) | Keeps the URL structure's source of truth in the application code, not split across app routes and proxy config. Either way the 6 templates need their absolute links updated, so there's no simplicity difference — only where the prefix is declared |
| **D5** | "Catálogo" nav link is left pointing at `/catalog/` (still 404s); only "Series" and "Operaciones" get temporary `/legacy/*` redirects | `/catalog` was already a forward-reference to an unbuilt page before this change — redirecting it to nothing in `apps/web` either would be inventing behaviour that never existed, not preserving it |
| **D6** | Both the generic (`deploy/docker-compose.prod.yml` + `deploy/Caddyfile`) and panda-specific (`Quadlet` + `/etc/caddy/sites/reim.caddy` + `docs/deployment-panda.md`) paths are updated together | The repo's established convention: `docs/deployment-panda.md` exists specifically because it and `docs/deployment.md` are meant to stay in sync as two answers to the same question, not let one drift |

## 4. Testing

* `make check` and `make frontend-check` — already green at `0a97046`, re-run
  after the `apps/web` prefix and template changes.
* `caddy validate --adapter caddyfile` on both `deploy/Caddyfile` (generic)
  and the candidate panda `reim.caddy`, per D3.
* Generic: `podman compose -f deploy/docker-compose.prod.yml up -d --build`
  brings up all four services; curl each routing class from outside the
  compose network.
* Panda, after `systemctl --user restart reim-frontend.service` and
  `systemctl reload caddy` — same verification shape
  `docs/deployment-panda.md` already uses for the api container:

  ```text
  curl -sk https://reim.panda.home.arpa/                    → new frontend index.html
  curl -sk https://reim.panda.home.arpa/map/                 → new frontend map page
  curl -sk https://reim.panda.home.arpa/legacy/               → apps/web catalog page
  curl -sk https://reim.panda.home.arpa/legacy/runs           → apps/web run history
  curl -sk https://reim.panda.home.arpa/legacy/series          → apps/web series picker
  curl -sk https://reim.panda.home.arpa/api/v1/countries       → API JSON
  curl -sk https://reim.panda.home.arpa/static/reim.css        → apps/web stylesheet
  curl -sk https://reim.panda.home.arpa/health                 → {"status":"ok",...}
  curl -sk -w '%{http_code}' https://reim.panda.home.arpa/metrics -o /dev/null → 404
  ```
* Re-confirm `REIM_TRUSTED_PROXY_HOPS=1` still holds: forge
  `X-Forwarded-For` through the (now two-upstream) proxy and confirm it buys
  no fresh rate-limit allowance — same method `docs/deployment-panda.md`
  already used, re-run because a second upstream now exists behind the same
  proxy, even though the api container's own topology hasn't changed.

## 5. Out of scope

* **Retiring `apps/web` entirely.** It moves to `/legacy`; deletion waits
  for the downstream catalog/observability plan to reach parity, per the
  original frontend scaffold plan's own deferral.
* **`/catalog` and full `/runs` client rewrite.** Unchanged from the
  scaffold plan's scope — still a separate downstream plan.
* **`panda-prometheus` scraping the new frontend, or a Grafana dashboard for
  it.** Same reasoning `docs/deployment-panda.md` already gives for not
  wiring the api container into either — no other panda service is scraped
  this way, so it would be a new pattern, not a matched one.
* **A public ACME certificate for the frontend.** It shares
  `reim.panda.home.arpa`'s existing `tls internal` / Let's Encrypt handling
  — nothing new to configure.
* **Multiple `uvicorn` workers, HA, or scaling the frontend container.**
  Same single-process assumption the rest of this deployment already makes.
