# Development Environment

The repository supports a small base environment and an optional Model 1 Hugging Face environment.

## Windows

From the repository root:

```powershell
.\scripts\setup_environment.ps1
```

To install the optional Transformers runtime as well:

```powershell
.\scripts\setup_environment.ps1 -WithModel1Hf
```

## macOS/Linux

```bash
bash scripts/setup_environment.sh
```

With Hugging Face support:

```bash
WITH_MODEL1_HF=1 bash scripts/setup_environment.sh
```

The base setup includes the dependencies required by the full test suite, including `jsonschema` and `PyYAML`. The Hugging Face option adds PyTorch, Transformers, Accelerate, and related packages; model weights are still downloaded only when a model is first run.

After setup:

```bash
python -m pytest -q
```

On Windows, use `.venv\\Scripts\\python.exe -m pytest -q` if the virtual environment is not activated.
