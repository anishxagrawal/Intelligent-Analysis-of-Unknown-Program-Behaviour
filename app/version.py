"""Version constants.

These are deliberately trivial today. Version 5 stamps every analysis report with
exactly these values, so that a verdict produced months ago can still be traced
back to the code, schema and configuration that produced it. Keeping them in one
module from the very start means provenance never has to be retrofitted.
"""

from __future__ import annotations

#: Version of the application code.
APP_VERSION = "0.1.0"

#: Version of the database schema. Bump whenever a migration changes meaning,
#: not merely whenever a migration is added.
SCHEMA_VERSION = "1"

#: Version of the configuration contract. Bump when a setting is added, removed
#: or changes its interpretation.
CONFIG_VERSION = "1"


def provenance() -> dict[str, str]:
    """Return the version triple recorded on every job and report."""
    return {
        "app_version": APP_VERSION,
        "schema_version": SCHEMA_VERSION,
        "config_version": CONFIG_VERSION,
    }
