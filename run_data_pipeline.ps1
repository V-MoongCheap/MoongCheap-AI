param([ValidateSet("all", "inspect", "catalog", "mfds", "facet")][string]$Stage = "all")
$ErrorActionPreference = "Stop"
$env:PYTHONPATH = Join-Path $PSScriptRoot "src"
python -m moongcheap_ai.pipeline --root $PSScriptRoot --stage $Stage
