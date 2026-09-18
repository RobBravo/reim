# Deployment Residuals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the nine residuals the last increment's final re-review parked, plus one disclosed gap that has become measurable.

**Architecture:** No new subsystem and no behaviour change an operator would notice. Three tasks: one paragraph that has now been wrong three times and gets measured on the platform it describes, one partition whose reach ends short of where it claims to go, and two pointers that outlived what they point at.

**Tech Stack:** podman + compose, Caddy 2.11.4, FastAPI, Typer, pytest.

**Spec:** none. The requirements are the residual findings in the previous increment's final re-review, restated in full below — a correction pass over an enumerated defect list does not need a spec, and writing one would only restate the list.

## Global Constraints

- The gate, from the repository root, is
  `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q`.
  Integration tests need `REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim`; **without it most skip silently**, and a number reported from a run without it is not the gate.
- The suite stands at **1067 passed, 7 deselected** before this plan. The 7 deselected are the pre-existing `-m 'not live'` in `pyproject.toml:154`.
- No Docker daemon; use `podman`, which is also the platform two of these findings are *about*. No `pip` in `.venv`; use `.venv/bin/<tool>`.
- `ruff format` silently rewrites any ` ```python ` block in Markdown that is not a valid standalone module. Fence shell, YAML, Caddyfile and cron samples as ` ```text `, then run `.venv/bin/ruff format .` and confirm no Markdown file changed.
- **Every measurement names its rival hypothesis before it runs.** State what the negation would predict; if it predicts the same output you are about to observe, the measurement decides nothing and must be redesigned. A multi-cell probe names the cell where the two diverge.
- Run the gate in the **foreground**. A backgrounded run does not survive a turn ending, and that cost four agents their reports during the previous increment.
- Never write a real password, token, email address or webhook URL into any file.

---

### Task 1: The healthcheck paragraph, measured on the platform it describes

`docs/deployment.md:150-182` explains why the API serves ~6.5 s after container start while the healthcheck reports healthy at ~30 s. It has now been wrong twice and rewritten twice. The current version is accurate about every figure it *observed* — and wrong in two things it reasoned:

* **`docs/deployment.md:180` offers `start_interval` as the lever on the gap.** podman 5.8.4 rejects the flag and silently drops the compose key. An operator following that advice edits, redeploys, and gets exactly the same timeline with no error to read.
* **`docs/deployment.md:179` says `start_period` is "load-bearing today".** Measured at `start_period: 0` with `retries: 3`, the health timeline is identical — `starting` → `healthy` at probe 2, never unhealthy.

**Files:**
- Modify: `docs/deployment.md:150-182`

**Interfaces:** none — documentation only.

- [ ] **Step 1: Measure `start_interval` on podman**

Build a throwaway compose file with a `start_interval` on a healthchecked service and bring it up under podman. Record: whether podman accepts the key, whether it warns, and whether the resulting container has `StartInterval` set (`podman inspect`).

**Rival hypothesis to name:** that podman honours `start_interval` and the earlier observation was a mis-read. It predicts `StartInterval` present in the inspect output and a shortened first-probe gap. The cell separates on both.

- [ ] **Step 2: Measure whether `start_period` changes anything here**

Same service, two cells: `start_period: 20s` as shipped, and `start_period: 0`. Record the full health timeline for each — every probe, its exit status, and when the status becomes `healthy`.

**Rival hypothesis:** that `start_period` is load-bearing, which predicts an unhealthy window or a different transition in the second cell. If both timelines are identical, the paragraph's claim is false and you say so.

- [ ] **Step 3: Rewrite the two sentences from what you measured**

Not from the compose fields, and not from this plan. If a measurement contradicts anything written here, the measurement wins and your report says which line of this plan was wrong.

Whatever replaces the `start_interval` advice must be a lever that works on podman, or an honest statement that the gap is cosmetic and the fix is not worth taking. "Nothing to do here" is an acceptable answer if that is what the measurement supports.

- [ ] **Step 4: Check the formatter, run the gate, commit**

```text
.venv/bin/ruff format . && git status --short
```

Expect no change to `docs/deployment.md`. Then the full gate, then:

```bash
git add docs/deployment.md
git commit -m "docs(deploy): measure the healthcheck gap on podman, not on the compose fields"
```

---

### Task 2: The partition's reach

The previous increment built four partitions so a setting cannot be half-introduced, and then extended one of them to every compose service. Five residuals say the reach still ends short of where the names claim it goes.

**Files:**
- Modify: `tests/unit/test_deploy_artifacts.py`
- Modify: `docs/deployment.md` (only if a prose line has to move; see Step 3)

**Interfaces:**
- Consumes: `OPERATOR_SETTABLE`, `PINNED_IN_COMPOSE`, `REQUIRED_IN_COMPOSE`, `EXCLUDED_FROM_COMPOSE`, and `_reim_environment()`, all module-level in that file.

- [ ] **Step 1: Write the failing tests**

Four properties, none currently asserted. Write them first and watch each fail.

```python
def test_operator_settable_variables_really_read_from_env(production: dict) -> None:
    """A member of OPERATOR_SETTABLE that is hardcoded is settable in name only.

    The class is checked for presence, not for form. Hardcoding caddy's
    REIM_ACME_EMAIL to a literal leaves every test green while an operator's
    .env value silently never reaches the container.
    """
    environment = _reim_environment(production)

    hardcoded = sorted(
        name
        for name in OPERATOR_SETTABLE
        if name in environment and "${" not in str(environment[name])
    )

    assert hardcoded == [], (
        f"these are named operator-settable but hold a literal: {hardcoded}. "
        "An operator setting them in deploy/.env would see no effect."
    )
```

```python
def test_a_non_reim_variable_on_any_service_is_not_reported_as_name_drift() -> None:
    """A service may legitimately carry TZ or PATH.

    The orphan assertion currently rejects any non-REIM_ key and blames a name
    drift in the partition, sending a maintainer to the wrong file.
    """
```

Write that second test against whatever the orphan assertion is called in the file — read it first. The property is: a non-`REIM_` key on any service is ignored rather than reported, and the message a genuine `REIM_*` orphan produces still names the partition.

Then two more, whose exact shape depends on what you find:

* **`PINNED_IN_COMPOSE` is structurally unreachable for non-`api` services** while the partition demands every service's keys be classified. Either make it reachable or make the partition say that pinning is an `api`-only concept — and assert whichever you choose, so the next person meets a message rather than a contradiction.
* **`_reim_environment()` is last-wins** when two services set the same key. No collision exists today. Assert that no collision exists, so one cannot appear silently.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_deploy_artifacts.py -q`

Expected: the first fails only if something is currently hardcoded — if nothing is, **the test passes on arrival and its mutation drill is the only evidence it works**. Say which case you are in.

- [ ] **Step 3: The prose that weakened a test**

Two illustrative `REIM_ACME_EMAIL=` lines added to `docs/deployment.md` during the last increment satisfy the documentation regex, so deleting the real entry from `deploy/.env.prod.example` no longer fails anything. Prose near a test quietly disarmed it.

Fix the check rather than the prose if you can — the documentation test should be looking at `deploy/.env.prod.example`, not at any file that happens to contain a matching line. If the prose genuinely has to move instead, move it and say why.

Drill it: delete `REIM_ACME_EMAIL` from the example file and confirm the test fails again.

- [ ] **Step 4: Make the fixes, and drill each**

For every test in Step 1, apply the mutation that should fail it, confirm it does, restore, and report the exact output. For the hardcoding test, the mutation is replacing a `${VAR:-default}` with a literal.

Name the rival hypothesis for each.

- [ ] **Step 5: Run the gate and commit**

```text
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
```

```bash
git add tests/unit/test_deploy_artifacts.py docs/deployment.md
git commit -m "test(deploy): make the partition reach as far as its names claim"
```

---

### Task 3: Two pointers that outlived what they point at

**Files:**
- Modify: `deploy/Caddyfile`
- Modify: `docs/deployment.md`

- [ ] **Step 1: The Caddyfile points at advice the guide no longer gives**

`deploy/Caddyfile:43-46` says `docs/deployment.md`'s "limit counts requests, not bytes" section "points here for a byte budget". The guide was then rewritten to state plainly that **no directive in the pinned build caps a response** — so it points nowhere, and the Caddyfile's own comment self-corrects nine lines later.

Rewrite the opening so the comment says what the block is from its first line: a request-body cap, shipped commented, which does not bound `export.csv` and is not the byte budget anyone was looking for.

Verify before you write: `caddy list-modules` against `docker.io/library/caddy:2.11.4-alpine` still shows `http.handlers.request_body` as the only body- or size-related handler.

- [ ] **Step 2: Measure whether the crontab lines work under rootless podman**

`docs/deployment.md` installs `podman compose … exec -T api …` lines in a host crontab, and discloses that the substitution was never run as a cron job. Under rootless podman a bare crontab environment typically lacks `XDG_RUNTIME_DIR`, so `podman` cannot find its socket and the job fails silently into cron mail.

That was untestable when written. It is testable now: run one of the guide's own cron lines through `env -i` — an empty environment with only `PATH` — and record what happens.

**Rival hypothesis:** that the bare environment is sufficient and the concern is theoretical. It predicts the command succeeding under `env -i`. If it fails, record the exact error, then find the minimum set of variables that makes it work and record that too.

- [ ] **Step 3: Write what you measured into the guide**

If the cron lines need `XDG_RUNTIME_DIR` (or anything else), say so where the crontab is installed and show the working form. Replace the "this was never run as a cron job" disclosure with what you observed — or keep a narrower disclosure if some part remains untested, and say which part.

- [ ] **Step 4: Check the formatter, run the gate, commit**

```text
.venv/bin/ruff format . && git status --short
```

Expect no change to `docs/deployment.md`. Then the full gate, then:

```bash
git add deploy/Caddyfile docs/deployment.md
git commit -m "docs(deploy): point at what exists, and run the crontab line before promising it"
```

---

## Deliberately not in this plan

* **Real ACME certificate issuance (Q1 of the deployment audit).** Nobody here has a public domain, so it cannot be measured, and the guide already discloses that the single step between an operator and a working deployment is the one step nobody has run. Documenting it further without running it would be the exact failure this project keeps correcting.
* **The commit-message character count (R8).** A merged commit message says 249 where the value is 260. Git history is not editable in place and the number is inconsequential; the range and argmax it referred to are correct.
* **The mapping-form assumption in `tests/unit/test_deploy_artifacts.py`.** The list form of compose's `environment:` yields misattributing failures. It fails *safe* — it stops a maintainer rather than waving one through — and `_reim_environment()` is now the single place a normalisation would go, so the cost of fixing it later has already fallen.
* **`reim/ingestion/runner.py:262`'s use of `indicators[0]`.** Out of scope by an earlier ruling and still correct: it feeds the quality battery, which is a different concern from reporting freshness.
* **The rate limiter's `_prune` rebuilding its dict per over-cap call.** A real observation from the API-keys increment, in a different subsystem, and it needs its own measurement before anyone decides it matters. It belongs in its own increment, not appended to a documentation pass.

## Done when

* The healthcheck paragraph offers only levers that work on podman, and says nothing about `start_period` that a two-cell measurement contradicts.
* A member of `OPERATOR_SETTABLE` cannot be hardcoded, a non-`REIM_` variable on any service is not reported as name drift, `PINNED_IN_COMPOSE`'s scope is either reachable or stated, and a key set by two services cannot appear silently.
* Deleting `REIM_ACME_EMAIL` from `deploy/.env.prod.example` fails a test again.
* The Caddyfile's commented block says what it is from its first line.
* The guide's crontab lines have been run, and what it says about them is what was observed.
* The full gate passes: `ruff check`, `ruff format --check`, `mypy reim apps`, `pytest -q`.
