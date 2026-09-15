# Deploying REIM

This is the guide for running REIM as a service, not for trying it out.
[Quick start](../README.md#quick-start) in the README is for the second; this
page is for the first. It ships as two files under
[`deploy/`](../deploy/) — `docker-compose.prod.yml` and `Caddyfile` — plus
`.env.prod.example`, because a file can be started and measured, and a fenced
code block in a document cannot. Every command below was actually run against
this stack; every output shown was actually observed. Where the observation
had to deviate from the real procedure, that is called out explicitly rather
than folded silently into the instructions.

## Local deviations, disclosed once

Standing this stack up to write this guide happened on a workstation running
rootless Podman with no public domain. Two things about that session are not
part of the real procedure, and they explain small details in the command
output below:

- **Ports.** Rootless Podman cannot bind privileged ports: `caddy` fails to
  start with `rootlessport cannot expose privileged port 80, ... listen tcp
  0.0.0.0:80: bind: permission denied`. A real server, running the container
  engine as root or with `CAP_NET_BIND_SERVICE` granted, does not hit this.
  The verification commands in this guide were run against a local copy of
  `deploy/docker-compose.prod.yml` with only `"80:80"` → `"8080:80"` and
  `"443:443"` → `"8443:443"` changed, so they use `https://localhost:8443` /
  `http://localhost:8080` and pass curl's `-k` flag. On a real deployment,
  drop `-k`, use ports 80/443, and use your own domain in place of
  `localhost`.
- **The certificate.** With no public domain to issue for, `REIM_DOMAIN` was
  set to `localhost`. Caddy recognizes `localhost` as a local name and issues
  from its own internal CA automatically (`"issuer":"local"` in its log),
  which is why the verification commands below need `-k`. Point `REIM_DOMAIN`
  at a real domain with DNS already pointed at this host, and Caddy obtains
  and renews a real certificate for it instead — that part was not itself
  exercised in this session, since there was no public domain available to
  exercise it against.

If you run rootless Podman, `podman compose` also needs its API socket
running (`systemctl --user start podman.socket`) before it will do anything —
it does not start this on its own.

## Prerequisites

- A container engine with a compose plugin: `docker compose` or `podman
  compose`. (`podman compose` delegates to the `docker-compose` CLI plugin as
  an external compose provider.)
- Ports 80 and 443 free on the host — see the callout above if your engine
  cannot bind them.
- A domain whose DNS already points at this host, for Caddy's automatic TLS.

## Get the code

```text
git clone https://github.com/RobBravo/reim.git
cd reim
```

## Secrets, and how to generate them

Copy the example environment file and fill it in:

```text
cp deploy/.env.prod.example deploy/.env
```

`deploy/.env.prod.example` documents three required values, none with a
default — a wrong default is worse than a missing one that stops the stack
from starting:

```text
# The domain Caddy serves and obtains a certificate for.
REIM_DOMAIN=reim.example.org

# The origins allowed to call the API from a browser. Comma-separated.
# A wildcard here undoes the reason this file exists.
REIM_CORS_ALLOW_ORIGINS=https://reim.example.org

# The database password. Generate one: openssl rand -base64 32
POSTGRES_PASSWORD=
```

Generate the password:

```text
openssl rand -base64 32
```

Everything below that line in `deploy/.env.prod.example` already has a safe
default baked into `docker-compose.prod.yml` — `REIM_RATE_LIMIT_ANONYMOUS`
(60), `REIM_RATE_LIMIT_KEYED` (600) and `REIM_RATE_LIMIT_WINDOW_SECONDS` (60),
each matching `reim.core.config.Settings`'s own default — so leaving them
commented out changes nothing. Uncomment one only to tune it.

## Bring it up

```text
podman compose -f deploy/docker-compose.prod.yml --env-file deploy/.env up -d
```

(`docker compose` works the same way if that is your engine.) Expect:

```text
 Network reim-prod_reim Created
 Volume reim-prod_caddy_config Created
 Volume reim-prod_postgres_data Created
 Volume reim-prod_caddy_data Created
 Container reim-prod-postgres-1 Started
 Container reim-prod-postgres-1 Healthy
 Container reim-prod-api-1 Started
 Container reim-prod-api-1 Healthy
 Container reim-prod-caddy-1 Started
```

Exit status 0. `podman compose ... ps` afterward shows `postgres` and `api` as
`Up ... (healthy)`; `caddy` has no configured healthcheck, so compose reports
it simply as `Up`.

**The `api` container can take close to 30 seconds to show healthy even
though it is ready in about 6.5.** Measured on a cold start: migrations,
seeding and `uvicorn`'s own "Application startup complete" all finish around
6.5 seconds after the container starts, but Docker's/Podman's healthcheck
only polls once at `start_period` (20s) and then every `interval` (30s)
after that — so the first check (at ~0s) fails before the app is listening,
is forgiven because it is inside `start_period`, and the *next* scheduled
check, at the 30-second mark, is the one that reports healthy. `caddy`, which
waits on `api`'s healthcheck, is delayed by that same margin. This is
healthcheck cadence, not a failure — the whole three-service stack (network
and volume creation, both healthchecks, `caddy` starting) took 37 seconds
wall-clock on a rerun with the image already built.

## Verify it

Through Caddy (see the callout above for why these use `-k` and port 8443 —
on your own deployment, drop both and use your domain on 443):

```text
curl -sk https://localhost:8443/health
{"status":"ok","version":"0.1.0"}

curl -sk https://localhost:8443/ready
{"status":"ready","version":"0.1.0","checks":{"database":true}}

curl -sk 'https://localhost:8443/api/v1/countries?page_size=3'
→ HTTP 200, {"meta":{"total":7,...},"data":[{"iso2":"BZ","name":"Belize",...}, ...]}
```

(Seven countries, seeded by `db seed` as part of the `api` container's start
command.)

The database and the API are not reachable from the host directly — only
Caddy is:

```text
timeout 3 bash -c 'cat < /dev/tcp/127.0.0.1/5432'
→ connection refused, exit 1

timeout 3 bash -c 'cat < /dev/tcp/127.0.0.1/8000'
→ connection refused, exit 1
```

And `/metrics` is closed at the proxy:

```text
curl -sk -w '%{http_code}' https://localhost:8443/metrics -o /dev/null
→ 404
```

## Mint your first API key

REIM stays open without a key — a missing key is never an error, it just
gets the lower, anonymous allowance. Keys are minted from the CLI, never
over HTTP, since the API is read-only by design:

```text
podman compose -f deploy/docker-compose.prod.yml --env-file deploy/.env \
  exec api reim key create --label "grafana"

key    c4e38b27-ec77-4933-81e4-d72f27220a3c
label  grafana
token  reim_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

Store the token now — it is not recoverable.
```

(The token above is a placeholder — REIM stores only its SHA-256 hash, so
the real one printed during this guide's own verification is not
reproduced. Store your own the moment it is printed; there is no way to
retrieve it afterward.)

```text
podman compose ... exec api reim key list

ID                                     LABEL                STATUS  LAST USED
c4e38b27-ec77-4933-81e4-d72f27220a3c   grafana              active  2026-09-15T17:29:19...

podman compose ... exec api reim key revoke c4e38b27-ec77-4933-81e4-d72f27220a3c
Revoked.
```

Revocation is immediate — a revoked key gets `401`, not the anonymous
fallback, **provided your own anonymous allowance is not already exhausted
in the current window**: the rate limiter counts every request and checks
the limit *before* it looks at whether a presented key is valid, so a
request that both exhausts its own anonymous bucket and presents an
invalid or revoked key gets `429`, not `401`.

## Run your first ingestion

Ingestion is not automatic — trigger it explicitly, one source at a time:

```text
podman compose -f deploy/docker-compose.prod.yml --env-file deploy/.env \
  exec api reim pipeline run worldbank_ni_exchange_rate

✓ worldbank_ni_exchange_rate  success  extracted=66 inserted=66 updated=0
  unchanged=0 rejected=0 (1151 ms)
```

A run can report `success` while some of its quality checks still fail —
that measurement's run also logged 4 failing quality checks
(`pipeline.quality_failures`) while still inserting all 66 observations, an
outcome you would see with `reim quality report` afterward, not from this
line alone.

## Schedule ingestion

`reim pipeline schedule` reads the catalog and prints an installable
crontab fragment — one line per cadence in use, staggered so they don't all
collide at the same minute, plus the alert check:

```text
podman compose -f deploy/docker-compose.prod.yml --env-file deploy/.env \
  exec api reim pipeline schedule --working-dir /app

# REIM — generated by `reim pipeline schedule`. Review before installing.
# Times follow the cron daemon's timezone; the defaults were written as UTC.

# daily — 2 pipeline(s): banguat_exchange_rate, bcn_exchange_rate
0 13 * * * cd /app && .venv/bin/python -m reim.cli pipeline run-all --frequency daily

# ... (monthly, quarterly, annual, similarly)

# Alerting — after the ingestion window, since staleness is only meaningful
# once the day's ingestion has finished.
0 15 * * * cd /app && .venv/bin/python -m reim.cli alert check
```

**The printed command line does not run as shown inside this container.**
It invokes `.venv/bin/python`, but the image's virtualenv lives at
`/opt/venv` (`Dockerfile` sets `PATH="/opt/venv/bin:$PATH"`, and there is no
`.venv` directory in the runtime image) — that path is correct only for a
bare-metal install done with `make setup`, not for this containerized
deployment. Install the crontab on the **host**, keeping each line's
schedule (the fields before the command) and its subcommand, but replacing
`cd /app && .venv/bin/python -m reim.cli` with the same `podman compose
exec` invocation demonstrated above:

```text
0 13 * * * cd /path/to/reim && podman compose -f deploy/docker-compose.prod.yml --env-file deploy/.env exec -T api reim pipeline run-all --frequency daily
0 15 * * * cd /path/to/reim && podman compose -f deploy/docker-compose.prod.yml --env-file deploy/.env exec -T api reim alert check
```

This substitution was not itself run as a cron job during this guide's own
verification — what was verified is each piece of it separately: the
`pipeline schedule` output above (the timing fields and subcommands), the
`/opt/venv` vs. `.venv` mismatch (read from `Dockerfile`), and the `exec api
reim <subcommand>` form (run directly, for `pipeline run` and `alert check`,
elsewhere in this guide).

## Point alerting at a webhook

`REIM_ALERT_WEBHOOK_URL` is the setting (see `reim/core/config.py`); unset,
alerting still evaluates and reports on every run, it just delivers
nothing. Three more settings tune it: `REIM_ALERT_SEVERITY_FLOOR` (default
`error`), `REIM_ALERT_REPEAT_HOURS` (default `24`) and
`REIM_ALERT_STUCK_RUN_HOURS` (default `6`).

All four are wired through the `api` service's `environment:` block in
`deploy/docker-compose.prod.yml`, so setting one in `deploy/.env` reaches the
container — `tests/unit/test_deploy_artifacts.py` pins this, the same way it
already pinned the rate-limit settings. Uncomment the ones you want in
`deploy/.env.prod.example`:

```text
# Webhook REIM posts alert digests to. A Slack or Discord webhook carries its
# posting credential in the URL's own path, so this is a secret — left empty
# here on purpose; never fill in a real URL, and never fill in a
# plausible-looking fake one someone might paste unchanged into a real
# deployment. Unset (empty), alerting still evaluates and reports every run —
# it just delivers nothing.
# REIM_ALERT_WEBHOOK_URL=

# Minimum severity that reaches the webhook: info | warning | error | critical.
# REIM_ALERT_SEVERITY_FLOOR=error

# Hours to wait before repeating a standing alert about the same condition on
# the same pipeline.
# REIM_ALERT_REPEAT_HOURS=24

# Hours a pipeline run may sit in 'running' before it's flagged as stuck.
# REIM_ALERT_STUCK_RUN_HOURS=6
```

then recreate `api` so it picks up the new environment:

```text
podman compose -f deploy/docker-compose.prod.yml --env-file deploy/.env \
  up -d --force-recreate api
```

What was actually run and observed, with the webhook unset (the only variant
exercised in this guide's own verification — the wiring above is a verified
property of the compose file and its test, not a run with delivery actually
firing):

```text
podman compose -f deploy/docker-compose.prod.yml --env-file deploy/.env \
  exec api reim alert check

No alert conditions are firing.
```

Exit 0.

## Hardening

Each of these is a property of the shipped files, not just advice — and each
one is pinned by a test in `tests/unit/test_deploy_artifacts.py` so the two
cannot silently drift apart. Running that file confirms every row at once:

```text
.venv/bin/pytest tests/unit/test_deploy_artifacts.py -q
→ 6 passed
```

| Do this | How it's verified |
|---|---|
| **Publish no database or API port.** Only `caddy` has a `ports:` entry in `docker-compose.prod.yml`; `postgres` and `api` are reachable only over the compose network. | `test_only_caddy_publishes_ports`, and directly: connecting to `127.0.0.1:5432` and `127.0.0.1:8000` from the host was refused (see "Verify it" above). |
| **Set exactly one trusted proxy hop.** `REIM_TRUSTED_PROXY_HOPS: "1"` is fixed in the `api` service's environment, matching the one proxy (`caddy`) actually in front of it. Higher hands identity to whoever sends the header. | `test_exactly_one_trusted_proxy_hop`, and at runtime: three requests through Caddy with different forged `X-Forwarded-For` headers, sent while the anonymous allowance was already exhausted, were all refused with `429` — no bypass. |
| **Refuse a CORS wildcard.** `REIM_CORS_ALLOW_ORIGINS` has no default in the compose file (`${REIM_CORS_ALLOW_ORIGINS:?set the allowed origins}`) — the stack does not start until you state an origin. | `test_compose_file_declares_no_cors_wildcard_default`. |
| **Close `/metrics` at the proxy.** The Caddyfile's `/metrics` handler responds `404` directly; it never reaches `reverse_proxy`. | `test_metrics_is_not_reachable_from_outside`, and at runtime: `curl` against `/metrics` through Caddy returned `404` (see "Verify it" above). |
| **Proxy to the API by its compose service name, never a published port.** The Caddyfile reverse-proxies to `api:8000` over the compose network. | `test_caddy_proxies_to_the_api_service_by_name`, and at runtime: the data route through Caddy worked while port 8000 was unreachable from the host. |
| **Make the rate limits and the alert settings configurable without editing the compose file.** `REIM_RATE_LIMIT_ANONYMOUS`, `REIM_RATE_LIMIT_KEYED`, `REIM_RATE_LIMIT_WINDOW_SECONDS`, `REIM_ALERT_WEBHOOK_URL`, `REIM_ALERT_SEVERITY_FLOOR`, `REIM_ALERT_REPEAT_HOURS` and `REIM_ALERT_STUCK_RUN_HOURS` are all read from `deploy/.env` through the `api` service's environment block. | `test_rate_limit_is_configurable_without_editing_the_compose_file`, drilled by removing one variable from the compose file and confirming the test fails, then restoring it and confirming the test passes again. |
| **Keep `--no-proxy-headers` in the `uvicorn` command.** uvicorn's `ProxyHeadersMiddleware` is on by default and trusts 127.0.0.1, so without this flag it rewrites the client address from a caller-supplied `X-Forwarded-For` before REIM's rate limiter runs, letting anyone who sets that header choose their own identity and escape the limit. The `Dockerfile`'s `CMD` has the flag with an explanation, but `docker-compose.prod.yml`'s `command:` overrides that `CMD` entirely. | `test_the_production_command_keeps_uvicorn_out_of_the_identity_decision`, and at runtime: three requests through Caddy with different forged `X-Forwarded-For` headers, sent while the anonymous allowance was already exhausted, were all refused with `429` — no bypass. |

## The limit counts requests, not bytes

`/api/v1/observations/export.csv` serves up to `REIM_MAX_EXPORT_ROWS` rows
(100,000 by default, see `reim/core/config.py`) for **one unit of rate-limit
allowance** — the same one unit a single-row request to `/api/v1/countries`
costs. An anonymous caller at the default 60 requests a minute can therefore
extract far more data than "60" suggests: sixty CSV exports a minute, each
up to 100,000 rows, is a request-shaped limit, not a byte-shaped one. If you
need a byte budget, set one at the proxy — REIM's own limiter does not
provide it.

## Limits of this deployment

- **One `uvicorn` worker.** Neither `Dockerfile` nor `docker-compose.prod.yml`
  passes `--workers`, so the rate-limit counters, which live in memory per
  process, are exact as shipped. To run *N* workers, add `--workers N` to the
  `uvicorn` command in `docker-compose.prod.yml`'s `api` service — but
  **preserve `--no-proxy-headers` when you do**, since the `command:` overrides
  the `Dockerfile`'s `CMD` entirely. Running *N* workers behind your own gateway
  multiplies the effective limit by *N*, since each worker counts its own
  window independently — an operator who scales workers needs a limiter in
  their own gateway, not this one.
- **No Kubernetes, no HA, no read replicas.** This is a single-host,
  single-database deployment: one Postgres instance, one API container, one
  Caddy instance in front. Nothing here fans out beyond that.

## Backups and teardown

Back up with `pg_dump`:

```text
podman compose -f deploy/docker-compose.prod.yml --env-file deploy/.env \
  exec -T postgres pg_dump -U reim -d reim > reim-backup.sql
```

Exit 0; the file this produced during this guide's own verification was
132,560 bytes across 929 lines, non-empty, with `COPY` statements for every
seeded and ingested table.

The stack's own volumes, from `podman volume ls`:

```text
reim-prod_caddy_config
reim-prod_postgres_data
reim-prod_caddy_data
```

Tear down without losing data:

```text
podman compose -f deploy/docker-compose.prod.yml --env-file deploy/.env down
```

This removes the containers and the compose network; the three volumes
above are untouched. To also delete the data — including the database —
add `-v`:

```text
podman compose -f deploy/docker-compose.prod.yml --env-file deploy/.env down -v
```

`-v` is what actually destroys it; `down` alone does not.
