"""The deployment as shipped, not as described.

Every claim the guide makes about these files is only true while the files say
so. These tests are what keeps the two from drifting apart.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

from reim.core.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION = REPO_ROOT / "deploy" / "docker-compose.prod.yml"
CADDYFILE = REPO_ROOT / "deploy" / "Caddyfile"


@pytest.fixture
def production() -> dict:
    return yaml.safe_load(PRODUCTION.read_text(encoding="utf-8"))


def test_only_caddy_publishes_ports(production: dict) -> None:
    """Every other service is reachable only from the compose network.

    Asserted over every service rather than naming postgres and api, so a
    service added later cannot quietly open a port nobody tested for. An
    earlier draft of this plan used a compose *overlay* declaring ``ports: []``
    and a test that read that overlay; both passed while the merged deployment
    still published 5432, because Compose concatenates ports when merging. The
    lesson kept here is that the assertion belongs on the whole resolved file.
    """
    publishing = {
        name: service.get("ports")
        for name, service in production["services"].items()
        if service.get("ports")
    }

    assert set(publishing) == {"caddy"}, (
        f"only caddy may publish ports; these also do: {sorted(set(publishing) - {'caddy'})}"
    )


def test_exactly_one_trusted_proxy_hop(production: dict) -> None:
    """One proxy is in front, and it is ours.

    Higher than the number of proxies actually run hands the choice of identity
    back to the client and the rate limiter stops limiting.
    """
    environment = production["services"]["api"]["environment"]

    assert str(environment["REIM_TRUSTED_PROXY_HOPS"]) == "1"


def test_the_settings_an_operator_tunes_reach_the_container(production: dict) -> None:
    """An operator's tuning must not require editing the file we shipped them.

    Each of these must be referenced in the api service's environment block so
    that setting it in .env actually reaches the container. Their absence there
    is exactly what let ``REIM_RATE_LIMIT_ANONYMOUS`` through unconfigurable
    until this test existed. Alerting had the identical gap, one subsystem
    over, and then ``REIM_MAX_EXPORT_ROWS`` had it a third time while
    ``docs/deployment.md`` named it as the export budget to tune — three
    instances found one at a time, each because somebody happened to look.

    So this list is no longer the subsystem somebody last noticed. It is the
    result of enumerating every field of ``reim.core.config.Settings`` against
    this block and keeping the ones an operator of a public deployment would
    plausibly set; the settings deliberately left out (``REIM_ENVIRONMENT``,
    ``REIM_DATABASE_URL``, ``REIM_CATALOG_PATH`` and the rest) are listed with
    their reasons in the task report beside this change. Adding a field to
    ``Settings`` that an operator would reach for means adding it here too.
    """
    environment = production["services"]["api"]["environment"]

    for variable in (
        "REIM_RATE_LIMIT_ENABLED",
        "REIM_RATE_LIMIT_ANONYMOUS",
        "REIM_RATE_LIMIT_KEYED",
        "REIM_RATE_LIMIT_WINDOW_SECONDS",
        "REIM_ALERT_WEBHOOK_URL",
        "REIM_ALERT_SEVERITY_FLOOR",
        "REIM_ALERT_REPEAT_HOURS",
        "REIM_ALERT_STUCK_RUN_HOURS",
        "REIM_DEFAULT_PAGE_SIZE",
        "REIM_MAX_PAGE_SIZE",
        "REIM_MAX_EXPORT_ROWS",
        "REIM_METRICS_ENABLED",
        "REIM_DATABASE_POOL_SIZE",
        "REIM_DATABASE_MAX_OVERFLOW",
        "REIM_HTTP_TIMEOUT_SECONDS",
        "REIM_HTTP_MAX_RETRIES",
        "REIM_HTTP_RETRY_BACKOFF_SECONDS",
    ):
        assert variable in environment, f"{variable} has no path through docker-compose.prod.yml"


def test_every_wired_variable_names_a_real_setting(production: dict) -> None:
    """The other half of the same gap: a key here that no ``Settings`` field reads.

    ``SettingsConfigDict(extra="ignore")`` means a misspelled or renamed
    ``REIM_*`` key is not an error — it is simply never read, which looks
    exactly like the setting being wired. The test above cannot see that:
    ``REIM_MAX_EXPORT_ROW`` would satisfy nothing and fail loudly, but
    ``REIM_MAX_EXPORT_ROWS`` surviving a later rename of the field itself would
    leave a line here that reaches nothing and a test that still passes.
    """
    environment = production["services"]["api"]["environment"]
    known = {f"REIM_{name.upper()}" for name in Settings.model_fields}

    unknown = sorted(key for key in environment if key.startswith("REIM_") and key not in known)

    assert not unknown, (
        f"these keys are set on the api service but no field of Settings reads them, "
        f"so they are silently ignored: {unknown}"
    )


def test_compose_file_declares_no_cors_wildcard_default(production: dict) -> None:
    """The compose file declares no wildcard default and requires the operator to supply origins.

    PyYAML does not resolve ${VAR}, so this checks the file's declared default, not the
    operator's runtime value — which is the right check for the regression that motivated it.
    """
    environment = production["services"]["api"]["environment"]
    value = str(environment.get("REIM_CORS_ALLOW_ORIGINS", ""))

    assert "*" not in value, "the production compose must not default CORS to a wildcard"


def test_caddy_proxies_to_the_api_service_by_name(production: dict) -> None:
    """Over the compose network, never over a published port."""
    text = CADDYFILE.read_text(encoding="utf-8")

    assert "api:8000" in text
    assert "localhost:8000" not in text


def test_metrics_is_not_reachable_from_outside() -> None:
    """The metrics design put authentication out of scope on the grounds that a
    scrape endpoint is restricted at the network. This is that restriction."""
    text = CADDYFILE.read_text(encoding="utf-8")

    # Structural check: the /metrics handler block must respond, not proxy.
    # Extract the handler block content and verify it responds rather than proxies.
    # This is not satisfied by having "respond 404" anywhere in the file — it must
    # be inside the /metrics handler block specifically.
    match = re.search(r"handle\s+/metrics\s*\{([^}]+)\}", text)
    assert match, "handle /metrics block not found in Caddyfile"

    handler_body = match.group(1)
    assert "respond" in handler_body, (
        "/metrics handler must respond, but found no 'respond' directive in its body"
    )
    assert "reverse_proxy" not in handler_body, (
        "/metrics handler must not reverse_proxy; found 'reverse_proxy' in its body"
    )


def _api_command_argv(production: dict) -> list[str]:
    """Return the argv the container's entrypoint would actually receive.

    An ``entrypoint:`` on the service can replace ``command:``'s role entirely
    — a script that ignores or rewrites its arguments would leave ``command:``
    (and anything asserted about its text) untouched while running whatever it
    likes. Nothing here can see inside such a script, so its presence is
    refused outright rather than silently trusted.

    Compose tokenizes a plain ``command:`` string the same way a shell would —
    quotes preserved, nothing else interpreted — before handing it to the
    entrypoint; ``shlex.split`` in POSIX mode does the same job. A list-form
    ``command:`` is already tokenized.
    """
    service = production["services"]["api"]
    assert "entrypoint" not in service, (
        "the api service now has an entrypoint:, which can replace or rewrite "
        "command: before it runs; this test cannot see inside an entrypoint "
        "script and must be taught how to check it before this is safe to ignore"
    )

    command = service["command"]
    if isinstance(command, list):
        return [str(part) for part in command]
    return shlex.split(str(command))


def _uvicorn_argv_from_actually_running_the_command(argv: list[str], tmp_path: Path) -> list[str]:
    """Run the command for real, with stand-ins for alembic/python/uvicorn on PATH.

    This is what "structural, not a substring check" means in practice: a `#`
    partway through the string, a flag living in the ``alembic`` segment
    instead of the ``uvicorn`` one, or ``--proxy-headers`` appended after
    ``--no-proxy-headers`` are all shell-level facts. Re-deriving shell
    comment and quoting rules in Python would just be a second, competing
    guess at what ``sh`` does; asking the real ``sh`` to run the command and
    recording what its ``uvicorn`` stand-in actually received removes the
    guessing entirely — the one thing this test cannot be fooled about is
    what argv its own fake ``uvicorn`` was called with.
    """
    record = tmp_path / "uvicorn_argv.txt"
    bindir = tmp_path / "bin"
    bindir.mkdir()

    # alembic and python must succeed and do nothing, so `&&` keeps going.
    for name in ("alembic", "python", "python3"):
        stub = bindir / name
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)

    uvicorn_stub = bindir / "uvicorn"
    uvicorn_stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{record}"\nexit 0\n')
    uvicorn_stub.chmod(0o755)

    result = subprocess.run(
        argv,
        env={"PATH": f"{bindir}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        "the api service's command exited "
        f"{result.returncode} running with stand-ins for alembic/python/uvicorn "
        f"on PATH (stderr: {result.stderr!r})"
    )
    assert record.exists(), "uvicorn was never invoked when the api service's command actually ran"

    return record.read_text().splitlines()


def test_the_production_command_keeps_uvicorn_out_of_the_identity_decision(
    production: dict, tmp_path: Path
) -> None:
    """``--no-proxy-headers`` must survive every edit to this command.

    uvicorn's own proxy-header handling is enabled by default and trusts
    127.0.0.1, so without this flag it rewrites the client address from a
    caller-supplied ``X-Forwarded-For`` before REIM's limiter runs whenever
    uvicorn's immediate TCP peer is itself trusted — the ``Dockerfile``'s
    ``CMD`` carries the same flag and an explanation, but this ``command:``
    overrides that ``CMD`` entirely, so the Dockerfile's copy protects nothing
    here.

    A substring check on the YAML text is satisfied by ``--proxy-headers``
    appended after this flag (click keeps whichever is given last), by a
    trailing shell comment, or by the flag sitting in a different ``&&``
    segment than the ``uvicorn`` call — none of which reach uvicorn. So this
    asserts on the argv uvicorn actually receives when the command runs for
    real, not on where the substring sits in the YAML scalar.
    """
    argv = _api_command_argv(production)
    uvicorn_args = _uvicorn_argv_from_actually_running_the_command(argv, tmp_path)

    no_proxy_positions = [i for i, arg in enumerate(uvicorn_args) if arg == "--no-proxy-headers"]
    proxy_positions = [i for i, arg in enumerate(uvicorn_args) if arg == "--proxy-headers"]

    assert no_proxy_positions, (
        "uvicorn's actual argv, once the api service's command really runs, carries no "
        f"--no-proxy-headers: {uvicorn_args!r}"
    )
    if proxy_positions:
        assert max(no_proxy_positions) > max(proxy_positions), (
            "click resolves this pair of flags to whichever is given last, and "
            f"--proxy-headers comes after --no-proxy-headers in {uvicorn_args!r}, so "
            "uvicorn would actually run with proxy headers enabled"
        )
