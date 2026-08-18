"""Application settings.

Every setting is read from the environment, with defaults suitable for local
development. Environment variables use the ``UPA_`` prefix so they cannot collide
with unrelated variables on the host.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_MEGABYTE = 1024 * 1024


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment variables and ``.env``."""

    model_config = SettingsConfigDict(
        env_prefix="UPA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- Environment ------------------------------------------------------
    environment: str = Field(
        default="development",
        description="Deployment environment name: development, test or production.",
    )
    log_level: str = Field(default="INFO", description="Root log level.")

    # -- Database ---------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://upa:upa@localhost:5432/upa_dev",
        description="SQLAlchemy async database URL. PostgreSQL only; see scripts/setup-db.sql.",
    )
    test_database_url: str | None = Field(
        default=None,
        description=(
            "Server to create throwaway test databases on. Defaults to database_url when unset. "
            "Only the test suite reads this."
        ),
    )
    database_echo: bool = Field(
        default=False,
        description="Echo emitted SQL. Useful when debugging, far too noisy otherwise.",
    )

    # -- Storage ----------------------------------------------------------
    storage_root: Path = Field(
        default=Path("var/samples"),
        description="Directory holding stored samples.",
    )

    # -- Intake limits ----------------------------------------------------
    max_upload_bytes: int = Field(
        default=100 * _MEGABYTE,
        gt=0,
        description="Largest accepted upload. Enforced while streaming, never after.",
    )

    # -- API --------------------------------------------------------------
    api_prefix: str = Field(default="/api/v1", description="Prefix for versioned routes.")

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        level = value.upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
        if level not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}, got {value!r}")
        return level

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance.

    Cached so that configuration is read once. Tests clear the cache through the
    ``settings`` fixture rather than mutating the object.
    """
    return Settings()
