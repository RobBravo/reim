"""Application settings, loaded from environment variables and ``.env``.

All variables use the ``REIM_`` prefix. Nothing in this module reads a secret
from disk or from the repository; secrets must arrive through the environment.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from reim.core.constants import Environment

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
            "REIM/0.1.0 (Regional Economic Intelligence Monitor; "
            "+https://github.com/reim-project/reim)"
        ),
        description="Sent on every outbound request so operators can identify us.",
    )

    # -- Catalog ----------------------------------------------------------
    catalog_path: Path = Field(default=REPO_ROOT / "sources" / "catalog.yml")
    quality_rules_path: Path = Field(default=REPO_ROOT / "sources" / "quality_rules.yml")

    # -- API --------------------------------------------------------------
    api_title: str = "REIM API"
    api_root_path: str = ""
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"])
    cors_allow_credentials: bool = False
    default_page_size: int = Field(default=100, ge=1, le=1000)
    max_page_size: int = Field(default=1000, ge=1, le=10000)
    max_export_rows: int = Field(default=100_000, ge=1)
    metrics_enabled: bool = True

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Allow a comma-separated string so the value works in a ``.env`` file."""
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):  # already JSON, let pydantic parse it
                return stripped
            return [item.strip() for item in stripped.split(",") if item.strip()]
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
