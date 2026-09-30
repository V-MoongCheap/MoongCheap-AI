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
- `A_LLM_ENABLED`: Model 2 보조를 활성화할 때 `true`로 설정한다. 기존 Cloud 호환 변수인
  `A_MODEL2_FALLBACK_ENABLED=true`도 지원한다. 두 설정이 모두 꺼져 있으면 Rule/Alias만 실행한다.
- `A_LLM_MODEL`: 사용할 LLM 모델 이름. 현재 후보는
  `qwen2.5:7b-instruct` Q4다.
- `A_LLM_ENDPOINT`: 현재 표준인 Ollama `/api/generate` endpoint. Cloud develop
  설정의 기본 주소는 `http://ollama:11434`이며, 실제 배치 위치에 따라 주입
  방식은 달라질 수 있다.
- Cloud develop의 기존 `A_MODEL2_FALLBACK_*`, `A_MODEL2_OLLAMA_BASE_URL` 이름도
  과도기 호환용으로 읽지만, 새 설정의 표준 이름은 `A_LLM_*`다.
- `A_LLM_TIMEOUT_SECONDS`: LLM 요청 timeout. 기본 300초
- `A_LLM_PREFLIGHT_TIMEOUT_SECONDS`: 배치 시작 시 `/api/tags` 모델 존재 확인 timeout. 기본 10초.
  `A_LLM_ENABLED=true` 또는 `A_MODEL2_FALLBACK_ENABLED=true`이면 모델이 없을 때 DB를
  조회·수정하지 않고 실패 종료한다. 따라서 다음 CronJob에서 같은 미처리 Demand를 재시도한다.
- `A_LLM_BATCH_SIZE`: 한 번에 보낼 행 수. 기본 5
- `A_LLM_MAX_ROWS`: 한 페이지에 보낼 행 수를 제한하는 선택적 운영 설정이다.
  `0` 또는 미설정이면 미해결 행 전체를 한 실행에서 처리한다. 양수를 설정해도
  나머지 행을 버리지 않고 다음 페이지로 계속 처리한다.
- `A_LLM_RETRIES`: 배치 요청 재시도 횟수. 기본값은 `2`이며, 재시도 후에도
  실패한 배치는 더 작은 단위로 분할하여 다른 수요의 처리를 계속한다.

`--write-db`로 Backend PostgreSQL을 직접 읽는 운영 경로에서는 Reader가 함께
조회한 `category.facet` TEXT(JSON 문자열)로 Taxonomy를 메모리에서 구성한다.
따라서 이 경로는 로컬 Taxonomy 파일이 없어도 동작하며, 이미지에는 Rule 파일과
B 호환 Alias 파일(`config/demand_constraint_aliases.json`)을 함께 포함해야 한다.
CSV dry-run 또는 고정 Artifact 검증에서는 `A_TAXONOMY_PATH`를 사용한다.

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
- 배포에서 Model 2 보조를 켤 때 A는 설정된 Ollama HTTP endpoint를 호출한다.
  A 이미지에는 모델 가중치나 Ollama가 포함되지 않는다. 이 계약은 별도 Worker를
  필수 아키텍처로 지정하지 않으며, Ollama의 배치·수명주기는 Cloud 배포 설정을 따른다.
- Rule이 처리한 행은 LLM으로 덮어쓰지 않는다. 모델 후보는 unresolved positive 요청에
  한정하며, 명시적 제외·충돌·부정·대조·대안 표현은 모델에 보내지 않고 검토 상태로 둔다.
- A 전용 정책은 같은 Facet의 서로 다른 값이 여러 개 등장하는 요구를 자동 확정하지 않는다.
  해석을 label 하나로 표현할 수 없는 문장은 `MULTIPLE_VALUES_SAME_FACET_UNRESOLVED`로 `REVIEW`에 두고,
  `processed_at`을 기록하지 않아 이후 재처리 가능하게 한다.
- 현재 DB 계약에는 A의 영속 보류/격리 상태가 없다. 따라서 `REVIEW`는 다음 배치에서도 읽힌다.
  사람 검수 없이 운영할 경우 반복 조회를 막을 별도 AI 처리상태 저장소가 필요하며, 의미 손실을 막기 위해
  이를 `ALL` label 완료로 대체하지 않는다.
- 모델 결과는 Category Taxonomy의 Facet key 전체를 정확히 포함해야 한다. 선택한 각
  Value/alias가 원문에 있어야 하며, 한 Facet에서 여러 Value가 언급되거나 결과 ID/key,
  JSON이 잘못되면 적용하지 않는다. 비어 있지 않은 요구사항을 전부 `ALL`로 만드는 결과도
  적용하지 않는다.
- 압축 `label`에는 긍정 `MUST`/`PREFER` 값만 인코딩한다. `EXCLUDE`는 typed constraints에
  보존하지만, 제외 대상을 긍정 label 코드로 저장하지 않는다.
- Cloud ConfigMap이 기존 호환 변수만 사용하는 경우에는
  `A_MODEL2_FALLBACK_ENABLED=true`도 함께 공급해야 한다. 해당 값이 `false`이면
  fallback과 모델 preflight가 모두 비활성화되어 Rule-only로 실행된다.
- `.env`, API Key, Raw Review, 생성 산출물은 Git에 올리지 않는다.
