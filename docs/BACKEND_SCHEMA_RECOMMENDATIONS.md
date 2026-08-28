# Backend Schema Recommendations

이번 작업에서는 DB Migration을 수행하지 않습니다. 현재 ERD와 외부 Product Source를 비교했을 때 다음 보완이 필요합니다.

1. `product_catalog.thumbnail_url`은 원천 데이터에 이미지가 없을 수 있으므로 nullable 또는 명시적인 placeholder 정책이 필요합니다.
2. Barcode와 외부 Product ID는 Product Identity Resolution에 필요합니다. `product_catalog_source` 같은 provenance 테이블을 권장합니다.
3. KAN Code와 외부 Category Code/Path는 `category_source_mapping`으로 관리하는 편이 안전합니다.
4. AI-Hub/MFDS 원본은 AI 저장소가 DB에 직접 넣지 않고 staging 및 검수 산출물로 전달합니다.

제안 테이블은 다음 정보를 포함할 수 있습니다.

```text
product_catalog_source
- id
- catalog_id
- source
- external_product_id
- barcode
- source_category_code
- source_url
- created_at
- updated_at
```
