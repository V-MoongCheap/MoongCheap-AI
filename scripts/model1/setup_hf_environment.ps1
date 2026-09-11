param(
    [string]$Python = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python executable not found: $Python"
}

& $Python -m pip install -r .\requirements-model1-hf.txt
& $Python -c "import torch, transformers, accelerate, huggingface_hub; print('torch=' + torch.__version__); print('transformers=' + transformers.__version__); print('accelerate=' + accelerate.__version__); print('huggingface_hub=' + huggingface_hub.__version__)"

Write-Output "Hugging Face runtime is ready. Model weights download on first model run."
