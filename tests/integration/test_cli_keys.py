"""``reim key``: the only way a key is ever issued.

Keys are minted here and never over HTTP — the API is read-only, and a
credential-issuing endpoint would be its first exception, on the most exposed
surface there is.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from reim.cli.main import app
from reim.repositories.api_keys import list_keys
from tests.conftest import requires_db

runner = CliRunner()


@pytest.fixture
def cli_session(session: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
    """Point the CLI's own ``session_scope`` at the test schema.

    The commands do not take an injected session; they open one. The real
    ``session_scope`` commits on exit, so the stub flushes — enough for the
    test to observe the write, and the ``session`` fixture truncates afterwards.
    """

    @contextmanager
    def _scope() -> Iterator[Session]:
        yield session
        session.flush()

    monkeypatch.setattr("reim.cli.main.session_scope", _scope)
    return session


def test_the_key_group_offers_create_list_and_revoke() -> None:
    result = runner.invoke(app, ["key", "--help"])

    assert result.exit_code == 0
    for command in ("create", "list", "revoke"):
        assert command in result.stdout


def test_create_requires_a_label() -> None:
    """An unlabelled key is one nobody can later identify to revoke."""
    result = runner.invoke(app, ["key", "create"])

    assert result.exit_code != 0


@requires_db
def test_create_rejects_an_empty_label(cli_session: Session) -> None:
    """An empty label is as unusable as a missing one, and gets in further.

    ``--label ""`` satisfies Typer's required-option check, so nothing else
    stops it: the key is minted and appears in ``key list`` as a blank column
    nobody can match to a consumer.
    """
    result = runner.invoke(app, ["key", "create", "--label", ""])

    assert result.exit_code != 0
    assert list_keys(cli_session) == []


@requires_db
def test_create_rejects_a_whitespace_label(cli_session: Session) -> None:
    """Whitespace is the same problem wearing a disguise."""
    result = runner.invoke(app, ["key", "create", "--label", "   "])

    assert result.exit_code != 0
    assert list_keys(cli_session) == []


@requires_db
def test_key_create_with_label(cli_session: Session) -> None:
    """Create exits 0, prints a token beginning reim_, and persists the key."""
    result = runner.invoke(app, ["key", "create", "--label", "grafana"])

    assert result.exit_code == 0
    assert "reim_" in result.stdout
    assert "grafana" in result.stdout

    keys = list_keys(cli_session)
    assert len(keys) == 1
    assert keys[0].label == "grafana"


@requires_db
def test_key_list_empty(cli_session: Session) -> None:
    """List with no keys prints the empty-state sentence and exits 0."""
    result = runner.invoke(app, ["key", "list"])

    assert result.exit_code == 0
    assert "No API keys have been issued." in result.stdout


@requires_db
def test_key_list_shows_active_key(cli_session: Session) -> None:
    """List after creating one shows its label and active status."""
    runner.invoke(app, ["key", "create", "--label", "datadog"])

    result = runner.invoke(app, ["key", "list"])

    assert result.exit_code == 0
    assert "datadog" in result.stdout
    assert "active" in result.stdout


@requires_db
def test_key_list_shows_revoked_key(cli_session: Session) -> None:
    """List after revoking shows revoked status."""
    create_result = runner.invoke(app, ["key", "create", "--label", "prometheus"])
    assert create_result.exit_code == 0

    key_id = None
    for line in create_result.stdout.split("\n"):
        if line.startswith("key"):
            key_id = line.split()[1]
            break

    assert key_id is not None
    revoke_result = runner.invoke(app, ["key", "revoke", key_id])
    assert revoke_result.exit_code == 0

    list_result = runner.invoke(app, ["key", "list"])

    assert list_result.exit_code == 0
    assert "prometheus" in list_result.stdout
    assert "revoked" in list_result.stdout


@requires_db
def test_key_revoke_active_key(cli_session: Session) -> None:
    """Revoke an active key exits 0 and the key is revoked afterwards."""
    create_result = runner.invoke(app, ["key", "create", "--label", "newrelic"])
    assert create_result.exit_code == 0

    key_id = None
    for line in create_result.stdout.split("\n"):
        if line.startswith("key"):
            key_id = line.split()[1]
            break

    assert key_id is not None
    result = runner.invoke(app, ["key", "revoke", key_id])

    assert result.exit_code == 0
    keys = list_keys(cli_session)
    assert len(keys) == 1
    assert keys[0].revoked_at is not None


@requires_db
def test_key_revoke_unknown_uuid_exits_1(cli_session: Session) -> None:
    """Revoke a valid but unknown UUID exits 1."""
    unknown_id = str(uuid.uuid4())
    result = runner.invoke(app, ["key", "revoke", unknown_id])

    assert result.exit_code == 1


@requires_db
def test_key_revoke_invalid_uuid_exits_2(cli_session: Session) -> None:
    """Revoke with an invalid UUID exits 2."""
    result = runner.invoke(app, ["key", "revoke", "not-a-uuid"])

    assert result.exit_code == 2
