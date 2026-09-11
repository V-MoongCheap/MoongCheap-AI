param(
    [switch]$WithModel1Hf
)

$ErrorActionPreference = "Stop"
$python = ".\.venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    py -3.12 -m venv .venv
}

& $python -m pip install --upgrade pip
& $python -m pip install -r requirements-dev.txt

if ($WithModel1Hf) {
    & $python -m pip install -r requirements-model1-hf.txt
}

& $python -m pip check
Write-Output "Environment ready. Activate with: .\.venv\Scripts\Activate.ps1"
