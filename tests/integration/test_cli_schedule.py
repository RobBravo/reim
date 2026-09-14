"""The two scheduling CLI surfaces.

The repository had no CLI tests before this file; these use Typer's own
``CliRunner``, which runs the command in-process and needs no database. They
assert what an operator sees — the emitted text and the accepted options — not
how it is computed, which ``tests/unit/test_schedule.py`` covers.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from typer.testing import CliRunner

from reim.cli.main import app
from reim.core.constants import Frequency
from reim.domain.sources.catalog import get_catalog

runner = CliRunner()


class _CapturingRunner:
    """Stands in for ``PipelineRunner``, recording what the CLI handed it."""

    calls: ClassVar[list[dict[str, object]]] = []

    def __init__(self, registry: object) -> None:
        pass

    async def run_all(self, *, enabled_only: bool, keys: list[str] | None = None) -> list[object]:
        _CapturingRunner.calls.append({"enabled_only": enabled_only, "keys": keys})
        return []


@pytest.fixture
def capturing_runner(monkeypatch: pytest.MonkeyPatch) -> type[_CapturingRunner]:
    _CapturingRunner.calls = []
    monkeypatch.setattr("reim.cli.main.PipelineRunner", _CapturingRunner)
    return _CapturingRunner


def test_run_all_accepts_a_frequency() -> None:
    """``--help`` is enough: actually running it would hit the network."""
    result = runner.invoke(app, ["pipeline", "run-all", "--help"])

    assert result.exit_code == 0
    assert "--frequency" in result.stdout


def test_run_all_rejects_a_frequency_that_is_not_one() -> None:
    result = runner.invoke(app, ["pipeline", "run-all", "--frequency", "fortnightly"])

    assert result.exit_code != 0


def test_run_all_with_frequency_filters_keys(
    capturing_runner: type[_CapturingRunner],
) -> None:
    """The filter reaches `run_all` with the correct filtered keys."""
    result = runner.invoke(app, ["pipeline", "run-all", "--frequency", "daily"])

    assert result.exit_code == 0
    expected = sorted(
        entry.key for entry in get_catalog().enabled_sources if entry.frequency is Frequency.DAILY
    )
    assert len(capturing_runner.calls) == 1
    assert sorted(capturing_runner.calls[0]["keys"]) == expected


def test_run_all_without_frequency_passes_none(
    capturing_runner: type[_CapturingRunner],
) -> None:
    """Omitting the flag passes `keys=None` to the runner."""
    result = runner.invoke(app, ["pipeline", "run-all"])

    assert result.exit_code == 0
    assert len(capturing_runner.calls) == 1
    assert capturing_runner.calls[0]["keys"] is None


def test_run_all_with_unused_frequency_exits_zero(
    capturing_runner: type[_CapturingRunner],
) -> None:
    """An unused cadence exits 0 and never calls the runner."""
    unused = next(
        (
            frequency
            for frequency in Frequency
            if not any(entry.frequency is frequency for entry in get_catalog().enabled_sources)
        ),
        None,
    )
    if unused is None:
        pytest.skip("every frequency is in use; nothing to assert")

    result = runner.invoke(app, ["pipeline", "run-all", "--frequency", unused.value])

    assert result.exit_code == 0
    assert capturing_runner.calls == []


def test_schedule_emits_a_crontab_for_the_real_catalog() -> None:
    result = runner.invoke(app, ["pipeline", "schedule"])

    assert result.exit_code == 0
    assert "pipeline run-all --frequency" in result.stdout
    assert "alert check" in result.stdout


def test_schedule_honours_the_working_directory() -> None:
    result = runner.invoke(app, ["pipeline", "schedule", "--working-dir", "/srv/reim"])

    assert result.exit_code == 0
    assert "cd /srv/reim" in result.stdout


def test_schedule_output_is_installable_as_written() -> None:
    """Every non-comment line must be five schedule fields then a command.

    This command exists to be piped into ``crontab -``; text that is merely
    informative would be a different feature.
    """
    result = runner.invoke(app, ["pipeline", "schedule"])

    for line in result.stdout.splitlines():
        if not line or line.startswith("#"):
            continue
        assert len(line.split(maxsplit=5)) == 6
