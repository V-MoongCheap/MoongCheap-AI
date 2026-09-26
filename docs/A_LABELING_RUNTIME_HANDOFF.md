# A파트 연결 실행 계약

## 흐름

```text
PostgreSQL read/write (A CronJob deployment)
  demand -> product_catalog -> category.facet
  -> TaxonomyLoader / product facet defaults
  -> Rule/Alias labeling
  -> unresolved rows only: external Model 2 Worker
  -> demand.label / demand.processed_at UPDATE
```

DB 연결정보와 Backend Endpoint가 아직 확정되지 않은 환경에서는 다음처럼
동일한 Labeling Core를 CSV로 검증한다.

```powershell
$env:PYTHONPATH = "src"
python -m moongcheap_ai.data_foundation.runtime_job `
  --input path/to/demands.csv `
  --taxonomy path/to/taxonomy.json `
  --dry-run
```

## 환경변수

- `A_DATABASE_URL`: PostgreSQL read/write DSN. `--write-db` 배포에서는
  `demand.label`과 `demand.processed_at` UPDATE 권한이 필요하다.
- `A_TAXONOMY_PATH`: 승인된 Taxonomy artifact 경로
- `A_RULES_PATH`: A 전용 입력 정책 규칙 파일 경로. 기본값은
  `config/demand_constraint_rules.json`이다.
- `A_PRODUCT_FACETS_PATH`: 선택적 Product Facet mapping artifact
- `A_BACKEND_BASE_URL`, `A_BACKEND_INTERNAL_KEY`, `A_LABEL_RESULT_ENDPOINT`:
  Backend API 제출 경로를 별도로 사용할 때만 필요한 선택 설정이다. 현재 A
  CronJob의 기본 저장 경로는 PostgreSQL 직접 UPDATE다.
- `A_BACKEND_HTTP_TIMEOUT_SECONDS`: 기본 15초
- `A_LLM_ENABLED`: 배포에서는 `true`가 필수다. `false`는 모델 런타임 없이
  로컬 Rule 회귀 테스트를 할 때만 허용한다.
- `A_LLM_MODEL`: 사용할 LLM 모델 이름. 현재 후보는
  `qwen2.5:7b-instruct` Q4다.
- `A_LLM_ENDPOINT`: 현재 표준인 Ollama `/api/generate` endpoint. Cloud develop
  설정의 기본 주소는 `http://ollama:11434`이며, 실제 배치 위치에 따라 주입
  방식은 달라질 수 있다.
- Cloud develop의 기존 `A_MODEL2_FALLBACK_*`, `A_MODEL2_OLLAMA_BASE_URL` 이름도
  과도기 호환용으로 읽지만, 새 설정의 표준 이름은 `A_LLM_*`다.
- `A_LLM_TIMEOUT_SECONDS`: LLM 요청 timeout. 기본 300초
- `A_LLM_BATCH_SIZE`: 한 번에 보낼 행 수. 기본 5
- `A_LLM_MAX_ROWS`: 한 페이지에 보낼 행 수를 제한하는 선택적 운영 설정이다.
  `0` 또는 미설정이면 미해결 행 전체를 한 실행에서 처리한다. 양수를 설정해도
  나머지 행을 버리지 않고 다음 페이지로 계속 처리한다.
- `A_LLM_RETRIES`: 배치 요청 재시도 횟수. 기본값은 `2`이며, 재시도 후에도
  실패한 배치는 더 작은 단위로 분할하여 다른 수요의 처리를 계속한다.

Model 2 통신 계약은 현재 Ollama HTTP API를 기준으로 한다.

- Method: `POST`
- Path: `/api/generate`
- Request: `model`, `prompt`, JSON `format`, `stream=false`
- Response: `response` 문자열 안의 JSON 결과
- 기본 모델: `qwen2.5:7b-instruct`

## Backend 계약

Backend API 제출 스키마는 별도 연동 경로의 초안이다. 현재 A 운영 경로는
Backend API를 거치지 않고 직접 DB에 반영한다.

- `demandId`, `catalogId`, `categoryId`
- `label`, `facetValues`, `labelStatus`, `warnings`
- `processedAt`

`--write-db` 실행에서는 AI 런타임이 DB에 직접 UPDATE한다. 따라서 Cloud는
`A_DATABASE_URL`에 해당 권한을 가진 Secret을 주입해야 한다. Backend API 제출
경로를 채택하는 경우에만 위의 Backend 계약과 내부 인증 키가 필요하다.

## Kubernetes/운영 원칙

- CronJob은 배치 1회 실행 후 종료한다.
- Taxonomy와 Product Facet artifact는 버전 경로로 마운트한다.
- DB URL은 Secret으로 주입한다. Backend API 경로를 사용할 때만 Internal Key도
  추가로 주입한다.
- API 호출은 설정된 횟수만큼 재시도한다. 그래도 실패하면 배치를 반으로
  분할하여 재시도하고, 단일 수요까지 실패한 행만 `FAILED/REVIEW`로 남긴다.
- 모델 사용은 필수지만, A Pod 내부 실행·sidecar·별도 LLM Worker 중 배치 방식은
  아직 미정이다. 현재 A 이미지에는 모델 가중치나 Ollama가 포함되어 있지 않으므로,
  A 이미지에 포함하는 방식을 선택하면 Dockerfile과 리소스 계약을 추가로 갱신해야 한다.
- Rule이 이미 처리한 행은 LLM으로 덮어쓰지 않는다. `REVIEW`/`CONFLICT`/
  `PASSTHROUGH`/`LABELED_WITH_REVIEW` 행만 LLM 후보로 보낸다.
- LLM 결과는 Taxonomy에 존재하는 Facet/Value를 모두 반환하고, 비어 있지 않은 요구사항을 `ALL`로 만들지 않을 때만 적용한다.
- 부정 표현은 Rule Parser가 담당하며 LLM은 부정 조건을 최종 확정하지 않는다.
- `.env`, API Key, Raw Review, 생성 산출물은 Git에 올리지 않는다.
