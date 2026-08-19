# Run the full test suite with the coverage gate.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
python -m pytest --cov=app --cov-report=term-missing @args
