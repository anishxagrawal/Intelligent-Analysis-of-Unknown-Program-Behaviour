"""Shared test fixtures.

Version 0 needs very little here. The settings fixture exists now because
``get_settings`` is cached, and tests that change the environment must clear that
cache or they will silently read stale configuration.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Ensure no test inherits settings cached by an earlier one."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pointing entirely at a temporary directory."""
    return Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        storage_root=tmp_path / "samples",
    )
