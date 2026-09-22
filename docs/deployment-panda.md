# REIM on panda — an already-running example

`docs/deployment.md` is the generic guide, written for an operator with their
own host, a domain of their own, and no existing services to fit around. This
page documents a *specific*, real deployment — `https://reim.panda.home.arpa`
— that did not have that luxury: it landed on a home server already running
four other services (`git`, `grafana`, `n8n`, `cockpit`), each with its own
established reverse-proxy, container-management and database convention. This
deployment follows those conventions instead of
[`deploy/docker-compose.prod.yml`](../deploy/docker-compose.prod.yml)'s
standalone model, and this page records exactly what was set up and measured,
so a rebuild — or an equivalent deployment on a similarly-shaped host — does
not have to re-derive any of it from scratch.

The plan this deployment executed, with its full rationale for each decision,
is [`docs/superpowers/plans/2026-09-21-panda-deployment.md`](superpowers/plans/2026-09-21-panda-deployment.md).
This page is the shorter, "what is actually running" record; that one is the
"why", task by task.

## Why not `deploy/docker-compose.prod.yml` as-is

That file assumes it owns ports 80/443 with its own Caddy container obtaining
a public Let's Encrypt certificate. Neither holds on panda:

- Port 443 is already owned by a system-wide Caddy serving four other sites.
- `reim.panda.home.arpa` is an RFC 8375 private-use name — no public CA can
  ever validate it, so public ACME was never going to work here regardless of
  what owned the port.

`docs/deployment.md` stays correct for the audience it was written for; this
is the adaptation for a host that already had its own answers to "how do
services get TLS and a domain" and "how are containers managed" before REIM
existed.

## Architecture

| Layer | panda's existing convention | What REIM uses |
|---|---|---|
| Reverse proxy | One native, system-wide Caddy (`caddy.service`, v2.11.4), one file per site under `/etc/caddy/sites/`, `tls internal` (Caddy's own local CA, not ACME) | `/etc/caddy/sites/reim.caddy` |
| Containers | Rootless Podman, managed as **Quadlets** (`~/.config/containers/systemd/*.container`, `systemctl --user`) — not `docker compose` / `podman compose` | `~/.config/containers/systemd/reim-api.container`, `~/.config/containers/systemd/reim-frontend.container` |
| Database | One shared `panda-postgres` instance; each app gets its own database and same-named role inside it (confirmed live for gitea and n8n before this deployment) | Database `reim`, role `reim`, inside `panda-postgres` |
| App config | `/srv/containers/<app>/<app>.env`, plain `KEY=value`, outside git | `/srv/containers/reim/reim.env` |

### `/etc/caddy/sites/reim.caddy`

```caddyfile
reim.panda.home.arpa {
	tls internal
	header Strict-Transport-Security "max-age=31536000; includeSubDomains"

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

	handle /docs* {
		reverse_proxy 127.0.0.1:8000
	}

	handle /redoc {
		reverse_proxy 127.0.0.1:8000
	}

	handle /openapi.json {
		reverse_proxy 127.0.0.1:8000
	}

	handle {
		reverse_proxy 127.0.0.1:8080
	}
}
```

This ports the two hardening properties `docs/deployment.md`'s own table
cares about — `/metrics` closed at the proxy, HSTS — out of
[`deploy/Caddyfile`](../deploy/Caddyfile) and into this host's per-site shape,
rather than losing them when the compose file's own `caddy` service is
dropped.

Updated for the frontend deployment (`docs/superpowers/specs/2026-09-21-frontend-deployment-integration-design.md`):
the api container now answers only `/api/*`, `/legacy*` (`apps/web`, relocated
there so the new frontend could take the root path), `/static/*`, `/health`,
`/ready`, `/docs*`, `/redoc` and `/openapi.json`; everything else — the
default `handle` — goes to the new frontend container on `127.0.0.1:8080`
instead of the api container.

**Two corrections applied after the initial rollout, both caught by a final
whole-branch review, not by inspection:**

- **`/docs`, `/docs/oauth2-redirect`, `/redoc` and `/openapi.json` were
  missing from the first version of this file's routing split** — an
  omission, not a decision; `docs/deployment.md` and `README.md` both
  document these as intentionally open, and this file's five-`handle` first
  draft simply didn't carry that forward. Added the three `handle` blocks
  above (`/docs*`, not `/docs` alone — `docs/deployment.md` itself notes the
  bare form misses `/docs/oauth2-redirect`).
- **HSTS moved from inside the default `handle` to the site-block level.**
  The first version left `header Strict-Transport-Security ...` nested only
  in the catch-all `handle` (the one now pointing at the frontend), so every
  api-routed response — `/api/*`, `/legacy*`, `/health`, the newly-restored
  `/docs*`, all of it — stopped carrying the header. Verified live before
  and after: `curl -sk -D - https://reim.panda.home.arpa/api/v1/countries`
  had no `strict-transport-security` line beforehand, has one after.

### `~/.config/containers/systemd/reim-api.container`

```ini
[Unit]
Description=Panda REIM API
After=network-online.target postgres.service
Wants=network-online.target
Requires=postgres.service

[Container]
Image=localhost/reim-api:prod
ContainerName=panda-reim-api
Network=panda-net
EnvironmentFile=/srv/containers/reim/reim.env
PublishPort=127.0.0.1:8000:8000
Exec=sh -c "alembic upgrade head && python -m reim.cli db seed && uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers"

[Service]
Restart=always
TimeoutStartSec=300

[Install]
WantedBy=default.target
```

Same shape as the existing `gitea.container` / `n8n.container` units:
`Network=panda-net` (so `panda-postgres` resolves by name),
`PublishPort=127.0.0.1:<port>:<port>` (Caddy reaches it over loopback, nothing
else can), `Restart=always`. `Exec=` carries the same
migrate-then-seed-then-serve command
`deploy/docker-compose.prod.yml` already runs for the standalone case — only
how the container is launched differs, not what it does once running.

### `~/.config/containers/systemd/reim-frontend.container`

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

Same shape as `reim-api.container`, minus what it doesn't need: no
`Requires=postgres.service` (the frontend has no database dependency), no
`EnvironmentFile=` (a static export has nothing to configure at runtime), and
`Exec=` is unset — `deploy/Dockerfile.frontend` overrides no `CMD` of its
own, so the runtime stage inherits the `caddy:2.11.4-alpine` base image's own
`CMD` (which runs Caddy against `/etc/caddy/Caddyfile`); the Dockerfile just
replaces which file that is with `deploy/Caddyfile.frontend`. No `Exec=`
override is needed in the Quadlet for that reason.

### `/srv/containers/reim/reim.env`

Real values redacted; shape only — see `docs/deployment.md`'s "Secrets"
section for what every other `REIM_*` variable defaults to when left unset.

```text
REIM_DATABASE_URL=postgresql+psycopg://reim:<password>@panda-postgres:5432/reim
REIM_ENVIRONMENT=production
REIM_LOG_LEVEL=INFO
REIM_LOG_JSON=true
REIM_CORS_ALLOW_ORIGINS=https://reim.panda.home.arpa
REIM_TRUSTED_PROXY_HOPS=1
REIM_METRICS_ENABLED=true
```

`REIM_TRUSTED_PROXY_HOPS` stays `1` for the same reason it does in
`deploy/docker-compose.prod.yml`: exactly one proxy (this Caddy) sits in
front, and it is the *identical* Caddy build (`v2.11.4`) already measured
there to overwrite `X-Forwarded-For` rather than append to it — confirmed
again below, against this real deployment, not just cited from the container
measurement.

## What was actually run, and what it actually did

Provisioning the database, inside the existing `panda-postgres` container —
matching gitea's and n8n's own database-per-app pattern, confirmed live
before creating REIM's:

```text
podman exec panda-postgres psql -U pandaadmin -d postgres -c "CREATE ROLE reim WITH LOGIN PASSWORD '...';"
podman exec panda-postgres psql -U pandaadmin -d postgres -c "CREATE DATABASE reim OWNER reim ENCODING 'UTF8';"
```

Building the image (Quadlets have no `build:` context the way compose does —
the image must exist, tagged, before the unit starts):

```text
podman build -t localhost/reim-api:prod -f Dockerfile .
→ Successfully tagged localhost/reim-api:prod
```

One observed wrinkle: Podman warned
`HEALTHCHECK is not supported for OCI image format and will be ignored. Must
use 'docker' format` — the `Dockerfile`'s `HEALTHCHECK` directive is silently
dropped under Podman's default OCI output format. Not load-bearing here (the
Quadlet doesn't reference the image's own healthcheck), but a real deviation
from what the `Dockerfile` declares, not a hypothetical one.

Starting the service:

```text
systemctl --user daemon-reload
systemctl --user start reim-api.service
```

Migrations ran clean against the fresh database on first start
(`alembic.runtime.migration`, four revisions applied in sequence), followed by
seeding and `uvicorn` startup, all inside the same `Exec=` command.

Validating the Caddy site file *before* touching the live config — this
matters because a syntax error taken live here could have broken TLS for
`git`/`grafana`/`n8n`/`cockpit`, not just REIM:

```text
caddy validate --config <candidate-copy>/Caddyfile --adapter caddyfile
→ Valid configuration
```

Only then was the real file written and the running Caddy reloaded — with
`reload`, not `restart`, matching the unit's own
`ExecReload=/usr/bin/caddy reload --config /etc/caddy/Caddyfile --force`:

```text
sudo cp <candidate>/reim.caddy /etc/caddy/sites/reim.caddy
sudo systemctl reload caddy
```

Confirmed afterward: `caddy.service` stayed `active (running) since` its
original two-days-ago start time (a reload, not a restart — the other four
sites' listeners and certificates were never interrupted), and the other four
`sites/*.caddy` files' modification times were untouched.

## Adding the frontend

Built and started the same way as the api container, following the same
Quadlet shape:

```text
podman build -t localhost/reim-frontend:prod -f deploy/Dockerfile.frontend .
→ Successfully tagged localhost/reim-frontend:prod

systemctl --user daemon-reload
systemctl --user start reim-frontend.service
→ active (running)
```

Then the same validate-before-touching-live discipline as the original
`reim.caddy` rollout: a candidate copy edited and validated
(`caddy validate --config <candidate-copy>/reim.caddy --adapter caddyfile` →
`Valid configuration`) before `sudo cp` over the live file and
`sudo systemctl reload caddy`.

**A real gap, found by the verification below, not by inspection:** after
the reload, `/legacy/*` 404'd — including hit directly against
`127.0.0.1:8000`, bypassing Caddy entirely, which ruled out a routing
mistake. `panda-reim-api` was still running the image built *before* the
`/legacy` prefix change landed in `apps/web/routes.py` — deploying the
frontend doesn't touch the api container at all, and nothing about that
change alone would have told an operator the api image was now stale too.
Fixed with the api container's own already-documented redeploy recipe below
(`podman build` + `systemctl --user restart reim-api.service`), not a new
procedure. The lesson: **a code change that lands in `apps/web` needs an api
redeploy alongside any frontend routing change that starts depending on
it** — the two are easy to treat as independent deploys because they build
and ship as separate images, but here one's route contract was the other
one's assumption.

## Verified

```text
curl -sk https://reim.panda.home.arpa/health
→ {"status":"ok","version":"0.1.0"}

curl -sk https://reim.panda.home.arpa/ready
→ {"status":"ready","version":"0.1.0","checks":{"database":true}}

curl -sk -w '%{http_code}' https://reim.panda.home.arpa/metrics -o /dev/null
→ 404
```

Re-verified after adding the frontend, each path checked against the content
it should actually serve, not just its status code:

```text
curl -sk https://reim.panda.home.arpa/          → 200, <title>REIM — Monitor Económico Regional de Centroamérica</title>
curl -sk https://reim.panda.home.arpa/map/      → 200
curl -sk https://reim.panda.home.arpa/legacy/   → 200, <title>Catalog · REIM</title>
curl -sk https://reim.panda.home.arpa/legacy/runs    → 200
curl -sk https://reim.panda.home.arpa/legacy/series  → 200
curl -sk https://reim.panda.home.arpa/api/v1/countries → 200
curl -sk https://reim.panda.home.arpa/static/reim.css  → 200
```

Re-verified again after the two corrections above (restoring `/docs*`/`/redoc`/
`/openapi.json`, hoisting HSTS):

```text
curl -sk https://reim.panda.home.arpa/docs                 → 200
curl -sk https://reim.panda.home.arpa/docs/oauth2-redirect  → 200
curl -sk https://reim.panda.home.arpa/redoc                  → 200
curl -sk https://reim.panda.home.arpa/openapi.json             → 200
curl -sk -D - https://reim.panda.home.arpa/                     → strict-transport-security present
curl -sk -D - https://reim.panda.home.arpa/api/v1/countries      → strict-transport-security present
curl -sk -D - https://reim.panda.home.arpa/legacy/                → strict-transport-security present
```

Also re-verified the frontend's own interim `/legacy` links no longer emit a
trailing slash (the earlier rollout's actual bug — `apps/web`'s routes have
none, so a trailing-slash request 307-redirected to a plain `http://` URL,
which panda refuses with no port-80 listener): `grep -rn
'href="/legacy/[^"]*/"' frontend/out/*.html` returns nothing after the fix,
and `curl -sk https://reim.panda.home.arpa/legacy/series` (the unslashed form
the frontend now actually links to) returns `200` directly, no redirect.
Typing the trailing-slash form by hand still 307s to `http://` — that's
`apps/web`'s own `redirect_slashes` behavior, unrelated to and unchanged by
this fix; the fix was making sure nothing shipped ever asks for that form.

**The rate-limit/proxy-identity measurement was re-run against this real
deployment, not just cited from the pinned container image.** Same method
`docs/deployment.md` itself uses: exhaust the anonymous allowance, then send
forged `X-Forwarded-For` headers and confirm they buy no bypass.

```text
# 61 plain requests to exhaust the default 60/minute anonymous allowance, then:
curl ... (no header)                              → 429
curl ... -H 'X-Forwarded-For: 1.2.3.4'             → 429
curl ... -H 'X-Forwarded-For: 9.9.9.9'             → 429
```

All three refused. This system Caddy behaves identically to the
`caddy:2.11.4-alpine` container `deploy/docker-compose.prod.yml` pins — same
version, same result, now measured on this exact topology (loopback to a
Quadlet-managed container, not a compose bridge network) rather than assumed
to transfer.

A first real ingestion and a first API key were both run for real:

```text
podman exec panda-reim-api reim key create --label "grafana"
→ (token printed once; not recoverable — stored outside this repo)

podman exec panda-reim-api reim pipeline run worldbank_ni_exchange_rate
→ ✓ worldbank_ni_exchange_rate  success  extracted=66 inserted=66 updated=0
    unchanged=0 rejected=0 (3326 ms)
```

The 4 quality-check failures that run also logged are the same documented
"success with some checks failing" outcome `docs/deployment.md` already
describes — not specific to this deployment. Confirmed the data reached the
public API afterward:

```text
curl -sk 'https://reim.panda.home.arpa/api/v1/observations?country=NI&indicator=ni_exchange_rate_official_annual_avg&page_size=2'
→ {"meta":{"total":66,...},"data":[...]}
```

## Scheduling ingestion — converted to this host's real timezone

`reim pipeline schedule`'s own printed header says its times are UTC. panda's
`crond` runs in `America/Managua` (UTC−6, no DST) — installing the printed
lines unchanged would run every job six hours off from what the schedule's own
comment claims. Every line below is the printed UTC time with 6 hours
subtracted (none of the five cross a day boundary, so only the hour field
moves):

```cron
# REIM — generated from `reim pipeline schedule` (UTC) and converted to this
# host's local timezone (America/Managua, UTC-6). Re-derive with
# `podman exec panda-reim-api reim pipeline schedule --working-dir /app`
# and re-subtract 6h if the pipeline catalog's cadences change.

# daily — banguat_exchange_rate, bcn_exchange_rate
0 7 * * * podman exec panda-reim-api reim pipeline run-all --frequency daily

# monthly — 12 pipelines (cepalstat_*, imf_imts_*, inide_cpi_monthly, siboif_bank_balance)
15 7 5 * * podman exec panda-reim-api reim pipeline run-all --frequency monthly

# quarterly — cepalstat_bop_quarterly, sieca_services_trade
25 7 10 1,4,7,10 * podman exec panda-reim-api reim pipeline run-all --frequency quarterly

# annual — 9 pipelines (cepalstat_debt_annual, cepalstat_gdp_annual, inec_pa_provincial, worldbank_ni_*)
45 7 15 4 * podman exec panda-reim-api reim pipeline run-all --frequency annual

# Alerting — after the ingestion window
0 9 * * * podman exec panda-reim-api reim alert check
```

Unlike `docs/deployment.md`'s own crontab section (written for
`podman compose exec`), these lines call `podman exec panda-reim-api`
directly — there is no compose project here, just the Quadlet's container
name. `/usr/bin/podman` is on cron's default minimal `PATH`, confirmed before
installing.

## Operating this deployment

- **Logs:** `journalctl --user -u reim-api -f`, or `podman logs -f
  panda-reim-api`.
- **Status:** `systemctl --user status reim-api.service`.
- **Redeploying a code change:** Quadlets have no build step of their own —
  rebuild the tag, then restart the unit:
  ```text
  podman build -t localhost/reim-api:prod -f Dockerfile .
  systemctl --user restart reim-api.service
  ```
- **Redeploying the frontend:** same shape as the api container —
  ```text
  podman build -t localhost/reim-frontend:prod -f deploy/Dockerfile.frontend .
  systemctl --user restart reim-frontend.service
  ```
  If the change also touched `apps/web` (or anything else the api container
  serves), redeploy the api container too — see "Adding the frontend" above
  for what happens when that's skipped.
- **Changing `reim.env`:** edit `/srv/containers/reim/reim.env`, then
  `systemctl --user restart reim-api.service` to pick it up (Quadlets read the
  `EnvironmentFile=` fresh on each container start, same as compose's
  `--force-recreate`).
- **Caddy config changes:** always validate a candidate copy with
  `caddy validate --config <copy>/Caddyfile --adapter caddyfile` before
  touching `/etc/caddy/sites/reim.caddy` for real, and reload
  (`sudo systemctl reload caddy`) rather than restart — this Caddy serves
  four other sites.

## Deliberately not done here

Carried over unchanged from the plan's own list — nothing below was skipped
by oversight:

- **`panda-prometheus` does not scrape REIM's `/metrics`.** It currently
  scrapes only `node_exporter`; none of gitea/grafana/n8n are scraped either,
  so wiring REIM in would be a new pattern for this host, not a matched one.
- **No Grafana dashboard for REIM.** Same reasoning.
- **No REIM-specific backup job.** `docs/deployment.md`'s `pg_dump` command
  needs `-U reim -d reim` unchanged but a different container name
  (`panda-postgres`, not this deployment's own `postgres` service, which does
  not exist here) — whether panda already backs up `panda-postgres` as a
  whole should be checked before adding a second, REIM-specific mechanism.
- **Only one `uvicorn` worker.** Same single-process assumption
  `docs/deployment.md`'s "Limits of this deployment" section already states.
