# Pipeline alerting — design

REIM can already tell you everything is wrong; it cannot yet tell you *that*
something is wrong. `/metrics` exports the figures, `/runs` shows the history,
and `reim quality report` exits non-zero — but all three require someone to
look. This increment adds the part that speaks first: a scheduled command that
evaluates what is broken, posts it to a webhook, and stays quiet until
something changes.

This is v0.5.0's second increment. Everything measured below was checked
against the repository on 2026-09-12.

## 1. What exists, and what this adds

Measured, not assumed:

| Piece | State |
|---|---|
| `build_metrics_snapshot` (`reim/services/metrics.py`) | Shipped last increment. Computes `data_age_days` and `freshness_max_age_days` per pipeline in six queries — the staleness comparison, already done |
| `PipelineMetrics` | Carries `last_run_at`, `last_success_at`, `last_run_duration_ms`, `last_run_records`, `runs_by_status` — but **no `last_run_status`**. See §1.2 |
| `FailedCheckCount` (`reim/repositories/pipeline_runs.py`) | `pipeline_key`, `check_name`, `failures` — **no severity**, and `summarize_failed_checks_by_pipeline` has no run or time scoping. See §1.2 |
| `CheckSeverity` (`reim/core/constants.py:163`) | `info` / `warning` / `error` / `critical`, with semantics documented on the enum itself: `critical` aborted the load, `error` rejected observations, `warning` and `info` were recorded only |
| `PipelineStatus` (`…/constants.py:133`) | `running`, `success`, `partial`, `failed`, `skipped` |
| `http_client` (`reim/ingestion/http.py:72`) | A configured `httpx.AsyncClient`: settings timeout, project User-Agent, MODERN TLS, connection limits. Its defaults are exactly what a webhook POST wants |
| `post` (`…/http.py:188`) | POST with the shared tenacity retry policy — transport errors and transient statuses retried, a `404` treated as a real answer |
| `Settings` (`reim/core/config.py:49-52`) | `http_timeout_seconds`, `http_max_retries`, `http_retry_backoff_seconds`, `http_user_agent` already exist |
| Migrations | **Exactly one exists** — `9b55f6392677_initial_schema`. This increment adds the second, and the first incremental one. See §6 |
| CLI | `catalog`, `db`, `pipeline`, `quality` groups; `EXIT_OK`/`EXIT_FAILURE`/`EXIT_INVALID` at `reim/cli/main.py:39-41` |

The addition is **one model, one migration, one repository query, one domain
module, one service, one CLI group and four settings**, plus two one-line edits
to existing files: the `last_run_status` field (§1.2) and the model export
Alembic needs (§6). No new dependency: `httpx` and `tenacity` are already here.

### 1.1 Why this is not `quality report` again

`reim quality report` (`reim/cli/main.py:269`) already summarises failing checks
and exits 1 when errors or worse are present, so an operator who cron's it with
mail-on-failure has a crude alert today. Two things are missing, and they are
the reason this increment exists.

**It cannot see staleness.** It reads recorded quality checks. A pipeline that
*stopped running* records nothing — no failed check, no failed run, no signal at
all. The most important operational failure in a data platform is the one where
nothing happens, and the only way to detect it is to compare the data's age
against a threshold from outside any run.

**It cannot stay quiet.** Exit-code alerting fires every time the condition
holds. A pipeline stale for three weeks against an hourly cron is 500
notifications, which trains the operator to filter them. Suppression needs
memory of what was already said (§3).

### 1.2 The two gaps the snapshot leaves

The decision to read staleness from `build_metrics_snapshot` rather than
re-deriving it (D4) is narrower than it first looks, because the snapshot does
not carry everything the four conditions need. Both gaps were measured.

**`PipelineMetrics` has no `last_run_status`.** `runs_by_status` is a cumulative
count across all history — `{"success": 40, "failed": 2}` — not the outcome of
the most recent run, so neither "the last run failed" nor "a run is stuck" can
be read from it. The fix costs **one line and zero queries**:
`latest_runs_by_pipeline` already fetches whole `PipelineRun` rows, and
`_pipeline_metrics` simply does not copy the status across. The renderer ignores
the new field and the six-query budget is untouched (D5).

**`FailedCheckCount` has no severity and no scoping.**
`summarize_failed_checks_by_pipeline` groups every failure ever recorded, by
name, which is right for a counter that only ever increases and wrong for "did
the latest run record anything at `error` or worse". That needs a genuinely new
query (D6).

Note what the reuse is actually protecting. The staleness *threshold comparison*
is policy, and D4 of the metrics design kept that policy in exactly one place —
`sources/quality_rules.yml` — rather than re-encoding it in the exporter. A
run's status is not policy; it is a fact. So reading staleness from the snapshot
matters, and fetching run facts separately costs nothing in consistency.

## 2. The four conditions

Evaluated per pipeline, over one snapshot plus one checks query. A pipeline the
catalog **disables is skipped entirely** — `reim_pipeline_enabled` exists so a
deliberately disabled source does not page anyone (D12).

| Condition | Fires when | Alert severity |
|---|---|---|
| `stale` | `data_age_days > freshness_max_age_days`, both present | `warning` |
| `failed_run` | `last_run_status` is `failed` | `error` |
| `stuck_run` | `last_run_status` is `running` and `last_run_at` is older than `REIM_ALERT_STUCK_RUN_HOURS` | `error` |
| `quality` | The latest run recorded at least one failed check at or above the severity floor | The worst severity among them |

`stale` requires both figures to be present, which follows the metrics design's
absent-series rule: no configured threshold means no policy, and no stored data
means no age. Neither is a condition to alert on.

`partial` is not a failure. It means some data was written, which is why the
metrics increment already treats it as a success for freshness.

**`stuck_run` is a fourth condition the ROADMAP does not name**, and it is here
because a crashed CLI process is otherwise invisible: the runner creates its row
before extraction starts and finalises it in a `finally` block, so a process
killed outright leaves `running` forever. It never becomes `failed`, so
`failed_run` cannot see it, and the data may be fresh enough that `stale` cannot
either (D15).

### 2.1 What deliberately stays silent

**A pipeline that has never run at all.** No `last_run_status`, so no
`failed_run` and no `stuck_run`; no stored data, so no `stale`. A newly added
source is silent until it has been scheduled and has run, which is correct — the
alternative is that adding a catalog entry immediately pages whoever is on call
about work nobody has started yet (D13).

That gap closes on its own the moment the source runs once, and it is visible on
the catalog page and in `reim pipeline list` meanwhile.

## 3. State: firing, repeating, resolving

One table, `alert_states`, one row per `(condition, pipeline_key)`: `condition`
(an `enum_column` over the four values), `pipeline_key` (`String(120)`, matching
`PipelineRun.pipeline_key`), `first_notified_at`, `last_notified_at`,
`resolved_at` (nullable), and `details` — a `JSONB` column holding the figures
sent with the last notification, so a resolution notice can quote what the
problem had been without recomputing it. A partial unique index enforces one
open row per `(condition, pipeline_key)`, scoped to `resolved_at IS NULL` so the
history of closed alerts accumulates rather than being overwritten.

Each run reconciles the evaluated set against the open rows:

```text
firing now, no open row     -> notify as new,      insert row
firing now, open row        -> notify only if last_notified_at is older
                               than REIM_ALERT_REPEAT_HOURS; then touch it
not firing, open row        -> notify as resolved, set resolved_at
```

The resolution notice is the real argument for a table over statelessness, and
it is worth more than the suppression is. "The Guatemala exchange-rate scrape is
working again" is information an operator otherwise has to go and check for
themselves, and without it a webhook channel accumulates failures that may all
have healed (D2).

Re-notification defaults to 24 hours: long enough that a three-week outage
produces 21 messages rather than 500, short enough that a problem cannot be
forgotten entirely.

## 4. Delivery

One `POST` per run, carrying every change as a digest rather than one request
per alert (D8). Twenty-three pipelines going stale together — a database that
was down during the nightly sweep — is one message, not twenty-three. The
payload:

```text
{
  "version": 1,
  "generated_at": "2026-09-12T18:00:00Z",
  "environment": "production",
  "firing":   [{"condition": "stale", "pipeline_key": "banguat_exchange_rate",
                "severity": "warning", "summary": "<one sentence>",
                "details": {"data_age_days": 9, "freshness_max_age_days": 7},
                "first_notified_at": "2026-09-10T18:00:00Z"}],
  "resolved": [{"condition": "failed_run", "pipeline_key": "inide_cpi_monthly",
                "summary": "<one sentence>",
                "first_notified_at": "2026-09-11T18:00:00Z"}]
}
```

Provider-agnostic: Slack, Discord, Mattermost, Alertmanager and every
automation tool accept a JSON POST, which is also how email gets reached without
REIM holding SMTP credentials (D3).

Delivery reuses `http_client` and `post`, so the retry policy is not written
twice. `post` raises `ExtractionError` on failure, which is an ingestion concept
and the wrong thing to surface from an alerting stack trace, so the service
translates it to an `AlertDeliveryError` at its boundary (D14). Generalising
`reim/ingestion/http.py` into a shared module is the right eventual fix and is
out of scope here.

**Redirects are not followed for delivery.** A misconfigured URL that redirects
should surface as a delivery failure the operator fixes, not as a request whose
body may or may not have survived the hop (D11).

**State is recorded only after a successful response** (D10). A webhook that is
down must not cost the alert: nothing is marked notified, so the next run says
it again. The inverse — recording first and delivering after — loses an alert
permanently on a transient failure, which is the one outcome an alerting system
may not have.

## 5. Configuration

Four settings on the existing `Settings`:

```text
alert_webhook_url:      str | None = None
alert_severity_floor:   CheckSeverity = CheckSeverity.ERROR
alert_repeat_hours:     int = 24   (ge=1)
alert_stuck_run_hours:  int = 6    (ge=1)
```

**An unset webhook URL means alerting is off, not broken.** `reim alert check`
still evaluates, still prints what it found, and still exits non-zero — it
degrades into exactly the `quality report` pattern, so the command is useful on
a machine with no webhook configured and the same cron line works either way
(D9). `--dry-run` forces that behaviour even when a URL is set.

The command lives in a new `alert` group rather than under `quality`, because
three of its four conditions are not quality checks (D16).

## 6. The migration — the project's second

`9b55f6392677_initial_schema` is the only migration in the repository, so this
is the first incremental one and the workflow gets exercised for the first time.
Three consequences:

* The model must be exported from `reim/database/models/__init__.py`, whose
  docstring already explains why: importing the package registers every table on
  `Base.metadata`, and Alembic's `env.py` relies on that for autogeneration. A
  model that is not exported produces an empty migration.
* `make migrate-check` runs `alembic upgrade head` followed by `alembic check`,
  so the migration must leave **no** model drift. That is the discriminating
  test that it matches the model rather than merely running.
* `make migrate-down` runs `downgrade -1`, so `downgrade()` must actually work
  rather than stay the autogenerated stub. It is only a `drop_table`: `enum_column`
  sets `native_enum=False`, so the condition is a `VARCHAR` with a `CHECK`
  constraint and there is no PostgreSQL `TYPE` to drop separately — which is
  exactly the reason `reim/database/types.py`'s docstring gives for the choice.

The table uses the project's existing conventions: `UUIDPrimaryKeyMixin`,
`enum_column` (`reim/database/types.py:27`) for the condition, and
`DateTime(timezone=True)` throughout. `details` needs no explicit type: `Base`'s
`type_annotation_map` already maps `dict[str, Any]` to `JSONB`.

It does **not** use `TimestampMixin`, which the reference and observation tables
do. That mixin's `updated_at` refreshes on every flush, including the one that
sets `resolved_at` — so it would sit beside `last_notified_at` looking like the
same fact while diverging from it. `PipelineRun` and `DataQualityCheck` set the
precedent for operational tables declaring their timestamps explicitly, and
`first_notified_at` already serves as this row's creation time.

One trap specific to the partial unique index of §3: it must be declared in
`__table_args__` with `postgresql_where`, not created by hand in the migration.
A hand-written index the model does not describe is exactly the drift
`alembic check` exists to catch, and it would fail `make migrate-check` on the
next person's branch rather than this one.

## 7. Testing

* **`reim/domain/alerts/rules.py` is pure** — snapshot and checks in, conditions
  out, no session and no clock beyond an injected `now`. Every condition and
  every boundary is unit-tested there without a database: age exactly equal to
  the threshold (not stale), a missing threshold, a missing age, `partial` not
  counting as a failure, a `running` run just under and just over the stuck
  threshold, and a failed check one severity below the floor.
* **The reconcile cycle is integration-tested** against real PostgreSQL across
  a sequence: fire, suppress on the next run, re-notify once the interval has
  passed, resolve when the condition clears, and stay quiet afterwards. That
  sequence is the whole feature, and no single-run test can cover it.
* **Delivery is injected**, not monkeypatched. The service takes an optional
  send callable defaulting to the real webhook; tests pass a recorder and assert
  the payload. This is also what `--dry-run` uses, so the seam earns its keep
  twice rather than existing only for tests.
* **The delivery-failure path is tested explicitly**: a sender that raises must
  leave no state recorded, so the next run re-notifies. This is the one
  behaviour whose failure loses data rather than producing noise.
* **The migration is verified by `make migrate-check`**, not by a test that the
  table exists.

## 8. Decisions

| | Decision | Rationale |
|---|---|---|
| **D1** | Evaluation is a cron'd CLI command, not run-time | Staleness is only observable from outside a run: a pipeline that stopped running fires nothing at run time (§1.1). Consistent with D13 of the original plan — ingestion and operations are CLI concerns |
| **D2** | A state table, with resolution notices | Suppression needs memory, and once the memory exists a recovery notice is nearly free and worth as much as the failure (§3) |
| **D3** | Generic JSON webhook only; no SMTP | One URL reaches Slack, Alertmanager and email-via-automation without REIM holding the first credentials it would ever store beyond the database URL (§4) |
| **D4** | Staleness is read from `build_metrics_snapshot`, never re-derived | The threshold comparison is policy, and the metrics design deliberately kept that policy in `quality_rules.yml` alone; a second derivation would re-encode it (§1.2) |
| **D5** | `last_run_status` is added to `PipelineMetrics` | One line, zero new queries — the run row is already fetched. Makes the snapshot a complete description of the last run instead of a partial one (§1.2) |
| **D6** | A new query for the latest run's failed checks, with severity | The existing aggregate groups all history by name, which cannot answer "did the latest run fail a check at `error` or worse" (§1.2) |
| **D7** | A quality regression is a failing check at or above a severity floor, not a newly-failing check | `CheckSeverity` already carries documented semantics; flip-detection goes quiet on a check that has failed continuously since it broke, which is still worth knowing (§2) |
| **D8** | One digest POST per run, not one per alert | A database down during the nightly sweep is one message rather than twenty-three (§4) |
| **D9** | An unset webhook URL evaluates, prints and exits non-zero | Alerting off must not mean the command is broken; the same cron line works with or without a webhook, degrading to the `quality report` pattern (§5) |
| **D10** | State is recorded only after a successful delivery | Recording first loses an alert permanently on a transient webhook failure — the one outcome alerting may not have (§4) |
| **D11** | Redirects are not followed for delivery | A misconfigured URL should fail visibly rather than succeed ambiguously (§4) |
| **D12** | Disabled pipelines are skipped entirely | A deliberately disabled source must not page anyone; the catalog already records the intent (§2) |
| **D13** | A pipeline that has never run stays silent | Otherwise adding a catalog entry pages someone about work nobody has started (§2.1) |
| **D14** | Reuse `http_client` and `post`; translate `ExtractionError` at the service boundary | Avoids writing the retry policy twice while keeping an ingestion exception out of an alerting stack trace (§4) |
| **D15** | A fourth condition, `stuck_run`, beyond the ROADMAP's three | A killed process leaves `running` forever and never becomes `failed`, so nothing else can see it (§2) |
| **D16** | A new `alert` CLI group, not a command under `quality` | Three of the four conditions are not quality checks (§5) |

## 9. Out of scope

* **SMTP.** D3. An operator who needs email points the webhook at something that
  sends it.
* **Per-pipeline routing.** One webhook for everything. Routing by pipeline,
  severity or time of day is the receiving system's job, and Alertmanager
  already does it better than REIM would.
* **An Alertmanager-native payload.** The generic shape is documented and
  stable; a translation layer for one vendor is not worth a format REIM has to
  keep matching.
* **Escalation, on-call schedules, acknowledgements.** Paging concerns, and they
  belong to whatever receives the webhook.
* **Authenticating the webhook.** An operator-controlled URL may carry a token
  in its query string, which is how most receivers work. REIM adds no signing
  header in this increment.
* **An alert history API or web page.** The table records it and `psql` reads
  it; a surface for that is worth building only once someone wants it.
* **Alerting on the API being down.** REIM cannot report its own unavailability
  from inside itself. That is a black-box monitoring job, and `/health` and
  `/ready` already exist for it.
