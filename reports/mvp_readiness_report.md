# MVP Readiness Report

## 상태

| 영역 | 상태 | 근거 |
|---|---|---|
| TAXONOMY_V2_2 | READY | 16 Category / 48 Facet / 413 Value, JSON 및 Category-local Code 검증 통과 |
| ALIAS_RUNTIME | READY | `APPLIED` Alias만 별도 Registry에서 사용, 24행 적용 대상 |
| DEMAND_LABELING | READY | V2.2 Rule/Alias CSV Dry-run 완료 |
| CLUSTERING_INTEGRATION | READY_LOCAL_DRY_RUN | 기존 B `cluster_demands` baseline에 `clustering_input_v2_2.csv` 연결 |
| MATCHING_INTEGRATION | NOT_RUN | 오늘 범위는 A→B이며 Seller Offer 입력/운영 Backend가 없어 실행하지 않음 |
| LLM_FALLBACK | DISABLED | `LABELING_LLM_FALLBACK_ENABLED=false`; Rule/Alias-only MVP |
| DATABASE_INTEGRATION | NOT_CONNECTED | PostgreSQL 자격정보와 실제 Backend endpoint 없음 |
| CRONJOB | PARTIAL | 단일 CLI Entry Point는 준비했으나 Kubernetes 배포 Manifest는 이번 범위에서 추가하지 않음 |
| DEMO_E2E | PASS_LOCAL | 200건 CSV에서 Labeling → Clustering 실행 성공 |

## 실제 Local Smoke 결과

입력: 기존 grounded evaluation sample 200건, V2.2 Taxonomy, Reviewed Alias Registry, Product Facet Mapping.

- Labeling: resolved 164, partial 34, conflict 2, failed 0
- Alias hit: 27
- Corrected alias hit: 27
- Clustering 처리: 198건
- 신규 Cluster: 137개
- Substitute 허용 Demand: 127건
- 실패 Demand 때문에 전체 Batch가 중단되지 않음
- 처리 완료 행은 `processed_at`이 기록되며 재실행 시 건너뜀

이 결과는 CSV Dry-run 결과이며 실제 PostgreSQL Read 또는 Backend Write 성공을 의미하지 않는다.

## 실행 명령

```powershell
$env:PYTHONPATH = "src"
python -m moongcheap_ai.mvp_pipeline `
  --input ..\data\processed\demand_5000_v1\model2_eval_sample_200_v1.csv `
  --taxonomy config/facet_taxonomy_v2_2.json `
  --alias-registry config/model1_aliases_reviewed_v2.json `
  --product-facets ..\data\processed\model1_v0_refresh4\product_facet_mapping_v0.csv `
  --output-dir data/processed/mvp_e2e_v2_2 `
  --dry-run
```

## 남은 Blocker

1. 실제 Backend-owned Demand/PostgreSQL 연결 정보가 없어 DB Read/Write는 아직 운영 검증하지 못했다.
2. B 운영 Runtime은 PostgreSQL과 Backend API 계약을 사용하므로, 실제 환경에서 별도 Integration Test가 필요하다.
3. Seller Matching은 입력 Offer와 C 파트 연결이 준비된 뒤 검증한다.

