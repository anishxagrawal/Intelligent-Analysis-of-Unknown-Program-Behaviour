#!/usr/bin/env bash
# Lint and type-check.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m ruff check .
python -m mypy app
