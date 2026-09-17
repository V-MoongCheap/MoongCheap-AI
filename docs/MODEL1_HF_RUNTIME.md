# Model 1 Hugging Face Runtime

The base project does not install a model runtime. Install the optional runtime only when running Model 1 with `--provider transformers`.

## Install

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-model1-hf.txt
.\.venv\Scripts\python.exe scripts\model1\check_hf_environment.py
```

The PowerShell helper is equivalent:

```powershell
scripts\model1\setup_hf_environment.ps1
```

## Model cache and authentication

Set `HF_HOME` to a local cache directory when the default user cache is not suitable. `HF_TOKEN` is needed only for gated or private models. Never commit either value.

```powershell
$env:HF_HOME = ".hf-cache"
$env:HF_TOKEN = "<token only when required>"
```

Public models do not require a token. Model weights are downloaded on first use and are not part of the repository.

## Run a small comparison

Kanana는 현재 Model 1의 선택된 후보 생성 보조 모델이다. 아래 다른 모델들은 비교·재현 실험용 후보이며 자동으로 운영 모델로 승격되지 않는다.

```powershell
$env:PYTHONPATH = "src;."

python scripts\model1\run_multisource_facet_discovery.py `
  --provider transformers `
  --models "yanolja/YanoljaNEXT-EEVE-Instruct-7B-v2-Preview" `
  --smoke-only `
  --max-products-per-category 4 `
  --max-sellers-per-category 4 `
  --max-queries-per-category 2 `
  --batch-size 8 `
  --output-dir data\processed\model1_eeve7b_smoke
```

비교 후보를 실행하려면 `--models`를 다음처럼 바꾼다:

```text
naver-hyperclovax/HyperCLOVAX-SEED-Text-Instruct-1.5B
```

Do not download several large models at once. Run one model, preserve its output directory, and compare schema pass rate, evidence validity, forbidden facet rate, Korean normalization quality, and runtime.

## Kimi candidates

Kimi를 일괄 제외하지 않는다. 현재 로컬 비교 후보는 공식 Moonshot의
`moonshotai/Moonlight-16B-A3B-Instruct`이며, 총 16B/활성 약 3B인 MoE 모델이다.
24GB Apple Silicon에서는 원본 BF16을 기본 경로로 사용하지 않고,
`mlx-community/Moonlight-16B-A3B-Instruct-4-bit` 같은 4-bit MLX 양자화판을
별도 `mlx-lm` 환경에서 검토한다. 양자화판은 변환/배포 주체가 공식 Moonshot이
아닐 수 있으므로 출처와 변환 정보를 결과에 기록한다.

Kimi-K2/K2.6/K3 등 초대형 계열은 현재 Mac 로컬 후보에서 제외한다. Kimi-VL은
멀티모달 모델이므로 텍스트 전용 Facet/Label 기본 비교에서는 제외한다.

Kimi API나 GPU 서버를 사용할 경우에는 정확한 모델 ID와 endpoint를 제공받아
별도 provider로 테스트한다. API key는 환경변수로만 전달하고 저장된 명령,
리포트, Git에 포함하지 않는다.

## Candidate-specific environment

The base project environment uses Transformers 4.x for the normal Model 1 runtime. The following locally cached candidates require Transformers 5.x remote-code compatibility:

- `LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct`
- `sh-024/LFM2.5-1.2B-Instruct-Korean`

Create a separate Python 3.12 environment for these candidates:

```bash
python3.12 -m venv .venv-model-lfm
.venv-model-lfm/bin/python -m pip install -r requirements-model1-hf-v5.txt
TOKENIZERS_PARALLELISM=false .venv-model-lfm/bin/python \
  scripts/model1/run_hf_candidate_smoke.py \
  --model LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct \
  --model sh-024/LFM2.5-1.2B-Instruct-Korean
```

This environment is optional and must not replace the base project environment. The smoke script checks loading and bounded generation only; it does not establish model quality.

## Kanana on Transformers 4

Kanana는 Transformers 5 환경에서 실행하지 않는다. 기존 Transformers 4 계열
환경에서 별도 실행한다.

```bash
python3.12 -m venv --system-site-packages .venv-model-kanana
.venv-model-kanana/bin/python -m pip install -r requirements-model1-hf.txt
TOKENIZERS_PARALLELISM=false .venv-model-kanana/bin/python \
  scripts/model1/run_hf_candidate_smoke.py \
  --model kakaocorp/kanana-nano-2.1b-instruct
```

MPS 여부는 환경별로 `torch.backends.mps.is_available()`를 별도 확인한다.
현재 검증에서는 Transformers 4.57.6에서 모델 로드와 64-token 생성이
성공했으며, 해당 실행 환경에서는 MPS가 노출되지 않아 CPU로 동작했다.
