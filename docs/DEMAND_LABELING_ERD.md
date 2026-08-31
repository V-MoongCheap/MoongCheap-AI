# ERD 기준 Demand Labeling

Backend의 `demand`에는 별도 `category_id`가 없으므로 다음 경로로 Facet을 조회합니다.

```text
demand.catalog_id -> product_catalog.id -> product_catalog.category_id -> category.facet
```

AI 파트는 category ID를 새로 만들거나 KAN 코드를 Backend PK로 저장하지 않습니다. Backend `product_catalog` export를 `--catalog`로 전달할 때 `id`와 `category_id`가 모두 있어야 합니다.

```powershell
$env:PYTHONPATH = "src"
python scripts/labeling/label_demands.py --catalog path/to/product_catalog.csv
```

미매칭, category 누락, 애매한 Alias는 `demand_label_review_queue_v0.csv`에 별도로 저장합니다. DB 반영은 Backend가 담당합니다.
