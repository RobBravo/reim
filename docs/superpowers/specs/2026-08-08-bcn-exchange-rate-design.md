# BCN daily exchange rate — design

Status: **approved, not yet implemented**
Date: 2026-08-08
Roadmap item: v0.2.0, "Unblock the BCN exchange-rate connector"

---

## 1. Why now

v0.1.0 shipped `bcn_exchange_rate` disabled. The recorded blocker was that the
host "only negotiates a pre-TLS 1.2 handshake, which OpenSSL 3.x rejects".

That diagnosis was wrong in its second half, and the service is reachable today.

Probing `servicios.bcn.gob.ni:443` from the development machine (Fedora,
OpenSSL 3.5.7):

* The host does negotiate **only TLS 1.0** — forcing TLS 1.1 or 1.2 makes the
  server pick 1.0 and the client reject it.
* Forcing TLS 1.0 alone still fails, but at a **later** stage:
  `do_sigver_init: invalid digest` during `ServerKeyExchange`. That is Fedora's
  ban on **SHA-1 signatures**, not a protocol-version rejection.
* From Python, `ssl.SSLContext` with `minimum_version = maximum_version =
  TLSv1` and `set_ciphers("DEFAULT:@SECLEVEL=0")`, verifying against
  `certifi`, **completes the handshake with no environment changes**:
  `TLSv1 / ECDHE-RSA-AES256-SHA`, certificate chain valid,
  `CN=*.bcn.gob.ni`, `O=Banco Central de Nicaragua`.
* End to end through `httpx.AsyncClient`: **HTTP 200, 31 rows**.

So the connector can be verified and enabled. Doing so gives REIM its first
daily-frequency series and its second national primary source.

## 2. The real service contract

Retrieved live from `https://servicios.bcn.gob.ni/Tc_Servicio/ServicioTC.asmx?WSDL`.

The shipped connector's assumptions are wrong in every particular:

| Shipped assumption | Actual contract |
|---|---|
| namespace `http://tempuri.org/` | `http://servicios.bcn.gob.ni/` |
| parameter `<strfecha>` as an ISO date | `<Ano>`, `<Mes>`, `<Dia>` as `s:int` |
| only a per-day lookup exists | `RecuperaTC_Mes(Ano, Mes)` returns the whole month |

Two operations:

* `RecuperaTC_Dia(Ano, Mes, Dia) -> s:double` — a single rate.
* `RecuperaTC_Mes(Ano, Mes)` — `RecuperaTC_MesResult` wrapping
  `<Detalle_TC><Tc><Fecha>YYYY-MM-DD</Fecha><Valor>36.6243</Valor>
  <Ano/><Mes/><Dia/></Tc>…</Detalle_TC>`, one `Tc` per **calendar** day.

SOAPAction is the namespace plus the operation name. Quoted and unquoted both
work.

### Observed behaviour

| Probe | Result |
|---|---|
| `2011-12` | 0 rows, no SOAP fault — a quiet empty result |
| `2012-01` | 31 rows, `2012-01-01 = 22.9797` … `2012-01-31 = 23.0718` |
| `2020-03` | 31 rows, `34.0052` → `34.0849` (the crawling peg) |
| `2024-01` onwards | 31 rows, flat `36.6243` (the peg was frozen) |
| `2026-12` (future) | **31 rows, already populated** at `36.6243` |
| `1999-01`, month `13` | 0 rows, no fault |

Two consequences that shape the design:

1. Rows arrive **unordered** (March 2020 came back starting at the 7th).
2. The service **answers for months that have not happened yet**, projecting the
   frozen rate forward.

One read timed out and succeeded on retry, so the service is somewhat flaky.

## 3. Decisions

| # | Decision | Rationale |
|---|---|---|
| B1 | Use `RecuperaTC_Mes` only; drop `RecuperaTC_Dia`. | The monthly operation is a strict superset at 1/30th the request count. |
| B2 | The legacy TLS concession lives in the shared HTTP layer and is **declared in `sources/catalog.yml`**. | A security concession belongs where it can be reviewed in a PR and audited alongside the source, not buried in a connector. |
| B3 | Certificate and hostname verification stay **on**. Only protocol version and cipher security level are relaxed, and only for a source that opts in. | The concession is "this host is old", not "trust anyone". |
| B4 | Default window is the current month plus the previous one (2 requests). Full history is an explicit, one-off catalog range. | The project's HTTP layer exists so "no connector can accidentally hammer an official source". A 176-request run on every schedule tick would do exactly that. |
| B5 | Rows dated after today are **discarded**, and the discarded count is reported as an `info` quality check. | Publishing a projected rate as an observed one would be a factual error. Silence would hide that the source projects at all. |
| B6 | An empty month is not an error; a month **inside** coverage that returns empty is. | 2011-12 returning nothing is correct. 2015-06 returning nothing means the feed broke. |
| B7 | Two months returning the same date with different values is a `TransformationError`. | Never pick a winner silently. |

## 4. Components

### 4.1 `reim/core/constants.py`

```python
class TlsProfile(StrEnum):
    """TLS policy a source requires."""

    MODERN = "modern"
    LEGACY = "legacy"
```

### 4.2 `reim/domain/sources/catalog.py`

`SourceEntry` gains:

```python
tls_profile: TlsProfile = TlsProfile.MODERN
tls_note: str | None = None
```

`_validate_entry` gains one rule, mirroring the existing `disabled_reason` rule:

> a source with `tls_profile: legacy` must document `tls_note`.

`extra="forbid"` and `frozen=True` are unchanged.

### 4.3 `reim/ingestion/http.py`

```python
def legacy_tls_context() -> ssl.SSLContext: ...


@asynccontextmanager
async def http_client(
    settings: Settings | None = None,
    *,
    tls_profile: TlsProfile = TlsProfile.MODERN,
) -> AsyncIterator[httpx.AsyncClient]: ...
```

`legacy_tls_context` builds `PROTOCOL_TLS_CLIENT`, sets
`minimum_version = maximum_version = TLSVersion.TLSv1`,
`set_ciphers("DEFAULT:@SECLEVEL=0")`,
`load_verify_locations(cafile=certifi.where())`, and asserts
`check_hostname is True` and `verify_mode is CERT_REQUIRED`.

Selecting the legacy profile emits a structured `warning` naming the host, so a
downgraded connection is never invisible in the logs.

A `post()` function is added as a sibling of `fetch()`, sharing the same
tenacity retry policy, `RETRYABLE_STATUS_CODES` and `ExtractionError`
translation. `fetch()` keeps its current signature and behaviour; the shared
retry loop is factored out so both use one implementation.

`certifi` becomes a direct dependency in `pyproject.toml` (today it is only
transitive through `httpx`).

### 4.4 `reim/ingestion/connectors/nicaragua/bcn_exchange_rate.py`

Rewritten. `version = "1.0.0"`, `expected_frequency = Frequency.DAILY`.

**Month resolution** (`options`, all optional):

| Option | Default | Meaning |
|---|---|---|
| `months_back` | `2` | Number of months ending at the current month. |
| `start_month` | — | `YYYY-MM`; with `end_month`, an explicit inclusive range that overrides `months_back`. |
| `end_month` | current month | `YYYY-MM`. |

Rules: nothing before `2012-01`; `end_month >= start_month`; at most
`MAX_MONTHS_PER_RUN = 400` months resolved, so a typo cannot launch a thousand
requests. The cap sits far above the ~176-month history so it does not need
revisiting as coverage grows. Violations raise `ExtractionError` before any
network call.

The resolver is a pure function of `options` and today's date, and is used by
both `extract` and `validate`.

**`extract`** opens one client with `tls_profile` taken from the catalog entry
and POSTs one envelope per month **sequentially**. Returns:

```python
RawDataset(
    payload=[{"ano": 2026, "mes": 7, "xml": "<soap:Envelope…>"}, …],
    metadata={"months": ["2026-07", "2026-08"], "operation": "RecuperaTC_Mes"},
)
```

so `transform` stays a pure function replayable from a fixture.

**`transform`** parses each envelope, raising `TransformationError` on malformed
XML or a `soap:Fault` (reporting `faultstring`). For each `Tc` it reads `Fecha`
and `Valor`, builds `Decimal` **from the string** — never through `float` — and
`parse_period(fecha, Frequency.DAILY)` for a single-day closed interval. Then:
sort by date; drop dates after `raw.retrieved_at.date()`, counting them; raise
on a duplicate date carrying a different value.

Each observation carries `source_record_id = f"tc_dia:{iso_date}"` and
`raw_metadata` recording the operation, the requested month and
`contract_status: "verified"`.

**`validate`** receives only the observation list, and the connector keeps no
hidden state between `transform` and `validate` — `transform` must stay a pure
function of `raw`. Everything the checks need is therefore **re-derived**: it
calls the same month resolver, and for each resolved month at or after 2012-01
computes the month's calendar days, splitting them into days at or before today
(expected to be present) and days after today (expected to have been discarded).
Comparing that expectation against the observation dates yields all three checks
without any shared mutable state.

A run started immediately before midnight UTC and validated after it would
resolve "today" one day later. The consequence is at most one day counted as
missing rather than discarded, in a check whose failure severity is `warning`;
it is not worth carrying state to prevent.

**`validate`** returns three source-specific checks:

| Check | Type | Severity on failure |
|---|---|---|
| `bcn_month_coverage` — every requested month at or after 2012-01 produced rows | completeness | `error` |
| `bcn_calendar_continuity` — no gap between the earliest and latest ingested date | consistency | `warning` |
| `bcn_future_rows_discarded` — reports how many future-dated rows were dropped | validity | `info` (always passes; it reports) |

Generic bounds, sign, maximum period change and freshness already come from
`sources/quality_rules.yml`, whose existing thresholds for
`ni_exchange_rate_official_daily` (`min_value: 1`, `max_value: 1000`,
`max_period_change_pct: 5`, `freshness_max_age_days: 7`) all hold against the
real 2012–2026 range of 22.98–36.62 and a peg that moved ~0.03%/day.

### 4.5 `sources/catalog.yml`

```yaml
    enabled: true            # was false
    tls_profile: legacy
    tls_note: >-
      servicios.bcn.gob.ni negotiates TLS 1.0 only and signs its key exchange
      with SHA-1. REIM relaxes the protocol version and cipher security level
      for this host alone; certificate chain and hostname verification remain
      enforced. Remove this profile if the BCN modernises the endpoint.
    options:
      months_back: 2
```

`disabled_reason` is removed.

## 5. Testing

Fixtures recorded from the live service, replacing the synthetic
`bcn_exchange_rate_soap.xml`:

| File | Recording |
|---|---|
| `bcn_tc_mes_2020_03.xml` | crawling peg, rows unordered as returned |
| `bcn_tc_mes_2012_01.xml` | first month of coverage |
| `bcn_tc_mes_2011_12.xml` | empty result, before coverage |
| `bcn_tc_mes_future.xml` | a month after the recording date, to exercise the discard |

`tests/fixtures/README.md` moves the BCN entry out of "Synthetic" into
"Recorded from live official sources", and the synthetic file is deleted.

Unit tests (`tests/unit/test_bcn_connector.py`):

* month resolution: default window, explicit range, pre-2012 rejection,
  inverted range, over-cap range
* transform: ordering, exact `Decimal` round trip, single-day periods,
  future-row discard, empty month tolerated, conflicting duplicate raises,
  `soap:Fault` raises, malformed XML raises
* validate: coverage error on an empty in-coverage month, continuity warning on
  a gap, info check counts discards

Plus: `tests/unit/test_catalog.py` covers `tls_profile`/`tls_note` validation,
and a new `tests/unit/test_http.py` asserts `legacy_tls_context()` sets exactly
the intended relaxations and keeps `check_hostname` and `CERT_REQUIRED`.

Extract-level tests use `respx`. One opt-in live test marked `-m live` calls the
real service, matching how the World Bank connector is tested.

## 6. Documentation

* `docs/sources.md` — rewrite the BCN section: correct the blocker diagnosis
  (SHA-1 signature policy, not protocol rejection), record the real contract,
  justify the TLS concession, document that the service answers for future
  months and that REIM discards those rows.
* `docs/implementation-plan.md` — add a post-MVP increment section with the
  verification record.
* `ROADMAP.md` — mark the BCN item done under v0.2.0.
* `tests/fixtures/README.md` — as above.

## 7. Risks

| Risk | Mitigation |
|---|---|
| TLS 1.0 is genuinely obsolete. | Scoped to one opted-in host, declared in the catalog, certificate verification intact, logged on every use. The alternative is depending on the World Bank's annual average instead of the official daily rate. |
| The service is flaky. | The shared tenacity retry policy already covers transport errors and 5xx. |
| A future BCN upgrade breaks the legacy handshake. | Remove `tls_profile` from the catalog entry; no code change. |
| The historical backfill is 176 sequential requests. | Run once, manually, with an explicit `start_month`; the scheduled path stays at 2 requests. |

## 8. Out of scope

BCN monthly monetary statistics, INIDE regional CPI and XLSX ingestion support
remain separate v0.2.0 items with their own specs.
