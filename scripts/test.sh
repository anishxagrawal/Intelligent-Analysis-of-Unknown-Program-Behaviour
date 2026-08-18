#!/usr/bin/env bash
# Run the full test suite.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pytest "$@"
