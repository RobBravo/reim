"""The two scheduling CLI surfaces.

The repository had no CLI tests before this file; these use Typer's own
``CliRunner``, which runs the command in-process and needs no database. They
assert what an operator sees — the emitted text and the accepted options — not
how it is computed, which ``tests/unit/test_schedule.py`` covers.
"""

from __future__ import annotations

from typer.testing import CliRunner

from reim.cli.main import app

runner = CliRunner()


def test_run_all_accepts_a_frequency() -> None:
    """``--help`` is enough: actually running it would hit the network."""
    result = runner.invoke(app, ["pipeline", "run-all", "--help"])

    assert result.exit_code == 0
    assert "--frequency" in result.stdout


def test_run_all_rejects_a_frequency_that_is_not_one() -> None:
    result = runner.invoke(app, ["pipeline", "run-all", "--frequency", "fortnightly"])

    assert result.exit_code != 0
