# Deploy REIM on panda, matching its existing service architecture

> **Status: PLAN ONLY.** Nothing in this document has been executed. Every
> step below is presented for review; per this session's human-gated
> workflow, writing any of these files or running any mutating command
> requires a separate, explicit go-ahead — and the steps marked **[sudo]**
> touch state shared with four other live services (git, grafana, n8n,
> cockpit), so they are called out individually rather than bundled.

**Goal:** Serve REIM at `https://reim.panda.home.arpa`, reachable the same
way `grafana.panda.home.arpa`, `git.panda.home.arpa` and
`n8n.panda.home.arpa` already are — same reverse proxy, same TLS model, same
container-management mechanism, same shared database — not the generic
standalone stack `docs/deployment.md` and `deploy/docker-compose.prod.yml`
describe for an operator with their own host.

**Why not just run `deploy/docker-compose.prod.yml` as documented:** that
file assumes it owns ports 80/443 with its own Caddy container getting a
public Let's Encrypt certificate. Neither is true here — panda's port 443 is
already owned by a system-wide Caddy serving four other sites, and
`reim.panda.home.arpa` is an RFC 8375 private-use name no public CA can ever
validate. `docs/deployment.md` stays correct for its documented audience (an
operator with a real domain and a spare host); this plan is the panda-specific
adaptation, not a replacement for it.

## Measured facts about panda (verified live this session, not assumed)

- **Reverse proxy:** one system-wide, natively-installed Caddy
  (`caddy.service`, `/usr/lib/systemd/system/caddy.service`, root-owned,
  `v2.11.4` — the *exact* version `deploy/docker-compose.prod.yml` already
  pins, so this repo's own measured X-Forwarded-For/hop-count findings
  transfer directly, not just by assumption). It owns ports 80 and 443
  host-wide. `/etc/caddy/Caddyfile` is two lines:
  ```caddyfile
  {
  	auto_https disable_redirects
  }

  import sites/*.caddy
  ```
  Each service gets its own file under `/etc/caddy/sites/`, e.g.
  `grafana.caddy`:
  ```caddyfile
  grafana.panda.home.arpa {
  	tls internal
  	reverse_proxy 127.0.0.1:3000
  }
  ```
  `tls internal` — Caddy's own local CA, not ACME — is used for every
  `*.panda.home.arpa` site, for the reason `docs/deployment.md` already
  documents in the abstract: no public CA can issue for a private name.
- **Containers:** rootless Podman, managed as **Quadlets**
  (`~/.config/containers/systemd/*.container`, user-level systemd units,
  `systemctl --user`), not `docker compose` / `podman compose`. Each unit
  follows one shape: `Image=`, `ContainerName=panda-<app>`, `Network=`,
  `EnvironmentFile=/srv/containers/<app>/<app>.env`, `Volume=` bind mounts
  under `/srv/containers/<app>/`, `Restart=always`, `WantedBy=default.target`.
- **Database:** one shared Postgres instance, `panda-postgres`
  (`postgres:18-alpine`), on a dedicated bridge network `panda-net`
  (DNS-enabled, so containers reach it by name). Gitea and n8n each have
  their **own database and same-named role** inside it — confirmed live:
  ```text
  gitea  | owner gitea
  n8n    | owner n8n
  ```
  — not one shared schema, and not a separate Postgres container per app.
  This plan gives REIM a `reim` database and `reim` role the same way.
- **Ports already bound on `127.0.0.1`:** `3000` (grafana), `3001` (gitea),
  `5678` (n8n), `9090` (cockpit), `9091` (prometheus), `9100` (node exporter),
  `2019` (Caddy's admin API), `631` (cups), `53` (dns). `8000` — REIM's own
  container port, per `Dockerfile`'s `EXPOSE 8000` — is free.
- **Monitoring:** `panda-prometheus` exists but currently scrapes only
  `node_exporter` (`/srv/containers/prometheus/config/prometheus.yml`) — none
  of grafana/gitea/n8n are scraped either. Wiring REIM's `/metrics` into it
  would be a *new* pattern, not matching an existing one, so this plan leaves
  it as an explicit follow-up, not a required step.
- **Filesystem ownership:** `/srv/containers/` and `/etc/caddy/sites/` are
  both root-owned (`drwxr-xr-x root:root`); each app's own subdirectory
  under `/srv/containers/` is `chown`ed to `blackzero` *after* creation.
  `~/.config/containers/systemd/` is already owned by `blackzero` — no sudo
  needed there.
- **sudo:** requires a password interactively (`sudo -n true` fails). No
  step in this plan assumes passwordless root.
- **Timezone:** `America/Managua` (CST, UTC-6). `reim pipeline schedule`'s
  own output is explicit that its printed times are UTC — installing its
  crontab verbatim on this host's cron (which runs in local time) would run
  ingestion six hours off from what the printed comment claims. This plan's
  cron step converts explicitly rather than installing the printed lines
  unchanged.
- **No existing crontab** for `blackzero` — nothing to conflict with.
- **Disk:** 385G free on `/` — not a constraint.

## Design decisions this plan makes, and why

1. **Keep REIM's own dedicated Postgres role/database, inside the shared
   `panda-postgres` container, not a second Postgres container.** Matches
   gitea/n8n exactly. `deploy/docker-compose.prod.yml`'s own `postgres`
   service is not used on this host at all — it exists for the
   standalone-operator case `docs/deployment.md` documents.
2. **Drop `deploy/docker-compose.prod.yml`'s own `caddy` service entirely.**
   Its job (TLS termination, HSTS, closing `/metrics`) is taken over by a new
   `/etc/caddy/sites/reim.caddy` file on the system Caddy — but the specific
   hardening properties `docs/deployment.md`'s own table cares about (HSTS
   header, `/metrics` closed at the proxy) are ported into that file
   verbatim, not silently dropped. `REIM_TRUSTED_PROXY_HOPS` stays `1`: the
   system Caddy is still exactly one proxy in front, and it is the identical
   Caddy build already measured to overwrite (not append to)
   `X-Forwarded-For`.
3. **Publish `api`'s port to `127.0.0.1:8000` only**, matching gitea
   (`127.0.0.1:3001`) and n8n (`127.0.0.1:5678`) — reachable from the host's
   Caddy, not from the network.
4. **Build the image locally with `podman build`, tag it, reference the tag
   from the Quadlet.** Quadlets have no `build:` context the way compose
   does; the image has to exist before the unit starts. Re-deploying a code
   change means rebuilding the tag and restarting the unit — this plan's
   last task states that explicitly so it isn't rediscovered later.
5. **No separate ingestion/scheduler container.** Matches
   `docs/deployment.md`'s own design (ingestion is triggered, not automatic)
   — a cron entry runs `podman exec panda-reim-api ...` the same shape
   `docs/deployment.md` already documents for the compose case, adjusted for
   Quadlet's container name and this host's real timezone.

## Global constraints

- Every step that touches `/etc/caddy/` or reloads `caddy.service` is
  **[sudo]** and is a shared-blast-radius action: a syntax error taken live
  can break TLS for git/grafana/n8n/cockpit, not just REIM. Each such step
  below runs `caddy validate` against the *candidate* config before any
  reload, and the existing `sites/*.caddy` files are listed, not touched.
- Steps with no **[sudo]** tag run as `blackzero`, no privilege escalation,
  and touch only paths already owned by `blackzero` (`~/.config/containers/
  systemd/`, this git checkout, `panda-net`-scoped `podman exec`).
- Never write a real password into a file this plan creates in the
  repository. Secrets (the `reim` Postgres role's password,
  `REIM_CORS_ALLOW_ORIGINS`'s value is not a secret but the DB password is)
  live only in `/srv/containers/reim/reim.env`, outside git, generated with
  `openssl rand -base64 32` at execution time — this plan shows the file's
  *shape*, never a real value.
- `reim-test-postgres` (this session's dev/test container, port `55432`) and
  `panda-postgres` are different containers. Nothing here touches
  `reim-test-postgres`.

---

## Task 1: Provision the database

**[no sudo]**

```bash
PGADMIN=pandaadmin   # confirmed live: podman exec panda-postgres psql -U pandaadmin -d postgres -c "\du"
REIM_DB_PASSWORD=$(openssl rand -base64 32)
podman exec panda-postgres psql -U "$PGADMIN" -d postgres -c \
  "CREATE ROLE reim WITH LOGIN PASSWORD '${REIM_DB_PASSWORD}';"
podman exec panda-postgres psql -U "$PGADMIN" -d postgres -c \
  "CREATE DATABASE reim OWNER reim ENCODING 'UTF8';"
```

Verify (matches the live `\l` / `\du` output already captured this session,
now with a fifth row):

```bash
podman exec panda-postgres psql -U "$PGADMIN" -d postgres -c "\l" | grep reim
podman exec panda-postgres psql -U "$PGADMIN" -d postgres -c "\du" | grep reim
```

Record `$REIM_DB_PASSWORD` for Task 3 — it is not retrievable from Postgres
afterward, the same one-shot property `docs/deployment.md` already notes for
API keys.

## Task 2: Build the image

**[no sudo]**

```bash
cd /home/blackzero/Documentos/GitHub/REIM-Proyect
podman build -t localhost/reim-api:prod -f Dockerfile .
```

Verify:

```bash
podman image inspect localhost/reim-api:prod --format '{{.Config.ExposedPorts}}'
# expect: map[8000/tcp:{}]
```

## Task 3: Create `/srv/containers/reim/` and its env file

**[sudo]** for the `mkdir`/`chown` (matches how every existing app directory
under `/srv/containers/` was set up — root-owned parent, `blackzero`-owned
child); **[no sudo]** for writing the file itself once the directory exists.

```bash
sudo mkdir -p /srv/containers/reim
sudo chown blackzero:blackzero /srv/containers/reim
```

`/srv/containers/reim/reim.env` (mirrors gitea/n8n's env-file shape — plain
`KEY=value`, no quoting):

```text
REIM_DATABASE_URL=postgresql+psycopg://reim:REPLACE_WITH_TASK_1_PASSWORD@panda-postgres:5432/reim
REIM_ENVIRONMENT=production
REIM_LOG_LEVEL=INFO
REIM_LOG_JSON=true
REIM_CORS_ALLOW_ORIGINS=https://reim.panda.home.arpa
REIM_TRUSTED_PROXY_HOPS=1
REIM_METRICS_ENABLED=true
```

Every other `REIM_*` setting `docs/deployment.md`'s "Secrets" section lists
(rate limits, alerting, paging, export size, database pool, outbound HTTP)
keeps its application default by staying absent — same rule as the compose
`.env`, just a different file format (no `${VAR:-default}` needed since
nothing here reads this file through compose's substitution).

## Task 4: The Quadlet unit

**[no sudo]** — `~/.config/containers/systemd/` is already `blackzero`-owned.

`~/.config/containers/systemd/reim-api.container`:

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

Matches gitea/n8n's shape exactly: same `Network=panda-net` (so
`panda-postgres` resolves by name), same `PublishPort=127.0.0.1:<port>:<port>`
pattern, same `Restart=`/`TimeoutStartSec=`/`WantedBy=`. `Exec=` carries the
same migrate-then-seed-then-serve command `deploy/docker-compose.prod.yml`
already runs for the standalone case — the container's actual startup
behavior is unchanged, only how it's launched differs.

```bash
systemctl --user daemon-reload
systemctl --user start reim-api.service
systemctl --user status reim-api.service --no-pager
```

Verify from the host, before Caddy is involved at all (mirrors
`docs/deployment.md`'s own "Verify it" step, against the published port
directly instead of through TLS):

```bash
curl -s http://127.0.0.1:8000/health
# expect: {"status":"ok","version":"0.1.0"}
curl -s http://127.0.0.1:8000/ready
# expect: {"status":"ready","version":"0.1.0","checks":{"database":true}}
```

## Task 5: The Caddy site file

**[sudo]** — shared blast radius. Validate before touching the live config.

`/etc/caddy/sites/reim.caddy` — ports the two hardening properties
`docs/deployment.md`'s table calls out (`/metrics` closed, HSTS) from
`deploy/Caddyfile` into this host's per-site shape:

```caddyfile
reim.panda.home.arpa {
	tls internal

	handle /metrics {
		respond 404
	}

	handle /metrics/ {
		respond 404
	}

	handle {
		header Strict-Transport-Security "max-age=31536000; includeSubDomains"
		reverse_proxy 127.0.0.1:8000
	}
}
```

Validate against a *copy* of the live config before touching the real one —
never adapt `/etc/caddy/Caddyfile` in place first:

```bash
sudo mkdir -p /tmp/caddy-check/sites
sudo cp /etc/caddy/Caddyfile /tmp/caddy-check/
sudo cp /etc/caddy/sites/*.caddy /tmp/caddy-check/sites/
# (the new file, written above, copied in alongside the other four)
sudo cp /path/to/reim.caddy /tmp/caddy-check/sites/reim.caddy
caddy validate --config /tmp/caddy-check/Caddyfile --adapter caddyfile
```

Only once that returns clean:

```bash
sudo cp /tmp/caddy-check/sites/reim.caddy /etc/caddy/sites/reim.caddy
sudo systemctl reload caddy
systemctl status caddy --no-pager | head -5   # confirm still "active (running)"
```

`systemctl reload` — not `restart` — matches the unit's own
`ExecReload=/usr/bin/caddy reload --config /etc/caddy/Caddyfile --force`,
already confirmed live this session: Caddy's own zero-downtime reload, not a
process restart that would drop the other four sites' listeners.

## Task 6: Verify end-to-end, including the X-Forwarded-For measurement

**[no sudo]**

```bash
curl -sk https://reim.panda.home.arpa/health
curl -sk https://reim.panda.home.arpa/ready
curl -sk 'https://reim.panda.home.arpa/api/v1/countries?page_size=3'
curl -sk -w '%{http_code}' https://reim.panda.home.arpa/metrics -o /dev/null
# expect: 404
```

`-k` is required unless Caddy's local CA root is separately trusted by this
shell's CA store — matches `docs/deployment.md`'s own documented tradeoff for
`tls internal`, not a new gap this plan introduces.

Re-run this repo's own rate-limit-bypass measurement against the *real*
system Caddy, not just cite the container measurement — same Caddy binary
version, but a fresh topology deserves a fresh check per this project's own
standing rule (name the rival hypothesis, don't assume a transferred result):

```bash
# Exhaust the anonymous allowance, then confirm a forged X-Forwarded-For buys no bypass.
for i in $(seq 1 61); do curl -sk -o /dev/null https://reim.panda.home.arpa/api/v1/countries; done
curl -sk -o /dev/null -w '%{http_code}\n' -H 'X-Forwarded-For: 1.2.3.4' https://reim.panda.home.arpa/api/v1/countries
# expect: 429, matching docs/deployment.md's own three-forged-header result
```

## Task 7: Mint a key, run one real ingestion

**[no sudo]** — same commands `docs/deployment.md` gives, `podman exec`
instead of `podman compose exec` since this is a Quadlet-managed container:

```bash
podman exec panda-reim-api reim key create --label "grafana"
podman exec panda-reim-api reim pipeline run worldbank_ni_exchange_rate
```

## Task 8: Cron, converted to this host's real timezone

**[no sudo]**

```bash
podman exec panda-reim-api reim pipeline schedule --working-dir /app
```

Its printed lines are UTC (`reim pipeline schedule`'s own header comment
says so); this host's cron runs in `America/Managua` (UTC-6). Subtract 6
hours from each printed field before installing, and substitute the command
the same way `docs/deployment.md` does for the compose case — `podman exec`
naming the Quadlet's container, not `podman compose exec`:

```cron
# Example: a line printed as "0 13 * * * ... run-all --frequency daily" (13:00 UTC)
# installs as 07:00 local:
0 7 * * * podman exec panda-reim-api reim pipeline run-all --frequency daily
# Similarly for monthly/quarterly/annual lines schedule prints, and:
0 9 * * * podman exec panda-reim-api reim alert check
```

(The alert-check line was printed at `0 15 * * *` UTC → `09:00` local — shift
every printed line by the same 6 hours, don't re-derive the minute/hour
arithmetic by hand per line.)

```bash
crontab -l 2>/dev/null | { cat; echo "<the converted lines above>"; } | crontab -
crontab -l   # confirm
```

## Deliberately not in this plan

- **Wiring `/metrics` into `panda-prometheus`.** No sibling service is
  scraped there today; adding REIM would be a new pattern for this host, not
  a matched one. A real, separately-scoped follow-up if wanted.
- **A Grafana dashboard for REIM.** Same reasoning — nothing to match yet.
- **Backups.** `docs/deployment.md`'s `pg_dump` command needs adjusting for
  the shared-Postgres case (`-U reim -d reim` still correct; the container
  name in the exec wrapper changes to `panda-postgres`) but this plan does
  not schedule it — ask whether panda already backs up `panda-postgres` as a
  whole (a reasonable single point to have to check, not to guess) before
  adding a second, REIM-specific mechanism.
- **Running more than one `uvicorn` worker.** Same single-process assumption
  `docs/deployment.md`'s "Limits of this deployment" section already states;
  nothing about panda's topology changes that tradeoff.

## Done when

- `systemctl --user status reim-api.service` shows `active (running)`.
- `https://reim.panda.home.arpa/health`, `/ready`, and one `/api/v1/*` route
  answer correctly through the system Caddy.
- `/metrics` returns `404` through the proxy (closed, matching every other
  hardening row `docs/deployment.md` documents).
- The X-Forwarded-For / rate-limit measurement is re-run against the real
  system Caddy and produces the same result already measured against the
  pinned container image.
- `reim` has its own database and role inside `panda-postgres`, confirmed via
  `\l` / `\du`, matching gitea and n8n's shape.
- At least one real ingestion has run and one real API key has been minted.
- A converted (not copy-pasted UTC) crontab is installed.
- No other site's Caddy config file was modified, and `caddy validate`
  passed against the full candidate config before the one live reload this
  plan performs.
