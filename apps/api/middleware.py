"""The one request-path concern REIM adds: how much, and from whom.

Only paths under ``/api/v1`` are limited. That single rule exempts the liveness
and readiness probes, the Prometheus scrape, the web pages, the static assets
and the docs without enumerating any of them — and a limiter that can throttle
a liveness probe can restart a healthy container.

An anonymous request does no database work at all: the key table is touched
only when a key is actually presented.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from apps.api.ratelimit import FixedWindowLimiter, client_identity
from reim.core.config import Settings
from reim.core.logging import get_logger
from reim.database.session import get_session_factory
from reim.repositories.api_keys import find_by_token

logger = get_logger(__name__)

#: Everything below this prefix is limited; everything else is not.
LIMITED_PREFIX = "/api/v1"

#: Header a caller presents a key in.
API_KEY_HEADER = "X-API-Key"

Handler = Callable[[Request], Awaitable[Response]]


def _envelope(code: str, message: str) -> dict[str, object]:
    """Match the shape ``apps/api/errors.py`` produces, so clients parse one."""
    return {"error": {"code": code, "message": message, "details": {}}}


def _resolve_key(token: str) -> tuple[str | None, bool]:
    """Return ``(identity, recognised)`` for a presented token.

    A lookup that fails because the database is unreachable reports the token
    as *recognised but unidentified*, so the request proceeds on the anonymous
    allowance instead of being rejected. A 401 is a misleading way to say the
    database is down, and the endpoint the request is heading for will report
    the outage in its own terms.
    """
    session = get_session_factory()()
    try:
        record = find_by_token(session, token)
        # Capture the ID before closing the session
        record_id = record.id if record is not None else None
    except SQLAlchemyError:
        logger.warning("api.key_lookup_unavailable")
        return None, True
    finally:
        session.rollback()
        session.close()

    if record_id is None:
        return None, False
    return f"key:{record_id}", True


def build_rate_limit_middleware(
    limiter: FixedWindowLimiter, settings: Settings
) -> Callable[[Request, Handler], Awaitable[Response]]:
    """Return the middleware, closed over this application's own limiter."""

    async def rate_limit(request: Request, call_next: Handler) -> Response:
        if not request.url.path.startswith(LIMITED_PREFIX):
            return await call_next(request)

        identity: str | None = None
        limit = settings.rate_limit_anonymous

        token = request.headers.get(API_KEY_HEADER)
        if token:
            identity, recognised = _resolve_key(token)
            if not recognised:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content=_envelope(
                        "invalid_api_key", "That API key is not valid or has been revoked."
                    ),
                )
            if identity is not None:
                limit = settings.rate_limit_keyed

        if identity is None:
            identity = client_identity(
                request.client.host if request.client else None,
                request.headers.get("X-Forwarded-For"),
                trusted_proxy_hops=settings.trusted_proxy_hops,
            )

        decision = limiter.check(identity, limit, now=time.time())
        if not decision.allowed:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content=_envelope(
                    "rate_limited",
                    "Too many requests. Present an API key for a higher allowance.",
                ),
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )
        return await call_next(request)

    return rate_limit
