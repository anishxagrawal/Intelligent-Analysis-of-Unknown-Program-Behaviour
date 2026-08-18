"""AC-S5: settings load defaults, and environment variables override them."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings, get_settings

pytestmark = pytest.mark.unit


def test_defaults_are_sensible() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.test_database_url is None
    assert settings.max_upload_bytes == 100 * 1024 * 1024
    assert settings.api_prefix == "/api/v1"
    assert settings.is_production is False


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPA_ENVIRONMENT", "production")
    monkeypatch.setenv("UPA_LOG_LEVEL", "warning")
    monkeypatch.setenv("UPA_MAX_UPLOAD_BYTES", "2048")
    monkeypatch.setenv("UPA_STORAGE_ROOT", "somewhere/else")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.environment == "production"
    assert settings.log_level == "WARNING"  # normalised to upper case
    assert settings.max_upload_bytes == 2048
    assert settings.storage_root == Path("somewhere/else")
    assert settings.is_production is True


def test_log_level_is_validated() -> None:
    with pytest.raises(ValueError, match="log_level must be one of"):
        Settings(_env_file=None, log_level="chatty")  # type: ignore[call-arg]


def test_max_upload_bytes_must_be_positive() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, max_upload_bytes=0)  # type: ignore[call-arg]


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
