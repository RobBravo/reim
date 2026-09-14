"""The limiter as a caller meets it.

Each test builds its own app, so each gets its own limiter — counters live on
the app instance precisely so a limit cannot leak between tests.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dependencies import get_db
from apps.api.main import create_app
from reim.core.config import get_settings
from reim.repositories.api_keys import create_key, revoke_key
from tests.conftest import requires_db

ANONYMOUS_LIMIT = 3


@pytest.fixture
def client(
    seeded_session: Session, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """An app with a deliberately tiny anonymous allowance.

    The middleware opens its **own** session rather than using a request-scoped
    dependency, so it has to be pointed at the test schema explicitly. The
    application engine reads ``public`` while the fixtures build their tables in
    ``reim_test``, and without this the key lookup would search a different
    table entirely and every keyed request would 401 for reasons unrelated to
    the code under test.
    """
    monkeypatch.setenv("REIM_RATE_LIMIT_ANONYMOUS", str(ANONYMOUS_LIMIT))
    monkeypatch.setenv("REIM_RATE_LIMIT_KEYED", "100")
    get_settings.cache_clear()

    test_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr("apps.api.middleware.get_session_factory", lambda: test_factory)

    app = create_app()
    app.dependency_overrides[get_db] = lambda: seeded_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


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
