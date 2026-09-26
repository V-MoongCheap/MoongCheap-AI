# Backend `product_catalog` Export 연동

## 확인된 Export

`result.csv`는 Backend의 실제 `product_catalog` Export로 확인되었다.

- 행 수: 1,989
- 컬럼: `id`, `name`, `spec_summary`, `list_price`, `thumbnail_url`, `description`, `status`, `created_at`, `updated_at`
- `id`: 1990~3978
- 기존 AI canonical catalog 1,989건과 상품명 기준 전건 매칭
- `category_id` 컬럼은 없음

## 생성 명령

```bash
PYTHONPATH=src .venv/bin/python \
  scripts/data/build_backend_catalog_mapping.py \
  --backend-export /path/to/result.csv \
  --canonical-seed data/processed/backend_seed_v5/product_catalog_seed_v5.csv \
  --output-dir data/processed/backend_catalog_mapping_v1
```

생성 파일:

- `backend_catalog_id_mapping_v1.csv`: Backend 실제 `product_catalog.id`와 AI canonical 상품 연결
- `backend_catalog_id_mapping_v1.json`: 건수·매칭 방식·제약 보고서

## 중요한 제한

이 Export에는 `category_id`가 없으므로 `category_key` 또는 AI seed의
`source_category_id`를 Backend `category.id`로 사용하지 않는다. 숫자 범위나
상품명으로 Category ID를 추측하는 것도 금지한다.

따라서 이 파일로 해결되는 범위는:

- B/C 입력의 `catalog_id`를 Backend 실제 ID로 변환
- Product Facet mapping의 catalog ID 연결
- AI 산출물과 Backend 도감의 상품 계보 연결

다음은 별도 Backend `category` Export 또는 `product_catalog.id → category.id`
Mapping이 필요하다.

- A Labeling에서 실제 DB `category.facet` 조회
- Backend Category ID 기준 Taxonomy 연결
- `A_CATALOG_CATEGORY_MAP_PATH` 운영 파일 완성
