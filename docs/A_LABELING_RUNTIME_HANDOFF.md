# A파트 연결 실행 계약

## 흐름

```text
PostgreSQL read/write (A 전용 최소 권한 계정)
  demand -> product_catalog -> category.facet
  -> category.facet JSON -> TaxonomyLoader / product facet defaults
  -> demand.label + demand.processed_at
```

운영 DB에서는 `category.facet` 전체 문자열을 Python에서 JSON parsing하여
Category별 Taxonomy를 구성한다. DB의 JSON 내부 값으로 WHERE 조건을 걸지 않는다.
DB 연결정보가 아직 확정되지 않은 환경에서는 다음처럼 동일한 Labeling Core를 CSV로 검증한다.

```powershell
$env:PYTHONPATH = "src"
python -m moongcheap_ai.data_foundation.runtime_job `
  --input path/to/demands.csv `
  --taxonomy path/to/taxonomy.json `
  --dry-run
```

## 환경변수

- `A_DATABASE_URL`: PostgreSQL DSN. 직접 저장 모드에서는 read/write session으로 연결한다.
- `A_TAXONOMY_PATH`: CSV/dry-run 또는 DB의 `category.facet`을 사용할 수 없는 fallback 환경에서 사용하는 승인된 Taxonomy artifact 경로
- `A_PRODUCT_FACETS_PATH`: 선택적 Product Facet mapping artifact
- `A_WRITE_DATABASE`: `true`이면 A가 PostgreSQL에 직접 결과 저장
- `A_BACKEND_BASE_URL`: 기존 API 제출 호환 모드에서만 사용
- `A_BACKEND_INTERNAL_KEY`: 기존 API 제출 호환 모드에서만 사용
- `A_LABEL_RESULT_ENDPOINT`: 기존 API 제출 호환 모드에서만 사용
- `A_BACKEND_HTTP_TIMEOUT_SECONDS`: 기본 15초

## Backend 계약

기존 Backend 제출 스키마는 `demand-label-result.v0.1` 초안이다. 현재 A 운영 방향은
Backend API 제출이 아니라 `--write-db` 또는 `A_WRITE_DATABASE=true`를 통한 직접 DB 저장이다.
API 제출 모드는 계약 호환성 검증용으로만 유지한다.

- `demandId`, `catalogId`, `categoryId`
- `label`, `facetValues`, `labelStatus`, `warnings`
- `processedAt`

AI 런타임은 A 전용 DB 계정으로 `demand.label`과 `demand.processed_at`만 UPDATE한다.
원본 Demand 생성과 비즈니스 상태 전이는 Backend가 소유한다.

## Kubernetes/운영 원칙

- CronJob은 배치 1회 실행 후 종료한다.
- Taxonomy와 Product Facet artifact는 버전 경로로 마운트한다.
- DB URL와 DB 계정/비밀번호는 Secret으로 주입한다.
- API 호출 실패 시 임의 재시도하지 않고 다음 배치에서 미처리 수요를 재조회한다.
- `.env`, API Key, Raw Review, 생성 산출물은 Git에 올리지 않는다.
