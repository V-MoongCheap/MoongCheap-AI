# A파트 연결 실행 계약

## 흐름

```text
PostgreSQL read-only
  demand -> product_catalog -> category.facet
  -> TaxonomyLoader / product facet defaults
  -> demand label + facet_values
  -> Backend internal API
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

- `A_DATABASE_URL`: PostgreSQL DSN. 런타임은 read-only session으로 연결한다.
- `A_TAXONOMY_PATH`: 승인된 Taxonomy artifact 경로
- `A_PRODUCT_FACETS_PATH`: 선택적 Product Facet mapping artifact
- `A_BACKEND_BASE_URL`: Backend base URL
- `A_BACKEND_INTERNAL_KEY`: 배포 환경에서 주입하는 내부 API Secret
- `A_LABEL_RESULT_ENDPOINT`: Backend와 합의한 라벨 결과 Endpoint. 임의 기본값을 두지 않는다.
- `A_BACKEND_HTTP_TIMEOUT_SECONDS`: 기본 15초

## Backend 계약

현재 제출 스키마는 `demand-label-result.v0.1` 초안이다. 실제 Backend API가
확정되기 전까지는 `--dry-run`만 사용한다.

- `demandId`, `catalogId`, `categoryId`
- `label`, `facetValues`, `labelStatus`, `warnings`
- `processedAt`

AI 런타임은 DB에 직접 UPDATE하지 않는다. Backend가 결과를 검증하고 상태를
반영하는 Endpoint를 소유해야 한다.

## Kubernetes/운영 원칙

- CronJob은 배치 1회 실행 후 종료한다.
- Taxonomy와 Product Facet artifact는 버전 경로로 마운트한다.
- DB URL와 Internal Key는 Secret으로 주입한다.
- API 호출 실패 시 임의 재시도하지 않고 다음 배치에서 미처리 수요를 재조회한다.
- `.env`, API Key, Raw Review, 생성 산출물은 Git에 올리지 않는다.
