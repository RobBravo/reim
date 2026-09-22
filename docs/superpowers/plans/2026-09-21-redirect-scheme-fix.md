# Redirect Scheme Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop REIM's API from ever sending a client a dead `http://` redirect `Location` when Starlette's default `redirect_slashes` fires — fix it at the Caddy layer, in both the generic `deploy/Caddyfile` and panda's live deployment.

**Architecture:** A reusable Caddy snippet (`(https_location) { header_down Location "^http://" "https://" }`) is imported into the `reverse_proxy` block of every `handle` that targets the api container. No REIM Python code changes.

**Tech Stack:** Caddy 2.11.4 (Caddyfile), pytest (test_deploy_artifacts.py).

**Spec:** `docs/superpowers/specs/2026-09-21-redirect-scheme-fix-design.md`

## Global Constraints

- Snippet name is exactly `https_location`; rewrite rule is exactly `header_down Location "^http://" "https://"`.
- Only the 8 api-targeting handles (`/api/*`, `/legacy*`, `/static/*`, `/health`, `/ready`, `/docs*`, `/redoc`, `/openapi.json`) import the snippet. The frontend's default `handle` is untouched — its own redirects are already scheme-correct.
- Both `deploy/Caddyfile` (generic) and panda's live `/etc/caddy/sites/reim.caddy` get the fix in the same rollout.
- Any change to panda's live Caddy file is validated with `caddy validate --adapter caddyfile` against a copy first, and applied with `systemctl reload caddy`, never `restart`.

---

### Task 1: Fix the generic `deploy/Caddyfile`

**Files:**
- Modify: `deploy/Caddyfile`
- Modify: `tests/unit/test_deploy_artifacts.py`

**Interfaces:**
- Produces: every api-targeting `handle` block's `reverse_proxy` now imports `https_location`, which later tasks and panda's live file mirror exactly.

- [ ] **Step 1: Write the failing assertion**

In `tests/unit/test_deploy_artifacts.py`, inside `test_each_api_handle_reverse_proxies_to_the_api_service` (the function parametrized over `API_HANDLE_PATHS`), replace:

```python
    match = re.search(rf"handle\s+{re.escape(path)}\s*\{{([^}}]+)\}}", text)
    assert match, f"no `handle {path}` block found in deploy/Caddyfile"

    assert "reverse_proxy api:8000" in match.group(1), (
        f"`handle {path}` block does not reverse_proxy to api:8000: {match.group(1)!r}"
    )
```

with:

```python
    match = re.search(rf"handle\s+{re.escape(path)}\s*\{{([^}}]+)\}}", text)
    assert match, f"no `handle {path}` block found in deploy/Caddyfile"

    assert "reverse_proxy api:8000" in match.group(1), (
        f"`handle {path}` block does not reverse_proxy to api:8000: {match.group(1)!r}"
    )
    assert "import https_location" in match.group(1), (
        f"`handle {path}` block does not import the https_location snippet, so a "
        f"redirect from this route would still carry a dead http:// Location: "
        f"{match.group(1)!r}"
    )
```

(This extends the existing parametrized test rather than adding a new one — the existing regex's capture group already reaches inside a `reverse_proxy { }` sub-block, confirmed in the design spec's §2.3/D2.)

- [ ] **Step 2: Run the test and confirm it fails**

```bash
REIM_TEST_DATABASE_URL=${REIM_TEST_DATABASE_URL:-postgresql+psycopg://reim:reim@localhost:55432/reim} \
  .venv/bin/python -m pytest tests/unit/test_deploy_artifacts.py::test_each_api_handle_reverse_proxies_to_the_api_service -v
```
Expected: 8 FAILs (one per parametrized `path`), each on the new `import https_location` assertion.

- [ ] **Step 3: Add the snippet definition to `deploy/Caddyfile`**

Insert immediately after the global options block's closing `}` (the block starting `{` at line 15 and ending `}` at line 25) and before `{$REIM_DOMAIN} {`. Replace:

```caddyfile
	email "{$REIM_ACME_EMAIL}"
}

{$REIM_DOMAIN} {
```

with:

```caddyfile
	email "{$REIM_ACME_EMAIL}"
}

# uvicorn runs with --no-proxy-headers (see Dockerfile's own comment on why:
# it keeps client-identity trust in exactly one place, REIM's own
# X-Forwarded-For handling in apps/api/middleware.py). That means the app's
# ASGI scope always reports scheme=http — Caddy is the only thing that knows
# this deployment actually terminates TLS — so any redirect_slashes 307/308
# the app issues builds a Location starting with the wrong scheme. Rewritten
# here, not by re-enabling uvicorn's ProxyHeadersMiddleware, which would also
# re-trust X-Forwarded-For and reopen the exact surface --no-proxy-headers
# was set to close. Imported into every reverse_proxy block that targets the
# api container; the frontend's own redirects (Caddy's file_server directory
# canonicalization) are already scheme-correct and need no rewrite.
(https_location) {
	header_down Location "^http://" "https://"
}

{$REIM_DOMAIN} {
```

- [ ] **Step 4: Import the snippet into all 8 api-targeting handles**

All 8 occurrences of the two-line body are identical, so this is one `replace_all` edit. Replace (every occurrence):

```caddyfile
		reverse_proxy api:8000
	}
```

with:

```caddyfile
		reverse_proxy api:8000 {
			import https_location
		}
	}
```

Verify the count matches expectations before and after:

```bash
grep -c '^		reverse_proxy api:8000$' deploy/Caddyfile
```
Expected before this step: `8`. After this step: `0` (every bare occurrence is now followed by `{`).

```bash
grep -c 'import https_location' deploy/Caddyfile
```
Expected after this step: `8`.

The frontend's `handle { ... reverse_proxy frontend:8080 }` block must be unchanged — confirm:
```bash
grep -A1 'reverse_proxy frontend:8080' deploy/Caddyfile
```
Expected: no `import https_location` line follows it.

- [ ] **Step 5: Run the test and confirm it passes**

```bash
REIM_TEST_DATABASE_URL=${REIM_TEST_DATABASE_URL:-postgresql+psycopg://reim:reim@localhost:55432/reim} \
  .venv/bin/python -m pytest tests/unit/test_deploy_artifacts.py -v
```
Expected: all PASS (including the pre-existing default-handle and HSTS-scope tests, unaffected by this change).

- [ ] **Step 6: Validate the Caddyfile syntax**

```bash
REIM_DOMAIN=example.test REIM_ACME_EMAIL= caddy validate --config deploy/Caddyfile --adapter caddyfile
```
Expected: `Valid configuration`.

- [ ] **Step 7: Run the full backend gate**

```bash
make check
```
Expected: exit code 0.

- [ ] **Step 8: Commit**

```bash
git add deploy/Caddyfile tests/unit/test_deploy_artifacts.py
git commit -m "fix(deploy): rewrite dead http:// redirect Location at the Caddy layer"
```

---

### Task 2: Deploy the fix to panda

**Files:**
- Modify (live, outside git): `/etc/caddy/sites/reim.caddy`
- Modify: `docs/deployment-panda.md`

**Interfaces:**
- Consumes: the exact snippet name/rule and the same 8 handle paths from Task 1 — panda's file gets the identical edit, upstream addresses aside.

- [ ] **Step 1: Prepare and validate a candidate copy of panda's live file**

```bash
mkdir -p /tmp/reim-caddy-candidate
cp /etc/caddy/sites/reim.caddy /tmp/reim-caddy-candidate/reim.caddy
```

Apply the same two edits Task 1 made to `deploy/Caddyfile`, adjusted for panda's upstream addresses (`127.0.0.1:8000` in place of `api:8000`; no global options block to insert after, since panda's `reim.caddy` has none of its own — the snippet goes at the very top of the file, before `reim.panda.home.arpa {`). The resulting file:

```caddyfile
(https_location) {
	header_down Location "^http://" "https://"
}

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
		reverse_proxy 127.0.0.1:8000 {
			import https_location
		}
	}

	handle /legacy* {
		reverse_proxy 127.0.0.1:8000 {
			import https_location
		}
	}

	handle /static/* {
		reverse_proxy 127.0.0.1:8000 {
			import https_location
		}
	}

	handle /health {
		reverse_proxy 127.0.0.1:8000 {
			import https_location
		}
	}

	handle /ready {
		reverse_proxy 127.0.0.1:8000 {
			import https_location
		}
	}

	handle /docs* {
		reverse_proxy 127.0.0.1:8000 {
			import https_location
		}
	}

	handle /redoc {
		reverse_proxy 127.0.0.1:8000 {
			import https_location
		}
	}

	handle /openapi.json {
		reverse_proxy 127.0.0.1:8000 {
			import https_location
		}
	}

	handle {
		reverse_proxy 127.0.0.1:8080
	}
}
```

Write this exact content to `/tmp/reim-caddy-candidate/reim.caddy`, then validate:

```bash
caddy validate --config /tmp/reim-caddy-candidate/reim.caddy --adapter caddyfile
```
Expected: `Valid configuration`.

- [ ] **Step 2: Apply the live Caddy config change — CONFIRM WITH THE USER FIRST**

This touches a process serving 4 other live sites (`git`, `grafana`, `n8n`, `cockpit`). Confirm with the user immediately before running this, even though it was approved as part of this plan. This session cannot supply an interactive `sudo` password — ask the user to run it themselves:

```bash
sudo cp /tmp/reim-caddy-candidate/reim.caddy /etc/caddy/sites/reim.caddy
sudo systemctl reload caddy
```

- [ ] **Step 3: Verify the reload, independently — do not trust a bare confirmation**

```bash
diff /etc/caddy/sites/reim.caddy /tmp/reim-caddy-candidate/reim.caddy
```
Expected: no output (files identical).

```bash
systemctl status caddy --no-pager | head -8
```
Expected: `Active: active (running) since` a date before today (proves reload, not restart), and `ExecReload=... (code=exited, status=0/SUCCESS)`.

- [ ] **Step 4: Reproduce the original bug and confirm it is gone**

```bash
curl -sk -D - https://reim.panda.home.arpa/legacy/series/
```
Expected: `307`, `location: https://reim.panda.home.arpa/legacy/series` (scheme now correct — was `http://`).

```bash
curl -sk -L -o /dev/null -w '%{http_code}\n' https://reim.panda.home.arpa/legacy/series/
```
Expected: `200` (the redirect now actually resolves, following it end-to-end).

- [ ] **Step 5: Spot-check ordinary responses are unaffected**

```bash
curl -sk -o /dev/null -w '%{http_code}\n' https://reim.panda.home.arpa/api/v1/countries
curl -sk -o /dev/null -w '%{http_code}\n' https://reim.panda.home.arpa/
curl -sk -D - -o /dev/null https://reim.panda.home.arpa/api/v1/countries 2>&1 | grep -i strict-transport
```
Expected: `200`, `200`, and the HSTS header still present (unrelated to this fix, confirms the earlier fix wave's HSTS change wasn't disturbed).

- [ ] **Step 6: Update `docs/deployment-panda.md`**

In the `### \`/etc/caddy/sites/reim.caddy\`` section, replace the existing code block with the new version from Step 1, and add a short paragraph after it (matching the style of the "Two corrections applied after the initial rollout" paragraph already there) explaining the `https_location` snippet and pointing at the live reproduction from Step 4 (before: `http://`, after: `https://`).

- [ ] **Step 7: Commit**

```bash
git add docs/deployment-panda.md
git commit -m "docs: record the redirect scheme fix deployed to panda"
```

---

## Done when

- `deploy/Caddyfile` and panda's live `/etc/caddy/sites/reim.caddy` both rewrite any `Location: http://...` from the api upstream to `https://`, verified by test (generic) and live curl (panda).
- The frontend's own handle is untouched.
- `make check` passes; `caddy validate` passes on both files.
- `docs/deployment-panda.md` matches what's actually running.
