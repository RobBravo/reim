"""``reim key``: the only way a key is ever issued.

Keys are minted here and never over HTTP — the API is read-only, and a
credential-issuing endpoint would be its first exception, on the most exposed
surface there is.
"""

from __future__ import annotations

from typer.testing import CliRunner

from reim.cli.main import app

runner = CliRunner()


def test_the_key_group_offers_create_list_and_revoke() -> None:
    result = runner.invoke(app, ["key", "--help"])

    assert result.exit_code == 0
    for command in ("create", "list", "revoke"):
        assert command in result.stdout


def test_create_requires_a_label() -> None:
    """An unlabelled key is one nobody can later identify to revoke."""
    result = runner.invoke(app, ["key", "create"])

    assert result.exit_code != 0
