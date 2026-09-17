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
  exercise it against. **Untested here, so protect your first real attempt:**
  Let's Encrypt caps failed issuances per account per hour, and a DNS record
  that is not yet pointed at this host, or a typo in `REIM_DOMAIN`, burns
  that budget without giving you a certificate. Point Caddy at Let's
  Encrypt's staging directory for the first run — Caddy's global `acme_ca`
  option (`{ acme_ca https://acme-staging-v02.api.letsencrypt.org/directory }`
  in `deploy/Caddyfile`'s top-level block) issues from staging instead of
  production, against a limit that is far more forgiving. Remove it once a
  staging certificate issues successfully, then let the real run happen
  against the production endpoint.

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
default baked into `docker-compose.prod.yml`, so leaving it commented out
changes nothing — uncomment a line only to tune it. That now covers far more
than the original three rate-limit settings: alerting, request paging, export
size, the database pool and outbound HTTP retries all work the same way, each
value matching `reim.core.config.Settings`'s own default, and so does
`REIM_LOG_LEVEL` (default `INFO`). Two more variables follow the same
"commented out changes nothing" rule but are not `Settings` fields at all —
`POSTGRES_USER` and `POSTGRES_DB` (both default `reim`) are read by the
official `postgres` image itself, not validated by REIM. Change either one
and also change the `pg_dump` command under "Backups and teardown" below,
which hardcodes `reim` for both.

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
6.5 seconds after the container starts, but the healthcheck reported healthy
only at ~30.4 seconds — a gap of about 24 seconds during which the app was
already serving. `api`'s healthcheck in `deploy/docker-compose.prod.yml` sets
`interval: 30s`, `timeout: 5s`, `retries: 3`, `start_period: 20s`, and declares
no `start_interval`. Without one, Docker's/Podman's healthcheck does not probe
at container start — its first probe fires `interval` seconds in, and every
`interval` after that. So the first (and, here, only) probe lands at ~30s
regardless of when the app becomes ready, finds it already listening, and
reports healthy immediately (~30.4s, the extra tenths being the check
command's own runtime). `start_period` never comes into play in this run: it
only forgives a *failing* probe during that window so it does not count
against `retries`, and the one probe that actually happens here succeeds on
first try. `caddy`, which waits on `api`'s healthcheck, is delayed by that
same margin. This is healthcheck cadence, not a failure — the whole
three-service stack (network and volume creation, both healthchecks, `caddy`
starting) took 37 seconds wall-clock on a rerun with the image already built.

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

## Reaching `/metrics` from Prometheus

Closed at the proxy is not closed everywhere. `apps/api/routers/system.py`
still serves `/metrics` itself — unauthenticated, gated only by
`REIM_METRICS_ENABLED` (`true` by default) — so the Caddyfile's `404` is what
keeps it off the public internet, not the application. The address that
route answers on is the same one `deploy/Caddyfile` already reverse-proxies
to: `api:8000`, reachable only from `docker-compose.prod.yml`'s own network —
named `reim-prod_reim` by Compose (`<project>_<network key>`; see the
`Network reim-prod_reim Created` line under "Bring it up" above, from this
guide's own verified session).

- **From inside the compose network.** Join a Prometheus container to
  `reim-prod_reim` — as an `external: true` network in your own compose file,
  or with `podman network connect reim-prod_reim <prometheus container>` —
  and point a scrape config at `api:8000`, path `/metrics`. No port is
  published for this and none needs to be: the same network `caddy` already
  uses to reach `api` is the one Prometheus joins.
- **Over a tunnel, if Prometheus cannot join that network.** `api` publishes
  no port (see "Publish no database or API port" in Hardening above), so
  nothing outside the compose network reaches `api:8000` directly; a tunnel
  has to land inside the network first — an SSH session to the host, or a
  small sidecar container on `reim-prod_reim`, forwarding to `api:8000`.
  **This is the untested half of this section**: verifying it means starting
  the stack and a second, tunneled scraper, which this guide's own session
  did not do — every command shown elsewhere in this guide was run for real,
  this one specific command was not, so none is given here rather than
  inventing one that has not been run.

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
elsewhere in this guide). **Also untested here, and worth protecting against
before you rely on it:** under rootless Podman, `crontab`'s own job
environment is a bare one — no login session ran to set it up — and
typically lacks `XDG_RUNTIME_DIR`, which is where `podman` looks for its API
socket (`$XDG_RUNTIME_DIR/podman/podman.sock`). Without it, the `podman
compose exec` line above fails with something like `unable to connect to
Podman socket`, and cron's own behavior on a failing job is to mail the
output to the crontab's owner rather than show it anywhere you would notice
at the time. Set `XDG_RUNTIME_DIR=/run/user/<uid>` (your numeric UID) at the
top of the crontab, or in each line before the command, so the job environment
matches the one your interactive shell already has when `podman compose`
works there.

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

# Minimum severity that reaches the webhook: one of info, warning, error,
# critical. Case is normalised, so ERROR is accepted too; any other word is
# not, and stops the container.
# REIM_ALERT_SEVERITY_FLOOR=error

# Hours to wait before repeating a standing alert about the same condition on
# the same pipeline. Whole number, 1 to 720 (30 days).
# REIM_ALERT_REPEAT_HOURS=24

# Hours a pipeline run may sit in 'running' before it's flagged as stuck.
# Whole number, 1 to 168 (7 days).
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
```

| Do this | How it's verified |
|---|---|
| **Publish no database or API port.** Only `caddy` has a `ports:` entry in `docker-compose.prod.yml`; `postgres` and `api` are reachable only over the compose network. | `test_only_caddy_publishes_ports`, and directly: connecting to `127.0.0.1:5432` and `127.0.0.1:8000` from the host was refused (see "Verify it" above). |
| **Set exactly one trusted proxy hop.** `REIM_TRUSTED_PROXY_HOPS: "1"` is fixed in the `api` service's environment, matching the one proxy (`caddy`) actually in front of it. Higher hands identity to whoever sends the header. This is pinned to the topology this compose file actually runs — one proxy — and breaks in the other direction too: put a CDN or load balancer (Cloudflare, say) in front of `caddy` and there are now two hops, but the pinned `1` still trusts only the last one, which is then the CDN's own address for every caller. Every request the CDN forwards collapses into that single bucket, one allowance for the whole world behind it. Putting anything in front of `caddy` means editing this compose file's `REIM_TRUSTED_PROXY_HOPS` and re-measuring, not leaving it at `1`. | `test_exactly_one_trusted_proxy_hop`, and at runtime: three requests through Caddy with different forged `X-Forwarded-For` headers, sent while the anonymous allowance was already exhausted, were all refused with `429` — no bypass. The reasoning above is recorded in code, not just here: `PINNED_IN_COMPOSE["REIM_TRUSTED_PROXY_HOPS"]` in `tests/unit/test_deploy_artifacts.py`. |
| **Demand an explicit CORS decision.** `REIM_CORS_ALLOW_ORIGINS` has no default in the compose file (`${REIM_CORS_ALLOW_ORIGINS:?set the allowed origins}`) — the stack refuses to start until you state a value. That does not reject a wildcard: `REIM_CORS_ALLOW_ORIGINS=*` boots fine and resolves to `['*']`. It makes the wildcard a decision an operator has to type, not a default nobody chose. | `test_compose_file_declares_no_cors_wildcard_default`, which checks the file's declared default (there is none), not what an operator sets at runtime. |
| **Close `/metrics` at the proxy.** The Caddyfile's `/metrics` handler responds `404` directly; it never reaches `reverse_proxy`. | `test_metrics_is_not_reachable_from_outside`, and at runtime: `curl` against `/metrics` through Caddy returned `404` (see "Verify it" above). |
| **Proxy to the API by its compose service name, never a published port.** The Caddyfile reverse-proxies to `api:8000` over the compose network. | `test_caddy_proxies_to_the_api_service_by_name`, and at runtime: the data route through Caddy worked while port 8000 was unreachable from the host. |
| **Make every setting an operator would plausibly tune configurable without editing the compose file.** Not just the rate limits and the alert settings any more — `OPERATOR_SETTABLE` in `tests/unit/test_deploy_artifacts.py` now names eighteen variables (rate limiting, alerting, request paging, export size, the database pool, outbound HTTP retries and log level), and every one of them is read from `deploy/.env` through the `api` service's environment block rather than fixed in the file you'd otherwise have to edit. | `test_the_settings_an_operator_tunes_reach_the_container`, which checks every name in `OPERATOR_SETTABLE` against the block, drilled by removing one variable from the compose file and confirming the test fails, then restoring it and confirming the test passes again. |
| **Ship the rate limiter on, and know that `.env` can switch it off.** `REIM_RATE_LIMIT_ENABLED` defaults to `true` in the compose file, so what ships is limited. But `false` in `deploy/.env` now reaches the container, and `apps/api/main.py` then adds no limiter middleware at all — every allowance named in this guide stops existing, silently and without an error anywhere. The switch is deliberate: it is how an operator who has moved limiting into their own gateway (see "Limits of this deployment" on running several workers) turns REIM's off. Setting it without that gateway in place leaves the API unlimited. | `test_the_rate_limiter_is_on_unless_an_operator_turns_it_off`, which pins both halves: `Settings.rate_limit_enabled` defaults to `True`, and the compose entry is `${REIM_RATE_LIMIT_ENABLED:-true}`. |
| **Keep `--no-proxy-headers` in the `uvicorn` command**, as the `Dockerfile`'s own `CMD` already does — but `docker-compose.prod.yml`'s `command:` overrides that `CMD` entirely, so this copy of the flag is the one that actually runs. Measured, not assumed: in this compose file's own topology (`caddy` and `api` as separate containers on the compose network, one `X-Forwarded-For` entry Caddy itself writes), removing the flag changed nothing — a forged header through Caddy was refused identically with and without it, at both `REIM_TRUSTED_PROXY_HOPS=0` and the shipped `=1`. The `api` container's peer is never uvicorn's default-trusted `127.0.0.1` here, and at hops=1 the header's own value decides identity, never the peer. The flag's measured effect is on a different topology: uvicorn run with its immediate TCP peer actually at `127.0.0.1` (no Caddy, no bridge network in front) — there, a caller-supplied `X-Forwarded-For` bought a fresh allowance without the flag. Keep it regardless: it is uvicorn's correct default, costs nothing, and a later change to how this command runs could make it load-bearing again in this topology too. | `test_the_production_command_keeps_uvicorn_out_of_the_identity_decision`. Runtime, this compose file's topology: three forged `X-Forwarded-For` headers through Caddy were refused identically at `REIM_TRUSTED_PROXY_HOPS=0` and `=1`, with the flag present and with it removed — four configurations, one result. Runtime, bare `uvicorn --host 127.0.0.1` (peer = uvicorn's trusted `127.0.0.1`): the same three forged headers each bought a fresh `200` without the flag; all three were refused with it. |

### What is public and unlimited

The rate limiter only inspects `/api/v1` — `LIMITED_PREFIX` in
`apps/api/middleware.py` is that one prefix, and a request whose path does not
start with it never reaches the limiter at all. Everything else Caddy
proxies through is public and carries no allowance of REIM's own: the web
pages under `apps/web/routes.py` (`/`, `/runs`, `/runs/{run_id}` and
`/series`), `/static` (served by `StaticFiles`), and FastAPI's own `/docs`
and `/openapi.json`.

This is the documented design, not a gap — the web UI and the interactive
API docs are meant to work without a key — but an operator reading only this
section would not know it without being told here. If you do not want the
docs published, close them at the proxy the same way `deploy/Caddyfile`
already closes `/metrics`: add a `handle /docs`, `/openapi.json` (and
`/static`, `/runs*`, `/series` if you want the API alone reachable) block
that `respond`s `404` before the catch-all `reverse_proxy`.

## The limit counts requests, not bytes

`/api/v1/observations/export.csv` serves up to `REIM_MAX_EXPORT_ROWS` rows
(100,000 by default, see `reim/core/config.py`) for **one unit of rate-limit
allowance** — the same one unit a single-row request to `/api/v1/countries`
costs. An anonymous caller at the default 60 requests a minute can therefore
extract far more data than "60" suggests: sixty CSV exports a minute, each
up to 100,000 rows, is a request-shaped limit, not a byte-shaped one. If you
need a byte budget, set one at the proxy — REIM's own limiter does not
provide it. `deploy/Caddyfile` ships the directive for that, commented out,
in the catch-all `handle` block: Caddy's `request_body` directive, whose
`max_size` subdirective (`request_body { max_size 10MB }`) caps a request
body before Caddy forwards it — verified for syntax against the pinned
`docker.io/library/caddy:2.11.4-alpine` build (`caddy validate`; `caddy
list-modules` on that build shows `http.handlers.request_body` present and
no other body- or size-related handler). Read that cap correctly: it bounds
what a client *sends*, not what a response *returns*, so it does nothing for
`export.csv` specifically — a `GET` with no body — and this build ships no
core directive that caps response size or egress bandwidth at all. Left
commented for the same reason it is accepted rather than fixed (the spec's
§3.2): enabling it is a policy decision about a public data platform, and
picking a size is yours to make, not this guide's.

## A bad value takes the site down

A `REIM_*` variable whose **name** matches a field of
`reim.core.config.Settings` is validated when the application is imported —
against that field's type, and against its `ge=`/`le=` bounds where it has them,
which is what `deploy/.env.prod.example` states beside each line. (Not every
field has bounds: `REIM_LOG_LEVEL` and `REIM_ALERT_SEVERITY_FLOOR` are checked
against a list of accepted words instead, and `REIM_CORS_ALLOW_ORIGINS` only
has to parse.) A value the field rejects **is not ignored, is not clamped, and
does not fall back to the default.** It raises, and it raises before `uvicorn`
has an application to serve.

Measured in this repository, two cells. The rival hypothesis is the comfortable
one — that pydantic-settings treats an out-of-range value as absent and uses
the field default — and it predicts the same output as the claim in the first
cell, so only the second decides anything:

```text
REIM_MAX_EXPORT_ROWS=5000 .venv/bin/python -c "import apps.api.main; \
  from reim.core.config import get_settings; print(get_settings().max_export_rows)"
→ 5000

REIM_MAX_EXPORT_ROWS=0 .venv/bin/python -c "import apps.api.main"
→ pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
  max_export_rows
    Input should be greater than or equal to 1 [type=greater_than_equal, ...]
```

The second cell raises rather than printing `100000`, which is what the rival
hypothesis would have produced.

Read off `docker-compose.prod.yml`, that failure does not stay inside the `api`
container. The service carries `restart: unless-stopped`, so a container that
dies at import is started again, and again; its healthcheck never passes
because nothing is listening on 8000; and `caddy` declares
`depends_on: api: condition: service_healthy`. So:

- If you recreated only `api` — `up -d --force-recreate api`, the command this
  guide gives for picking up a changed `.env` — `caddy` is already running and
  keeps its certificate, but every request it proxies reaches a container that
  is not there. The site answers `502`.
- On the next `up -d` from a stopped stack, or the next reboot of the host,
  `caddy` never starts at all, because the condition it waits on is never
  satisfied. Nothing listens on 80 or 443: no HTTP, **no HTTPS, and no
  certificate renewal.** One mistyped number in `.env` is the whole site,
  TLS included.

For a bad value there is no partial-failure mode and no warning in between. The
check that catches it is one command:

```text
podman compose -f deploy/docker-compose.prod.yml --env-file deploy/.env logs api
```

A validation failure is at the end of that output, naming the field and what it
rejected — the same `ValidationError` as the cell above. Run it after every
`.env` change and restart, and read it before you walk away.

### A bad *name* does the opposite: nothing at all

That command is necessary and it is not sufficient, because the likeliest
mistake in a `.env` file is not a bad value, it is a misspelled variable name —
and `Settings` is configured with `extra="ignore"`. An unknown `REIM_*` name is
not an error. It is read by nobody, the setting you meant to change stays at its
default, the stack comes up healthy, and `logs api` says nothing, because
nothing went wrong as far as the application is concerned.

Two cells again, and the rival hypothesis is the one most people assume — that
an unknown `REIM_*` name is rejected the way a bad value is. It predicts a
raise; what happens is a boot:

```text
REIM_MAX_EXPORT_ROWS=5000 → 5000
REIM_MAX_EXPORT_ROW=5000  → 100000        # name typo'd: silently the default
```

Inside this repository the corresponding mistake is caught —
`test_every_wired_variable_names_a_real_setting` fails on any `REIM_*` key in
`docker-compose.prod.yml` that no `Settings` field reads, and
`test_the_env_example_documents_what_the_compose_file_reads` does the same for
`deploy/.env.prod.example`. **Nothing checks your `deploy/.env`**, because it is
yours and it never reaches us. So the check for a name is not "did the container
come up" but "is the value what I set":

```text
podman compose -f deploy/docker-compose.prod.yml --env-file deploy/.env \
  exec api python -c \
  "from reim.core.config import get_settings; print(get_settings().max_export_rows)"
```

That prints what the running application actually resolved, which is the only
thing that settles it. Substitute the field name — the lower-case form of the
variable without its `REIM_` prefix — for whichever setting you changed. Run it
once after an edit; a number you did not set is a typo in the name, not a
setting that refused to apply.

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

This hardcodes `reim` for both the user and the database name —
`docker-compose.prod.yml`'s own defaults for `POSTGRES_USER` and
`POSTGRES_DB` (that file's `postgres` service also documents a `psql -U reim`
shell in a comment, for the same reason). If you set either one in
`deploy/.env` to something else, change `-U reim` and `-d reim` to match
wherever you invoke `pg_dump` or `psql`, or the command connects as, or to, a
role/database that no longer exists.

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
