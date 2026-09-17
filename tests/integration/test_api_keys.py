"""The key lifecycle, against real PostgreSQL.

The unique index on the hash and the partial-index behaviour of revocation are
database semantics, so these run against the database rather than being mocked
into agreement with themselves.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reim.core.exceptions import InvalidRequestError
from reim.database.models import ApiKey
from reim.repositories.api_keys import (
    TOKEN_PREFIX,
    create_key,
    find_by_token,
    hash_token,
    list_keys,
    revoke_key,
)
from tests.conftest import requires_db

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


@requires_db
def test_create_key_rejects_an_empty_label(session: Session) -> None:
    """The CLI is not the only caller: the row's own layer refuses this too."""
    with pytest.raises(InvalidRequestError):
        create_key(session, label="", now=NOW)

    assert list_keys(session) == []


@requires_db
def test_create_key_rejects_a_whitespace_label(session: Session) -> None:
    """Whitespace is the same problem wearing a disguise."""
    with pytest.raises(InvalidRequestError):
        create_key(session, label="   ", now=NOW)

    assert list_keys(session) == []


@requires_db
def test_a_created_key_is_returned_once_and_stored_hashed(session: Session) -> None:
    """The raw token exists in exactly one place: the caller's hands."""
    record, token = create_key(session, label="grafana", now=NOW)

    assert token.startswith(TOKEN_PREFIX)
    assert record.label == "grafana"
    assert record.token_hash == hash_token(token)
    assert record.token_hash != token


@requires_db
def test_a_key_is_found_by_its_token(session: Session) -> None:
    _, token = create_key(session, label="grafana", now=NOW)

    found = find_by_token(session, token)

    assert found is not None
    assert found.label == "grafana"


@requires_db
def test_an_unknown_token_finds_nothing(session: Session) -> None:
    create_key(session, label="grafana", now=NOW)

    assert find_by_token(session, f"{TOKEN_PREFIX}nonsense") is None


@requires_db
def test_a_revoked_key_is_no_longer_found(session: Session) -> None:
    record, token = create_key(session, label="grafana", now=NOW)

    assert revoke_key(session, key_id=record.id, now=NOW) is True

    assert find_by_token(session, token) is None


@requires_db
def test_a_revoked_key_is_retained_and_listed(session: Session) -> None:
    """ "When was this revoked" is a question an operator asks."""
    record, _ = create_key(session, label="grafana", now=NOW)
    revoke_key(session, key_id=record.id, now=NOW + timedelta(days=1))

    keys = list_keys(session)

    assert len(keys) == 1
    assert keys[0].revoked_at == NOW + timedelta(days=1)


@requires_db
def test_revoking_a_key_twice_reports_the_second_as_a_no_op(session: Session) -> None:
    record, _ = create_key(session, label="grafana", now=NOW)
    revoke_key(session, key_id=record.id, now=NOW)

    assert revoke_key(session, key_id=record.id, now=NOW) is False


@requires_db
def test_each_created_key_gets_a_distinct_token(session: Session) -> None:
    """The generator, not the constraint: two calls never collide in practice."""
    _, first = create_key(session, label="a", now=NOW)
    _, second = create_key(session, label="b", now=NOW)

    assert first != second


@requires_db
def test_the_database_refuses_two_keys_with_the_same_hash(session: Session) -> None:
    """The constraint, not the generator.

    ``secrets`` makes a duplicate hash vanishingly unlikely, which is exactly
    why the generator cannot stand in for the constraint: a test that only
    compares two generated tokens would pass with no unique index at all.
    """
    shared = hash_token("reim_whatever")
    session.add(ApiKey(token_hash=shared, label="first", created_at=NOW))
    session.flush()
    session.add(ApiKey(token_hash=shared, label="second", created_at=NOW))

    with pytest.raises(IntegrityError):
        session.flush()


@requires_db
def test_keys_are_listed_newest_first(session: Session) -> None:
    create_key(session, label="older", now=NOW)
    create_key(session, label="newer", now=NOW + timedelta(hours=1))

    assert [key.label for key in list_keys(session)] == ["newer", "older"]
