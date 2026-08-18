"""AC-S7: version constants exist and are non-empty strings."""

from __future__ import annotations

import pytest

from app.version import APP_VERSION, CONFIG_VERSION, SCHEMA_VERSION, provenance

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "constant",
    [APP_VERSION, SCHEMA_VERSION, CONFIG_VERSION],
)
def test_constants_are_non_empty_strings(constant: str) -> None:
    assert isinstance(constant, str)
    assert constant.strip()


def test_provenance_carries_all_three_versions() -> None:
    stamp = provenance()

    assert stamp == {
        "app_version": APP_VERSION,
        "schema_version": SCHEMA_VERSION,
        "config_version": CONFIG_VERSION,
    }
