# Lint and type-check.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
python -m ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m mypy app
