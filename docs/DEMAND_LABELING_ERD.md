# ERD 기준 Demand Labeling

Backend의 `demand`에는 별도 `category_id`가 없으므로 다음 경로로 Facet을 조회합니다.

```text
demand.catalog_id -> product_catalog.id -> product_catalog.category_id -> category.facet
```

AI 파트는 category ID를 새로 만들거나 KAN 코드를 Backend PK로 저장하지 않습니다. Backend `product_catalog` export를 `--catalog`로 전달할 때 `id`와 `category_id`가 모두 있어야 합니다.

## 현재 DB 없는 로컬 실행

PostgreSQL 연결과 인증키가 없어도 Labeling Core는 실행할 수 있습니다. 현재는
Demand CSV에 `category_id`가 있으면 그것을 사용하고, 없으면 선택적으로 전달한
Catalog CSV의 `catalog_id -> category_id` 매핑을 사용합니다. DB 조회·갱신은 하지 않습니다.

```powershell
$env:PYTHONPATH = "src"
python scripts/labeling/label_demands.py `
  --input data/synthetic/demands/synthetic_demands_v0.csv `
  --taxonomy data/processed/facet_discovery/facet_taxonomy_v0.json `
  --output data/processed/demands/demand_labeled_v0.csv `
  --failure-output data/processed/demands/labeling_failures_v0.csv
```

```powershell
$env:PYTHONPATH = "src"
python scripts/labeling/label_demands.py --catalog path/to/product_catalog.csv
```

기본 Taxonomy 경로는 건강기능식품용 `facet_taxonomy_v0.json`입니다. AI-Hub exploratory Taxonomy는 파이프라인 동작 확인이 필요할 때만 `--taxonomy`로 명시합니다.

미매칭, category 누락, 애매한 Alias는 `demand_label_review_queue_v0.csv`와
`labeling_failures_v0.csv`에 별도로 저장합니다. DB 연동은 인증정보를 받은 뒤
동일한 Labeling Service를 호출하는 별도 작업으로 붙입니다.
