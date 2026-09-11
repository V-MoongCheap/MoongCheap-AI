# Model 1 Hugging Face Runtime

The base project does not install a model runtime. Install the optional runtime only when running Model 1 with `--provider transformers`.

## Install

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .git_upload_workspace\requirements-model1-hf.txt
.\.venv\Scripts\python.exe .git_upload_workspace\scripts\model1\check_hf_environment.py
```

The PowerShell helper is equivalent:

```powershell
.git_upload_workspace\scripts\model1\setup_hf_environment.ps1
```

## Model cache and authentication

Set `HF_HOME` to a local cache directory when the default user cache is not suitable. `HF_TOKEN` is needed only for gated or private models. Never commit either value.

```powershell
$env:HF_HOME = "F:\hf-cache"
$env:HF_TOKEN = "<token only when required>"
```

Public models do not require a token. Model weights are downloaded on first use and are not part of the repository.

## Run a small comparison

The following models are candidates, not an automatic production choice:

```powershell
$env:PYTHONPATH = "F:\kt\kt\integration_project\.git_upload_workspace\src;F:\kt\kt\integration_project\.git_upload_workspace"

python .git_upload_workspace\scripts\model1\run_multisource_facet_discovery.py `
  --provider transformers `
  --models "yanolja/YanoljaNEXT-EEVE-Instruct-7B-v2-Preview" `
  --smoke-only `
  --max-products-per-category 4 `
  --max-sellers-per-category 4 `
  --max-queries-per-category 2 `
  --batch-size 8 `
  --output-dir .git_upload_workspace\data\processed\model1_eeve7b_smoke
```

For another candidate, replace `--models` with:

```text
naver-hyperclovax/HyperCLOVAX-SEED-Text-Instruct-1.5B
```

Do not download several large models at once. Run one model, preserve its output directory, and compare schema pass rate, evidence validity, forbidden facet rate, Korean normalization quality, and runtime.

## Kimi and OpenAI-compatible providers

Kimi is not installed by this runtime. It should be tested through an official API or a GPU inference server using the exact model ID and endpoint supplied by the provider. Put the API key in an environment variable and pass only the variable name with `--api-key-env`; never put the key in a command saved to a file, report, or Git.
