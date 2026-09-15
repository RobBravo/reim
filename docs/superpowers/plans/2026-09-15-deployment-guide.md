# Public Deployment Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a deployment an operator can actually run — files in `deploy/`, a guide written while standing that deployment up — and close the two small correctness gaps it exposes.

**Architecture:** Two artifacts (`deploy/docker-compose.prod.yml`, `deploy/Caddyfile`) that are started and measured rather than described; a guide (`docs/deployment.md`) whose every command was run; and two folded fixes — one freshness threshold shared by `/api/v1/status` and `/metrics`, and rejection of an empty `--label`.

**Tech Stack:** podman + compose, Caddy 2, FastAPI, Typer, SQLAlchemy 2, pytest.

**Spec:** `docs/superpowers/specs/2026-09-15-deployment-guide-design.md`

## Global Constraints

- The verification gate, run from the repository root, is
  `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q`.
  Integration tests need `REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim`; without it most of them skip.
- The suite stands at **1040 passed, 7 deselected** before this plan. The 7 deselected are the pre-existing `-m 'not live'` in `pyproject.toml:154`.
- There is no Docker daemon on this machine and no `pip` in `.venv`. Use `podman`, and `.venv/bin/<tool>` for every Python tool.
- `ruff format` silently rewrites any ` ```python ` block in Markdown that is not a valid standalone module. Fence shell, YAML, Caddyfile and fragment samples as ` ```text `, then re-run `.venv/bin/ruff format .` and confirm no change to any Markdown file.
- **D2 from the spec binds every claim about the proxy:** what the guide says about `X-Forwarded-For` is measured through the running proxy, never reasoned from documentation.
- Never commit a real API key token, a database password other than the throwaway ones in this plan, or a webhook URL. Redact tokens in reports, **including in any sentence explaining that you redacted one.**

---

### Task 1: One freshness threshold

Two places compute how stale a pipeline may be, and they disagree by
construction. `reim/services/status.py:53` takes the threshold of
`entry.indicators[0]`; `reim/services/metrics.py:113` takes the strictest
across every indicator the source declares. `/api/v1/status` and `/metrics` can
therefore report different staleness for the same pipeline. They agree today
only because no catalog entry's indicators disagree — 14 of the 23 entries
declare more than one indicator.

**Files:**
- Create: `reim/domain/quality/freshness.py`
- Create: `tests/unit/test_freshness_threshold.py`
- Modify: `reim/services/metrics.py` (remove `_freshness_threshold`, import instead; call site at line 166)
- Modify: `reim/services/status.py:53`

**Interfaces:**
- Consumes: `QualityRuleSet.for_indicator(code) -> IndicatorRule` with `.freshness_max_age_days: int | None`; `SourceEntry.indicators: list[str]`.
- Produces: `freshness_threshold(entry: SourceEntry, rules: QualityRuleSet) -> int | None`, importable from `reim.domain.quality.freshness`.

- [ ] **Step 1: Write the failing test**

`imf_imts_nicaragua` is a real catalog entry declaring three indicators:
`exports_goods_monthly`, `imports_goods_monthly`, `trade_balance_goods_monthly`.
The rule set below makes the **first** one lenient and a later one strict, so
`indicators[0]` and "strictest" give different answers. That difference is the
whole test: every real catalog input gives the same answer either way, which is
why this case has to be built.

Create `tests/unit/test_freshness_threshold.py`:

```python
"""One freshness threshold, shared by every reporter of it.

The catalog contains no source whose indicators disagree, so every real input
gives the same answer whether you read ``indicators[0]`` or take the strictest.
These tests build the case the catalog lacks — the only input that can tell the
two rules apart.
"""

from __future__ import annotations

import pytest

from reim.domain.quality.freshness import freshness_threshold
from reim.domain.quality.rules import IndicatorRule, QualityRuleSet
from reim.domain.sources.catalog import get_catalog

#: A real entry declaring three indicators, in this order.
ENTRY_KEY = "imf_imts_nicaragua"
FIRST_INDICATOR = "exports_goods_monthly"
SECOND_INDICATOR = "imports_goods_monthly"


@pytest.fixture
def entry():
    catalog = get_catalog()
    entry = next(source for source in catalog.sources if source.key == ENTRY_KEY)
    assert entry.indicators[0] == FIRST_INDICATOR, "catalog changed; pick another entry"
    assert SECOND_INDICATOR in entry.indicators
    return entry


def test_the_strictest_threshold_wins_over_the_first_indicator(entry) -> None:
    """A lenient first indicator must not hide a strict sibling."""
    rules = QualityRuleSet(
        indicators={
            FIRST_INDICATOR: IndicatorRule(freshness_max_age_days=400),
            SECOND_INDICATOR: IndicatorRule(freshness_max_age_days=30),
        }
    )

    assert freshness_threshold(entry, rules) == 30


def test_an_indicator_without_a_threshold_cannot_silence_one_that_has_it(entry) -> None:
    """``None`` means "no policy here", not "zero days"."""
    rules = QualityRuleSet(
        indicators={
            FIRST_INDICATOR: IndicatorRule(freshness_max_age_days=None),
            SECOND_INDICATOR: IndicatorRule(freshness_max_age_days=30),
        }
    )

    assert freshness_threshold(entry, rules) == 30


def test_no_thresholds_at_all_is_no_threshold(entry) -> None:
    """Not zero, which would mark every pipeline stale."""
    rules = QualityRuleSet(
        defaults=IndicatorRule(freshness_max_age_days=None),
        indicators={},
    )

    assert freshness_threshold(entry, rules) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_freshness_threshold.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'reim.domain.quality.freshness'`.

- [ ] **Step 3: Create the shared function**

Create `reim/domain/quality/freshness.py`. The body is moved verbatim from
`reim/services/metrics.py:113`; only the name and the docstring's framing
change.

```python
"""How stale a pipeline's data may get before anyone says so.

Freshness is per source — ``latest_period_end`` is keyed on ``source_id`` — but
thresholds are per indicator, and 14 of the 23 catalog entries declare more
than one. This is the single answer every reporter of staleness uses, so
``/api/v1/status`` and ``/metrics`` cannot disagree about the same pipeline.
"""

from __future__ import annotations

from reim.domain.quality.rules import QualityRuleSet
from reim.domain.sources.catalog import SourceEntry


def freshness_threshold(entry: SourceEntry, rules: QualityRuleSet) -> int | None:
    """Return the strictest freshness threshold across a pipeline's indicators.

    When indicators disagree the strictest wins: a staleness report that fires
    early beats one that never fires.

    An indicator with no threshold is skipped rather than read as zero, so "no
    policy here" cannot silence a sibling indicator that does have one.
    """
    configured = [
        threshold
        for threshold in (
            rules.for_indicator(code).freshness_max_age_days for code in entry.indicators
        )
        if threshold is not None
    ]
    return min(configured) if configured else None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_freshness_threshold.py -q`
Expected: 3 passed.

- [ ] **Step 5: Point both reporters at it**

In `reim/services/metrics.py`: delete the whole `_freshness_threshold` function
(it begins at line 113 with `def _freshness_threshold(`), add
`from reim.domain.quality.freshness import freshness_threshold` to the imports,
and change the call — currently `freshness_max_age_days=_freshness_threshold(entry, rules)`
at line 166 — to `freshness_max_age_days=freshness_threshold(entry, rules)`.

In `reim/services/status.py`, replace line 53, which reads:

```text
threshold = resolved_rules.for_indicator(entry.indicators[0]).freshness_max_age_days
```

with:

```text
threshold = freshness_threshold(entry, resolved_rules)
```

and add `from reim.domain.quality.freshness import freshness_threshold` to its
imports.

- [ ] **Step 6: Prove the change reaches `/api/v1/status`, not just the helper**

Add to `tests/unit/test_freshness_threshold.py`. This is the test that fails if
someone edits `status.py` back; the three above would not notice.

```python
def test_the_status_summary_uses_the_strictest_threshold(entry) -> None:
    """``build_pipeline_summaries`` must not read ``indicators[0]`` any more.

    Asserted through the service rather than the helper, because the helper
    being right is not the same as the summary using it.
    """
    import inspect

    from reim.services import status

    source = inspect.getsource(status.build_pipeline_summaries)

    assert "indicators[0]" not in source, (
        "build_pipeline_summaries still derives a threshold from the first "
        "indicator, so /api/v1/status and /metrics can disagree"
    )
    assert "freshness_threshold(" in source
```

- [ ] **Step 7: Run the whole gate**

```text
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
```

Expected: 1044 passed (1040 + 4).

- [ ] **Step 8: Mutation drill — prove the tests have teeth**

Report the exact observed output of each, and revert after each:

1. In `freshness.py`, change `min(configured)` to `max(configured)` → the first two tests must fail.
2. In `freshness.py`, change `if threshold is not None` to `if True` → `test_an_indicator_without_a_threshold_cannot_silence_one_that_has_it` must fail (a `None` in the list makes `min` raise or compare wrongly — report what actually happens).
3. In `status.py`, restore `resolved_rules.for_indicator(entry.indicators[0]).freshness_max_age_days` → Step 6's test must fail.

If a drill does not produce a failure, stop and report it.

- [ ] **Step 9: Commit**

```bash
git add reim/domain/quality/freshness.py reim/services/metrics.py reim/services/status.py tests/unit/test_freshness_threshold.py
git commit -m "fix(quality): one freshness threshold, not two that agree by luck"
```

---

### Task 2: An empty `--label` is rejected

`reim key create --label ""` mints a key that `reim key list` cannot
distinguish from any other. A label is how an operator decides which key to
revoke.

**Files:**
- Modify: `reim/cli/main.py:176-194` (`key_create`)
- Test: `tests/integration/test_cli_keys.py`

**Interfaces:**
- Consumes: `create_key(session, label=..., now=...) -> tuple[ApiKey, str]`; `EXIT_OK`, and the CLI's existing error exit code (read it from the neighbouring `key revoke` command rather than assuming a number).

**Note:** `tests/integration/test_cli_keys.py:51` already has
`test_create_requires_a_label`, which covers the option being **absent**. This
task is about it being **present and empty**. Do not duplicate or rewrite the
existing test.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_cli_keys.py`:

```python
def test_create_rejects_an_empty_label(cli_session: Session) -> None:
    """An empty label is as unusable as a missing one, and gets in further.

    ``--label ""`` satisfies Typer's required-option check, so nothing else
    stops it: the key is minted and appears in ``key list`` as a blank column
    nobody can match to a consumer.
    """
    result = runner.invoke(app, ["key", "create", "--label", ""])

    assert result.exit_code != 0
    assert list_keys(cli_session) == []


def test_create_rejects_a_whitespace_label(cli_session: Session) -> None:
    """Whitespace is the same problem wearing a disguise."""
    result = runner.invoke(app, ["key", "create", "--label", "   "])

    assert result.exit_code != 0
    assert list_keys(cli_session) == []
```

Check the top of the file for how `list_keys` and `cli_session` are already
imported and named; reuse them rather than inventing a second spelling. If the
existing tests assert persistence a different way, match that way.

- [ ] **Step 2: Run it to verify it fails**

Run: `REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest tests/integration/test_cli_keys.py -q`
Expected: both new tests FAIL — the command exits 0 and a key is created.

- [ ] **Step 3: Reject it**

In `reim/cli/main.py`, inside `key_create`, before the `session_scope` block:

```python
    if not label.strip():
        typer.echo("A key needs a label: it is how you identify which key to revoke.", err=True)
        raise typer.Exit(EXIT_USAGE)
```

Use whatever the file's existing non-zero exit constant is — read `key_revoke`,
which already has failure paths, and use the same constant it uses for a bad
argument. Do not introduce a new one.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest tests/integration/test_cli_keys.py -q`
Expected: all pass, including the pre-existing `test_create_requires_a_label`.

- [ ] **Step 5: Mutation drill**

Delete the `if not label.strip():` guard and confirm both new tests fail.
Report the exact output. Restore.

- [ ] **Step 6: Commit**

```bash
git add reim/cli/main.py tests/integration/test_cli_keys.py
git commit -m "fix(cli): a key with no label is a key nobody can revoke"
```

---

### Task 3: The deployment artifacts

Two files an operator runs, plus the tests that keep them honest. Per spec D1,
these are files rather than code blocks in the guide precisely so they can be
started and measured — a fenced block cannot be, which is how `.env.example`
came to ship a value that stopped the application from booting.

**Files:**
- Create: `deploy/docker-compose.prod.yml`
- Create: `deploy/Caddyfile`
- Create: `deploy/.env.prod.example`
- Create: `tests/unit/test_deploy_artifacts.py`

**Interfaces:**
- Consumes: the base `docker-compose.yml` as a *reference* for service names, image, healthchecks and the network — read it, copy what production also needs, but do not merge with it.
- Produces: `deploy/docker-compose.prod.yml`, a **standalone** file used as `podman compose -f deploy/docker-compose.prod.yml up -d`.

**Why standalone and not an overlay** (spec D8): Compose concatenates
multi-value options when merging files. Measured with podman — a base
publishing `5432:5432` merged with an overlay declaring `ports: []` still
publishes 5432. An overlay cannot close a port, and closing ports is most of
what this file is for. Copy what you need from the base file into a complete
production file instead.

- [ ] **Step 1: Write the failing test**

These assert the properties that make this file a *production* file.
Each one, if wrong, is a door left open — which is why they are asserted rather
than trusted to review.

Create `tests/unit/test_deploy_artifacts.py`:

```python
"""The deployment as shipped, not as described.

Every claim the guide makes about these files is only true while the files say
so. These tests are what keeps the two from drifting apart.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION = REPO_ROOT / "deploy" / "docker-compose.prod.yml"
CADDYFILE = REPO_ROOT / "deploy" / "Caddyfile"


@pytest.fixture
def production() -> dict:
    return yaml.safe_load(PRODUCTION.read_text(encoding="utf-8"))


def test_only_caddy_publishes_ports(production: dict) -> None:
    """Every other service is reachable only from the compose network.

    Asserted over every service rather than naming postgres and api, so a
    service added later cannot quietly open a port nobody tested for. An
    earlier draft of this plan used a compose *overlay* declaring ``ports: []``
    and a test that read that overlay; both passed while the merged deployment
    still published 5432, because Compose concatenates ports when merging. The
    lesson kept here is that the assertion belongs on the whole resolved file.
    """
    publishing = {
        name: service.get("ports")
        for name, service in production["services"].items()
        if service.get("ports")
    }

    assert set(publishing) == {"caddy"}, (
        f"only caddy may publish ports; these also do: {sorted(set(publishing) - {'caddy'})}"
    )


def test_exactly_one_trusted_proxy_hop(production: dict) -> None:
    """One proxy is in front, and it is ours.

    Higher than the number of proxies actually run hands the choice of identity
    back to the client and the rate limiter stops limiting.
    """
    environment = production["services"]["api"]["environment"]

    assert str(environment["REIM_TRUSTED_PROXY_HOPS"]) == "1"


def test_cors_is_not_a_wildcard(production: dict) -> None:
    """A wildcard is a development convenience; the operator must state an origin."""
    environment = production["services"]["api"]["environment"]
    value = str(environment.get("REIM_CORS_ALLOW_ORIGINS", ""))

    assert "*" not in value, "the production compose must not default CORS to a wildcard"


def test_caddy_proxies_to_the_api_service_by_name(production: dict) -> None:
    """Over the compose network, never over a published port."""
    text = CADDYFILE.read_text(encoding="utf-8")

    assert "api:8000" in text
    assert "localhost:8000" not in text


def test_metrics_is_not_reachable_from_outside() -> None:
    """The metrics design put authentication out of scope on the grounds that a
    scrape endpoint is restricted at the network. This is that restriction."""
    text = CADDYFILE.read_text(encoding="utf-8")

    assert "/metrics" in text, (
        "the Caddyfile must say something about /metrics; leaving it unmentioned "
        "publishes it to the internet"
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_deploy_artifacts.py -q`
Expected: every test fails — `deploy/` does not exist.

- [ ] **Step 3: Write the production compose file**

Create `deploy/docker-compose.prod.yml`. Read `docker-compose.yml` first: the
base file has exactly two services, `postgres` and `api`, plus the `reim`
network and the `postgres_data` volume. Copy what production also needs —
image, healthchecks, the migrate-and-seed command — and change what differs.
Do not merge with the base file; this one stands alone.

```text
# REIM in production. Stands alone — do NOT combine with docker-compose.yml,
# which is the development environment and publishes ports this file exists to
# close. Compose concatenates ports when merging files, so an overlay could not
# close them.
#
#   podman compose -f deploy/docker-compose.prod.yml up -d
#
# Copy deploy/.env.prod.example to .env beside this file and fill it in first.
# Ingestion is not automatic; see docs/deployment.md.

name: reim-prod

services:
  postgres:
    image: docker.io/library/postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-reim}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set a real password in .env}
      POSTGRES_DB: ${POSTGRES_DB:-reim}
      # Deterministic collation so ORDER BY does not depend on the host locale.
      POSTGRES_INITDB_ARGS: "--encoding=UTF8 --locale=C"
    # No published port. Development publishes 5432 so psql works from the
    # host; here the database is reachable only from this network. For a shell:
    #   podman compose -f deploy/docker-compose.prod.yml exec postgres psql -U reim
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-reim} -d ${POSTGRES_DB:-reim}"]
      interval: 5s
      timeout: 5s
      retries: 10
      start_period: 10s
    networks:
      - reim

  api:
    build:
      context: ..
      dockerfile: Dockerfile
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      REIM_DATABASE_URL: >-
        postgresql+psycopg://${POSTGRES_USER:-reim}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB:-reim}
      REIM_ENVIRONMENT: production
      REIM_LOG_LEVEL: ${REIM_LOG_LEVEL:-INFO}
      REIM_LOG_JSON: "true"
      # No default on purpose: state the origins that may call this API.
      REIM_CORS_ALLOW_ORIGINS: ${REIM_CORS_ALLOW_ORIGINS:?set the allowed origins}
      # Exactly one proxy sits in front, and it is the caddy service below.
      # Higher than the number you actually run lets a client choose its own
      # identity and escape rate limiting entirely.
      REIM_TRUSTED_PROXY_HOPS: "1"
    # No published port either: caddy is the only way in, so there is no second
    # door on 8000 that skips TLS and the proxy the limiter assumes.
    command: >-
      sh -c "alembic upgrade head
      && python -m reim.cli db seed
      && uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers"
    healthcheck:
      test: ["CMD-SHELL", "curl --fail --silent http://localhost:8000/health || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s
    networks:
      - reim

  caddy:
    image: docker.io/library/caddy:2-alpine
    restart: unless-stopped
    depends_on:
      - api
    environment:
      REIM_DOMAIN: ${REIM_DOMAIN:?set the domain this deployment serves}
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro,z
      - caddy_data:/data
      - caddy_config:/config
    networks:
      - reim

volumes:
  postgres_data:
  caddy_data:
  caddy_config:

networks:
  reim:
    driver: bridge
```

- [ ] **Step 4: Write the Caddyfile**

Create `deploy/Caddyfile`:

```text
# Caddy obtains and renews the certificate for REIM_DOMAIN by itself.
#
# It also writes X-Forwarded-For, which is the whole reason
# REIM_TRUSTED_PROXY_HOPS=1 is correct in the compose file: REIM reads the last
# entry, the one this proxy appended. Whatever a client sent sits to the left
# of it and is never read.

{$REIM_DOMAIN} {
	encode zstd gzip

	# The Prometheus scrape endpoint carries no authentication by design; the
	# metrics design put that out of scope on the grounds that a scrape
	# endpoint is restricted at the network. This is that restriction. Remove
	# it only if you have another way to keep it off the public internet.
	handle /metrics {
		respond 404
	}

	handle {
		reverse_proxy api:8000
	}
}
```

- [ ] **Step 5: Write the example environment file**

Create `deploy/.env.prod.example`:

```text
# Copy to deploy/.env and fill in — beside docker-compose.prod.yml, whose
# variables it supplies. Nothing here has a
# default: every one of these is a decision, and a wrong default is worse than
# a missing value that stops the stack from starting.

# The domain Caddy serves and obtains a certificate for.
REIM_DOMAIN=reim.example.org

# The origins allowed to call the API from a browser. Comma-separated.
# A wildcard here undoes the reason this file exists.
REIM_CORS_ALLOW_ORIGINS=https://reim.example.org

# The database password. Generate one: openssl rand -base64 32
POSTGRES_PASSWORD=
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_deploy_artifacts.py -q`
Expected: 5 passed.

- [ ] **Step 7: Confirm the formatter leaves the artifacts alone**

Run: `.venv/bin/ruff format . && git status --short`
Expected: no modification to anything under `deploy/`.

- [ ] **Step 8: Commit**

```bash
git add deploy tests/unit/test_deploy_artifacts.py
git commit -m "feat(deploy): ship the production stack as files, not as prose"
```

---

### Task 4: Stand the stack up, and measure it

The guide is written from what this task observes. Nothing here is written
down as guidance — this task produces **measurements**, and Task 5 turns them
into prose.

**Files:**
- Create: `.superpowers/sdd/2026-09-15-deployment-guide/measurements.md`

**Interfaces:**
- Consumes: `deploy/docker-compose.prod.yml`, `deploy/Caddyfile`, `deploy/.env.prod.example` from Task 3.
- Produces: `measurements.md`, whose headings Task 5 quotes from.

**Constraints:** there is no Docker daemon here — use `podman`. You do not have
a public domain, so Caddy cannot obtain a real certificate; run it with
Caddy's internal CA instead (`tls internal`, or by setting the site address to
`localhost`) and record exactly what you changed to make it work locally, so
Task 5 can distinguish "what the operator does" from "what we did to observe
it".

- [ ] **Step 1: Bring the stack up**

Copy `deploy/.env.prod.example` to a throwaway `.env` with a generated
password, `REIM_DOMAIN=localhost`, and a concrete `REIM_CORS_ALLOW_ORIGINS`.
Bring it up with podman and the production compose file — that file alone, never combined with the base one. Record the exact command
and what it printed.

If it does not come up, **that is the most valuable result this task can
produce** — it means the artifacts from Task 3 are wrong, and a guide written
from them would have been wrong too. Fix `deploy/` and record what was wrong
and why, in `measurements.md`, under a heading `## What did not work the first
time`.

- [ ] **Step 2: Record the health of the stack**

For each, record the command and the observed output:

- the API answers `/health` and `/ready` through Caddy
- a data route answers through Caddy
- the database is **not** reachable from the host on 5432
- the API is **not** reachable from the host on 8000
- `/metrics` from outside returns 404

- [ ] **Step 3: Measure the proxy's header handling — this is D2**

This is the step the whole spec turns on. Do not reason about what Caddy does;
observe it.

1. Set the anonymous allowance low for this measurement (`REIM_RATE_LIMIT_ANONYMOUS`), and restart the API service.
2. Exhaust the allowance through Caddy with plain requests. Record the `429` and its `Retry-After`.
3. Send three further requests through Caddy, each carrying a **different** forged `X-Forwarded-For`. Record every status code.

Three different values, because one would not distinguish a proxy that
overwrites the header from one that funnels every caller into a single wrong
bucket.

**Expected:** all three refused. If any is served, the deployment has the
bypass this increment exists to prevent — stop, record it under `## What did
not work the first time`, and fix `deploy/` before continuing. Do not write a
guide that documents a vulnerable configuration.

Also record what `REIM_TRUSTED_PROXY_HOPS=1` resolves identity to: whether
Caddy appends to a client-supplied header or replaces it. Say how you
determined it, from observation.

- [ ] **Step 4: Measure the operator's first five minutes**

Record command and output for each:

- `reim key create --label "<something>"` through `compose exec` — **redact the token in the recorded output, and in any sentence you write about redacting it**
- that the key raises the allowance, by exceeding the anonymous limit with it
- `reim key list`
- `reim key revoke <id>`, and that the revoked key is then refused with `401`
- one ingestion run, and the observations it produced
- `reim pipeline schedule`
- `reim alert check` against a webhook you control or with the webhook unset, whichever runs cleanly; record which

- [ ] **Step 5: Measure what an operator backs up**

Record the `pg_dump` command through `compose exec` and that it produced a
non-empty dump. Record the volume names the stack actually creates.

- [ ] **Step 6: Tear the stack down and record how**

Including whether volumes survive, since an operator needs to know which
command destroys their data.

- [ ] **Step 7: Write `measurements.md` and commit nothing**

This file lives in the git-ignored SDD workspace. Nothing in this task is
committed to the repository. Report the path and a summary.

---

### Task 5: The guide

Turn Task 4's measurements into `docs/deployment.md`. Every command in it is
one that was run; every output it promises is one that was observed.

**Files:**
- Create: `docs/deployment.md`
- Modify: `README.md` (link to it from Quick start; the limitations entry on rate limiting)
- Modify: `ROADMAP.md` (the last v0.5.0 bullet)

**Interfaces:**
- Consumes: `.superpowers/sdd/2026-09-15-deployment-guide/measurements.md`.

- [ ] **Step 1: Write the guide**

`docs/deployment.md`, in this order: prerequisites; get the code; the secrets
to set and how to generate them; bring it up; verify it (the checks from Task 4
Step 2); mint the first key; run the first ingestion; install the crontab
`reim pipeline schedule` emits; point alerting at a webhook.

Then a hardening section. Each item states what to do **and the command that
shows it worked** — the table in spec §3.1 is the list, and Task 4 measured
every row. An item you cannot show a verification for does not go in.

Then, plainly (spec §3.2): the limit counts requests, not bytes.
`/api/v1/observations/export.csv` serves up to `REIM_MAX_EXPORT_ROWS` rows
(100,000 by default) for one unit of allowance, so an anonymous caller at 60
requests a minute can extract far more data than that number suggests. An
operator who needs a byte budget sets one at the proxy.

Then the limits of this deployment: one uvicorn worker, so the rate limit is
exact; *N* workers multiply it by *N*, and that operator needs a limiter in
their own gateway. No Kubernetes, no HA, no read replicas.

Where Task 4 had to deviate to observe something locally — the certificate,
most likely — say what the operator does differently, rather than documenting
the local workaround as the real procedure.

- [ ] **Step 2: Link it, and fix what it makes stale**

In `README.md`: link `docs/deployment.md` from the Quick start section, framed
so a reader can tell which of the two they want — Quick start is for trying
REIM, the guide is for running it. Check the rate-limiting entry in the
Limitations section and the `REIM_TRUSTED_PROXY_HOPS` paragraph for anything
the guide now makes untrue or duplicated.

- [ ] **Step 3: Update the ROADMAP**

Replace the `- Public deployment guide with hardening notes.` bullet under
`## v0.5.0 — Operations` with a struck-through `✅ **done** — ` entry.
**Check the format against its siblings first**: the four completed entries in
this section use `~~**Title**~~ ✅ **done** — ` with an em-dash.

Convey: that the deployment ships as files under `deploy/` rather than as
prose, because a file can be started and measured; that the guide was written
while standing the stack up; that Caddy terminates TLS and writes
`X-Forwarded-For`, which is what makes `REIM_TRUSTED_PROXY_HOPS=1` correct;
that `/metrics` is closed at the proxy; and that the limit counts requests
rather than bytes.

- [ ] **Step 4: Verify every claim the guide makes about the repository**

For each file path, setting name, default value, command and exit code in
`docs/deployment.md`: check it against the repository. A setting the guide
names must be a setting; a default it quotes must be the default in
`reim/core/config.py`; a file it names must exist. List what you checked in
your report.

- [ ] **Step 5: Confirm the formatter leaves the Markdown alone**

```text
.venv/bin/ruff format . && git status --short
```

Expected: no modification to `docs/deployment.md`, `README.md` or
`ROADMAP.md`. Shell, YAML and Caddyfile samples must be fenced ` ```text `,
never ` ```python `.

- [ ] **Step 6: Run the whole gate and commit**

```text
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
```

```bash
git add docs/deployment.md README.md ROADMAP.md
git commit -m "docs: a deployment an operator can actually run"
```

---

## Done when

* `/api/v1/status` and `/metrics` report the same staleness for the same pipeline, pinned by a test whose mutation (restoring `indicators[0]`) makes it fail.
* `reim key create --label ""` is refused, pinned by a test whose mutation (deleting the guard) makes it fail.
* `deploy/docker-compose.prod.yml` and `deploy/Caddyfile` exist, publish no database or API port, set exactly one trusted proxy hop, refuse a CORS wildcard, and close `/metrics` — each pinned by a test.
* The stack was actually brought up under podman, and a forged `X-Forwarded-For` through Caddy was observed to buy no fresh allowance.
* `docs/deployment.md` contains no command that was not run and no output that was not observed.
* The README links the guide, and `ROADMAP.md` marks v0.5.0's last item done.
* The full gate passes: `ruff check`, `ruff format --check`, `mypy reim apps`, `pytest -q`.
