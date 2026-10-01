# A파트 연결 실행 계약

## 흐름

```text
PostgreSQL read/write (A CronJob deployment)
  demand -> product_catalog -> category.facet
  -> backend_catalog_id keyed product Facet mapping artifact
  -> exact category/taxonomy and complete product profile validation
  -> original product Facet baseline
  -> stable positive demand constraints override matching Facets
  -> unresolved rows only: external Model 2 Worker
  -> demand.label / demand.processed_at UPDATE
```

Each pending Demand starts from the Facet values in the explicit product mapping
artifact for its actual Backend `catalog_id`, carried in the distinct
`backend_catalog_id` column. The map's `category_id` must match
the key used by the corresponding `category.facet` Taxonomy, and it must include
one row per Taxonomy Facet. `MAPPED` values are validated against that Taxonomy;
`UNKNOWN` is distinct from `ALL` and cannot be encoded by the current numeric
label contract. A profile with an unknown Facet therefore remains unprocessed;
it must not be converted to `ALL`. Missing, conflicting, incomplete, or
taxonomy-incompatible profiles remain unprocessed;
the runtime does not infer product Facets from product name or description. A
stable positive `MUST`/`PREFER` interpretation overrides only its own Facet.
Empty requirements, parser/model failure, ambiguous input, and explicit
exclusions retain the original product baseline.

This baseline is not a consumer preference: it represents the original
selected product. `label_source` in the local run output distinguishes
`PRODUCT_DEFAULT`, `PRODUCT_DEFAULT_PLUS_DEMAND`, and
`PRODUCT_DEFAULT_PLUS_LLM`; it is diagnostic and is not persisted to Backend.
The lower-level `run_part_a_batch` parser helper emits typed consumer
constraints only: its `label`, `facet_values`, and `processed_at` remain empty.
Only `runtime_job.run_batch`, after joining and validating the original-product
profile, produces a final Backend-writable label.

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
- `A_PRODUCT_FACETS_PATH`: 필수 Product Facet mapping CSV 경로. 실제 Backend
  `product_catalog.id`만 `backend_catalog_id` 컬럼에 넣고, Taxonomy의 `category_id`,
  모든 Facet별 `mapping_status`와 `value`를 포함한다. 배치 입력의 상품 ID를
  Seed/source ID로 추정하지 않는다. 예시 컬럼 계약은
  `backend_catalog_id,category_id,facet_name,mapping_status,value,value_code`다.
  `MAPPED`는 Taxonomy의 0보다 큰 값과 일치해야 한다. `UNKNOWN`은 `ALL`과
  다르며 현재 numeric label로 표현할 수 없으므로 해당 Demand 처리를 보류한다.
  같은 Facet의 중복·상충 행도 저장을 보류한다.
- `A_RULES_PATH`: A 전용 입력 정책 규칙 파일 경로. 기본값은
  `config/demand_constraint_rules.json`이다.
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
  `A_LLM_ENABLED=true` 또는 `A_MODEL2_FALLBACK_ENABLED=true`일 때 확인한다. 모델이
  없거나 Ollama에 연결할 수 없으면 LLM만 비활성화하고, 유효한 상품 Facet profile이 있는
  Demand는 그 기본값으로 Labeling을 계속한다. 설정 오류인 0 이하 timeout은 실패 처리한다.
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
- 운영에서는 DB `category.facet`과 실제 Backend `product_catalog.id`에 매핑된 Product Facet
  artifact를 함께 사용한다. Artifact는 taxonomy와 같은 버전 release로 공급해야 한다.
  현재 Docker image에는 이 데이터 파일이 포함되어 있지 않으므로, Cloud/build 입력에서
  `/artifacts/product_facets.csv`를 공급하기 전까지 비어 있지 않은 배치는 fail-closed된다.
- DB URL은 Secret으로 주입한다. Backend API 경로를 사용할 때만 Internal Key도
  추가로 주입한다.
- Model 2 호출은 설정된 횟수만큼 재시도한다. 그래도 실패하면 배치를 반으로
  분할한다. 단일 수요까지 실패하더라도 유효한 원상품 Facet 기본값을 저장하고,
  LLM 진단은 로컬 결과 파일에 남긴다.
- 배포에서 Model 2 보조를 켤 때 A는 설정된 Ollama HTTP endpoint를 호출한다.
  A 이미지에는 모델 가중치나 Ollama가 포함되지 않는다. 이 계약은 별도 Worker를
  필수 아키텍처로 지정하지 않으며, Ollama의 배치·수명주기는 Cloud 배포 설정을 따른다.
- 모델은 파서가 명확하게 처리하지 못한 비어 있지 않은 긍정 후보만 보조한다.
  명시적 제외·충돌·부정·대조·대안 또는 같은 Facet의 복수값은 모델로 재해석하지 않고
  상품 기본 Facet을 유지한다.
- 모델 결과는 Category Taxonomy의 Facet key 전체를 정확히 포함해야 한다. 선택한 각
  Value/alias가 원문에 있어야 하며, 한 Facet에서 여러 Value가 언급되거나 결과 ID/key,
  JSON이 잘못되면 적용하지 않는다. 모델이 반환한 `ALL`은 상품 기본값을 지우지 않으며,
  검증된 양성 Value만 해당 Facet 기본값을 덮어쓴다.
- 압축 `label`에는 긍정 `MUST`/`PREFER` 값만 인코딩한다. `EXCLUDE`는 typed constraints에
  보존하지만, 제외 대상을 긍정 label 코드로 저장하지 않는다.
- Cloud ConfigMap이 기존 호환 변수만 사용하는 경우에는
  `A_MODEL2_FALLBACK_ENABLED=true`도 함께 공급해야 한다. 해당 값이 `false`이면
  fallback과 모델 preflight가 모두 비활성화되고, 소비자 요구조건 파싱과
  원상품 기본 Facet 초기값을 결합한 결과로 실행된다.
- `.env`, API Key, Raw Review, 생성 산출물은 Git에 올리지 않는다.
