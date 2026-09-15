# Public deployment guide — design

REIM's README stopped telling operators to put a gateway in front of it. This
increment is what makes that true in practice rather than on paper: a
deployment an operator can actually run, shipped as files in the repository,
and a guide written by standing that deployment up and measuring every step.

This is v0.5.0's last increment. Everything measured below was checked against
the repository on 2026-09-15, at `5fe0407`.

## 1. What exists, and what this adds

Measured, not assumed:

| Piece | State |
|---|---|
| Deployment docs | **None.** `docs/` holds `implementation-plan.md` and `sources.md`; the README's Quick start is development-shaped (`docker compose up --build`, then `make` targets) |
| `docker-compose.yml` | One file, development-shaped: Postgres publishes `${POSTGRES_PORT:-5432}:5432`, the API publishes `${REIM_API_PORT:-8000}:8000`, `REIM_CORS_ALLOW_ORIGINS` defaults to `*` |
| Reverse proxy | Nothing. No TLS anywhere in the repository |
| `deploy/` | Does not exist |
| `Makefile` | `CONTAINER_ENGINE ?= docker`, `COMPOSE ?= $(CONTAINER_ENGINE) compose` — podman works by overriding one variable |
| uvicorn | Runs with `--no-proxy-headers` as of `5fe0407`, so `REIM_TRUSTED_PROXY_HOPS` is the only thing deciding identity |
| Freshness threshold | Two sites disagree: `reim/services/status.py:53` reads `indicators[0]`, `reim/services/metrics.py:113` takes the strictest across all of a source's indicators |
| `reim key create` | Accepts `--label ""` |

The addition is **two deployment artifacts, one guide, and two small fixes**.
No new runtime dependency: Caddy is a container image, not a Python package.

### 1.1 Why the artifacts ship as files

The guide could show its compose file and its proxy config inline and let the
operator copy them. That is how `.env.example` came to ship
`REIM_CORS_ALLOW_ORIGINS=*`, a value that prevented the application from
starting, undetected until someone measured it during the previous increment.

Files in the repository can be started, exercised and measured. A fenced code
block in Markdown cannot. Everything this guide asserts about the deployment is
therefore asserted about files that exist, at paths the guide names (D1).

## 2. What ships

### 2.1 `deploy/docker-compose.prod.yml`

An overlay over the existing `docker-compose.yml`, not a replacement — the base
file stays the development environment it is. It differs in exactly the ways a
public deployment differs:

* **Postgres publishes no port.** Development publishes 5432 so `psql` works
  from the host. In production the database is reachable only from the compose
  network, and an operator who wants a shell uses `compose exec`.
* **The API publishes no port either.** Only Caddy is reachable from outside,
  so there is no second door on 8000 bypassing TLS and the proxy.
* **`REIM_TRUSTED_PROXY_HOPS=1`**, because now there is exactly one proxy and
  it is ours.
* **`REIM_CORS_ALLOW_ORIGINS` has no default.** The overlay requires the
  operator to state it; a wildcard is a development convenience.
* **`REIM_LOG_JSON=true`** and a real `REIM_ENVIRONMENT`.

### 2.2 `deploy/Caddyfile`

Caddy terminates TLS, obtains and renews certificates automatically, and
proxies to the API over the internal network. It also does the one thing this
whole increment depends on: it writes `X-Forwarded-For` itself.

`REIM_TRUSTED_PROXY_HOPS=1` means "take the entry my own proxy appended". That
is only correct if Caddy actually appends the real peer to whatever the client
sent. **The guide may not assert this from documentation — the implementation
must prove it by forging a header through the running proxy and observing the
identity REIM counts against** (D2). A guide that reasons about this instead of
measuring it is how the uvicorn bypass survived five reviews.

`/metrics` is restricted at the proxy rather than exposed. The metrics design
put authentication out of scope on the grounds that network-level restriction
is the usual answer for a scrape endpoint; this is where that answer gets
written down.

## 3. The guide

`docs/deployment.md`, written **while standing the stack up with podman**, not
from the code (D3). Every command in it is one that was run; every output it
promises is one that was observed.

It is a sequence an operator follows, not a survey of options. The shape:
prerequisites, obtaining the code, the secrets that must be set and how to
generate them, bringing the stack up, verifying it, minting the first API key,
running the first ingestion, installing the crontab `reim pipeline schedule`
emits, and pointing alerting at a webhook.

### 3.1 Hardening, each point with its verification

The guide's hardening section is not advice. Each item names what to do and the
command that shows it worked:

| Item | Verified by |
|---|---|
| TLS terminates at Caddy | the certificate the deployment actually serves |
| `REIM_TRUSTED_PROXY_HOPS=1` matches one proxy | a forged `X-Forwarded-For` through Caddy buys no fresh allowance |
| uvicorn runs `--no-proxy-headers` | already covered by tests; the guide says why an operator running uvicorn themselves must pass it |
| CORS narrowed | a request from a disallowed origin |
| `/metrics` not publicly reachable | a request to it from outside the network |
| One worker | the limit is exact; *N* workers multiply it by *N* |
| Database not publicly reachable | no published port |
| Keys rotated by create-then-revoke | `reim key list` before and after |
| The alert webhook secret stays out of logs | the URL is redacted where it is reported |

### 3.2 The limit counts requests, not bytes

`/api/v1/observations/export.csv` serves up to `REIM_MAX_EXPORT_ROWS` rows
(100,000 by default) and costs one unit of allowance, the same as any other
call. An anonymous caller at 60 requests a minute can therefore extract far
more data than the number suggests.

This is the accepted consequence of D2 in the API keys design, not a defect
against it, and the guide states it plainly (D4) rather than leaving an
operator to discover it from their egress bill. An operator who needs a byte
budget sets one at the proxy, where byte budgets belong.

## 4. The two folded fixes

### 4.1 One freshness threshold, not two

`reim/services/status.py:53` derives a pipeline's freshness threshold from
`entry.indicators[0]`. `reim/services/metrics.py:113` takes the strictest
threshold across every indicator the source declares, and its docstring already
records that the two agree only because no catalog entry disagrees today — 14
of the 23 entries declare more than one indicator.

`_freshness_threshold` moves somewhere both can import, and `status.py` uses
it, so `/api/v1/status` and `/metrics` cannot report different staleness for
the same pipeline (D5).

`reim/ingestion/runner.py:262` also reads `indicators[0]`, and is **not** part
of this: `_rule_for` returns the whole `IndicatorRule` that feeds the quality
battery, a different concern from reporting freshness. Changing it would be a
behaviour change nobody asked for.

The test is the case the catalog does not contain: a source whose indicators
declare different thresholds, asserting the stricter one is reported. Without
it the change is unmeasurable, because every real input gives the same answer
either way.

### 4.2 `--label` may not be empty

`reim key create --label ""` mints a key that `reim key list` cannot
distinguish from any other. A label is how an operator decides which key to
revoke; an empty one defeats the only management surface keys have. It is
rejected with the CLI's usual exit code (D6).

## 5. Testing

* **The artifacts are exercised, not just written.** The stack comes up under
  podman and the guide's verification commands run against it.
* **The proxy's header handling is measured**, per D2: a forged
  `X-Forwarded-For` through Caddy, asserting the identity REIM counts against.
* **The freshness threshold** gets the divergent-indicator case the catalog
  lacks, and a mutation drill: revert `status.py` to `indicators[0]` and
  confirm the test fails.
* **The empty label** gets a test, and a drill: remove the validation and
  confirm it fails.
* **The guide's commands** are checked against the repository they document —
  a file the guide names must exist, and a setting it names must be a setting.

## 6. Decisions

| | Decision | Rationale |
|---|---|---|
| **D1** | The deployment ships as files in `deploy/`, not as code blocks in the guide | Files can be started and measured; a fenced block cannot, which is how `.env.example` shipped a value that stopped the app from booting (§1.1) |
| **D2** | The guide's claims about the proxy are measured through the running proxy, never reasoned from documentation | The uvicorn bypass survived five reviews because nothing ran a real server (§2.2) |
| **D3** | The guide is written while standing the stack up, not from the code | Its content is entirely claims about behaviour, which is where this project's defects have clustered (§3) |
| **D4** | The request-not-bytes limit is stated in the guide | It is an accepted trade-off, and an operator should meet it in the documentation rather than in their egress bill (§3.2) |
| **D5** | `status.py` adopts the metrics snapshot's strictest-threshold rule | Two reports of the same pipeline's staleness that can disagree is a bug waiting for the first catalog entry that disagrees (§4.1) |
| **D6** | An empty `--label` is rejected | A label is the only way an operator identifies a key to revoke (§4.2) |
| **D7** | Caddy rather than nginx | It writes `X-Forwarded-For` itself and obtains certificates without a second tool; its config is short enough that the one mistake that matters is hard to make |
| **D8** | The production compose is an overlay, not a replacement | The base file is the development environment and stays that |

## 7. Out of scope

* **Kubernetes, high availability, read replicas, more than one worker.** The
  guide states that scaling horizontally multiplies the effective rate limit
  and that such an operator needs a limiter in their own gateway.
* **A managed-platform guide.** Fly, Render, systemd units. One deployment,
  documented properly.
* **Backup automation.** The guide says what to back up and shows the command;
  scheduling it is the operator's, as cron is for pipelines.
* **Log shipping, dashboards, tracing.** `/metrics` exists and Prometheus
  scrapes it; what an operator builds on that is theirs.
* **Authentication for `/metrics`.** Still out of scope, as the metrics design
  decided. Network restriction is the answer, and this guide is where it is
  written down.
* **`runner.py`'s use of `indicators[0]`.** Different concern (§4.1).
