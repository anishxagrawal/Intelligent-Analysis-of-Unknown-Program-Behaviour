"""AC-S2: the test harness collects and runs."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_harness_runs() -> None:
    assert True


def test_app_package_is_importable() -> None:
    import app

    assert app is not None


async def test_async_tests_run() -> None:
    """pytest-asyncio is configured in auto mode, so this needs no decorator.

    Version 1 depends entirely on async tests working, so prove it here where
    there is nothing else that could be at fault.
    """
    assert True
