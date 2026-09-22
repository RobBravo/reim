# Redirect scheme fix — design

The final whole-branch review of the frontend deployment integration found a
live bug and it was patched narrowly (the two `/legacy` nav links no longer
emit a trailing slash). That patch closed the symptom, not the cause: any
307/308 Starlette issues from `apps/api/main.py`'s app — for *any* route, not
just `/legacy/*` — builds its `Location` header from the ASGI scope's scheme,
which uvicorn reports as plain `http`, because `--no-proxy-headers` is a
deliberate choice (`Dockerfile:57-69`, `deploy/docker-compose.prod.yml:108-131`)
made to keep exactly one thing — REIM's own middleware — deciding client
identity from `X-Forwarded-For` (`apps/api/middleware.py:140-144`,
`reim/core/config.py`'s `trusted_proxy_hops`). uvicorn's bundled
`ProxyHeadersMiddleware`, which `--no-proxy-headers` disables, would fix the
scheme too, but only by also re-trusting `X-Forwarded-For` — the exact
surface that flag was set to keep closed.

Measured at `bb37bfe` / live on panda before this fix: `curl -sk -D -
https://reim.panda.home.arpa/legacy/series/` (trailing slash) returns `307`
with `location: http://reim.panda.home.arpa/legacy/series` — dead, since
panda has no listener on port 80. `grep -rn "RedirectResponse" apps/ reim/`
returns nothing: the *only* source of any redirect in this app is Starlette's
default `redirect_slashes=True` (`apps/api/main.py:117`, never overridden),
so this reproduces on any trailing-slash mismatch anywhere under the app —
`/api/v1/...`, `/docs`, a future route — not only the two links already
patched.

## 1. What exists, and what this adds

| Piece | State |
|---|---|
| `apps/api/main.py:117` | `FastAPI(...)`, no `redirect_slashes` argument — Starlette's default (`True`) is in effect app-wide |
| `apps/api/middleware.py:140-144` | REIM's own rate-limit identity middleware reads `X-Forwarded-For` directly, with `trusted_proxy_hops` — a separate, already-hardened mechanism unrelated to response `Location` headers |
| `deploy/Caddyfile:44-74`, `/etc/caddy/sites/reim.caddy` (panda, live, outside git) | 8 `handle` blocks reverse-proxying single-line to `api:8000` / `127.0.0.1:8000`: no header rewriting on the way back |
| `tests/unit/test_deploy_artifacts.py` | Table-driven over `API_HANDLE_PATHS` (the same 8 paths), regex-matches each `handle <path> { ... }` block's body — confirmed (§3 below) the existing regex still matches correctly once a `reverse_proxy` block gains a nested sub-block, so this file extends without disruption |

The addition is **one Caddy snippet, imported into 8 existing `reverse_proxy`
blocks, in both `deploy/Caddyfile` and panda's live file** — no REIM Python
code changes, no new container image, no rebuild.

## 2. What ships

### 2.1 The rewrite snippet

```caddyfile
(https_location) {
	header_down Location "^http://" "https://"
}
```

Defined once, near the top of each Caddyfile (after the global options block
in `deploy/Caddyfile`; at the top of panda's `reim.caddy`, which has no
global options block of its own — that lives centrally in
`/etc/caddy/Caddyfile`). `header_down` performs a regexp substitution on a
response header's *value*; anchored to `^http://` so it only ever touches an
absolute-URL `Location` that starts wrong, never a relative one (`/foo`,
already correct) and never any other header. It is a no-op on the
overwhelming majority of responses, which carry no `Location` header at all —
only 3xx redirects do.

### 2.2 Every api-targeting `handle` gains a `reverse_proxy` sub-block

All 8 blocks that answer `/api/*`, `/legacy*`, `/static/*`, `/health`,
`/ready`, `/docs*`, `/redoc`, `/openapi.json` expand from:

```caddyfile
handle /legacy* {
	reverse_proxy api:8000
}
```

to:

```caddyfile
handle /legacy* {
	reverse_proxy api:8000 {
		import https_location
	}
}
```

(panda's copy uses `127.0.0.1:8000` in place of `api:8000`, same shape as
every other place the two files already differ only by upstream address.)
The frontend's own `handle { reverse_proxy frontend:8080 }` is **not**
touched — measured directly against the live deployment before writing this
spec: `curl -sk -D - -o /dev/null https://reim.panda.home.arpa/map` (no
trailing slash) returns `308` with a scheme-correct `https://` `Location` —
Caddy's own `file_server` directory-canonicalization redirect already knows
it terminated TLS itself, so nothing there needs a rewrite (D1).

### 2.3 Test coverage

`tests/unit/test_deploy_artifacts.py`'s `API_HANDLE_PATHS`-parametrized test
(`test_each_api_handle_reverse_proxies_to_the_api_service`) already captures
each handle's body with `re.search(rf"handle\s+{{path}}\s*\{{([^}}]+)\}}",
text)`. Because the regex's capture group is `[^}]+` (everything up to the
*first* literal `}`), and the new `reverse_proxy { import https_location }`
sub-block's own closing brace becomes that first `}`, the capture still ends
inside the sub-block — meaning the existing test's assertion
(`"reverse_proxy api:8000" in match.group(1)`) continues to pass unmodified,
and the same captured text already contains the `import https_location` line
this fix adds. Confirmed by hand-tracing the regex against the post-fix
block text (D2) — no existing test breaks, and a new assertion on the same
capture (`"import https_location" in match.group(1)`) is enough to lock the
fix in, no new regex needed.

The default `handle {}` test
(`test_default_handle_reverse_proxies_to_the_frontend_service`) is untouched
by this change and needs no edit — it asserts the *absence* of `reverse_proxy
api:8000`+presence of `reverse_proxy frontend:8080` in the tail of the file,
neither of which this fix alters.

## 3. Decisions

| | Decision | Rationale |
|---|---|---|
| **D1** | Only the 8 api-targeting `handle` blocks get the rewrite; the frontend's `handle` does not | Measured live: Caddy's own `file_server` redirects are already scheme-correct (it terminated the TLS connection itself), so there is nothing to fix there — adding the snippet would be inert but still unexplained clutter (§2.2) |
| **D2** | No changes to `tests/unit/test_deploy_artifacts.py`'s existing regex; one new assertion added to the same parametrized test instead of a new test function | Hand-traced: the existing `[^}]+` capture already stops inside the new `reverse_proxy { }` sub-block, so it already "sees" the `import https_location` line — writing a second, separate regex would duplicate matching logic for no reason (§2.3) |
| **D3** | Fix ships as a Caddy `header_down` rewrite (Approach 1 of 3 considered), not app-level `X-Forwarded-Proto` trust middleware or disabling `redirect_slashes` | Zero changes to REIM's Python code or its measured proxy-trust model (`REIM_TRUSTED_PROXY_HOPS`, `--no-proxy-headers`); fixes the entire bug class (any route, any future redirect) in the one place — the Caddyfiles — that already carries every other piece of proxy-level hardening this deployment has (HSTS, `/metrics` closure, `/docs` reachability) |
| **D4** | Both `deploy/Caddyfile` (generic) and panda's live `/etc/caddy/sites/reim.caddy` get the fix, in the same rollout | Same D6 established in the prior spec: the two Caddyfiles are meant to stay in sync as two answers to the same question, not let one drift |

## 4. Testing

* `tests/unit/test_deploy_artifacts.py`'s existing `API_HANDLE_PATHS`
  parametrized test, extended with one assertion per D2 — no rebuild, no
  container change, pure text-level check.
* `caddy validate --config deploy/Caddyfile --adapter caddyfile` (dummy
  `REIM_DOMAIN`/`REIM_ACME_EMAIL`), and the same against a validated copy of
  panda's live file before it touches the real one — same discipline as
  every prior Caddy change here.
* Live, on panda, reproducing the exact bug the final review found and
  confirming it is gone:
  ```text
  curl -sk -D - https://reim.panda.home.arpa/legacy/series/
  → 307, location: https://reim.panda.home.arpa/legacy/series   (was http://)

  curl -sk -L https://reim.panda.home.arpa/legacy/series/
  → 200, the actual page (was: connection refused, following the old Location)
  ```
* Spot-check that ordinary 200 responses are unaffected (the rewrite is a
  no-op without a `Location` header): `curl -sk -D -
  https://reim.panda.home.arpa/api/v1/countries` still returns 200 with no
  behavior change.

## 5. Out of scope

* **App-level `X-Forwarded-Proto` trust (Approach 2).** Considered and
  rejected for this increment — see D3. Would make the app correct
  independent of which reverse proxy fronts it, at the cost of new
  security-sensitive code; not needed while every shipped deployment path
  uses the Caddyfiles this fix already covers.
* **Disabling `redirect_slashes` (Approach 3).** Considered and rejected —
  trades a real (if narrow) behavior change — silently losing trailing-slash
  tolerance across the whole API — for a fix that this approach achieves
  more completely and with no such trade-off.
* **Restructuring the Caddyfiles' handle-per-path shape into something more
  centralized.** The snippet already centralizes the rewrite *rule* itself;
  it still needs importing into each handle individually, which is an
  acceptable, minimal-footprint use of what Caddyfile syntax offers — not a
  reason to redesign the routing shape this deployment already settled on.
