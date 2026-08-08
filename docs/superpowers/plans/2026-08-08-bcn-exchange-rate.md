# BCN Daily Exchange Rate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the `bcn_exchange_rate` connector against the BCN's real SOAP contract and enable it, giving REIM its first daily-frequency series from a national primary source.

**Architecture:** A new `TlsProfile` declared per source in `sources/catalog.yml` lets the shared HTTP layer build a TLS 1.0 context for the one host that needs it, with certificate verification intact. The connector resolves a window of months from catalog options, POSTs one `RecuperaTC_Mes` request per month through that client, and transforms the concatenated envelopes into one observation per calendar day — sorted, deduplicated, and truncated at today.

**Tech Stack:** Python 3.12, httpx + tenacity, `xml.etree.ElementTree`, Pydantic 2, pytest + respx, structlog.

## Global Constraints

- Coverage starts at **2012-01**. Nothing before it may be requested.
- `MAX_MONTHS_PER_RUN = 400`; `DEFAULT_MONTHS_BACK = 2`.
- SOAP namespace is `http://servicios.bcn.gob.ni/`. SOAPAction is that namespace plus the operation name.
- Economic values are built as `Decimal` **from the source string**. Never through `float`.
- Certificate chain and hostname verification stay enabled in every TLS profile. Only protocol version and cipher security level are relaxed.
- `transform` must remain a pure function of its `RawDataset`. No state is carried from `transform` to `validate`.
- `pyproject.toml` sets `filterwarnings = ["error::DeprecationWarning:reim.*"]`, so any `DeprecationWarning` raised inside `reim.*` fails the suite.
- Every task ends with `ruff check`, `ruff format --check` and `mypy --strict reim apps` passing.

---

### Task 1: `TlsProfile` and its catalog declaration

**Files:**
- Modify: `reim/core/constants.py`
- Modify: `reim/domain/sources/catalog.py:38-94`
- Test: `tests/unit/test_catalog.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `reim.core.constants.TlsProfile` (`StrEnum` with `MODERN = "modern"`, `LEGACY = "legacy"`); `SourceEntry.tls_profile: TlsProfile` and `SourceEntry.tls_note: str | None`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_catalog.py`. Reuse whatever helper the file already uses to build a minimal valid entry dict; if it builds entries inline, follow that style.

```python
from reim.core.constants import TlsProfile


def test_source_defaults_to_the_modern_tls_profile(valid_source_dict):
    entry = SourceEntry.model_validate(valid_source_dict)

    assert entry.tls_profile is TlsProfile.MODERN
    assert entry.tls_note is None


def test_legacy_tls_profile_requires_a_note(valid_source_dict):
    payload = {**valid_source_dict, "tls_profile": "legacy"}

    with pytest.raises(ValidationError, match="tls_note"):
        SourceEntry.model_validate(payload)


def test_legacy_tls_profile_is_accepted_with_a_note(valid_source_dict):
    payload = {
        **valid_source_dict,
        "tls_profile": "legacy",
        "tls_note": "Host negotiates TLS 1.0 only; verification stays enforced.",
    }

    entry = SourceEntry.model_validate(payload)

    assert entry.tls_profile is TlsProfile.LEGACY
```

If `valid_source_dict` does not already exist in the file, add it as a fixture returning a dict that validates today:

```python
@pytest.fixture
def valid_source_dict() -> dict[str, object]:
    return {
        "key": "tls_probe_source",
        "name": "TLS probe source",
        "organization": "BCN",
        "country": "NI",
        "category": "exchange_rate",
        "access_type": "soap",
        "frequency": "daily",
        "format": "xml",
        "base_url": "https://servicios.bcn.gob.ni/Tc_Servicio/ServicioTC.asmx",
        "connector": "reim.ingestion.connectors.nicaragua.bcn_exchange_rate",
        "indicators": ["ni_exchange_rate_official_daily"],
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog.py -k tls -v`
Expected: FAIL — `AttributeError: TlsProfile` on import, or `extra="forbid"` rejecting `tls_profile`.

- [ ] **Step 3: Add the enum**

In `reim/core/constants.py`, next to `AccessType` and `SourceFormat`:

```python
class TlsProfile(StrEnum):
    """TLS policy a source requires.

    ``LEGACY`` relaxes the protocol version and cipher security level for
    hosts that never modernised. It never relaxes certificate or hostname
    verification.
    """

    MODERN = "modern"
    LEGACY = "legacy"
```

- [ ] **Step 4: Add the fields and the validator rule**

In `reim/domain/sources/catalog.py`, import `TlsProfile` alongside the other constants, then add to `SourceEntry` immediately after `disabled_reason`:

```python
    #: TLS policy this host requires. ``LEGACY`` must justify itself.
    tls_profile: TlsProfile = TlsProfile.MODERN
    tls_note: str | None = None
```

Add to `_validate_entry`, directly after the existing `disabled_reason` rule:

```python
        if self.tls_profile is TlsProfile.LEGACY and not self.tls_note:
            msg = "a source with tls_profile 'legacy' must document 'tls_note'"
            raise ValueError(msg)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_catalog.py -v`
Expected: PASS, including the pre-existing tests.

- [ ] **Step 6: Lint, type-check and commit**

```bash
.venv/bin/ruff check reim tests && .venv/bin/ruff format --check reim tests
.venv/bin/mypy --strict reim apps
git add reim/core/constants.py reim/domain/sources/catalog.py tests/unit/test_catalog.py
git commit -m "feat(catalog): declare a per-source TLS profile

A source that needs a relaxed TLS handshake must now say so in the
catalog and justify it, the same way a disabled source must document
disabled_reason. Keeps a security concession reviewable in a PR."
```

---

### Task 2: The legacy TLS context

**Files:**
- Modify: `reim/ingestion/http.py:43-57`
- Modify: `pyproject.toml` (dependencies)
- Test: `tests/unit/test_http.py` (create)

**Interfaces:**
- Consumes: `TlsProfile` from Task 1.
- Produces: `reim.ingestion.http.legacy_tls_context() -> ssl.SSLContext`; `http_client(settings=None, *, tls_profile: TlsProfile = TlsProfile.MODERN)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_http.py`:

```python
"""Tests for the shared HTTP layer."""

from __future__ import annotations

import ssl

import pytest

from reim.core.constants import TlsProfile
from reim.ingestion.http import http_client, legacy_tls_context


def test_legacy_context_pins_tls_10() -> None:
    ctx = legacy_tls_context()

    assert ctx.minimum_version is ssl.TLSVersion.TLSv1
    assert ctx.maximum_version is ssl.TLSVersion.TLSv1


def test_legacy_context_keeps_certificate_verification() -> None:
    ctx = legacy_tls_context()

    assert ctx.check_hostname is True
    assert ctx.verify_mode is ssl.CERT_REQUIRED
    assert ctx.get_ca_certs(), "the CA bundle must be loaded"


def test_legacy_context_does_not_leak_a_deprecation_warning() -> None:
    # pyproject turns DeprecationWarning from reim.* into an error, so a
    # naked assignment of ssl.TLSVersion.TLSv1 would fail the suite.
    with pytest.warns(None) as recorded:  # noqa: PT030 - asserting absence
        legacy_tls_context()

    assert not [w for w in recorded if issubclass(w.category, DeprecationWarning)]


async def test_http_client_uses_a_plain_verify_by_default() -> None:
    async with http_client() as client:
        assert client is not None


async def test_http_client_accepts_the_legacy_profile() -> None:
    async with http_client(tls_profile=TlsProfile.LEGACY) as client:
        assert client is not None
```

Note: `pytest.warns(None)` is removed in pytest 8. Use this instead for the third test:

```python
def test_legacy_context_does_not_leak_a_deprecation_warning(
    recwarn: pytest.WarningsRecorder,
) -> None:
    legacy_tls_context()

    assert not [w for w in recwarn if issubclass(w.category, DeprecationWarning)]
```

Use the `recwarn` version and delete the `pytest.warns(None)` variant.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_http.py -v`
Expected: FAIL — `ImportError: cannot import name 'legacy_tls_context'`.

- [ ] **Step 3: Add certifi as a direct dependency**

In `pyproject.toml`, in `dependencies`, after the `httpx` line:

```toml
    # Pinned CA bundle for the legacy-TLS profile, which builds its own
    # SSLContext instead of relying on httpx's default verification.
    "certifi>=2024.8.30",
```

Then: `.venv/bin/pip install -e ".[dev]"`

- [ ] **Step 4: Implement the context and the profile switch**

In `reim/ingestion/http.py`, add to the imports:

```python
import ssl
import warnings

import certifi

from reim.core.constants import TlsProfile
```

Add after `RETRYABLE_STATUS_CODES`:

```python
def legacy_tls_context() -> ssl.SSLContext:
    """Build an SSL context for hosts stuck on a pre-TLS-1.2 handshake.

    ``servicios.bcn.gob.ni`` negotiates TLS 1.0 only and signs its key
    exchange with SHA-1, which a modern OpenSSL profile refuses. This context
    lowers the protocol version and the cipher security level for that class
    of host — and nothing else. The certificate chain and the hostname are
    still verified, against certifi's bundle.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=certifi.where())
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    with warnings.catch_warnings():
        # Assigning TLSv1 is deprecated in CPython, and pyproject promotes
        # DeprecationWarning from reim.* to an error. Pinning it is the
        # deliberate point of this function.
        warnings.simplefilter("ignore", DeprecationWarning)
        context.minimum_version = ssl.TLSVersion.TLSv1
        context.maximum_version = ssl.TLSVersion.TLSv1
    context.set_ciphers("DEFAULT:@SECLEVEL=0")
    return context
```

Replace the `http_client` signature and body:

```python
@asynccontextmanager
async def http_client(
    settings: Settings | None = None,
    *,
    tls_profile: TlsProfile = TlsProfile.MODERN,
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield a configured :class:`httpx.AsyncClient`.

    Args:
        settings: Override settings; defaults to the process-wide instance.
        tls_profile: TLS policy the source requires. ``LEGACY`` downgrades the
            handshake and is logged at warning level on every use.
    """
    resolved = settings or get_settings()
    verify: ssl.SSLContext | bool = True
    if tls_profile is TlsProfile.LEGACY:
        logger.warning("http.legacy_tls_enabled", tls_profile=tls_profile.value)
        verify = legacy_tls_context()

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(resolved.http_timeout_seconds),
        headers={"User-Agent": resolved.http_user_agent, "Accept-Encoding": "gzip, deflate"},
        follow_redirects=True,
        limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        verify=verify,
    ) as client:
        yield client
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_http.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 6: Verify the handshake against the real host**

This is the whole point of the task, so confirm it before committing:

```bash
.venv/bin/python - <<'PY'
import socket, ssl
from reim.ingestion.http import legacy_tls_context

ctx = legacy_tls_context()
with socket.create_connection(("servicios.bcn.gob.ni", 443), timeout=20) as sock:
    with ctx.wrap_socket(sock, server_hostname="servicios.bcn.gob.ni") as tls:
        print(tls.version(), tls.cipher()[0])
        print(dict(x[0] for x in tls.getpeercert()["subject"]))
PY
```

Expected: `TLSv1 ECDHE-RSA-AES256-SHA` and a subject naming `Banco Central de Nicaragua`.

- [ ] **Step 7: Lint, type-check and commit**

```bash
.venv/bin/ruff check reim tests && .venv/bin/ruff format --check reim tests
.venv/bin/mypy --strict reim apps
git add reim/ingestion/http.py tests/unit/test_http.py pyproject.toml
git commit -m "feat(http): legacy TLS profile for pre-TLS-1.2 official hosts

servicios.bcn.gob.ni negotiates TLS 1.0 only and signs its key exchange
with SHA-1. This lowers the protocol version and cipher security level
for sources that opt in, and nothing else: the certificate chain and
hostname are still verified against certifi. Every use is logged."
```

---

### Task 3: `post()` with the shared retry policy

**Files:**
- Modify: `reim/ingestion/http.py:60-113`
- Test: `tests/unit/test_http.py`

**Interfaces:**
- Consumes: `http_client` from Task 2.
- Produces: `reim.ingestion.http.post(client, url, *, content: bytes, headers: Mapping[str, str] | None = None, settings: Settings | None = None) -> httpx.Response`.

`fetch()` keeps its current signature and behaviour; both it and `post()` delegate to one private retry loop.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_http.py`:

```python
import httpx
import respx

from reim.core.exceptions import ExtractionError
from reim.ingestion.http import fetch, post

SOAP_URL = "https://servicios.bcn.gob.ni/Tc_Servicio/ServicioTC.asmx"


@respx.mock
async def test_post_returns_a_successful_response() -> None:
    route = respx.post(SOAP_URL).mock(return_value=httpx.Response(200, text="<ok/>"))

    async with http_client() as client:
        response = await post(client, SOAP_URL, content=b"<req/>")

    assert response.status_code == 200
    assert route.call_count == 1


@respx.mock
async def test_post_retries_a_transient_status_then_succeeds() -> None:
    route = respx.post(SOAP_URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, text="<ok/>")]
    )

    async with http_client() as client:
        response = await post(client, SOAP_URL, content=b"<req/>")

    assert response.status_code == 200
    assert route.call_count == 2


@respx.mock
async def test_post_does_not_retry_a_real_error_status() -> None:
    route = respx.post(SOAP_URL).mock(return_value=httpx.Response(404))

    async with http_client() as client:
        response = await post(client, SOAP_URL, content=b"<req/>")

    assert response.status_code == 404
    assert route.call_count == 1


@respx.mock
async def test_post_raises_extraction_error_when_the_host_is_unreachable() -> None:
    respx.post(SOAP_URL).mock(side_effect=httpx.ConnectError("boom"))

    async with http_client() as client:
        with pytest.raises(ExtractionError, match="Could not reach"):
            await post(client, SOAP_URL, content=b"<req/>")


@respx.mock
async def test_post_sends_the_body_and_headers_unchanged() -> None:
    route = respx.post(SOAP_URL).mock(return_value=httpx.Response(200, text="<ok/>"))

    async with http_client() as client:
        await post(
            client,
            SOAP_URL,
            content=b"<envelope/>",
            headers={"SOAPAction": "http://servicios.bcn.gob.ni/RecuperaTC_Mes"},
        )

    request = route.calls.last.request
    assert request.content == b"<envelope/>"
    assert request.headers["SOAPAction"] == "http://servicios.bcn.gob.ni/RecuperaTC_Mes"
```

Do not try to zero the backoff: `Settings.http_retry_backoff_seconds` is
constrained `gt=0`. The single-retry test costs about a second at the default
multiplier, matching the cost of the existing
`test_extract_retries_transient_failures` in `tests/unit/test_connectors.py`.
The tests above deliberately never exhaust all four attempts, which would cost
roughly seven seconds of exponential backoff.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_http.py -k post -v`
Expected: FAIL — `ImportError: cannot import name 'post'`.

- [ ] **Step 3: Factor the retry loop out of `fetch`**

In `reim/ingestion/http.py`, add to imports:

```python
from collections.abc import AsyncIterator, Callable, Coroutine, Mapping
```

Insert the shared loop before `fetch`:

```python
async def _send_with_retries(
    send: Callable[[], Coroutine[Any, Any, httpx.Response]],
    url: str,
    resolved: Settings,
) -> httpx.Response:
    """Run ``send`` under the shared retry policy.

    Args:
        send: Zero-argument coroutine factory performing one attempt.
        url: Absolute URL, used for logging and error messages.
        resolved: Already-resolved settings.

    Raises:
        ExtractionError: The source was unreachable, kept failing, or returned
            a non-retryable error status.
    """
    attempts = resolved.http_max_retries + 1

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(multiplier=resolved.http_retry_backoff_seconds, max=30),
            retry=retry_if_exception_type((httpx.TransportError, TransientHTTPError)),
            reraise=True,
        ):
            with attempt:
                response = await send()
                if response.status_code in RETRYABLE_STATUS_CODES:
                    logger.warning(
                        "http.retryable_status",
                        url=url,
                        status_code=response.status_code,
                        attempt=attempt.retry_state.attempt_number,
                    )
                    raise TransientHTTPError(response.status_code, url)
                return response
    except RetryError as exc:  # pragma: no cover - reraise=True makes this rare
        msg = f"Exhausted {attempts} attempt(s) requesting {url}"
        raise ExtractionError(msg, url=url) from exc
    except TransientHTTPError as exc:
        msg = f"Source kept returning HTTP {exc.status_code} after {attempts} attempt(s): {url}"
        raise ExtractionError(msg, url=url, status_code=exc.status_code) from exc
    except httpx.TransportError as exc:
        msg = f"Could not reach {url}: {type(exc).__name__}: {exc}"
        raise ExtractionError(msg, url=url) from exc

    msg = f"Retry loop exited without a response for {url}"  # pragma: no cover
    raise ExtractionError(msg, url=url)  # pragma: no cover
```

Replace the body of `fetch` (keep its docstring) with:

```python
    resolved = settings or get_settings()

    async def send() -> httpx.Response:
        return await client.get(url, params=params, headers=dict(headers or {}))

    return await _send_with_retries(send, url, resolved)
```

Add `post` after `fetch`:

```python
async def post(
    client: httpx.AsyncClient,
    url: str,
    *,
    content: bytes,
    headers: Mapping[str, str] | None = None,
    settings: Settings | None = None,
) -> httpx.Response:
    """POST ``content`` to ``url`` with retries.

    Shares :func:`fetch`'s retry policy: transport errors and transient server
    statuses are retried, a ``404`` is a real answer and is not.

    Args:
        client: Client returned by :func:`http_client`.
        url: Absolute URL to request.
        content: Request body, already encoded.
        headers: Extra request headers.
        settings: Override settings; defaults to the process-wide instance.

    Raises:
        ExtractionError: The source was unreachable or kept failing.
    """
    resolved = settings or get_settings()

    async def send() -> httpx.Response:
        return await client.post(url, content=content, headers=dict(headers or {}))

    return await _send_with_retries(send, url, resolved)
```

- [ ] **Step 4: Run the whole suite to verify nothing regressed**

Run: `.venv/bin/python -m pytest tests/unit -v`
Expected: PASS — the new `post` tests plus every pre-existing test, since `fetch` behaviour is unchanged.

- [ ] **Step 5: Lint, type-check and commit**

```bash
.venv/bin/ruff check reim tests && .venv/bin/ruff format --check reim tests
.venv/bin/mypy --strict reim apps
git add reim/ingestion/http.py tests/unit/test_http.py
git commit -m "feat(http): add post() sharing fetch()'s retry policy

SOAP sources need POST. Rather than let a connector hand-roll retries,
fetch and post now delegate to one loop with the same backoff, the same
retryable statuses and the same ExtractionError translation."
```

---

### Task 4: Record real fixtures

**Files:**
- Create: `tests/fixtures/bcn_tc_mes_2012_01.xml`, `bcn_tc_mes_2020_03.xml`, `bcn_tc_mes_2011_12.xml`, `bcn_tc_mes_2027_03.xml`
- Delete: `tests/fixtures/bcn_exchange_rate_soap.xml`
- Modify: `tests/fixtures/README.md`
- Modify: `tests/unit/test_connectors.py` (delete the obsolete BCN block)
- Modify: `tests/conftest.py:91-93` (delete the `bcn_soap_payload` fixture)

**Interfaces:**
- Consumes: `legacy_tls_context` from Task 2.
- Produces: four fixture files holding **verbatim** SOAP responses, replayed by Tasks 6–8.

- [ ] **Step 1: Record the four months from the live service**

```bash
.venv/bin/python - <<'PY'
import asyncio, pathlib
import httpx
from reim.ingestion.http import legacy_tls_context

URL = "https://servicios.bcn.gob.ni/Tc_Servicio/ServicioTC.asmx"
ENV = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
    "<soap:Body>"
    '<RecuperaTC_Mes xmlns="http://servicios.bcn.gob.ni/">'
    "<Ano>{year}</Ano><Mes>{month}</Mes>"
    "</RecuperaTC_Mes></soap:Body></soap:Envelope>"
)
WANTED = {
    "bcn_tc_mes_2012_01.xml": (2012, 1),
    "bcn_tc_mes_2020_03.xml": (2020, 3),
    "bcn_tc_mes_2011_12.xml": (2011, 12),
    "bcn_tc_mes_2027_03.xml": (2027, 3),
}
out = pathlib.Path("tests/fixtures")

async def main() -> None:
    async with httpx.AsyncClient(verify=legacy_tls_context(), timeout=60) as client:
        for name, (year, month) in WANTED.items():
            response = await client.post(
                URL,
                content=ENV.format(year=year, month=month).encode("utf-8"),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": "http://servicios.bcn.gob.ni/RecuperaTC_Mes",
                },
            )
            response.raise_for_status()
            (out / name).write_text(response.text, encoding="utf-8")
            print(f"{name}: HTTP {response.status_code}, {response.text.count('<Tc>')} rows")

asyncio.run(main())
PY
```

Expected output:

```
bcn_tc_mes_2012_01.xml: HTTP 200, 31 rows
bcn_tc_mes_2020_03.xml: HTTP 200, 31 rows
bcn_tc_mes_2011_12.xml: HTTP 200, 0 rows
bcn_tc_mes_2027_03.xml: HTTP 200, 31 rows
```

If the service times out, rerun — it is intermittently slow. Do **not** hand-edit the recordings.

- [ ] **Step 2: Sanity-check the recordings**

```bash
grep -c '<Tc>' tests/fixtures/bcn_tc_mes_2012_01.xml
head -c 400 tests/fixtures/bcn_tc_mes_2020_03.xml
```

Confirm 2012-01 opens with a value near `22.9797` and that 2020-03's rows are **not** in date order — the out-of-order recording is what makes the sorting test meaningful.

- [ ] **Step 3: Delete the synthetic fixture and everything that reads it**

```bash
git rm tests/fixtures/bcn_exchange_rate_soap.xml
```

Six existing tests assert the *old* connector's behaviour and would fail from
here on. Delete the whole block in `tests/unit/test_connectors.py` that starts
at the banner comment:

```python
# --------------------------------------------------------------------------
# BCN (disabled connector, synthetic fixture)
# --------------------------------------------------------------------------
```

through the end of `test_bcn_validate_requires_exactly_one_rate` — that is
`test_bcn_source_is_disabled_in_the_catalog`,
`test_bcn_transform_parses_the_result_element`,
`test_bcn_transform_rejects_malformed_xml`,
`test_bcn_transform_rejects_a_missing_result`,
`test_bcn_refuses_dates_before_documented_coverage` and
`test_bcn_validate_requires_exactly_one_rate`. Tasks 5–8 replace all of them in
`tests/unit/test_bcn_connector.py`, and Task 9 restores the catalog assertion in
its enabled form.

Then delete the now-dangling fixture at `tests/conftest.py:91-93`:

```python
@pytest.fixture
def bcn_soap_payload() -> str:
    return (FIXTURES / "bcn_exchange_rate_soap.xml").read_text()
```

Keep the `bcn_source` fixture at `tests/conftest.py:115` — Task 9 uses it.

Finally, remove the `BcnExchangeRateConnector` import from
`tests/unit/test_connectors.py:20` if nothing else in that file uses it, or
`ruff` will fail on the unused import.

- [ ] **Step 4: Update the fixtures README**

In `tests/fixtures/README.md`, delete the `bcn_exchange_rate_soap.xml` row from the "Synthetic" table and add to "Recorded from live official sources":

```markdown
| `bcn_tc_mes_2012_01.xml` | `POST https://servicios.bcn.gob.ni/Tc_Servicio/ServicioTC.asmx`, `RecuperaTC_Mes(2012, 1)` — the first month of coverage | 2026-08-08 |
| `bcn_tc_mes_2020_03.xml` | Same endpoint, `RecuperaTC_Mes(2020, 3)` — the crawling peg, rows in the source's own arbitrary order | 2026-08-08 |
| `bcn_tc_mes_2011_12.xml` | Same endpoint, `RecuperaTC_Mes(2011, 12)` — one month before coverage; the service answers with an empty `Detalle_TC` and no SOAP fault | 2026-08-08 |
| `bcn_tc_mes_2027_03.xml` | Same endpoint, `RecuperaTC_Mes(2027, 3)` — a month that has not happened. The service projects the frozen rate forward; the connector discards these rows | 2026-08-08 |
```

Add below the tables:

> The BCN service requires a TLS 1.0 handshake. The recordings above were made
> through `reim.ingestion.http.legacy_tls_context()`; the exact script is in
> `docs/superpowers/plans/2026-08-08-bcn-exchange-rate.md`, Task 4.

- [ ] **Step 5: Confirm the suite still collects and passes**

Run: `.venv/bin/python -m pytest tests/unit -v`
Expected: PASS with six fewer tests than before. Nothing may reference
`bcn_exchange_rate_soap.xml` any more.

- [ ] **Step 6: Commit**

```bash
git add tests/
git commit -m "test(bcn): record real SOAP responses, drop the synthetic one

v0.1.0 shipped a plausible-shaped envelope because the endpoint could not
be reached. It can be now, so these are genuine recordings: coverage
start, the crawling peg with rows unordered as returned, an empty
pre-coverage month, and a future month the service answers anyway."
```

---

### Task 5: Month resolution

**Files:**
- Rewrite: `reim/ingestion/connectors/nicaragua/bcn_exchange_rate.py`
- Test: `tests/unit/test_bcn_connector.py` (create)

**Interfaces:**
- Consumes: `TlsProfile` (Task 1).
- Produces: module constants `COVERAGE_START = date(2012, 1, 1)`, `MAX_MONTHS_PER_RUN = 400`, `DEFAULT_MONTHS_BACK = 2`, `SOAP_NAMESPACE`, `SOAP_ACTION`; module helper `_utc_today() -> date`; `BcnExchangeRateConnector.resolve_months(today: date) -> list[tuple[int, int]]` returning `(year, month)` pairs in ascending order.

This task replaces the file's module docstring and everything above `extract`. Leave the old `extract`/`transform`/`validate` in place for now — Tasks 6–8 replace them — but delete the old `_SOAP_ENVELOPE`, `_RESULT_TAG` and `reference_date`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_bcn_connector.py`:

```python
"""Unit tests for the BCN daily exchange-rate connector."""

from __future__ import annotations

from datetime import date

import pytest

from reim.core.exceptions import ExtractionError
from reim.domain.sources.catalog import SourceEntry
from reim.ingestion.connectors.nicaragua.bcn_exchange_rate import (
    BcnExchangeRateConnector,
)


def build_connector(**options: object) -> BcnExchangeRateConnector:
    """Build the connector with a catalog entry carrying ``options``."""
    entry = SourceEntry.model_validate(
        {
            "key": "bcn_exchange_rate",
            "name": "Nicaragua official exchange rate (daily)",
            "organization": "BCN",
            "country": "NI",
            "category": "exchange_rate",
            "access_type": "soap",
            "frequency": "daily",
            "format": "xml",
            "base_url": "https://servicios.bcn.gob.ni/Tc_Servicio/ServicioTC.asmx",
            "connector": "reim.ingestion.connectors.nicaragua.bcn_exchange_rate",
            "indicators": ["ni_exchange_rate_official_daily"],
            "tls_profile": "legacy",
            "tls_note": "TLS 1.0 only; verification stays enforced.",
            "options": dict(options),
        }
    )
    return BcnExchangeRateConnector(entry)


def test_default_window_is_the_current_month_and_the_previous_one() -> None:
    connector = build_connector()

    assert connector.resolve_months(date(2026, 8, 8)) == [(2026, 7), (2026, 8)]


def test_default_window_crosses_a_year_boundary() -> None:
    connector = build_connector()

    assert connector.resolve_months(date(2026, 1, 20)) == [(2025, 12), (2026, 1)]


def test_months_back_of_one_asks_for_the_current_month_only() -> None:
    connector = build_connector(months_back=1)

    assert connector.resolve_months(date(2026, 8, 8)) == [(2026, 8)]


def test_explicit_range_overrides_months_back() -> None:
    connector = build_connector(months_back=2, start_month="2012-01", end_month="2012-03")

    assert connector.resolve_months(date(2026, 8, 8)) == [(2012, 1), (2012, 2), (2012, 3)]


def test_explicit_start_defaults_its_end_to_the_current_month() -> None:
    connector = build_connector(start_month="2026-06")

    assert connector.resolve_months(date(2026, 8, 8)) == [(2026, 6), (2026, 7), (2026, 8)]


def test_a_start_before_coverage_is_rejected() -> None:
    connector = build_connector(start_month="2011-12")

    with pytest.raises(ExtractionError, match="2012-01"):
        connector.resolve_months(date(2026, 8, 8))


def test_an_inverted_range_is_rejected() -> None:
    connector = build_connector(start_month="2026-06", end_month="2026-03")

    with pytest.raises(ExtractionError, match="precedes"):
        connector.resolve_months(date(2026, 8, 8))


def test_a_range_over_the_cap_is_rejected() -> None:
    connector = build_connector(start_month="2012-01", end_month="2200-01")

    with pytest.raises(ExtractionError, match="400"):
        connector.resolve_months(date(2026, 8, 8))


def test_a_malformed_month_option_is_rejected() -> None:
    connector = build_connector(start_month="March 2020")

    with pytest.raises(ExtractionError, match="YYYY-MM"):
        connector.resolve_months(date(2026, 8, 8))


def test_a_non_positive_months_back_is_rejected() -> None:
    connector = build_connector(months_back=0)

    with pytest.raises(ExtractionError, match="months_back"):
        connector.resolve_months(date(2026, 8, 8))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_bcn_connector.py -v`
Expected: FAIL — `AttributeError: 'BcnExchangeRateConnector' object has no attribute 'resolve_months'`.

- [ ] **Step 3: Replace the module header and add the resolver**

Replace everything in `reim/ingestion/connectors/nicaragua/bcn_exchange_rate.py` from the top of the file down to and including the `reference_date` property with:

```python
"""Nicaragua — daily official exchange rate published by the Banco Central de Nicaragua.

The BCN exposes a free SOAP service at
``https://servicios.bcn.gob.ni/Tc_Servicio/ServicioTC.asmx``, documented at
https://www.bcn.gob.ni/servicio-web-tipo-de-cambio and covering January 2012
onwards. The connector calls ``RecuperaTC_Mes(Ano, Mes)``, which returns every
calendar day of the requested month, rather than the per-day operation.

Two properties of the service shape this connector:

* Rows come back in **arbitrary order**, so they are sorted here.
* The service **answers for months that have not happened yet**, projecting the
  currently frozen rate forward. Those rows are discarded: a projection is not
  an observation.

The host negotiates TLS 1.0 only and signs its key exchange with SHA-1, so the
catalog entry declares ``tls_profile: legacy``. That relaxes the protocol
version and cipher security level for this host alone — certificate and
hostname verification remain enforced. See :func:`reim.ingestion.http.legacy_tls_context`.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import ClassVar

from reim.core.constants import Frequency
from reim.core.exceptions import ExtractionError
from reim.domain.pipelines.models import (
    NormalizedObservation,
    QualityResult,
    RawDataset,
)
from reim.ingestion.base import BaseConnector

SOAP_NAMESPACE = "http://servicios.bcn.gob.ni/"
SOAP_ACTION = f"{SOAP_NAMESPACE}RecuperaTC_Mes"
SOAP_ENVELOPE_NS = "http://schemas.xmlsoap.org/soap/envelope/"

#: Earliest month the BCN service holds data for; 2011-12 returns nothing.
COVERAGE_START = date(2012, 1, 1)
#: Months requested when the catalog does not say otherwise.
DEFAULT_MONTHS_BACK = 2
#: Ceiling on one run, so a mistyped range cannot launch a thousand requests.
MAX_MONTHS_PER_RUN = 400

_MONTH_OPTION = re.compile(r"^(?P<year>\d{4})-(?P<month>0[1-9]|1[0-2])$")

_SOAP_ENVELOPE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<soap:Envelope xmlns:soap="{envelope_ns}">'
    "<soap:Body>"
    '<RecuperaTC_Mes xmlns="{namespace}"><Ano>{year}</Ano><Mes>{month}</Mes></RecuperaTC_Mes>'
    "</soap:Body></soap:Envelope>"
)


def _utc_today() -> date:
    """Return today's UTC date. Indirected so tests can pin it."""
    return datetime.now(UTC).date()


def _month_of(day: date) -> tuple[int, int]:
    return (day.year, day.month)


def _shift_month(month: tuple[int, int], delta: int) -> tuple[int, int]:
    index = month[0] * 12 + (month[1] - 1) + delta
    return (index // 12, index % 12 + 1)


def _month_span(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    """Return every month from ``start`` to ``end`` inclusive, ascending."""
    count = (end[0] * 12 + end[1]) - (start[0] * 12 + start[1]) + 1
    return [_shift_month(start, offset) for offset in range(count)]


class BcnExchangeRateConnector(BaseConnector):
    """Daily NIO/USD official rate from the BCN SOAP service."""

    connector_key = "bcn_exchange_rate"
    version = "1.0.0"
    expected_frequency = Frequency.DAILY
    indicator_code: ClassVar[str] = "ni_exchange_rate_official_daily"
    unit: ClassVar[str] = "NIO per USD"

    def resolve_months(self, today: date) -> list[tuple[int, int]]:
        """Resolve which ``(year, month)`` pairs to request.

        Pure function of the catalog ``options`` and ``today``, so ``extract``
        and ``validate`` can both call it and agree.

        Args:
            today: The date the run considers "now".

        Raises:
            ExtractionError: The options are malformed, reach before coverage,
                invert the range, or exceed :data:`MAX_MONTHS_PER_RUN`.
        """
        end = self._month_option("end_month") or _month_of(today)
        start = self._month_option("start_month")

        if start is None:
            months_back = self._months_back()
            start = _shift_month(end, -(months_back - 1))

        coverage = _month_of(COVERAGE_START)
        if start < coverage:
            msg = (
                f"BCN coverage starts at {coverage[0]}-{coverage[1]:02d}; "
                f"requested start {start[0]}-{start[1]:02d} is before it"
            )
            raise ExtractionError(msg, source_key=self.source.key)

        if end < start:
            msg = (
                f"end_month {end[0]}-{end[1]:02d} precedes "
                f"start_month {start[0]}-{start[1]:02d}"
            )
            raise ExtractionError(msg, source_key=self.source.key)

        months = _month_span(start, end)
        if len(months) > MAX_MONTHS_PER_RUN:
            msg = (
                f"Requested {len(months)} months, above the {MAX_MONTHS_PER_RUN} "
                f"allowed in one run; narrow start_month/end_month"
            )
            raise ExtractionError(msg, source_key=self.source.key)
        return months

    def _months_back(self) -> int:
        raw = self.source.options.get("months_back", DEFAULT_MONTHS_BACK)
        try:
            months_back = int(raw)
        except (TypeError, ValueError) as exc:
            msg = f"months_back must be an integer, got {raw!r}"
            raise ExtractionError(msg, source_key=self.source.key) from exc
        if months_back < 1:
            msg = f"months_back must be at least 1, got {months_back}"
            raise ExtractionError(msg, source_key=self.source.key)
        return months_back

    def _month_option(self, name: str) -> tuple[int, int] | None:
        raw = self.source.options.get(name)
        if raw is None:
            return None
        match = _MONTH_OPTION.match(str(raw).strip())
        if match is None:
            msg = f"{name} must be formatted YYYY-MM, got {raw!r}"
            raise ExtractionError(msg, source_key=self.source.key)
        return (int(match["year"]), int(match["month"]))
```

The import block above is deliberately minimal: `ruff` fails on an unused
import, so Tasks 6, 7 and 8 each add the imports their own code needs. Module
constants and private helpers defined ahead of their use are fine — no lint rule
flags those.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_bcn_connector.py -v`
Expected: PASS, 10 tests.

The old `extract`/`transform`/`validate` below will now reference removed names. That is expected; Tasks 6–8 replace them. If the module fails to import, temporarily leave the old methods raising `NotImplementedError` so the tests can run:

```python
    async def extract(self) -> RawDataset:
        raise NotImplementedError

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        raise NotImplementedError

    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        raise NotImplementedError
```

- [ ] **Step 5: Commit**

```bash
.venv/bin/ruff check reim tests && .venv/bin/ruff format --check reim tests
git add reim/ingestion/connectors/nicaragua/bcn_exchange_rate.py tests/unit/test_bcn_connector.py
git commit -m "feat(bcn): resolve the request window from catalog options

Defaults to the current month plus the previous one, two requests. The
2012-2026 backfill is an explicit one-off start_month/end_month range,
capped so a typo cannot launch a thousand calls at an official source."
```

---

### Task 6: `transform`

**Files:**
- Modify: `reim/ingestion/connectors/nicaragua/bcn_exchange_rate.py`
- Test: `tests/unit/test_bcn_connector.py`

**Interfaces:**
- Consumes: `resolve_months`, the module constants and helpers from Task 5; the fixtures from Task 4.
- Produces: `transform(raw: RawDataset) -> list[NormalizedObservation]` reading `raw.payload` as `list[dict[str, Any]]` with keys `ano: int`, `mes: int`, `xml: str`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_bcn_connector.py`:

```python
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from reim.core.exceptions import TransformationError
from reim.domain.pipelines.models import RawDataset

FIXTURES = Path(__file__).parent.parent / "fixtures"
SOAP_URL = "https://servicios.bcn.gob.ni/Tc_Servicio/ServicioTC.asmx"


def build_raw(*months: tuple[int, int], retrieved_at: datetime) -> RawDataset:
    """Build a RawDataset from recorded fixtures for ``months``."""
    payload = [
        {
            "ano": year,
            "mes": month,
            "xml": (FIXTURES / f"bcn_tc_mes_{year}_{month:02d}.xml").read_text(encoding="utf-8"),
        }
        for year, month in months
    ]
    return RawDataset(
        source_key="bcn_exchange_rate",
        retrieved_at=retrieved_at,
        source_url=SOAP_URL,
        payload=payload,
        content_type="text/xml; charset=utf-8",
        http_status=200,
        metadata={"months": [f"{y}-{m:02d}" for y, m in months]},
    )


def test_transform_reads_every_calendar_day_of_a_month() -> None:
    connector = build_connector()
    raw = build_raw((2012, 1), retrieved_at=datetime(2026, 8, 8, tzinfo=UTC))

    observations = connector.transform(raw)

    assert len(observations) == 31
    assert observations[0].period.start == date(2012, 1, 1)
    assert observations[-1].period.start == date(2012, 1, 31)


def test_transform_sorts_the_unordered_source_rows() -> None:
    connector = build_connector()
    raw = build_raw((2020, 3), retrieved_at=datetime(2026, 8, 8, tzinfo=UTC))

    observations = connector.transform(raw)
    days = [obs.period.start for obs in observations]

    assert days == sorted(days)


def test_transform_preserves_the_published_decimal_exactly() -> None:
    connector = build_connector()
    raw = build_raw((2012, 1), retrieved_at=datetime(2026, 8, 8, tzinfo=UTC))

    first = connector.transform(raw)[0]

    assert first.value_numeric == Decimal("22.9797")
    assert str(first.value_numeric) == "22.9797"


def test_transform_emits_single_day_periods_with_full_provenance() -> None:
    connector = build_connector()
    raw = build_raw((2012, 1), retrieved_at=datetime(2026, 8, 8, tzinfo=UTC))

    first = connector.transform(raw)[0]

    assert first.period.start == first.period.end == date(2012, 1, 1)
    assert first.period.label == "2012-01-01"
    assert first.country_iso3 == "NIC"
    assert first.indicator_code == "ni_exchange_rate_official_daily"
    assert first.unit == "NIO per USD"
    assert first.currency_code == "NIO"
    assert first.source_record_id == "tc_dia:2012-01-01"
    assert first.raw_metadata["bcn_operation"] == "RecuperaTC_Mes"
    assert first.raw_metadata["bcn_requested_month"] == "2012-01"
    assert first.raw_metadata["contract_status"] == "verified"


def test_transform_discards_rows_dated_after_the_retrieval_date() -> None:
    connector = build_connector()
    raw = build_raw((2027, 3), retrieved_at=datetime(2027, 3, 10, tzinfo=UTC))

    observations = connector.transform(raw)

    assert len(observations) == 10
    assert observations[-1].period.start == date(2027, 3, 10)


def test_transform_discards_a_wholly_future_month() -> None:
    connector = build_connector()
    raw = build_raw((2027, 3), retrieved_at=datetime(2026, 8, 8, tzinfo=UTC))

    assert connector.transform(raw) == []


def test_transform_tolerates_a_month_outside_coverage() -> None:
    connector = build_connector()
    raw = build_raw((2011, 12), retrieved_at=datetime(2026, 8, 8, tzinfo=UTC))

    assert connector.transform(raw) == []


def test_transform_rejects_the_same_day_with_two_different_values() -> None:
    connector = build_connector()
    original = (FIXTURES / "bcn_tc_mes_2012_01.xml").read_text(encoding="utf-8")
    conflicting = original.replace("22.9797", "99.9999", 1)
    raw = RawDataset(
        source_key="bcn_exchange_rate",
        retrieved_at=datetime(2026, 8, 8, tzinfo=UTC),
        source_url=SOAP_URL,
        payload=[
            {"ano": 2012, "mes": 1, "xml": original},
            {"ano": 2012, "mes": 1, "xml": conflicting},
        ],
    )

    with pytest.raises(TransformationError, match="two different values"):
        connector.transform(raw)


def test_transform_accepts_the_same_day_repeated_with_one_value() -> None:
    connector = build_connector()
    xml = (FIXTURES / "bcn_tc_mes_2012_01.xml").read_text(encoding="utf-8")
    raw = RawDataset(
        source_key="bcn_exchange_rate",
        retrieved_at=datetime(2026, 8, 8, tzinfo=UTC),
        source_url=SOAP_URL,
        payload=[{"ano": 2012, "mes": 1, "xml": xml}, {"ano": 2012, "mes": 1, "xml": xml}],
    )

    assert len(connector.transform(raw)) == 31


def test_transform_raises_on_a_soap_fault() -> None:
    connector = build_connector()
    fault = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        "<soap:Body><soap:Fault><faultcode>soap:Server</faultcode>"
        "<faultstring>Server was unable to read request.</faultstring>"
        "</soap:Fault></soap:Body></soap:Envelope>"
    )
    raw = RawDataset(
        source_key="bcn_exchange_rate",
        retrieved_at=datetime(2026, 8, 8, tzinfo=UTC),
        source_url=SOAP_URL,
        payload=[{"ano": 2012, "mes": 1, "xml": fault}],
    )

    with pytest.raises(TransformationError, match="unable to read request"):
        connector.transform(raw)


def test_transform_raises_on_malformed_xml() -> None:
    connector = build_connector()
    raw = RawDataset(
        source_key="bcn_exchange_rate",
        retrieved_at=datetime(2026, 8, 8, tzinfo=UTC),
        source_url=SOAP_URL,
        payload=[{"ano": 2012, "mes": 1, "xml": "<soap:Envelope>truncated"}],
    )

    with pytest.raises(TransformationError, match="malformed XML"):
        connector.transform(raw)


def test_transform_rejects_a_payload_that_is_not_a_list() -> None:
    connector = build_connector()
    raw = RawDataset(
        source_key="bcn_exchange_rate",
        retrieved_at=datetime(2026, 8, 8, tzinfo=UTC),
        source_url=SOAP_URL,
        payload="<soap:Envelope/>",
    )

    with pytest.raises(TransformationError, match="list of per-month"):
        connector.transform(raw)
```

Note on `test_transform_discards_rows_dated_after_the_retrieval_date`: the assertion of 10 surviving rows assumes the fixture holds every day of March 2027. Confirm with `grep -c '<Tc>' tests/fixtures/bcn_tc_mes_2027_03.xml` — if the service returned a different count, adjust the expected number to match the days 1–10.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_bcn_connector.py -k transform -v`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement `transform`**

First add the imports this step needs, keeping isort order:

```python
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

from reim.core.exceptions import ExtractionError, TransformationError
from reim.domain.observations.periods import parse_period
```

Then replace the placeholder `transform` in the connector with:

```python
    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Normalize the per-month envelopes into one observation per day.

        Pure function of ``raw``. Rows are sorted, deduplicated and truncated
        at ``raw.retrieved_at``: the service answers for future months, and a
        projected rate is not an observation.

        Raises:
            TransformationError: The payload is not the expected shape, an
                envelope is malformed or carries a SOAP fault, a value is not
                numeric, or one day arrives with two different values.
        """
        payload = raw.payload
        if not isinstance(payload, list):
            msg = "BCN payload must be a list of per-month envelopes"
            raise TransformationError(msg, source_key=self.source.key)

        today = raw.retrieved_at.date()
        values: dict[date, Decimal] = {}
        months: dict[date, str] = {}

        for entry in payload:
            month_label = f"{int(entry['ano'])}-{int(entry['mes']):02d}"
            root = self._parse_envelope(str(entry["xml"]), month_label)
            for node in root.iter("Tc"):
                day, value = self._read_row(node, month_label)
                previous = values.get(day)
                if previous is not None and previous != value:
                    msg = (
                        f"BCN returned {day.isoformat()} with two different values: "
                        f"{previous} and {value}"
                    )
                    raise TransformationError(msg, source_key=self.source.key)
                values[day] = value
                months[day] = month_label

        return [
            NormalizedObservation(
                country_iso3="NIC",
                indicator_code=self.indicator_code,
                source_key=self.source.key,
                period=parse_period(day.isoformat(), Frequency.DAILY),
                unit=self.unit,
                currency_code="NIO",
                value_numeric=values[day],
                retrieved_at=raw.retrieved_at,
                source_url=raw.source_url,
                source_record_id=f"tc_dia:{day.isoformat()}",
                raw_metadata={
                    "bcn_operation": "RecuperaTC_Mes",
                    "bcn_requested_month": months[day],
                    "contract_status": "verified",
                },
            )
            for day in sorted(values)
            if day <= today
        ]

    def _parse_envelope(self, xml: str, month_label: str) -> ElementTree.Element:
        """Parse one SOAP envelope, surfacing a fault as a transformation error."""
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError as exc:
            msg = f"BCN returned malformed XML for {month_label}: {exc}"
            raise TransformationError(msg, source_key=self.source.key) from exc

        fault = root.find(f".//{{{SOAP_ENVELOPE_NS}}}Fault")
        if fault is not None:
            detail = (fault.findtext("faultstring") or "no faultstring").strip()
            msg = f"BCN returned a SOAP fault for {month_label}: {detail}"
            raise TransformationError(msg, source_key=self.source.key)
        return root

    def _read_row(self, node: ElementTree.Element, month_label: str) -> tuple[date, Decimal]:
        """Read one ``<Tc>`` element into a date and an exact Decimal."""
        raw_date = (node.findtext("Fecha") or "").strip()
        raw_value = (node.findtext("Valor") or "").strip()

        try:
            day = date.fromisoformat(raw_date[:10])
        except ValueError as exc:
            msg = f"BCN returned an unparseable date {raw_date!r} in {month_label}"
            raise TransformationError(msg, source_key=self.source.key) from exc

        try:
            value = Decimal(raw_value)
        except InvalidOperation as exc:
            msg = f"BCN returned a non-numeric rate {raw_value!r} for {raw_date}"
            raise TransformationError(msg, source_key=self.source.key) from exc

        return day, value
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_bcn_connector.py -v`
Expected: PASS — the 10 resolver tests plus 12 transform tests.

- [ ] **Step 5: Lint, type-check and commit**

```bash
.venv/bin/ruff check reim tests && .venv/bin/ruff format --check reim tests
.venv/bin/mypy --strict reim apps
git add reim/ingestion/connectors/nicaragua/bcn_exchange_rate.py tests/unit/test_bcn_connector.py
git commit -m "feat(bcn): transform monthly envelopes into daily observations

Sorts the source's arbitrarily-ordered rows, builds Decimals from the
published strings, and truncates at the retrieval date — the service
answers for months that have not happened, and a projected rate is not
an observation. A day arriving twice with different values is an error
rather than a silent winner."
```

---

### Task 7: `validate`

**Files:**
- Modify: `reim/ingestion/connectors/nicaragua/bcn_exchange_rate.py`
- Test: `tests/unit/test_bcn_connector.py`

**Interfaces:**
- Consumes: `resolve_months`, `_utc_today`, `_days_in_month` (Task 5); `transform` (Task 6).
- Produces: `validate(observations) -> list[QualityResult]` returning exactly three checks named `bcn_month_coverage`, `bcn_calendar_continuity`, `bcn_future_rows_discarded`.

`validate` re-derives everything it needs by calling `resolve_months(_utc_today())`. No state crosses from `transform`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_bcn_connector.py`:

```python
from reim.core.constants import CheckSeverity, CheckStatus
from reim.ingestion.connectors.nicaragua import bcn_exchange_rate


@pytest.fixture
def pinned_today(monkeypatch: pytest.MonkeyPatch) -> date:
    """Pin the connector's notion of today so validate is deterministic."""
    today = date(2012, 1, 20)
    monkeypatch.setattr(bcn_exchange_rate, "_utc_today", lambda: today)
    return today


def results_by_name(results: list[QualityResult]) -> dict[str, QualityResult]:
    return {result.check_name: result for result in results}


def test_validate_returns_the_three_source_checks(pinned_today: date) -> None:
    connector = build_connector(start_month="2012-01", end_month="2012-01")
    raw = build_raw((2012, 1), retrieved_at=datetime(2012, 1, 20, tzinfo=UTC))

    results = connector.validate(connector.transform(raw))

    assert set(results_by_name(results)) == {
        "bcn_month_coverage",
        "bcn_calendar_continuity",
        "bcn_future_rows_discarded",
    }


def test_month_coverage_passes_when_every_started_month_has_rows(pinned_today: date) -> None:
    connector = build_connector(start_month="2012-01", end_month="2012-01")
    raw = build_raw((2012, 1), retrieved_at=datetime(2012, 1, 20, tzinfo=UTC))

    check = results_by_name(connector.validate(connector.transform(raw)))["bcn_month_coverage"]

    assert check.status is CheckStatus.PASSED


def test_month_coverage_fails_when_a_started_month_returned_nothing(
    pinned_today: date,
) -> None:
    connector = build_connector(start_month="2012-01", end_month="2012-01")

    check = results_by_name(connector.validate([]))["bcn_month_coverage"]

    assert check.status is CheckStatus.FAILED
    assert check.severity is CheckSeverity.ERROR
    assert "2012-01" in check.actual_value


def test_calendar_continuity_warns_on_a_missing_day(pinned_today: date) -> None:
    connector = build_connector(start_month="2012-01", end_month="2012-01")
    raw = build_raw((2012, 1), retrieved_at=datetime(2012, 1, 20, tzinfo=UTC))
    observations = connector.transform(raw)
    del observations[5]

    check = results_by_name(connector.validate(observations))["bcn_calendar_continuity"]

    assert check.status is CheckStatus.FAILED
    assert check.severity is CheckSeverity.WARNING
    assert "2012-01-06" in check.message


def test_calendar_continuity_passes_on_an_unbroken_run(pinned_today: date) -> None:
    connector = build_connector(start_month="2012-01", end_month="2012-01")
    raw = build_raw((2012, 1), retrieved_at=datetime(2012, 1, 20, tzinfo=UTC))

    check = results_by_name(connector.validate(connector.transform(raw)))[
        "bcn_calendar_continuity"
    ]

    assert check.status is CheckStatus.PASSED


def test_future_rows_discarded_reports_the_count(pinned_today: date) -> None:
    connector = build_connector(start_month="2012-01", end_month="2012-01")
    raw = build_raw((2012, 1), retrieved_at=datetime(2012, 1, 20, tzinfo=UTC))

    check = results_by_name(connector.validate(connector.transform(raw)))[
        "bcn_future_rows_discarded"
    ]

    # January has 31 days; today is the 20th, so 11 days are still ahead.
    assert check.status is CheckStatus.PASSED
    assert check.actual_value == "11"


def test_future_rows_discarded_reports_zero_for_a_closed_month() -> None:
    connector = build_connector(start_month="2012-01", end_month="2012-01")
    raw = build_raw((2012, 1), retrieved_at=datetime(2026, 8, 8, tzinfo=UTC))

    check = results_by_name(connector.validate(connector.transform(raw)))[
        "bcn_future_rows_discarded"
    ]

    assert check.actual_value == "0"
```

`test_future_rows_discarded_reports_zero_for_a_closed_month` deliberately does **not** use `pinned_today`: with the real today far past 2012, no day of that month lies ahead.

Import `QualityResult` at the top of the test file alongside `RawDataset`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_bcn_connector.py -k "coverage or continuity or discarded or three_source" -v`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement `validate`**

First widen the constants import to `from reim.core.constants import CheckSeverity, CheckType, Frequency`, then add the `_days_in_month` helper next to `_month_span`:

```python
def _days_in_month(month: tuple[int, int]) -> list[date]:
    """Return every calendar day of ``month``."""
    first = date(month[0], month[1], 1)
    following = date(*_shift_month(month, 1), 1)
    return [date.fromordinal(o) for o in range(first.toordinal(), following.toordinal())]
```

Then replace the placeholder `validate` with:

```python
    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert BCN-specific expectations beyond the standard battery.

        The checks re-derive the requested window rather than carrying state
        out of :meth:`transform`, which must stay a pure function of its input.
        """
        today = _utc_today()
        months = self.resolve_months(today)
        days = {obs.period.start for obs in observations}
        return [
            self._check_month_coverage(days, months, today),
            self._check_calendar_continuity(days),
            self._check_future_rows_discarded(months, today),
        ]

    def _check_month_coverage(
        self,
        days: set[date],
        months: list[tuple[int, int]],
        today: date,
    ) -> QualityResult:
        """Every requested month that has already begun must have produced rows."""
        started = [month for month in months if month <= _month_of(today)]
        empty = [
            f"{year}-{month:02d}"
            for year, month in started
            if not any(day.year == year and day.month == month for day in days)
        ]

        if not empty:
            return QualityResult.passed(
                "bcn_month_coverage",
                CheckType.COMPLETENESS,
                f"All {len(started)} requested month(s) returned rates",
                expected_value=str(len(started)),
                actual_value=str(len(started)),
            )
        return QualityResult.failure(
            "bcn_month_coverage",
            CheckType.COMPLETENESS,
            CheckSeverity.ERROR,
            f"No rates returned for {len(empty)} requested month(s): {', '.join(empty)}",
            expected_value=str(len(started)),
            actual_value=", ".join(empty),
        )

    def _check_calendar_continuity(self, days: set[date]) -> QualityResult:
        """The BCN publishes a rate for every calendar day, so gaps are suspect."""
        if len(days) < 2:
            return QualityResult.passed(
                "bcn_calendar_continuity",
                CheckType.CONSISTENCY,
                "Too few days ingested to assess continuity",
                actual_value=str(len(days)),
            )

        first, last = min(days), max(days)
        expected = (last - first).days + 1
        missing = sorted(
            date.fromordinal(o)
            for o in range(first.toordinal(), last.toordinal() + 1)
            if date.fromordinal(o) not in days
        )

        if not missing:
            return QualityResult.passed(
                "bcn_calendar_continuity",
                CheckType.CONSISTENCY,
                f"{expected} consecutive days from {first} to {last}",
                expected_value=str(expected),
                actual_value=str(len(days)),
            )

        shown = ", ".join(day.isoformat() for day in missing[:5])
        suffix = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
        return QualityResult.failure(
            "bcn_calendar_continuity",
            CheckType.CONSISTENCY,
            CheckSeverity.WARNING,
            f"{len(missing)} calendar day(s) missing between {first} and {last}: {shown}{suffix}",
            expected_value=str(expected),
            actual_value=str(len(days)),
        )

    def _check_future_rows_discarded(
        self,
        months: list[tuple[int, int]],
        today: date,
    ) -> QualityResult:
        """Report how many projected rows were dropped, so the discard is visible.

        The service returns a row for every calendar day of a requested month,
        including days that have not happened. This never fails: it records
        what was thrown away.
        """
        discarded = sum(1 for month in months for day in _days_in_month(month) if day > today)
        return QualityResult.passed(
            "bcn_future_rows_discarded",
            CheckType.VALIDITY,
            f"{discarded} projected row(s) after {today.isoformat()} were discarded",
            expected_value="0 ingested",
            actual_value=str(discarded),
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_bcn_connector.py -v`
Expected: PASS — 29 tests.

- [ ] **Step 5: Lint, type-check and commit**

```bash
.venv/bin/ruff check reim tests && .venv/bin/ruff format --check reim tests
.venv/bin/mypy --strict reim apps
git add reim/ingestion/connectors/nicaragua/bcn_exchange_rate.py tests/unit/test_bcn_connector.py
git commit -m "feat(bcn): source-specific quality checks

Coverage of every started month is an error when it fails, a gap in the
calendar is a warning, and the count of discarded future rows is reported
as info so the truncation is auditable rather than silent. All three
re-derive the window instead of carrying state out of transform."
```

---

### Task 8: `extract`

**Files:**
- Modify: `reim/ingestion/connectors/nicaragua/bcn_exchange_rate.py`
- Test: `tests/unit/test_bcn_connector.py`

**Interfaces:**
- Consumes: `post`, `http_client`, `ensure_ok` (Tasks 2–3); `resolve_months` (Task 5).
- Produces: `extract() -> RawDataset` whose `payload` is `list[dict[str, Any]]` matching what Task 6's `transform` consumes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_bcn_connector.py`:

```python
import respx


@respx.mock
async def test_extract_requests_one_envelope_per_month(pinned_today: date) -> None:
    connector = build_connector(start_month="2012-01", end_month="2012-01")
    fixture = (FIXTURES / "bcn_tc_mes_2012_01.xml").read_text(encoding="utf-8")
    route = respx.post(SOAP_URL).mock(
        return_value=httpx.Response(
            200, text=fixture, headers={"Content-Type": "text/xml; charset=utf-8"}
        )
    )

    raw = await connector.extract()

    assert route.call_count == 1
    assert raw.http_status == 200
    assert raw.metadata["months"] == ["2012-01"]
    assert raw.payload == [{"ano": 2012, "mes": 1, "xml": fixture}]


@respx.mock
async def test_extract_sends_the_documented_soap_contract(pinned_today: date) -> None:
    connector = build_connector(start_month="2012-01", end_month="2012-01")
    fixture = (FIXTURES / "bcn_tc_mes_2012_01.xml").read_text(encoding="utf-8")
    route = respx.post(SOAP_URL).mock(return_value=httpx.Response(200, text=fixture))

    await connector.extract()
    request = route.calls.last.request

    assert request.headers["SOAPAction"] == "http://servicios.bcn.gob.ni/RecuperaTC_Mes"
    assert request.headers["Content-Type"] == "text/xml; charset=utf-8"
    body = request.content.decode("utf-8")
    assert '<RecuperaTC_Mes xmlns="http://servicios.bcn.gob.ni/">' in body
    assert "<Ano>2012</Ano><Mes>1</Mes>" in body


@respx.mock
async def test_extract_walks_the_whole_requested_range(pinned_today: date) -> None:
    connector = build_connector(start_month="2012-01", end_month="2012-03")
    fixture = (FIXTURES / "bcn_tc_mes_2012_01.xml").read_text(encoding="utf-8")
    route = respx.post(SOAP_URL).mock(return_value=httpx.Response(200, text=fixture))

    raw = await connector.extract()

    assert route.call_count == 3
    assert raw.metadata["months"] == ["2012-01", "2012-02", "2012-03"]


@respx.mock
async def test_extract_raises_when_the_service_errors(pinned_today: date) -> None:
    connector = build_connector(start_month="2012-01", end_month="2012-01")
    # 404 rather than 500: a real answer, so ensure_ok raises immediately
    # instead of burning four attempts of exponential backoff.
    respx.post(SOAP_URL).mock(return_value=httpx.Response(404, text="not found"))

    with pytest.raises(ExtractionError, match="HTTP 404"):
        await connector.extract()


async def test_extract_rejects_bad_options_before_touching_the_network() -> None:
    connector = build_connector(start_month="2011-01")

    with pytest.raises(ExtractionError, match="2012-01"):
        await connector.extract()


@pytest.mark.live
async def test_live_service_answers_the_documented_contract() -> None:
    """Opt-in: hits the real BCN service. Run with `pytest -m live`."""
    connector = build_connector(months_back=1)

    raw = await connector.extract()
    observations = connector.transform(raw)

    assert observations, "the current month must contain at least one rate"
    assert all(obs.value_numeric > 0 for obs in observations)
    assert all(obs.period.start <= raw.retrieved_at.date() for obs in observations)
```

Ensure `httpx`, `respx` and `ExtractionError` are imported at the top of the test file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_bcn_connector.py -k extract -v`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement `extract`**

First add the imports this step needs, keeping isort order:

```python
from typing import Any, ClassVar
from urllib.parse import urlsplit

from reim.core.constants import CheckSeverity, CheckType, Frequency, TlsProfile
from reim.ingestion.http import ensure_ok, http_client, post
```

Then replace the placeholder `extract` with:

```python
    async def extract(self) -> RawDataset:
        """Fetch one ``RecuperaTC_Mes`` envelope per resolved month.

        Requests are issued sequentially rather than concurrently: this is an
        official service on a legacy stack, and a backfill can span years.

        Raises:
            ExtractionError: The options are unusable, or the service was
                unreachable or kept failing.
        """
        months = self.resolve_months(_utc_today())
        url = str(self.source.base_url)
        retrieved_at = datetime.now(UTC)

        if self.source.tls_profile is TlsProfile.LEGACY:
            self.logger.warning(
                "bcn.legacy_tls",
                host=urlsplit(url).hostname,
                tls_note=self.source.tls_note,
            )

        payload: list[dict[str, Any]] = []
        status: int | None = None
        content_type: str | None = None

        async with http_client(tls_profile=self.source.tls_profile) as client:
            for year, month in months:
                body = _SOAP_ENVELOPE.format(
                    envelope_ns=SOAP_ENVELOPE_NS,
                    namespace=SOAP_NAMESPACE,
                    year=year,
                    month=month,
                )
                response = await post(
                    client,
                    url,
                    content=body.encode("utf-8"),
                    headers={
                        "Content-Type": "text/xml; charset=utf-8",
                        "SOAPAction": SOAP_ACTION,
                    },
                )
                ensure_ok(response)
                payload.append({"ano": year, "mes": month, "xml": response.text})
                status = response.status_code
                content_type = response.headers.get("content-type")

        return RawDataset(
            source_key=self.source.key,
            retrieved_at=retrieved_at,
            source_url=url,
            payload=payload,
            content_type=content_type,
            http_status=status,
            metadata={
                "operation": "RecuperaTC_Mes",
                "months": [f"{year}-{month:02d}" for year, month in months],
            },
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_bcn_connector.py -v`
Expected: PASS, 34 tests. The `live` test is deselected by default.

- [ ] **Step 5: Run the live test explicitly**

Run: `.venv/bin/python -m pytest tests/unit/test_bcn_connector.py -m live -v`
Expected: PASS against the real service. If it times out, rerun once — the service is intermittently slow.

- [ ] **Step 6: Lint, type-check and commit**

```bash
.venv/bin/ruff check reim tests && .venv/bin/ruff format --check reim tests
.venv/bin/mypy --strict reim apps
git add reim/ingestion/connectors/nicaragua/bcn_exchange_rate.py tests/unit/test_bcn_connector.py
git commit -m "feat(bcn): fetch RecuperaTC_Mes over the legacy TLS profile

One sequential request per resolved month against the real contract:
namespace http://servicios.bcn.gob.ni/ and integer Ano/Mes, not the
tempuri.org/strfecha shape v0.1.0 guessed at while unable to reach the
service."
```

---

### Task 9: Enable the source and verify end to end

**Files:**
- Modify: `sources/catalog.yml:191-216`
- Modify: `docs/sources.md`, `docs/implementation-plan.md`, `ROADMAP.md`

**Interfaces:**
- Consumes: everything above.
- Produces: an enabled `bcn_exchange_rate` pipeline.

- [ ] **Step 1: Enable the source in the catalog**

In `sources/catalog.yml`, in the `bcn_exchange_rate` entry: delete the whole `disabled_reason` block, set `enabled: true`, and add:

```yaml
    enabled: true
    tls_profile: legacy
    tls_note: >-
      servicios.bcn.gob.ni negotiates TLS 1.0 only and signs its key exchange
      with SHA-1. REIM relaxes the protocol version and cipher security level
      for this host alone; certificate chain and hostname verification remain
      enforced. Remove this profile if the BCN modernises the endpoint.
    options:
      months_back: 2
```

- [ ] **Step 2: Validate the catalog**

Run: `.venv/bin/reim catalog validate`
Expected: the source count now reports 7 enabled rather than 6, and every connector imports.

- [ ] **Step 3: Restore the catalog assertion in its enabled form**

Task 4 deleted `test_bcn_source_is_disabled_in_the_catalog`. Add its replacement
to `tests/unit/test_connectors.py`, which keeps the catalog entry itself under
test rather than only the hand-built entries the connector unit tests use:

```python
# --------------------------------------------------------------------------
# BCN (enabled, legacy TLS)
# --------------------------------------------------------------------------
def test_bcn_source_is_enabled_with_a_justified_legacy_tls_profile(
    bcn_source: SourceEntry,
) -> None:
    """The TLS concession is declared in the catalog and explains itself."""
    assert bcn_source.enabled is True
    assert bcn_source.disabled_reason is None
    assert bcn_source.tls_profile is TlsProfile.LEGACY
    assert bcn_source.tls_note and "TLS 1.0" in bcn_source.tls_note
```

Import `TlsProfile` from `reim.core.constants` at the top of that file.

- [ ] **Step 4: Run the full test suite**

Run: `.venv/bin/python -m pytest`
Expected: PASS — the pre-existing tests minus the six removed in Task 4, plus
the ~35 added here, with no regressions.

- [ ] **Step 5: Seed and run the pipeline against a real database**

```bash
make db-up
.venv/bin/alembic upgrade head
.venv/bin/reim db seed
.venv/bin/reim pipeline run bcn_exchange_rate
```

Expected: status `success`, roughly 40–62 observations (two months, truncated at today), zero rejected.

- [ ] **Step 6: Prove idempotency**

Run: `.venv/bin/reim pipeline run bcn_exchange_rate`
Expected: 0 inserted, 0 updated, and every prior observation reported unchanged.

- [ ] **Step 7: Run the historical backfill once**

Temporarily add `start_month: "2012-01"` to the entry's `options`, then:

```bash
.venv/bin/reim pipeline run bcn_exchange_rate
```

Expected: ~176 sequential requests and roughly 5,300 observations inserted. This takes several minutes. Then **remove `start_month`** so scheduled runs return to two requests, and re-run once to confirm 0 inserted and everything unchanged.

- [ ] **Step 8: Check the data through the API**

```bash
curl -s 'http://localhost:8000/api/v1/observations?indicator_code=ni_exchange_rate_official_daily&limit=3&order=-period_start' | head -40
```

Expected: the three most recent days, no date later than today, values near `36.6243`.

- [ ] **Step 9: Update the documentation**

`docs/sources.md` — rewrite the BCN section. It must state: the real WSDL contract (namespace, `Ano`/`Mes`/`Dia`, both operations); that coverage starts 2012-01 and 2011-12 returns an empty result with no fault; that rows arrive unordered; that the service answers for future months and REIM discards those rows; and that the v0.1.0 blocker was **misdiagnosed** — the host does negotiate only TLS 1.0, but the handshake failure came from the SHA-1 signature ban, and pinning TLS 1.0 at `SECLEVEL=0` with certifi succeeds while keeping certificate verification.

`docs/implementation-plan.md` — add a section `## 12. Post-MVP increment — BCN daily exchange rate (2026-08-08)` with a verification table recording the results of Steps 2–8.

`ROADMAP.md` — under v0.2.0, change the BCN bullet to the struck-through "done" form used by the INIDE entry, noting it is REIM's first daily-frequency series.

`README.md` — if it states a connector or observation count, update both.

- [ ] **Step 10: Final gate and commit**

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check reim apps tests && .venv/bin/ruff format --check reim apps tests
.venv/bin/mypy --strict reim apps
git add sources/catalog.yml docs/ ROADMAP.md README.md
git commit -m "feat(bcn): enable the daily exchange-rate connector

REIM's first daily-frequency series and second national primary source,
covering 2012-01 onward. Corrects the v0.1.0 blocker note: the endpoint
was reachable all along once the SHA-1 signature ban, not the protocol
version, was identified as the cause of the failed handshake."
```

---

## Self-review notes

**Spec coverage.** Spec §4.1 → Task 1; §4.2 → Task 1; §4.3 → Tasks 2–3; §4.4 → Tasks 5–8; §4.5 → Task 9; §5 → Tasks 4–8; §6 → Task 9; §3 decisions B1–B7 → Tasks 5–8. Decision B4's "one-off historical backfill" is exercised in Task 9 Step 7.

**Fixed during self-review.**

- The first draft gave Task 5 the connector's full final import block. `ruff` fails on an unused import, so Task 5's own commit would not have linted. Imports are now added per task, alongside the code that uses them.
- The first draft never mentioned the six existing BCN tests in `tests/unit/test_connectors.py` or the `bcn_soap_payload` fixture in `tests/conftest.py`, all of which assert the old connector's behaviour and read the fixture Task 4 deletes. Task 4 now removes them explicitly; Task 9 restores the catalog assertion in its enabled form.
- Explicit `@pytest.mark.asyncio` markers were dropped: `pyproject.toml` sets `asyncio_mode = "auto"` and no existing test carries one.
- `Settings.http_retry_backoff_seconds` is constrained `gt=0`, so the planned "zero the backoff" fixture could not have worked. The retry tests now use the real default, and the extract failure test uses a `404` — a real answer that `ensure_ok` rejects at once — instead of a `500` that would burn four attempts of exponential backoff.

**Known deviation from the spec.** The spec says the legacy profile "emits a structured warning naming the host". `http_client` does not know the host, so the warning is split: `http.legacy_tls_enabled` in the HTTP layer guarantees no connector can downgrade silently, and `bcn.legacy_tls` in the connector adds the hostname. Both fire on every run.

**Deferred to a later increment.** The generic `check_period_change` rule at `max_period_change_pct: 5` is untouched. The real series never moves more than ~0.03% a day, so it should not fire; if the backfill in Task 9 Step 7 produces unexpected warnings, investigate before adjusting the threshold — per `sources/quality_rules.yml`, thresholds are tripwires for a broken feed, not economic priors.
