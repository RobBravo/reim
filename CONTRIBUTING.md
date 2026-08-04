# Contributing to REIM

Thanks for considering a contribution. The most valuable thing you can add is a
**working connector for an official source REIM cannot yet reach** — especially
national sources for Central American countries.

Before anything else, please read the project's principles in the
[README](./README.md). The one that matters most: **never invent data.** A
documented gap is a contribution; a fabricated number is a defect.

---

## Environment setup

Requires Python 3.12+ and Docker or Podman.

```bash
git clone https://github.com/<you>/reim.git
cd reim

make setup                       # virtualenv, dependencies, .env
make db-up                       # PostgreSQL 16 on port 55432
export REIM_DATABASE_URL="postgresql+psycopg://reim:reim@localhost:55432/reim"
export REIM_TEST_DATABASE_URL="$REIM_DATABASE_URL"

make migrate && make seed
make check                       # lint + typecheck + catalog + tests
```

`make check` must pass before you open a pull request. It is exactly what CI runs.

Using Podman instead of Docker:

```bash
make db-up CONTAINER_ENGINE=podman
```

---

## Code conventions

- **All code, comments, docstrings and identifiers in English.** (Documentation
  aimed at users may be bilingual; the codebase is not.)
- **Strict typing.** `mypy --strict` passes on `reim` and `apps`. No bare `Any`,
  no untyped defs. If you need an escape hatch, use a narrow `# type: ignore[code]`
  with a comment explaining why.
- **Ruff for lint and format**, line length 100. `make format` fixes most things.
- **Docstrings on public components** and on any logic that is not obvious.
  Google convention. Say *why*, not *what the code already says*.
- **`Decimal` for every economic value.** Never `float`. Values are stored in
  unconstrained PostgreSQL `NUMERIC`.
- **UTC everywhere.** `datetime.now(UTC)`, `TIMESTAMPTZ` columns.
- **Typed domain exceptions.** Raise something deriving from `REIMError` with a
  stable `code`; never a bare `Exception` or `ValueError` in domain code.
- **Preserve the original meaning of a period.** Never collapse a monthly figure
  into a day without documenting the convention.
- **No premature abstraction.** A function is fine. Add a class when there is a
  second real caller, not in anticipation of one.
- **Keep files focused.** If a module is getting long, that is usually a sign it
  is doing two things.

---

## How to register a new source

Sources are declared in [`sources/catalog.yml`](./sources/catalog.yml). This is
the single source of truth — nothing in core code enumerates sources.

```yaml
  - key: bcn_monthly_cpi                    # snake_case; must equal connector_key
    name: Nicaragua monthly consumer price index
    description: >-
      What the source publishes, in one or two sentences.
    country: NI                             # ISO alpha-2; omit for global sources
    organization: BCN                       # must exist in the organization registry
    category: prices
    access_type: http_api                   # http | http_api | soap | file_download | manual
    frequency: monthly
    format: json                            # json | csv | xml | xlsx | xls | html | pdf
    base_url: https://example.gob.ni/api
    documentation_url: https://example.gob.ni/docs
    connector: reim.ingestion.connectors.nicaragua.bcn_monthly_cpi
    indicators:
      - ni_cpi_index_monthly                # must exist in the indicator registry
    license: public_official_data
    official: true
    enabled: true
```

Validation is enforced by a Pydantic schema, so mistakes fail loudly:

```bash
python -m reim.cli catalog validate
```

Rules the schema enforces:

- `key` is unique, snake_case, and equals the connector's `connector_key`.
- `organization` and every entry in `indicators` must already be registered.
- An **enabled** source may not use a placeholder host (`example.invalid`, …).
- A **disabled** source must carry a `disabled_reason` explaining the blocker.

If the organization does not exist yet, add it to
`reim/domain/sources/organizations.py` first.

---

## How to add an indicator

Indicators are canonical *concepts*, independent of who publishes them. Add one
to `reim/domain/indicators/registry.py`:

```python
INDICATORS: tuple[IndicatorDefinition, ...] = (
    # ... existing entries ...
    IndicatorDefinition(
        code="ni_cpi_index_monthly",  # {iso2_lower}_{concept}_{qualifier}
        name="Nicaragua — consumer price index (monthly)",
        description="What this measures and how the source defines it.",
        category=IndicatorCategory.PRICES,
        frequency=Frequency.MONTHLY,
        unit="index (2006=100)",  # be specific about the base period
        value_type=ValueType.INDEX,
        methodology_url="https://...",  # link the source's methodology
    ),
)
```

Then optionally add quality thresholds in
[`sources/quality_rules.yml`](./sources/quality_rules.yml):

```yaml
  ni_cpi_index_monthly:
    min_value: 0
    allow_negative: false
    monotonic_increasing: true             # a price index should not fall
    freshness_max_age_days: 60
    max_period_change_pct: 15
```

Keep thresholds **wide**. They exist to catch a broken feed, not to encode an
economic prior. A legitimate value must never be rejected because a bound was
set too tightly — this has already bitten us once (see `docs/sources.md`).

Re-run `make seed` to materialise the new indicator.

---

## How to write a connector

### 1. Research the source first

Do this **before** writing code, and follow the checklist at the end of
[`docs/sources.md`](./docs/sources.md). Confirm the publisher is official, find a
structured endpoint, fetch it twice to verify stability, and record the URL,
format, coverage and limitations.

**If the source cannot be automated reliably, do not invent a connector.**
Ship it `enabled: false` with a documented `disabled_reason`, write down the
blocker in `docs/sources.md`, and pick another source. That is a complete,
welcome contribution.

### 2. Record a real fixture

```bash
curl -s "https://example.gob.ni/api/cpi?format=json" \
  > tests/fixtures/bcn_monthly_cpi.json
```

Trim it to a manageable slice if it is huge, but **keep it a genuine recording**.
Document its origin and capture date in `tests/fixtures/README.md`. If a fixture
is synthetic — because you could not reach the source — it must say so
explicitly, and the connector must ship disabled.

### 3. Implement the three methods

Create `reim/ingestion/connectors/{country}/{source}.py` with exactly one
concrete `BaseConnector` subclass (the registry imports it by dotted path).

```python
class BcnMonthlyCpi(BaseConnector):
    """One paragraph: what this reads, from where, and any caveat."""

    connector_key = "bcn_monthly_cpi"  # must equal the catalog key
    version = "1.0.0"  # bump when transform output changes
    expected_frequency = Frequency.MONTHLY

    async def extract(self) -> RawDataset:
        """Fetch the payload. No database access, no global state."""
        async with http_client() as client:
            response = await fetch(client, self.request_url)
            ensure_ok(response, expected_content_type="json")
            payload = response.json()
        return RawDataset(...)

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Pure function of `raw` — testable against the fixture, no network."""

    def validate(self, observations) -> list[QualityResult]:
        """Only source-specific expectations; the standard battery runs anyway."""
```

**What a connector must never do:**

- Write to the database, or open a session. The runner owns persistence.
- Catch and swallow its own errors. Raise a typed `REIMError`; the runner records it.
- Impute, interpolate or carry forward a missing value. Skip the row.
- Compute a derived figure the source does not publish. Store what was published.
- Perform its own retry loop. Use `reim.ingestion.http.fetch`.
- Use `float` for a value.

The shared runner already handles run bookkeeping, transactions, idempotency,
quality gating, error capture and structured logging — so no connector can get
those subtly wrong.

### 4. Test it

Every connector needs, at minimum:

- `transform` against the recorded fixture: correct count, values, periods, units.
- Full `Decimal` precision preserved.
- Null/missing upstream values skipped, not imputed.
- Malformed payloads raise `TransformationError`.
- `extract` against a `respx` mock: correct URL, error handling, retries.
- `validate` failing when its specific expectation is violated.

```bash
pytest tests/unit/test_connectors.py -q
```

**No test may call a live official source.** CI must never depend on a public
institution's uptime, and REIM should not poll them on every push. Use
`scripts/smoke_test_sources.py` for deliberate live checks.

### 5. Verify against the real source, once

```bash
python scripts/smoke_test_sources.py --source bcn_monthly_cpi
python -m reim.cli pipeline run bcn_monthly_cpi
python -m reim.cli pipeline run bcn_monthly_cpi     # must insert 0, all unchanged
```

The second run proving idempotency is not optional.

---

## Database changes

Models live in `reim/database/models/`. After changing one:

```bash
make revision MESSAGE="add observation source_vintage"
# review the generated file by hand — autogenerate is a draft, not an answer
make migrate
make migrate-check        # alembic check must report no drift
```

Migrations must be reversible (`make migrate-down` works) and must never destroy
data silently. CI verifies the full `upgrade → downgrade → upgrade` round trip.

---

## Testing requirements

| Change | Required tests |
|--------|----------------|
| New connector | Unit tests for `transform`/`validate` against a fixture, plus mocked `extract` |
| New quality check | Unit tests for pass, fail and skip paths |
| New endpoint | Integration test covering success, filters and the error envelope |
| Schema change | Integration test for persistence and idempotency |
| Bug fix | A regression test that fails before the fix |

Tests are named for the behaviour they protect
(`test_null_values_are_skipped_not_imputed`), not the function they call.

---

## Commit conventions

[Conventional Commits](https://www.conventionalcommits.org/):

```text
feat(connectors): add BCN monthly CPI connector
fix(quality): stop rejecting pre-redenomination exchange rates
docs(sources): record BCN SOAP TLS blocker
test(pipeline): cover rollback on critical quality failure
chore(deps): bump httpx to 0.28
refactor(repositories): make apply_filters generic over the statement type
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`, `ci`.
Scopes follow the package layout: `connectors`, `quality`, `api`, `cli`,
`database`, `domain`, `sources`, `docs`.

Write the body to explain **why**, not what the diff already shows.

---

## Pull request process

1. Branch from `main`: `feat/bcn-monthly-cpi`.
2. Make the change, with tests.
3. Run `make check` — it must pass.
4. If you added or changed a source, update `docs/sources.md`.
5. Open the PR describing:
   - What it changes and why.
   - For a new source: the endpoint, format, coverage, licence and **known
     limitations**.
   - How you verified it against the real source.
   - Anything you deliberately did *not* do.
6. CI runs lint, strict typing, catalog validation, the full test suite against
   PostgreSQL 16, migration round-trip, a container build with a live API smoke
   test, and a secret scan.

### What reviewers will check

- Is the source genuinely official, and is its licence recorded?
- Is anything fabricated, imputed or interpolated? (Instant blocker.)
- Is provenance complete on every observation?
- Is the load idempotent?
- Are quality thresholds wide enough not to reject legitimate values?
- Are limitations documented rather than hidden?
- Does `transform` stay pure and testable without a network?

## Reporting problems

- **A wrong number:** open an issue with the indicator code, the period, what
  REIM shows and what the official source shows. Include the `source_url` and
  `content_hash` from the API response — that identifies the exact record.
- **A broken source:** run `python scripts/smoke_test_sources.py` and paste the
  output.
- **A security issue:** do **not** open a public issue. See [SECURITY.md](./SECURITY.md).

## Code of conduct

Be straightforward and respectful. Assume good faith. Critique the work, not the
person. Maintainers may remove contributions or contributors that make the
project worse to participate in.

## License

By contributing, you agree your contributions are licensed under the
[Apache License 2.0](./LICENSE).
