"""The deployment as shipped, not as described.

Every claim the guide makes about these files is only true while the files say
so. These tests are what keeps the two from drifting apart.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

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
