# MVP E2E 실행 안내

## 현재 범위

오늘의 로컬 MVP는 `Demand CSV → V2.2 Rule/Alias Labeling → clustering_input → B Clustering baseline` 순서로 실행한다. PostgreSQL 조회와 Backend 쓰기는 별도 운영 Adapter가 담당하며, 자격 정보가 없는 로컬 실행에서는 수행하지 않는다.

## 실행

```powershell
$env:PYTHONPATH = "src"
python -m moongcheap_ai.mvp_pipeline `
  --input <demand.csv> `
  --output-dir data/processed/mvp_e2e_v2_2 `
  --taxonomy config/facet_taxonomy_v2_2.json `
  --alias-registry config/model1_aliases_reviewed_v2.json `
  --product-facets <product_facet_mapping.csv> `
  --limit 20 `
  --dry-run
```

`--limit`을 생략하면 입력에서 `processed_at`이 비어 있는 Demand를 모두 처리한다. 이미 처리된 행은 건너뛴다. `LABELING_LLM_FALLBACK_ENABLED`는 기본적으로 `false`이며 이 Entry Point는 LLM을 호출하지 않는다.

## 결과

- `demand_labeled_v2_2.csv`: Category, Facet 값, Category-local Label, 처리 상태
- `clustering_input_v2_2.csv`: B에 전달하는 입력
- `demand_cluster_summary_v2_2.csv`: Cluster별 참여 인원·수량·Catalog 요약
- `mvp_e2e_summary_v2_2.json`: Labeling/Clustering 관측 지표와 실행 상태

## 운영 연결 상태

- CSV Dry-run: 오늘 검증 대상이며 실제 동작한다.
- PostgreSQL read: 기존 `data_foundation.runtime_job`와 B의 `demand_clustering.runtime_job` Adapter를 사용한다.
- Backend write: `--dry-run`에서는 수행하지 않는다. 운영 연결 시 Backend 계약과 내부 키가 필요하다.
- Runtime 분리: 실패 Demand가 전체 Batch를 중단하지 않도록 행 단위 결과와 상태를 남긴다.

