"""``REIM_CORS_ALLOW_ORIGINS`` as the environment actually sets it.

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

from reim.core.config import Settings


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
