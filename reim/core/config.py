"""Application settings, loaded from environment variables and ``.env``.

All variables use the ``REIM_`` prefix. Nothing in this module reads a secret
from disk or from the repository; secrets must arrive through the environment.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from reim.core.constants import CheckSeverity, Environment

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration for the API, the CLI and the ingestion runner."""

    model_config = SettingsConfigDict(
        env_prefix="REIM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # -- General ----------------------------------------------------------
    environment: Environment = Environment.LOCAL
    log_level: str = "INFO"
    log_json: bool = Field(
        default=False,
        description="Emit JSON logs instead of the human-readable console renderer.",
    )

    # -- Database ---------------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg://reim:reim@localhost:5432/reim",
        description="SQLAlchemy URL for the primary PostgreSQL database.",
    )
    database_echo: bool = False
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=10, ge=0, le=50)

    # -- HTTP client used by connectors -----------------------------------
    http_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    http_max_retries: int = Field(default=3, ge=0, le=10)
    http_retry_backoff_seconds: float = Field(default=1.0, gt=0, le=30)
    http_user_agent: str = Field(
        default=(
            "REIM/0.1.0 (Regional Economic Intelligence Monitor; +https://github.com/RobBravo/reim)"
        ),
        description="Sent on every outbound request so operators can identify us.",
    )

    # -- Catalog ----------------------------------------------------------
    catalog_path: Path = Field(default=REPO_ROOT / "sources" / "catalog.yml")
    quality_rules_path: Path = Field(default=REPO_ROOT / "sources" / "quality_rules.yml")

    # -- API --------------------------------------------------------------
    api_title: str = "REIM API"
    api_root_path: str = ""
    # NoDecode: pydantic-settings JSON-decodes complex-typed fields inside
    # EnvSettingsSource before any field_validator runs, so a comma-separated
    # or bare "*" value from the environment would raise SettingsError and
    # the app would not boot before ``_split_origins`` ever saw it.
    # Suppressing that pre-parse hands the raw string to the validator below,
    # which does its own JSON parsing for the one form pydantic-settings used
    # to handle.
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])
    cors_allow_credentials: bool = False
    default_page_size: int = Field(default=100, ge=1, le=1000)
    max_page_size: int = Field(default=1000, ge=1, le=10000)
    max_export_rows: int = Field(default=100_000, ge=1)
    metrics_enabled: bool = True

    # -- Alerting ---------------------------------------------------------
    alert_webhook_url: str | None = None
    alert_severity_floor: CheckSeverity = CheckSeverity.ERROR
    alert_repeat_hours: int = Field(default=24, ge=1, le=720)
    alert_stuck_run_hours: int = Field(default=6, ge=1, le=168)

    # -- API access -------------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_anonymous: int = Field(default=60, ge=1)
    rate_limit_keyed: int = Field(default=600, ge=1)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    trusted_proxy_hops: int = Field(default=0, ge=0, le=8)

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Allow a comma-separated string so the value works in a ``.env`` file.

        ``NoDecode`` on the field stops pydantic-settings from JSON-decoding
        this value before this validator runs, so a JSON-looking string
        reaches here undecoded and must be parsed here rather than merely
        returned for pydantic to parse later.
        """
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                try:
                    return json.loads(stripped)
                except json.JSONDecodeError as exc:
                    msg = f"REIM_CORS_ALLOW_ORIGINS is not valid JSON: {exc}"
                    raise ValueError(msg) from exc
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @field_validator("alert_severity_floor", mode="before")
    @classmethod
    def _normalize_severity_floor(cls, value: object) -> object:
        """Accept ``ERROR`` as well as ``error``.

        ``CheckSeverity``'s members are lower-case, so an operator who wrote
        ``REIM_ALERT_SEVERITY_FLOOR=ERROR`` in ``deploy/.env`` used to take the
        API container down: the value fails validation, ``Settings()`` raises at
        import, uvicorn never binds, and ``caddy`` waits on a healthcheck that
        never passes. ``log_level`` two lines down already normalises case, and
        nothing about the two settings, sitting in the same file and written the
        same way, tells an operator that one forgives and the other does not.

        Normalising is the choice here rather than only documenting it, because
        documentation cannot undo the outage for the operator who did not read
        it, and ``.strip().lower()`` cannot turn a legal value into a different
        legal one — every member is already lower-case and free of whitespace.
        A genuinely unknown value still raises, naming the four that are legal.

        ``environment`` is the other lower-case ``StrEnum`` in this class and is
        deliberately *not* normalised, so the argument above is about
        reachability rather than symmetry: ``REIM_ALERT_SEVERITY_FLOOR`` is
        ``${...:-error}`` in ``deploy/docker-compose.prod.yml`` and squarely an
        operator's to set, while ``REIM_ENVIRONMENT`` is pinned there and in the
        ``Dockerfile``, so no operator of that deployment reaches it from
        ``.env``. ``REIM_ENVIRONMENT=PRODUCTION`` does still raise, which is a
        live edge for a developer or a staging deployment writing its own
        ``.env``; it is recorded rather than fixed here.
        """
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        level = value.upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
        if level not in allowed:
            msg = f"log_level must be one of {sorted(allowed)}, got {value!r}"
            raise ValueError(msg)
        return level

    @property
    def is_production(self) -> bool:
        """True when running in an environment where debug affordances must be off."""
        return self.environment is Environment.PRODUCTION


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()


def reset_settings_cache() -> None:
    """Clear the settings cache (used by tests that patch the environment)."""
    get_settings.cache_clear()
