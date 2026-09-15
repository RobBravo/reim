# Deployment Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close what the final audit of the deployment increment found — one HIGH, seven MEDIUM and several LOW findings, almost all of them claims the documentation makes that the deployment does not keep.

**Architecture:** No new subsystem. Five tasks over the files the previous increment shipped: the production compose file, the Caddyfile, the example environment file, the deployment guide, and two small CLI corrections. Every claim corrected here is corrected toward what was measured, not toward what reads well.

**Tech Stack:** podman + compose, Caddy 2, FastAPI, Typer, SQLAlchemy 2, pytest.

**Spec:** `docs/superpowers/specs/2026-09-15-deployment-guide-design.md` — still governing, unchanged. The requirements for *this* plan are the findings in `.superpowers/sdd/2026-09-15-deployment-guide/final-audit.md`, which is the audit of that spec's implementation. No new spec: a correction pass whose input is an enumerated defect list does not need one, and writing it would only restate the audit.

## Global Constraints

- The gate, from the repository root, is
  `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q`.
  Integration tests need `REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim`; **without it most of them skip silently**, and a suite number reported from a run without it is not the gate. Report the number from a full run.
- The suite stands at **1052 passed, 7 deselected** before this plan. The 7 deselected are the pre-existing `-m 'not live'` in `pyproject.toml:154`.
- No Docker daemon; use `podman`. No `pip` in `.venv`; use `.venv/bin/<tool>`.
- `ruff format` silently rewrites any ` ```python ` block in Markdown that is not a valid standalone module. Fence shell, YAML, Caddyfile and cron samples as ` ```text `, then run `.venv/bin/ruff format .` and confirm no change to any Markdown file.
- **A correction is only correct if it matches what was measured.** `.superpowers/sdd/2026-09-15-deployment-guide/measurements.md` holds the observations; the audit holds what it reproduced. Where this plan and either of those disagree, they win — say so rather than following the plan.
- Do not write a real password, token, webhook URL or ACME email into any file.
- **Every measurement names its rival hypothesis before it runs.** State what
  the negation of your claim would predict. If it predicts the same output you
  are about to observe, the measurement decides nothing — redesign it rather
  than run it. A multi-cell probe must have at least one cell where the two
  hypotheses diverge, and you say which cell that is. This is the design-time
  half of the mutation drills; the drills check the implementation, this checks
  the instrument.

---

### Task 1: The flag that must survive being edited

`--no-proxy-headers` is what stops uvicorn deciding the rate limiter's identity from a header any client can set. It was added to `Dockerfile` with a five-line comment explaining why — and then `deploy/docker-compose.prod.yml` gave the `api` service its own `command:`, which **overrides** that `CMD` entirely. So the flag now lives at `deploy/docker-compose.prod.yml:77` with no comment, no test, and no mention in the guide, while the guide's own scaling bullet at `docs/deployment.md:359-364` says "Neither `Dockerfile` nor `docker-compose.prod.yml` passes `--workers`" — pointing a reader at that exact line and inviting them to retype it.

This is the defect shape the whole increment existed to prevent, returned through a different door.

**Files:**
- Modify: `deploy/docker-compose.prod.yml:74-77`
- Modify: `docs/deployment.md` (the hardening table, and the scaling bullet at 359-364)
- Test: `tests/unit/test_deploy_artifacts.py`

**Interfaces:**
- Consumes: the existing `production` fixture in `tests/unit/test_deploy_artifacts.py`, which parses `deploy/docker-compose.prod.yml` with `yaml.safe_load`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_deploy_artifacts.py`:

```python
def test_the_production_command_keeps_uvicorn_out_of_the_identity_decision(
    production: dict,
) -> None:
    """``--no-proxy-headers`` must survive every edit to this command.

    uvicorn's own proxy-header handling is enabled by default and trusts
    127.0.0.1, so without this flag it rewrites the client address from a
    caller-supplied ``X-Forwarded-For`` before REIM's limiter runs — and
    ``REIM_TRUSTED_PROXY_HOPS`` decides nothing. The ``Dockerfile``'s ``CMD``
    carries the same flag and an explanation, but this ``command:`` overrides
    that ``CMD`` entirely, so the Dockerfile's copy protects nothing here.
    """
    command = production["services"]["api"]["command"]

    assert "uvicorn" in command, "the api service no longer runs uvicorn; this test needs rewriting"
    assert "--no-proxy-headers" in command, (
        "docker-compose.prod.yml runs uvicorn without --no-proxy-headers, so a "
        "client-supplied X-Forwarded-For header decides its own rate-limit identity"
    )
```

- [ ] **Step 2: Run it to verify it passes, then prove it can fail**

Run: `.venv/bin/pytest tests/unit/test_deploy_artifacts.py -q`
Expected: PASS — the flag is already there; this test guards it rather than adding it.

Then the drill, which is the point of the test: delete `--no-proxy-headers` from the `command:` in `deploy/docker-compose.prod.yml`, re-run, confirm it FAILS with the message above, and restore. Report the exact output.

- [ ] **Step 3: Comment the flag where it now lives**

In `deploy/docker-compose.prod.yml`, above the `command:` block:

```text
    # This command REPLACES the Dockerfile's CMD, including the comment there
    # explaining --no-proxy-headers. Keep the flag: uvicorn's own
    # ProxyHeadersMiddleware is on by default and trusts 127.0.0.1, so without
    # it uvicorn rewrites the client address from a caller-supplied
    # X-Forwarded-For before REIM's limiter runs, and REIM_TRUSTED_PROXY_HOPS
    # stops meaning anything. If you edit this line — to add --workers, say —
    # the flag goes with it.
```

- [ ] **Step 4: Give it a hardening row in the guide**

The spec's §3.1 binds the hardening section to one row per item, each with what to do **and the command or test that shows it worked**. `--no-proxy-headers` has no row. Add one, in the table's existing format, citing the test from Step 1 and the runtime evidence already recorded: with the flag, three forged `X-Forwarded-For` headers through Caddy were all refused.

- [ ] **Step 5: Fix the bullet that invites the mistake**

`docs/deployment.md:359-364` currently reads, in part: "Neither `Dockerfile` nor `docker-compose.prod.yml` passes `--workers`".

Rewrite it so a reader who acts on it keeps the flag: say that `--workers` would be added to the `command:` in `docker-compose.prod.yml`, that `--no-proxy-headers` must be preserved when doing so, and keep the existing point that *N* workers multiply the effective rate limit by *N* because counters are per process.

- [ ] **Step 6: Run the gate and commit**

```text
.venv/bin/ruff format . && git status --short
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
```

Expect no formatter change to `docs/deployment.md`, and 1053 passed.

```bash
git add deploy/docker-compose.prod.yml docs/deployment.md tests/unit/test_deploy_artifacts.py
git commit -m "fix(deploy): guard the flag that keeps uvicorn out of the identity decision"
```

---

### Task 2: Every setting an operator can set, and what a bad one costs

Two findings, one cause. `REIM_MAX_EXPORT_ROWS` has no path through `deploy/docker-compose.prod.yml` — the **third** instance of the same gap, after the rate-limit settings and the alert settings — so `docs/deployment.md:346-355` names it as a thing to tune while setting it does nothing, silently. And a typo in any of four settings does not degrade: `Settings` validation raises at import, uvicorn dies, the container crash-loops, `caddy`'s `condition: service_healthy` is never satisfied, and TLS goes down with it.

**Files:**
- Modify: `deploy/docker-compose.prod.yml`
- Modify: `deploy/.env.prod.example`
- Modify: `docs/deployment.md`
- Test: `tests/unit/test_deploy_artifacts.py`

- [ ] **Step 1: Find every setting that is not wired, rather than fixing the one the audit named**

Three instances of this gap have been found one at a time. Enumerate instead: list the fields of `Settings` in `reim/core/config.py`, list the `REIM_*` keys in the `api` service's environment block, and report the difference. Put that list in your report.

Then decide, per unwired setting, whether an operator of a public deployment would plausibly want it — and wire those. A setting nobody would set from `.env` does not need a line; say which you excluded and why.

- [ ] **Step 2: Extend the configurability test to what you wired**

`tests/unit/test_deploy_artifacts.py` already has `test_rate_limit_is_configurable_without_editing_the_compose_file`, whose tuple now covers seven variables. Its name no longer matches its scope. Rename it to cover what it now asserts — the settings an operator tunes reach the container — and add the variables from Step 1.

Drill: remove one of the newly added variables, confirm the test fails, restore, report the output.

- [ ] **Step 3: Document the bounds in `.env.prod.example`**

Each setting you wired gets a line saying what it does and what values are legal. Read the bounds from `reim/core/config.py` — several fields carry `ge=`/`le=` constraints, and `alert_severity_floor` is an enum with four members. An operator who knows the bounds does not discover them through a crash loop.

- [ ] **Step 4: Tell the guide what a bad value does**

Add a short subsection to `docs/deployment.md`. It must say plainly: a value that fails validation is not ignored and does not fall back to a default — the API container fails at import and restarts forever, and because `caddy` waits on `condition: service_healthy`, **the site goes down with it, TLS included**.

Then give the operator the check that avoids it. A validation failure is visible in `podman compose … logs api`; name the command, and say to run it after changing `.env` and restarting, before walking away.

- [ ] **Step 5: Run the gate and commit**

```text
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
```

```bash
git add deploy/docker-compose.prod.yml deploy/.env.prod.example docs/deployment.md tests/unit/test_deploy_artifacts.py
git commit -m "fix(deploy): wire the settings an operator tunes, and say what a bad one costs"
```

---

### Task 3: Pin the version the invariant was measured at

`REIM_TRUSTED_PROXY_HOPS=1` is correct because Caddy **overwrites** `X-Forwarded-For` rather than appending. That was measured through a running proxy — twice, and the final audit reproduced it at **Caddy v2.11.4** with four header shapes. But `deploy/docker-compose.prod.yml:88` pulls `docker.io/library/caddy:2-alpine`, a floating tag: the next `2.x` release replaces the binary the measurement was taken against, and nothing notices.

Two smaller Caddyfile gaps go with it.

**Files:**
- Modify: `deploy/docker-compose.prod.yml:88`
- Modify: `deploy/Caddyfile`
- Modify: `deploy/.env.prod.example`
- Modify: `docs/deployment.md`
- Test: `tests/unit/test_deploy_artifacts.py`

- [ ] **Step 1: Write the failing test**

```python
def test_the_proxy_image_is_pinned_to_an_exact_version(production: dict) -> None:
    """The header behaviour REIM_TRUSTED_PROXY_HOPS=1 rests on was measured
    against one Caddy build.

    Caddy overwrites X-Forwarded-For rather than appending, which is what makes
    one hop the right number. A floating tag lets a future release replace the
    binary that was measured, with nothing to notice the change.
    """
    image = production["services"]["caddy"]["image"]

    tag = image.rsplit(":", 1)[-1]
    assert re.fullmatch(r"\d+\.\d+\.\d+(-\w+)?", tag), (
        f"caddy image tag {tag!r} is not an exact version; the measured "
        "X-Forwarded-For behaviour is not pinned to anything"
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_deploy_artifacts.py -q`
Expected: FAIL — the tag is `2-alpine`.

- [ ] **Step 3: Pin it, and say why in the file**

Change `deploy/docker-compose.prod.yml:88` to `docker.io/library/caddy:2.11.4-alpine`, with a comment saying that this is the version the overwrite-not-append behaviour was measured against, and that upgrading means re-measuring — a forged `X-Forwarded-For` through the new proxy, checking it buys no fresh allowance.

Verify the tag exists before committing: `podman pull docker.io/library/caddy:2.11.4-alpine`. If it does not, use the exact version the audit recorded and say what you found.

- [ ] **Step 4: Add the ACME contact and HSTS**

`deploy/Caddyfile` sets no global `email`, so the ACME account has no contact address and the CA sends the operator nothing about expiry or problems. Add a global options block taking the address from an environment variable — `REIM_ACME_EMAIL` — and add it to `deploy/.env.prod.example` with an empty value and a line saying what it is for. **Never write a real address into either file.**

Nothing sets `Strict-Transport-Security`; Caddy does not add it by default. Add it in the catch-all handler.

- [ ] **Step 5: Say how to scrape `/metrics`, since the proxy closes it**

The Caddyfile returns `404` for `/metrics`, which is the intended restriction — but `docs/deployment.md` never tells an operator how Prometheus is supposed to reach it. Document the way that works with this deployment: from inside the compose network, or over a tunnel to the api service. Name the address the api service answers on.

Only document what you can state accurately from the compose file; if you cannot verify a scrape path without starting the stack, say which part is untested rather than inventing a command.

- [ ] **Step 6: Name the byte budget the guide already tells operators to set**

`docs/deployment.md:346-355` states the trade-off honestly — the limiter counts
requests, not bytes, so `export.csv` at up to `REIM_MAX_EXPORT_ROWS` rows costs
one unit like any other call — and then says *"If you need a byte budget, set
one at the proxy."* No directive is shipped and none is named, which leaves the
mitigation as a gesture.

Name the Caddy directive that would do it, in the guide, next to the sentence
that recommends it. Do not ship it enabled: a byte cap is a policy decision
about a public data platform, and the spec's §3.2 is explicit that this
trade-off is accepted rather than fixed. Shipping it commented in the Caddyfile,
with the guide pointing at it, is the shape to aim for.

If you cannot confirm the directive's exact name and syntax for the pinned Caddy
version, say so and name only what you verified — an invented directive is worse
than the gesture it replaces.

- [ ] **Step 7: Run the gate and commit**

```text
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
```

```bash
git add deploy/docker-compose.prod.yml deploy/Caddyfile deploy/.env.prod.example docs/deployment.md tests/unit/test_deploy_artifacts.py
git commit -m "fix(deploy): pin the proxy the header behaviour was measured against"
```

---

### Task 4: The claims the guide makes that the deployment does not keep

Documentation only. Each item is a specific line the audit checked and found wrong, stale, or missing. Verify each against the code before rewriting it — the audit is right as of `fb77e57`, but the file is what you are editing.

**Files:**
- Modify: `docs/deployment.md`
- Modify: `deploy/.env.prod.example`

- [ ] **Step 1: The CORS row is false**

`docs/deployment.md:341` claims **"Refuse a CORS wildcard"**. The compose file uses `${REIM_CORS_ALLOW_ORIGINS:?set the allowed origins}`, which requires the variable to be *set* — it does not reject `*`. Measured: `REIM_CORS_ALLOW_ORIGINS=*` boots fine and resolves to `['*']`.

Rewrite the row to what the mechanism does: the stack refuses to start until the operator states a value, which makes the wildcard a deliberate choice rather than a default. Keep the verification column honest — the test it cites checks the file's declared default, not a runtime value.

- [ ] **Step 2: The healthcheck explanation states a wrong rule**

`docs/deployment.md:119-130` explains the cold-start timing with a polling rule that is wrong, and contradicts the measurement quoted in the same sentence. The measurement: the app served at ~6.5s, and the healthcheck reported healthy at ~30.4s. Rewrite the explanation so it matches `deploy/docker-compose.prod.yml`'s actual `interval`, `timeout`, `retries` and `start_period`, and so it explains the ~24s gap as a consequence of when the check next runs rather than of anything being slow.

- [ ] **Step 3: Three settings are read from `.env` and documented nowhere**

`POSTGRES_USER`, `POSTGRES_DB` and `REIM_LOG_LEVEL` are read by `deploy/docker-compose.prod.yml` but appear in neither `deploy/.env.prod.example` nor the guide. Setting the first two silently breaks the guide's own `pg_dump` and `psql` commands, which hardcode the defaults.

Document all three. For the two Postgres ones, say in the backup section that the commands assume the defaults and must be adjusted if they were changed.

- [ ] **Step 4: What is public and unlimited is not in the hardening section**

The rate limiter covers `/api/v1` only. The three web pages, `/static`, `/docs` and `/openapi.json` are served through Caddy, publicly, exempt from it. That is the documented design — but the hardening section never says so, and an operator reading only that section would not know.

Add it plainly: what is exposed, that it is deliberate, and that an operator who does not want the docs published closes them at the proxy the way `/metrics` is closed.

- [ ] **Step 5: The example file contradicts itself**

`deploy/.env.prod.example:2-4` says "Nothing here has a default: every one of these is a decision." Lines 16-19 say the opposite about everything below them. Scope the opening sentence to the variables it is true of.

- [ ] **Step 6: Two honest gaps deserve the advice that goes with them**

The guide already discloses both of these, which is why they are corrections rather than defects:

- **Certificate issuance was never exercised** — `REIM_DOMAIN` was `localhost` and Caddy used its internal CA. Add the advice that makes the first real attempt survivable: Let's Encrypt limits failures per account per hour, a DNS mistake burns that budget, and Caddy can be pointed at the ACME staging endpoint for a first run. Name the directive; mark it untested here.
- **The crontab lines were never run as cron jobs** — and under rootless podman, a bare crontab environment typically lacks `XDG_RUNTIME_DIR`, so `podman` cannot find its socket and the job fails silently into cron mail. Say so where the crontab is installed, and give the variable that has to be set. Mark it untested.

- [ ] **Step 7: Check the formatter, run the gate, commit**

```text
.venv/bin/ruff format . && git status --short
```

Expect no change to `docs/deployment.md` or `deploy/.env.prod.example`. Then the full gate, then:

```bash
git add docs/deployment.md deploy/.env.prod.example
git commit -m "docs(deploy): correct what the guide claims but the deployment does not do"
```

---

### Task 5: Two small corrections in the CLI

Both were deferred as minors during the previous increment and confirmed by the audit. Neither is exploitable; both are the kind of inconsistency that costs a reader confidence in everything around it.

**Files:**
- Modify: `reim/cli/main.py:186`
- Modify: `reim/repositories/api_keys.py`
- Test: `tests/integration/test_cli_keys.py`, and wherever `create_key` is unit-tested

- [ ] **Step 1: The empty-label error does not follow the file's own convention**

`reim/cli/main.py:186` uses `typer.echo(..., err=True)` directly. Every other error path in that file — 17 call sites — uses the `err` alias with a `✗ ` prefix. The stream and the exit code are already right; only the prefix differs. Make it match, and check the existing tests still pass: one of them may assert on the message text.

- [ ] **Step 2: `create_key` carries no invariant of its own**

The empty-label rule lives only at the CLI call site. `create_key` in `reim/repositories/api_keys.py` will happily write a row with an empty label if anything else ever calls it. One caller exists today, so this is not a live defect — it is an invariant belonging to the layer that owns the row.

Write the failing test first: call `create_key` directly with an empty label and with a whitespace-only label, and assert it raises. Then add the guard, raising the exception type this repository already uses for invalid input — read `reim/core/exceptions.py` and follow the existing pattern rather than introducing a new type.

- [ ] **Step 3: Confirm the CLI's behaviour is unchanged**

The CLI guard now sits in front of a repository guard. The CLI must still exit with its own code and message rather than surfacing a traceback — the existing tests cover this, and they must still pass unchanged.

- [ ] **Step 4: Mutation drill**

Remove the repository guard, confirm the new tests fail and the CLI tests still pass — which is the point: the two guards are independent, and the CLI's behaviour does not depend on the repository's. Report the output, restore.

- [ ] **Step 5: Run the gate and commit**

```text
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
```

```bash
git add reim/cli/main.py reim/repositories/api_keys.py tests/
git commit -m "fix(cli): one error convention, and the label invariant where the row lives"
```

---

## Deliberately not in this plan

* **LOW-6 — `pipeline schedule` has a `python=` hook the CLI does not expose.**
  Exposing it is a new CLI option, which is a feature rather than a correction,
  and nothing in the audit shows an operator blocked by its absence. It stays
  recorded in the audit.
* **Q1's underlying gap — real ACME issuance.** Nobody here has a public domain,
  so it cannot be measured, and this plan does not pretend otherwise. Task 4
  Step 6 adds the advice that makes a first attempt survivable; the step itself
  stays unverified and is marked so in the guide.

## Done when

* `--no-proxy-headers` is commented where it actually lives, pinned by a test whose mutation makes it fail, present in the hardening table, and the scaling bullet no longer invites deleting it.
* Every `Settings` field an operator would plausibly set reaches the container, the list of what was excluded and why is recorded, and the guide says what a value that fails validation costs.
* The Caddy image is pinned to the version the header behaviour was measured against, with a test that rejects a floating tag.
* The guide's CORS row, healthcheck explanation and settings enumeration match the code; what is public and unlimited is stated; the two disclosed gaps carry the advice that makes them survivable.
* `create_key` refuses an empty label on its own, and the CLI's error matches the seventeen others in its file.
* The full gate passes: `ruff check`, `ruff format --check`, `mypy reim apps`, `pytest -q`.
