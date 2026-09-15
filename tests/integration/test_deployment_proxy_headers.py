"""The limiter as uvicorn actually serves it.

Every other test of the limiter drives the app through ``TestClient``, which
calls the ASGI application directly. uvicorn is never involved, so nothing
those tests do can see what uvicorn does to a request before the application
receives it — and what uvicorn does, by default, is rewrite ``scope["client"]``
from a header the caller supplies.

``ProxyHeadersMiddleware`` ships enabled and trusts ``127.0.0.1``. A reverse
proxy on the same host is therefore trusted, which is the point; but so is
anything else arriving from the loopback address, and the value it reads is
whatever the caller wrote. ``REIM_TRUSTED_PROXY_HOPS`` defaults to ``0`` and
promises that identity is the socket peer. Under uvicorn's default that promise
is not kept, and no setting inside REIM can keep it: the original peer is gone
by the time the application runs.

So these tests start a real server. They are the only ones positioned to.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Low enough that exhausting it costs three requests.
ANONYMOUS_LIMIT = 3

#: Long enough that no test here can cross a window boundary.
WINDOW_SECONDS = 300

#: How long a spawned server gets to answer its first request.
STARTUP_TIMEOUT_SECONDS = 20.0


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def _shipped_uvicorn_flags() -> list[str]:
    """The flags ``Dockerfile``'s ``CMD`` passes uvicorn, minus host and port.

    Read from the file rather than repeated here on purpose. A test that spells
    its own flags proves only that uvicorn honours them; this one fails when
    the image stops passing them, which is the thing that would actually put a
    deployment at risk.
    """
    for line in (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines():
        if not line.startswith("CMD ["):
            continue
        argv = json.loads(line.removeprefix("CMD ").strip())
        if argv[0] != "uvicorn":
            continue
        flags: list[str] = []
        rest = iter(argv[2:])
        for arg in rest:
            if arg in {"--host", "--port"}:
                next(rest, None)
                continue
            flags.append(arg)
        return flags
    pytest.fail("Dockerfile has no uvicorn CMD; this test needs rewriting")


def _serve(*extra_args: str) -> Iterator[str]:
    """Run the app under a real uvicorn and yield its base URL."""
    port = _free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "apps.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
            *extra_args,
        ],
        cwd=REPO_ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "REIM_RATE_LIMIT_ANONYMOUS": str(ANONYMOUS_LIMIT),
            "REIM_RATE_LIMIT_WINDOW_SECONDS": str(WINDOW_SECONDS),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail(f"uvicorn exited during startup with {process.returncode}")
            try:
                httpx.get(f"{base_url}/health", timeout=1.0)
            except httpx.TransportError:
                time.sleep(0.2)
                continue
            break
        else:
            pytest.fail("uvicorn did not start within the timeout")
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - only on a hung server
            process.kill()
            process.wait(timeout=10)


@pytest.fixture
def shipped_server() -> Iterator[str]:
    """The server started with the flags the shipped image actually passes."""
    yield from _serve(*_shipped_uvicorn_flags())


@pytest.fixture
def default_server() -> Iterator[str]:
    """The server as uvicorn runs it when nobody passes the flag."""
    yield from _serve()


def _exhaust(base_url: str) -> None:
    """Spend the anonymous allowance, and confirm it is spent."""
    for _ in range(ANONYMOUS_LIMIT + 2):
        response = httpx.get(f"{base_url}/api/v1/nope", timeout=5.0)
    assert response.status_code == 429, "the allowance was never exhausted"


def test_a_forged_header_buys_nothing_under_the_shipped_command(
    shipped_server: str,
) -> None:
    """The promise ``REIM_TRUSTED_PROXY_HOPS=0`` makes, kept end to end.

    Three *different* forged values, because one would not distinguish a
    limiter that ignores the header from one that hashes every caller into a
    single wrong bucket.
    """
    _exhaust(shipped_server)

    for forged in ("10.0.0.1", "10.0.0.2", "10.0.0.3"):
        response = httpx.get(
            f"{shipped_server}/api/v1/nope",
            headers={"X-Forwarded-For": forged},
            timeout=5.0,
        )
        assert response.status_code == 429, f"{forged} bought a fresh allowance"


def test_the_flag_is_what_closes_the_bypass(default_server: str) -> None:
    """Without the flag the bypass is real — which is why the flag is shipped.

    Asserting that the vulnerable configuration *is* vulnerable looks strange
    until you ask what the test above proves on its own: nothing. It would pass
    against a server that had never read ``X-Forwarded-For`` for any reason at
    all, including a uvicorn release that quietly changed the default. This is
    the test that makes the other one discriminating, and it fails the day
    ``--no-proxy-headers`` stops being the thing that matters.
    """
    _exhaust(default_server)

    served = 0
    for forged in ("10.0.0.1", "10.0.0.2", "10.0.0.3"):
        response = httpx.get(
            f"{default_server}/api/v1/nope",
            headers={"X-Forwarded-For": forged},
            timeout=5.0,
        )
        if response.status_code != 429:
            served += 1

    assert served == 3, (
        "uvicorn no longer rewrites the client from X-Forwarded-For by default; "
        "re-check whether --no-proxy-headers is still the right fix"
    )


@pytest.mark.parametrize("path", ["Dockerfile", "docker-compose.yml"])
def test_the_shipped_commands_disable_uvicorn_proxy_headers(path: str) -> None:
    """The behaviour above only protects a deployment that asks for it.

    Both files invoke uvicorn, and a limiter silently stops limiting if either
    one loses the flag.
    """
    text = (REPO_ROOT / path).read_text(encoding="utf-8")

    assert "uvicorn" in text, f"{path} no longer invokes uvicorn; this test needs rewriting"
    assert "--no-proxy-headers" in text, (
        f"{path} runs uvicorn without --no-proxy-headers, so a client-supplied "
        "X-Forwarded-For header decides its own rate-limit identity"
    )
