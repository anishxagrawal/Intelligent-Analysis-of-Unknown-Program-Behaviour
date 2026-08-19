#!/usr/bin/env bash
# Run the full test suite with the coverage gate.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pytest --cov=app --cov-report=term-missing "$@"
