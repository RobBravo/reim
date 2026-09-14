# API keys and rate limiting — design

REIM's README currently tells you not to expose the API publicly without putting
a gateway in front of it. This increment removes that advice by doing the job
itself: anonymous requests keep working at a rate nobody legitimate notices, a
key raises the allowance, and the platform stays open — which is what it is for.

This is v0.5.0's fourth increment and the last thing standing between REIM and
the public deployment the tier is named for. Everything measured below was
checked against the repository on 2026-09-13.

## 1. What exists, and what this adds

Measured, not assumed:

| Piece | State |
|---|---|
| Authentication | **None anywhere.** No `api_key`, `APIKey`, `rate_limit` or auth dependency in `reim/` or `apps/` |
| README | States the limitation plainly: "**No authentication or rate limiting.** Do not expose this publicly without putting a gateway in front and narrowing `REIM_CORS_ALLOW_ORIGINS`" |
| Routers | Every data router carries an explicit `/api/v1/...` prefix. `apps/api/routers/system.py` carries **none**, so `/health`, `/ready` and `/metrics` sit at the root while `/api/v1/status` does not |
| The app | Serves the API, the three web pages at `/`, and `/static` from one process (`apps/api/main.py:129-140`) |
| Middleware | `add_middleware` is used once, for CORS (`main.py:119`) |
| Error envelope | `{"error": {"code", "message", "details"}}` (`apps/api/errors.py:20`) |
| Deployment | `Dockerfile:57` and `docker-compose.yml:61` both run `uvicorn` with **no `--workers` flag** — a single worker |
| Migrations | Two exist; head is `e831f3829f6e` (alert states) |

The addition is **one model, one migration, one middleware, one CLI group and
five settings**. No new dependency: hashing is `hashlib`, tokens are `secrets`.

### 1.1 What a key is for, and what it is not

REIM publishes open official data. Redistribution with provenance is the whole
point of the project, and the licence terms on `/api/v1/sources` invite it. A
key that gated access would contradict the thing the platform is for.

So a key does not grant access — **it raises an allowance** (D1). Anonymous
requests keep working. A heavy consumer identifies themselves and gets more
headroom; an operator gets abuse and cost control; nobody is locked out of data
that is public by design.

This also decides the failure modes below. A *missing* key is not an error,
because anonymous is a supported mode. An *invalid* key is a `401`, because
presenting a credential that does not exist is a mistake worth telling someone
about rather than silently downgrading them.

## 2. What is limited

Requests whose path starts with `/api/v1`. That single rule exempts, without
enumerating anything:

* `/health` and `/ready` — a limiter that can throttle a liveness probe can
  restart a healthy container.
* `/metrics` — Prometheus scrapes it every 15 seconds by design, which is
  exactly the traffic shape a limiter would punish.
* The three web pages and `/static` — the public surface, where a browser fetch
  is one page plus a stylesheet.
* `/docs` and `/openapi.json`.

`/api/v1/status` **is** limited. It lives in the system router for historical
reasons but it is a data endpoint, and not a cheap one — it counts over the
observations table.

## 3. The key

A `reim_`-prefixed token from `secrets.token_urlsafe`, shown **once** at
creation and never recoverable. Stored as a SHA-256 hash.

Lookup hashes the presented token and selects by hash on a unique index. There
is therefore one indexed read and no comparison against a stored secret — the
constant-time question does not arise, because nothing is compared (D4).

`api_keys` carries the hash, a `label` the operator chooses, `created_at`,
`last_used_at` and a nullable `revoked_at`. A revoked key is kept, not deleted:
"this key was revoked in March" is a question an operator will ask.

**Keys are minted from the CLI, never over HTTP** (D5). The API is read-only by
decision D13 of the original plan, and an endpoint that issues credentials would
be the first exception to that — a large one, on the surface most exposed to the
internet. `reim key create --label "grafana"`, `reim key list`, `reim key revoke`.

### 3.1 Anonymous requests cost no database work

A request with no key never touches `api_keys`. Only a presented key costs the
one indexed read. The limiter's own state is in memory (§4), so the common case
— an anonymous reader — adds nothing to the database at all.

**If that read fails because the database is down, the request is treated as
anonymous rather than rejected** (D8). The endpoint it is heading for will
report the outage in its own terms; failing it on authentication grounds would
blame the caller for the server's problem, and a `401` is a particularly
misleading way to say "the database is unreachable".

## 4. The limiter

A fixed window, counted in memory, keyed by identity: the key's id when one is
presented, the client address otherwise.

**In memory, because the shipped deployment is a single uvicorn worker** —
neither `Dockerfile:57` nor `docker-compose.yml:61` passes `--workers`. For that
deployment the count is exact, it adds no write to a read-only API, and it needs
no schema (D2).

Scale to *N* workers and each enforces its own window, so the effective limit
becomes *N×* the configured one. That is documented rather than hidden, and an
operator running multiple workers is already running something in front of them.
The alternative — a counter row in Postgres — turns every read request on a
read-only API into a write, putting the database on the hot path for exactly the
traffic a limiter exists to shed.

### 4.1 The proxy trap

Identity for an anonymous request is the **socket peer** (`request.client.host`),
not `X-Forwarded-For` (D3).

Trusting that header blindly is the standard way to build a limiter that
enforces nothing: any client sets it to a random value per request, gets a fresh
bucket every time, and the limiter reports healthy while doing nothing. The
header is attacker-controlled unless something you run wrote it.

`REIM_TRUSTED_PROXY_HOPS` opts in, defaulting to `0`. At *n*, the identity is
the *n*-th entry from the right of `X-Forwarded-For` — the last hop your own
proxy appended. An operator behind one reverse proxy sets `1`. Setting it higher
than the number of proxies you actually control hands the choice back to the
client, which is why the setting's documentation says so in those words.

## 5. Responses

Both reuse the existing envelope (`apps/api/errors.py:20`), so an API consumer
parses one error shape.

| Condition | Status | Notes |
|---|---|---|
| No key presented | — | Anonymous allowance. Not an error |
| Key not found, or revoked | `401` | `code: "invalid_api_key"` |
| Allowance exhausted | `429` | `code: "rate_limited"`, plus a `Retry-After` header in seconds |

`Retry-After` carries seconds until the current window resets, so a client can
back off correctly instead of guessing.

## 6. Configuration

```text
rate_limit_enabled:        bool = True
rate_limit_anonymous:      int  = 60    per minute (ge=1)
rate_limit_keyed:          int  = 600   per minute (ge=1)
rate_limit_window_seconds: int  = 60    (ge=1, le=3600)
trusted_proxy_hops:        int  = 0     (ge=0, le=8)
```

**On by default** (D6). Off-by-default would mean the operator most likely to
need this is the one least likely to read about it, and the README's "put a
gateway in front" warning would have to stay. The defaults are set so that a
person browsing, a dashboard polling, or a script paging through observations
never sees a `429`; a scraper pulling as fast as it can does.

## 7. Testing

* **The window arithmetic is pure**, with an injected clock: exhaustion, the
  reset boundary, and a request arriving exactly at the boundary are unit-tested
  with no sleeping and no database.
* **The identity resolution is pure too**, and gets the case that matters: with
  `trusted_proxy_hops = 0`, a request carrying a forged `X-Forwarded-For` must
  resolve to the socket peer. A limiter that can be bypassed by setting a header
  is not a limiter, and this is the assertion that says so.
* **Integration**: a keyed request receives the higher allowance; an unknown key
  gets `401`; a revoked key gets `401`; an exempt path stays unlimited under
  more requests than the anonymous limit; and `429` carries `Retry-After`.
* **The database-down path**: a presented key with an unreachable database is
  treated as anonymous, not rejected.
* **The migration** is verified by `make migrate-check`, which runs
  `alembic upgrade head` then `alembic check` — the discriminating test that it
  matches the model rather than merely running.

## 8. Decisions

| | Decision | Rationale |
|---|---|---|
| **D1** | A key raises an allowance; it does not gate access | REIM publishes open data and invites redistribution. Gating it would contradict the platform's purpose (§1.1) |
| **D2** | Counters live in memory, not in Postgres | The shipped deployment is a single uvicorn worker, so the count is exact; a counter table would turn every read on a read-only API into a write (§4) |
| **D3** | Identity is the socket peer unless `trusted_proxy_hops` says otherwise | Trusting `X-Forwarded-For` by default builds a limiter any client bypasses by setting a header (§4.1) |
| **D4** | Keys are stored and looked up by SHA-256 hash | One indexed read, and nothing is ever compared against a stored secret (§3) |
| **D5** | Keys are minted from the CLI, never over HTTP | The API is read-only by D13; a credential-issuing endpoint would be the first exception, on the most exposed surface (§3) |
| **D6** | Rate limiting is on by default | The operator who needs it most is the least likely to enable it, and the README's gateway warning cannot otherwise be retired (§6) |
| **D7** | Limiting keys on the `/api/v1` path prefix | One rule exempts probes, the scrape, the pages, the static assets and the docs without enumerating them (§2) |
| **D8** | A key lookup that fails because the database is down downgrades to anonymous | A `401` is a misleading way to report an unreachable database, and the endpoint will report the outage itself (§3.1) |
| **D9** | A revoked key is retained, not deleted | "When was this revoked" is a question an operator asks (§3) |

## 9. Out of scope

* **Per-key limits, scopes, expiry, quotas.** One anonymous limit and one keyed
  limit. A key needing different treatment is a case nobody has yet.
* **A usage-analytics endpoint.** `last_used_at` records enough to find a dead
  key; anything richer is a product, not a limit.
* **Shared counters across workers.** D2. An operator scaling horizontally is
  already running a proxy that can limit.
* **Authentication for the web pages.** They are the public surface. Nothing
  about them changes.
* **Protecting `/metrics`.** Still unauthenticated, as `/health` and `/ready`
  are. Network-level restriction is the usual answer for a scrape endpoint, and
  the metrics design already put this out of scope.
* **Rotating a key in place.** Create a new one, revoke the old one; the two
  commands exist and the sequence is the rotation.
