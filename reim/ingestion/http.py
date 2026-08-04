"""Shared HTTP client for connectors.

Centralises timeouts, retries, redirect policy and the User-Agent so that no
connector can accidentally hammer an official source. Retries use exponential
backoff and only apply to transport errors and transient server responses —
a ``404`` is a real answer and is never retried.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from reim.core.config import Settings, get_settings
from reim.core.exceptions import ExtractionError
from reim.core.logging import get_logger

logger = get_logger(__name__)

#: Server responses worth retrying: transient overload or gateway problems.
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


class TransientHTTPError(Exception):
    """Internal marker for a response that should be retried."""

    def __init__(self, status_code: int, url: str) -> None:
        super().__init__(f"Transient HTTP {status_code} from {url}")
        self.status_code = status_code
        self.url = url


@asynccontextmanager
async def http_client(settings: Settings | None = None) -> AsyncIterator[httpx.AsyncClient]:
    """Yield a configured :class:`httpx.AsyncClient`.

    Args:
        settings: Override settings; defaults to the process-wide instance.
    """
    resolved = settings or get_settings()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(resolved.http_timeout_seconds),
        headers={"User-Agent": resolved.http_user_agent, "Accept-Encoding": "gzip, deflate"},
        follow_redirects=True,
        limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
    ) as client:
        yield client


async def fetch(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    settings: Settings | None = None,
) -> httpx.Response:
    """GET ``url`` with retries, raising :class:`ExtractionError` on failure.

    Args:
        client: Client returned by :func:`http_client`.
        url: Absolute URL to request.
        params: Query parameters.
        headers: Extra request headers.
        settings: Override settings; defaults to the process-wide instance.

    Raises:
        ExtractionError: The source was unreachable, kept failing, or returned a
            non-retryable error status.
    """
    resolved = settings or get_settings()
    attempts = resolved.http_max_retries + 1

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(multiplier=resolved.http_retry_backoff_seconds, max=30),
            retry=retry_if_exception_type((httpx.TransportError, TransientHTTPError)),
            reraise=True,
        ):
            with attempt:
                response = await client.get(url, params=params, headers=dict(headers or {}))
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
        msg = f"Exhausted {attempts} attempt(s) fetching {url}"
        raise ExtractionError(msg, url=url) from exc
    except TransientHTTPError as exc:
        msg = f"Source kept returning HTTP {exc.status_code} after {attempts} attempt(s): {url}"
        raise ExtractionError(msg, url=url, status_code=exc.status_code) from exc
    except httpx.TransportError as exc:
        msg = f"Could not reach {url}: {type(exc).__name__}: {exc}"
        raise ExtractionError(msg, url=url) from exc

    msg = f"Retry loop exited without a response for {url}"  # pragma: no cover
    raise ExtractionError(msg, url=url)  # pragma: no cover


def ensure_ok(response: httpx.Response, *, expected_content_type: str | None = None) -> None:
    """Validate an HTTP response before it is handed to ``transform``.

    Args:
        response: The response to validate.
        expected_content_type: Substring the ``Content-Type`` header must
            contain, e.g. ``"json"``. Skipped when ``None``.

    Raises:
        ExtractionError: The status is not 2xx, the body is empty, or the
            content type does not match.
    """
    url = str(response.request.url)
    if response.status_code >= 400:
        msg = f"Source returned HTTP {response.status_code} for {url}"
        raise ExtractionError(
            msg,
            url=url,
            status_code=response.status_code,
            body_preview=response.text[:200],
        )
    if not response.content:
        msg = f"Source returned an empty body for {url}"
        raise ExtractionError(msg, url=url, status_code=response.status_code)

    if expected_content_type:
        actual = response.headers.get("content-type", "")
        if expected_content_type.lower() not in actual.lower():
            msg = (
                f"Expected a {expected_content_type!r} response from {url}, "
                f"got Content-Type {actual!r}"
            )
            raise ExtractionError(msg, url=url, content_type=actual)
