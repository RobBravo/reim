"""``Settings`` as the environment actually sets it, not as a keyword argument.

Both groups below construct ``Settings()`` through ``monkeypatch.setenv``
rather than passing values to the constructor, because the environment
source and the init source are different code paths and only one of them is
what a ``deploy/.env`` file reaches.

``REIM_CORS_ALLOW_ORIGINS``:

pydantic-settings JSON-decodes complex-typed fields inside its environment
source *before* any ``field_validator`` runs, so a plain ``*`` or a
comma-separated list set through the environment raised ``SettingsError`` and
the application never booted — ``_split_origins`` had never once run for a
value that came from the environment. ``Settings()`` is constructed directly
here, through ``monkeypatch.setenv``, because passing the value to the
constructor as a keyword argument takes a different code path (the init
source, not the environment source) and would pass even with the bug
present.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from reim.core.config import Settings
from reim.core.constants import CheckSeverity


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("*", ["*"]),
        ("https://a.com,https://b.com", ["https://a.com", "https://b.com"]),
        ('["https://a.com"]', ["https://a.com"]),
        (" https://a.com , ", ["https://a.com"]),
        ("", []),
    ],
)
def test_cors_allow_origins_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: list[str]
) -> None:
    monkeypatch.setenv("REIM_CORS_ALLOW_ORIGINS", raw)
    assert Settings().cors_allow_origins == expected


def test_malformed_json_names_the_setting_rather_than_a_bare_json_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REIM_CORS_ALLOW_ORIGINS", '["unclosed')
    with pytest.raises(ValueError, match="REIM_CORS_ALLOW_ORIGINS is not valid JSON"):
        Settings()


def test_the_severity_floor_accepts_the_case_an_operator_would_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``REIM_ALERT_SEVERITY_FLOOR=ERROR`` must not take the deployment down.

    ``CheckSeverity``'s members are lower-case, so before ``Settings`` normalised
    the case this raised at import — and a value that raises at import is not a
    bad setting, it is an outage: uvicorn never binds, the ``api`` container
    crash-loops under ``restart: unless-stopped``, and ``caddy``'s
    ``condition: service_healthy`` is never met. ``deploy/.env.prod.example``
    prints the four members in lower case, which is exactly the kind of hint an
    operator reads as an enumeration rather than as a spelling requirement.
    """
    for raw in ("ERROR", "Error", "  error  "):
        monkeypatch.setenv("REIM_ALERT_SEVERITY_FLOOR", raw)
        assert Settings().alert_severity_floor is CheckSeverity.ERROR, raw


def test_normalising_the_severity_floor_did_not_stop_it_validating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The complementary cell for the test above.

    A validator that lower-cased its way to accepting anything would satisfy
    that test just as well as a correct one. This is the cell where the two
    differ: an unknown member must still raise, and the message must still name
    the four that are legal, since that message is what the operator reads in
    ``podman compose ... logs api``.
    """
    monkeypatch.setenv("REIM_ALERT_SEVERITY_FLOOR", "URGENT")

    with pytest.raises(ValidationError, match="'info', 'warning', 'error' or 'critical'"):
        Settings()
