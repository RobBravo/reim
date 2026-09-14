"""The limiter as a caller meets it.

Each test builds its own app, so each gets its own limiter — counters live on
the app instance precisely so a limit cannot leak between tests.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dependencies import get_db
from apps.api.main import create_app
from apps.api.middleware import build_rate_limit_middleware
from reim.core.config import get_settings
from reim.repositories.api_keys import create_key, revoke_key
from tests.conftest import requires_db

ANONYMOUS_LIMIT = 3

#: Far enough above the anonymous allowance that a request served on the keyed
#: one cannot be mistaken for a request served anonymously.
KEYED_LIMIT = 100

#: The instant every request in this module is counted at.
#:
#: Windows are aligned to the wall clock, so a test that read the real clock
#: could straddle a boundary, see the counter reset, and pass while the limiter
#: was broken. Pinning the clock removes that flake — and it flaked toward
#: passing, which is the direction that matters for a limiter.
FROZEN_NOW = 1_000_000.0


@pytest.fixture
def build_app(
    seeded_session: Session, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., FastAPI]]:
    """Build apps with a tiny anonymous allowance and a pinned clock.

    Keyword arguments are environment variables set before the settings cache
    is cleared, so a test can build the same app under a different deployment
    shape (a root path, a CORS origin) without a fixture of its own.

    The middleware opens its **own** session rather than using a request-scoped
    dependency, so it has to be pointed at the test schema explicitly. The
    application engine reads ``public`` while the fixtures build their tables in
    ``reim_test``, and without this the key lookup would search a different
    table entirely and every keyed request would 401 for reasons unrelated to
    the code under test.
    """
    monkeypatch.setenv("REIM_RATE_LIMIT_ANONYMOUS", str(ANONYMOUS_LIMIT))
    monkeypatch.setenv("REIM_RATE_LIMIT_KEYED", str(KEYED_LIMIT))

    test_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr("apps.api.middleware.get_session_factory", lambda: test_factory)
    monkeypatch.setattr(
        "apps.api.main.build_rate_limit_middleware",
        functools.partial(build_rate_limit_middleware, clock=lambda: FROZEN_NOW),
    )

    def build(**environment: str) -> FastAPI:
        for name, value in environment.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()
        app = create_app()
        app.dependency_overrides[get_db] = lambda: seeded_session
        return app

    yield build
    get_settings.cache_clear()


@pytest.fixture
def client(build_app: Callable[..., FastAPI]) -> Iterator[TestClient]:
    """A client for the default deployment shape: no root path, no proxy."""
    with TestClient(build_app()) as test_client:
        yield test_client


@requires_db
def test_anonymous_requests_are_allowed_up_to_the_limit(client: TestClient) -> None:
    for _ in range(ANONYMOUS_LIMIT):
        assert client.get("/api/v1/countries").status_code == 200


@requires_db
def test_the_request_past_the_limit_is_refused_with_retry_after(client: TestClient) -> None:
    for _ in range(ANONYMOUS_LIMIT):
        client.get("/api/v1/countries")

    response = client.get("/api/v1/countries")

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response.headers["Retry-After"]) >= 1


@requires_db
def test_exempt_paths_are_never_limited(client: TestClient) -> None:
    """A limiter that can throttle a liveness probe can restart a container."""
    for _ in range(ANONYMOUS_LIMIT * 3):
        assert client.get("/health").status_code == 200
        assert client.get("/metrics").status_code == 200


@requires_db
def test_a_key_raises_the_allowance(client: TestClient, seeded_session: Session) -> None:
    _, token = create_key(seeded_session, label="test", now=datetime.now(UTC))
    # Committed, not merely flushed: the middleware reads through its own
    # session and would not see an uncommitted write.
    seeded_session.commit()
    headers = {"X-API-Key": token}

    for _ in range(ANONYMOUS_LIMIT + 2):
        assert client.get("/api/v1/countries", headers=headers).status_code == 200


@requires_db
def test_an_unknown_key_is_rejected(client: TestClient) -> None:
    """Presenting a credential that does not exist is worth telling someone."""
    response = client.get("/api/v1/countries", headers={"X-API-Key": "reim_nonsense"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


@requires_db
def test_an_unknown_key_is_counted_against_the_anonymous_allowance(client: TestClient) -> None:
    """A junk header must not buy unlimited, uncounted lookups.

    Every presented token costs a hash and an indexed read of ``api_keys``. If
    the 401 returns before the count, an unauthenticated caller converts a
    rate-limited endpoint into an unmetered database-load generator by adding
    one header. So the count comes first and the refusal reason second: past
    the allowance the answer is 429, not another 401.
    """
    headers = {"X-API-Key": "reim_nonsense"}
    for _ in range(ANONYMOUS_LIMIT):
        assert client.get("/api/v1/countries", headers=headers).status_code == 401

    response = client.get("/api/v1/countries", headers=headers)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"


@requires_db
def test_a_refusal_carries_the_same_envelope_as_any_other_error(client: TestClient) -> None:
    """Both refusals happen before any exception handler runs.

    Nothing else asserts the middleware's envelope agrees with the handlers',
    so a key could quietly disappear from one of them.
    """
    handled = client.get("/api/v1/countries/ZZ")
    unauthorized = client.get("/api/v1/countries", headers={"X-API-Key": "reim_nonsense"})
    for _ in range(ANONYMOUS_LIMIT):
        client.get("/api/v1/countries")
    limited = client.get("/api/v1/countries")

    assert handled.status_code == 404
    assert unauthorized.status_code == 401
    assert limited.status_code == 429
    for response, code in ((unauthorized, "invalid_api_key"), (limited, "rate_limited")):
        error = response.json()["error"]
        assert error.keys() == handled.json()["error"].keys()
        assert error["code"] == code
        assert error["message"]
        assert error["details"] == {}


@requires_db
def test_a_revoked_key_is_rejected(client: TestClient, seeded_session: Session) -> None:
    record, token = create_key(seeded_session, label="test", now=datetime.now(UTC))
    revoke_key(seeded_session, key_id=record.id, now=datetime.now(UTC))
    seeded_session.commit()

    response = client.get("/api/v1/countries", headers={"X-API-Key": token})

    assert response.status_code == 401


@requires_db
def test_no_key_is_not_an_error(client: TestClient) -> None:
    """Anonymous is a supported mode, not a failure."""
    assert client.get("/api/v1/countries").status_code == 200


@requires_db
def test_a_forged_forwarded_header_does_not_buy_a_fresh_allowance(
    client: TestClient,
) -> None:
    """With no trusted proxies, the header must not choose the identity.

    If it did, a client would send a different value each request and never
    exhaust anything — the limiter would report healthy and enforce nothing.
    """
    for index in range(ANONYMOUS_LIMIT):
        client.get("/api/v1/countries", headers={"X-Forwarded-For": f"10.0.0.{index}"})

    response = client.get("/api/v1/countries", headers={"X-Forwarded-For": "10.0.0.99"})

    assert response.status_code == 429


@requires_db
def test_the_limiter_still_counts_behind_a_root_path(
    build_app: Callable[..., FastAPI],
) -> None:
    """``root_path`` must not exempt every data route from the limiter.

    ``request.url.path`` carries the prefix the proxy did not strip, while the
    router matches on the path with it removed. If the middleware tests the
    former, every route under ``REIM_API_ROOT_PATH`` serves normally and is
    counted by nothing — the limiter reporting healthy while enforcing nothing,
    in the deployment most likely to need it.
    """
    app = build_app(REIM_API_ROOT_PATH="/reim")

    with TestClient(app, root_path="/reim") as test_client:
        for _ in range(ANONYMOUS_LIMIT):
            assert test_client.get("/reim/api/v1/countries").status_code == 200

        assert test_client.get("/reim/api/v1/countries").status_code == 429
