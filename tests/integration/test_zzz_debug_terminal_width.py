"""TEMPORARY diagnostic — not for merge. Deleted once the real cause is found."""

from __future__ import annotations

import os
import shutil

from typer.testing import CliRunner

from reim.cli.main import app


def test_zzz_dump_terminal_width_diagnostics() -> None:
    lines = [
        f"COLUMNS env: {os.environ.get('COLUMNS', '<unset>')!r}",
        f"LINES env: {os.environ.get('LINES', '<unset>')!r}",
        f"TERM env: {os.environ.get('TERM', '<unset>')!r}",
        f"FORCE_COLOR env: {os.environ.get('FORCE_COLOR', '<unset>')!r}",
        f"CI env: {os.environ.get('CI', '<unset>')!r}",
        f"GITHUB_ACTIONS env: {os.environ.get('GITHUB_ACTIONS', '<unset>')!r}",
    ]
    import sys

    for fd, name in ((0, "stdin"), (1, "stdout"), (2, "stderr")):
        try:
            lines.append(f"os.get_terminal_size({fd}) [{name}]: {os.get_terminal_size(fd)}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"os.get_terminal_size({fd}) [{name}] raised: {e!r}")

    for name, stream in (("stdin", sys.stdin), ("stdout", sys.stdout), ("stderr", sys.stderr)):
        try:
            lines.append(f"sys.{name}.isatty(): {stream.isatty()}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"sys.{name}.isatty() raised: {e!r}")

    lines.append(f"shutil.get_terminal_size(): {shutil.get_terminal_size()}")

    runner = CliRunner()
    result_no_override = runner.invoke(app, ["pipeline", "run-all", "--help"])
    lines.append(f"--- no-override stdout repr ---\n{result_no_override.stdout!r}")
    lines.append(f"has --frequency (no override): {'--frequency' in result_no_override.stdout}")

    result_override = runner.invoke(
        app, ["pipeline", "run-all", "--help"], env={"COLUMNS": "200"}
    )
    lines.append(f"has --frequency (COLUMNS=200 override): {'--frequency' in result_override.stdout}")

    dump = "\n".join(lines)
    # Force the report to show even under default capture, by failing.
    raise AssertionError("\n\n===== DIAGNOSTIC DUMP =====\n" + dump + "\n===========================\n")
