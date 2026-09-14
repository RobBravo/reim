"""The one request-path concern REIM adds: how much, and from whom.

Only paths under ``/api/v1`` are limited. That single rule exempts the liveness
and readiness probes, the Prometheus scrape, the web pages, the static assets
and the docs without enumerating any of them — and a limiter that can throttle
a liveness probe can restart a healthy container.

An anonymous request does no database work at all: the key table is touched
only when a key is actually presented.

Every request under the prefix is counted, and *then* a refusal reason is
chosen. Deciding the other way round — refusing an invalid key before counting
it — leaves the one request that costs a database read as the only one nothing
bounds.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from apps.api.errors import error_envelope
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
    limiter: FixedWindowLimiter,
    settings: Settings,
    *,
    clock: Callable[[], float] = time.time,
) -> Callable[[Request, Handler], Awaitable[Response]]:
    """Return the middleware, closed over this application's own limiter.

    ``clock`` is injectable so a test can pin the instant every request is
    counted at. The window is aligned to the wall clock, so a test reading the
    real clock can straddle a boundary, watch the counter reset, and pass while
    the limiter is broken — a flake in the one direction that matters here.
    """

    async def rate_limit(request: Request, call_next: Handler) -> Response:
        # ``request.url.path`` still carries the ``root_path`` a proxy did not
        # strip, while the router matches on the path with it removed. Test the
        # same path the router will route, or an app behind
        # ``REIM_API_ROOT_PATH`` serves every data route unlimited: the prefix
        # would never match, and nothing would say so.
        path = request.url.path
        root = request.scope.get("root_path", "")
        if root and path.startswith(root):
            path = path[len(root) :] or "/"
        if not path.startswith(LIMITED_PREFIX):
            return await call_next(request)

        # Resolved for every request, keyed or not. An invalid key is still
        # counted, against the peer that presented it, so the lookup it costs
        # is bounded by the anonymous allowance like everything else.
        identity = client_identity(
            request.client.host if request.client else None,
            request.headers.get("X-Forwarded-For"),
            trusted_proxy_hops=settings.trusted_proxy_hops,
        )
        limit = settings.rate_limit_anonymous
        invalid = False

        token = request.headers.get(API_KEY_HEADER)
        if token:
            keyed_identity, recognised = _resolve_key(token)
            if keyed_identity is not None:
                identity = keyed_identity
                limit = settings.rate_limit_keyed
            elif not recognised:
                # Refused below, after the count — never instead of it.
                invalid = True
            # Recognised but unidentified is D8: the database is down, so the
            # request keeps the anonymous identity and allowance.

        decision = limiter.check(identity, limit, now=clock())
        if not decision.allowed:
            # Identity, never the token: a refusal is worth a line, and one
            # carrying a credential would be worse than no line at all.
            logger.warning("api.rate_limited", identity=identity, path=path)
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content=error_envelope(
                    "rate_limited",
                    "Too many requests. Present an API key for a higher allowance.",
                ),
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )

        if invalid:
            logger.warning("api.invalid_api_key", identity=identity, path=path)
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content=error_envelope(
                    "invalid_api_key", "That API key is not valid or has been revoked."
                ),
            )

        return await call_next(request)

    return rate_limit
