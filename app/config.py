"""Application settings.

Every setting is read from the environment, with defaults suitable for local
development. Environment variables use the ``UPA_`` prefix so they cannot collide
with unrelated variables on the host.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
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
    storage_backend: Literal["local", "memory"] = Field(
        default="local",
        description="Where samples are kept. 'memory' is for tests only.",
    )
    storage_root: Path = Field(
        default=Path("var/samples"),
        description="Directory holding stored samples when using the local backend.",
    )
    sample_encryption_key: str | None = Field(
        default=None,
        description=(
            "Base64-encoded 32-byte key used to encrypt stored samples. "
            "Required in production; a fixed development key is used otherwise."
        ),
    )
    sample_encryption_key_id: str = Field(
        default="dev",
        description="Identifier recorded with each encrypted object, so keys can rotate.",
    )

    # -- Intake limits ----------------------------------------------------
    max_upload_bytes: int = Field(
        default=100 * _MEGABYTE,
        gt=0,
        description="Largest accepted upload. Enforced while streaming, never after.",
    )

    # -- Job queue --------------------------------------------------------
    job_lease_seconds: int = Field(
        default=300,
        gt=0,
        description=(
            "How long a worker owns a claimed job before the lease lapses. "
            "Must comfortably exceed the heartbeat interval, or healthy workers "
            "lose jobs they are still working on."
        ),
    )
    job_max_attempts: int = Field(
        default=3,
        gt=0,
        description=(
            "How many times a job may be handed out before it is cancelled. "
            "Without a limit, a job that kills every worker it touches is retried forever."
        ),
    )
    reaper_interval_seconds: float = Field(
        default=30.0,
        gt=0,
        description="How often the reaper looks for lapsed leases.",
    )
    worker_poll_seconds: float = Field(
        default=2.0,
        gt=0,
        description="How long a worker waits before asking for work again when the queue is empty.",
    )
    run_reaper: bool = Field(
        default=True,
        description=(
            "Run the lease reaper alongside the API. On by default: a reaper that has to be "
            "started separately is a reaper that eventually is not, and abandoned jobs then "
            "pile up with nothing reporting it."
        ),
    )

    # -- Access control ---------------------------------------------------
    rate_limit_per_minute: int = Field(
        default=120,
        gt=0,
        description="Requests allowed per API key per minute, refilled continuously.",
    )
    rate_limit_burst: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Largest burst a key may spend at once. Defaults to the per-minute rate, "
            "which lets a caller flush a backlog without averaging above the limit."
        ),
    )
    bootstrap_api_key: str | None = Field(
        default=None,
        description=(
            "If set, an API key with every scope is created at startup with this token. "
            "For development and for the first key in a new deployment. Refused in production, "
            "where keys are issued with scripts/create-api-key.py instead."
        ),
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

    @model_validator(mode="after")
    def _require_encryption_key_in_production(self) -> Settings:
        """Refuse to start in production without a real key.

        The development fallback is derived from a constant in the source, so it
        is public knowledge. Falling back to it in production would mean samples
        that look encrypted but are readable by anyone with the repository.
        """
        if self.is_production and not self.sample_encryption_key:
            raise ValueError(
                "UPA_SAMPLE_ENCRYPTION_KEY must be set when UPA_ENVIRONMENT=production."
            )
        return self

    @model_validator(mode="after")
    def _refuse_bootstrap_key_in_production(self) -> Settings:
        """A credential in an environment variable is not a production credential.

        It appears in process listings, in orchestrator manifests and in shell
        history, and it is the same value on every instance. Convenient in
        development, and exactly the kind of shortcut that survives into
        production if nothing refuses it.
        """
        if self.is_production and self.bootstrap_api_key:
            raise ValueError(
                "UPA_BOOTSTRAP_API_KEY must not be set when UPA_ENVIRONMENT=production. "
                "Issue keys with scripts/create-api-key.py instead."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance.

    Cached so that configuration is read once. Tests clear the cache through the
    ``settings`` fixture rather than mutating the object.
    """
    return Settings()
