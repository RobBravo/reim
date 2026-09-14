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
from sqlalchemy.exc import SQLAlchemyError
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


#: Every surface spec §2 names as exempt, in its order.
EXEMPT_PATHS = [
    "/health",
    "/ready",
    "/metrics",
    "/",
    "/runs",
    "/series",
    "/static/reim.css",
    "/docs",
    "/openapi.json",
]


@requires_db
@pytest.mark.parametrize("path", EXEMPT_PATHS)
def test_exempt_paths_are_never_limited(client: TestClient, path: str) -> None:
    """A limiter that can throttle a liveness probe can restart a container.

    The assertion is "not refused" rather than "200": ``/metrics`` answers 404
    when ``REIM_METRICS_ENABLED`` is off, and this test should not fail for a
    reason that has nothing to do with limiting.
    """
    for _ in range(ANONYMOUS_LIMIT * 3):
        assert client.get(path).status_code != 429


@requires_db
def test_the_status_endpoint_is_limited_even_though_it_is_a_system_route(
    client: TestClient,
) -> None:
    """The positive half of the prefix rule, which §2 names explicitly.

    ``/api/v1/status`` lives in the prefix-less system router for historical
    reasons, so its exemption or otherwise rests entirely on the literal path
    it is declared with. It is a data endpoint, and not a cheap one — it counts
    over the observations table — so it is limited.
    """
    for _ in range(ANONYMOUS_LIMIT):
        assert client.get("/api/v1/status").status_code == 200

    assert client.get("/api/v1/status").status_code == 429


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
def test_a_keyed_request_records_that_the_key_was_used(
    client: TestClient, seeded_session: Session
) -> None:
    """Otherwise ``reim key list`` reports every key as never used.

    Refreshed at most hourly, so this asserts the column is written at all —
    not that it is written on every request, which it deliberately is not.
    """
    record, token = create_key(seeded_session, label="test", now=datetime.now(UTC))
    seeded_session.commit()
    assert record.last_used_at is None

    client.get("/api/v1/countries", headers={"X-API-Key": token})

    seeded_session.expire_all()
    assert record.last_used_at is not None


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


def _break_the_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """The query fails: the database is reachable no longer."""

    def raise_on_lookup(*_args: object, **_kwargs: object) -> None:
        raise SQLAlchemyError("database is down")

    monkeypatch.setattr("apps.api.middleware.find_by_token", raise_on_lookup)


def _break_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opening the session fails, which is what a bad URL or a dead pool does."""

    def raise_on_connect() -> None:
        raise SQLAlchemyError("could not connect")

    monkeypatch.setattr("apps.api.middleware.get_session_factory", raise_on_connect)


BROKEN_DATABASES = pytest.mark.parametrize(
    "break_the_database",
    [_break_the_lookup, _break_the_connection],
    ids=["lookup", "connection"],
)


@requires_db
@BROKEN_DATABASES
def test_a_presented_key_is_served_when_the_database_is_down(
    client: TestClient,
    seeded_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    break_the_database: Callable[[pytest.MonkeyPatch], None],
) -> None:
    """D8: a 401 is a misleading way to say the database is unreachable.

    The endpoint the request is heading for will report the outage in its own
    terms; blaming the caller's credential for the server's problem would not.
    """
    _, token = create_key(seeded_session, label="test", now=datetime.now(UTC))
    seeded_session.commit()
    break_the_database(monkeypatch)

    response = client.get("/api/v1/countries", headers={"X-API-Key": token})

    assert response.status_code == 200


@requires_db
@BROKEN_DATABASES
def test_a_key_whose_lookup_failed_gets_only_the_anonymous_allowance(
    client: TestClient,
    seeded_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    break_the_database: Callable[[pytest.MonkeyPatch], None],
) -> None:
    """Served, but *as anonymous*: an unverifiable key cannot raise a limit."""
    _, token = create_key(seeded_session, label="test", now=datetime.now(UTC))
    seeded_session.commit()
    break_the_database(monkeypatch)
    headers = {"X-API-Key": token}

    for _ in range(ANONYMOUS_LIMIT):
        assert client.get("/api/v1/countries", headers=headers).status_code == 200

    # The keyed allowance is far higher, so a 429 here can only be the
    # anonymous one.
    assert client.get("/api/v1/countries", headers=headers).status_code == 429


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
@pytest.mark.parametrize(
    ("root_path", "url"),
    [
        ("/reim", "/reim/api/v1/countries"),
        # A root path the proxy does not prepend to this URL at all. The router
        # strips only on a segment boundary, so it routes this normally — and a
        # middleware stripping by length alone would leave "i/v1/countries",
        # miss the prefix, and exempt every data route in the deployment.
        ("/ap", "/api/v1/countries"),
    ],
    ids=["prepended", "not-a-segment-prefix"],
)
def test_the_limiter_still_counts_behind_a_root_path(
    build_app: Callable[..., FastAPI], root_path: str, url: str
) -> None:
    """``root_path`` must not exempt every data route from the limiter.

    ``request.url.path`` carries the prefix the proxy did not strip, while the
    router matches on the path with it removed. If the middleware tests the
    former, every route under ``REIM_API_ROOT_PATH`` serves normally and is
    counted by nothing — the limiter reporting healthy while enforcing nothing,
    in the deployment most likely to need it.
    """
    app = build_app(REIM_API_ROOT_PATH=root_path)

    with TestClient(app, root_path=root_path) as test_client:
        for _ in range(ANONYMOUS_LIMIT):
            assert test_client.get(url).status_code == 200

        assert test_client.get(url).status_code == 429


ALLOWED_ORIGIN = "https://dashboard.example.org"

#: JSON, because the env source parses a list field before the settings
#: validator that accepts a comma-separated spelling ever sees it.
ALLOWED_ORIGINS_ENV = f'["{ALLOWED_ORIGIN}"]'


@requires_db
def test_a_refusal_is_readable_by_a_browser(build_app: Callable[..., FastAPI]) -> None:
    """A refusal without CORS headers is an opaque network error, not an answer.

    Starlette applies middleware in reverse registration order, so a limiter
    registered after CORS sits outside it and its responses never pass through
    the CORS path. The one response whose whole purpose is to say "back off,
    and for this long" would be the one a cross-origin caller cannot read.
    """
    app = build_app(REIM_CORS_ALLOW_ORIGINS=ALLOWED_ORIGINS_ENV)
    headers = {"Origin": ALLOWED_ORIGIN}

    with TestClient(app) as test_client:
        for _ in range(ANONYMOUS_LIMIT):
            test_client.get("/api/v1/countries", headers=headers)
        response = test_client.get("/api/v1/countries", headers=headers)

    assert response.status_code == 429
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert int(response.headers["Retry-After"]) >= 1


@requires_db
def test_a_preflight_does_not_spend_the_anonymous_allowance(
    build_app: Callable[..., FastAPI],
) -> None:
    """``X-API-Key`` is not CORS-safelisted, so a keyed browser request is
    always preceded by an ``OPTIONS`` preflight — and a preflight never carries
    the key. Counted, it would spend the anonymous allowance the key was meant
    to raise, so a 600/min key holder would still be cut off at 60/min. With
    CORS outermost, CORS answers the preflight and the limiter never sees it.
    """
    app = build_app(REIM_CORS_ALLOW_ORIGINS=ALLOWED_ORIGINS_ENV)
    preflight = {
        "Origin": ALLOWED_ORIGIN,
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "x-api-key",
    }

    with TestClient(app) as test_client:
        for _ in range(ANONYMOUS_LIMIT * 2):
            assert test_client.options("/api/v1/countries", headers=preflight).status_code == 200

        # Untouched: the data request that follows is the first one counted.
        assert test_client.get("/api/v1/countries").status_code == 200
