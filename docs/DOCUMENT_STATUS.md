# 문서 상태 및 현재 기준

이 문서는 저장소 문서가 여러 실험 단계에서 누적되면서 생길 수 있는 버전 혼동을 막기 위한 안내다.

## 현재 기준 문서

| 주제 | 현재 기준 | 의미 |
|---|---|---|
| AI 범위 | `README.md` | Model 1/2, Clustering, Seller Matching, Seller Analysis의 MVP 범위 |
| 모델 선택 | `MODEL_SELECTION_FINAL_V1.md` | Model 1 Kanana 보조 + Evidence Gate, Model 2 Rule-first Hybrid + 선택적 Qwen fallback |
| 데이터 계보 | `DATA_LINEAGE.md` | 원천 데이터, Category 매핑, Facet Evidence와 산출물 관계 |
| 데이터 상태 | `DATA_ARTIFACT_STATUS.md` | Seed, Evidence, Taxonomy, 평가 데이터의 사용 가능 범위 |
| Model 1 입력 | `MODEL1_MULTISOURCE_INPUTS_V1.md`, `MODEL1_MULTISOURCE_SOURCE_POLICY_V1.md` | 상품·판매자·명시적 Category Evidence의 역할과 제외 경계 |
| Backend/Part B 연계 | `PART_B_V22_INTEGRATION.md` | V2.2 taxonomy, catalog profile, Labeling 경계 |
| 로컬 E2E | `MVP_E2E_HANDOFF.md` | CSV 기반 B/C 통합 테스트 흐름 |
| 배포/인프라 | `A_LABELING_CONTAINER.md`, `DEMAND_CLUSTERING_CONTAINER.md`, `k8s/README.md` | 실제 DB·Secret·EKS 연결 전의 배포 계약 |

## 역사적·진단용 문서

- `DEMAND_LABELING_MODEL_SELECTION_V1.md`: 초기 V2.1 taxonomy와 200건 평가를 사용한 비교 기록. 현재 Gold 확정 결과가 아니다.
- `DAY1_COMPLETION_REPORT.md`: 초기 작업일 기준 보고서다.
- `HEALTH_FOUNDATION_V0.md`: 초기 건강기능식품 foundation 산출물 설명이다.
- `CODEX_HANDOFF.md`: 현재 저장소로 갱신된 인수인계 문서지만, 경로에 표시된 데이터는 로컬 전용이다.
- `MODEL_BENCHMARK.md`: 바코드 중복 기반 Proxy 평가 기록이며, 검증된 정답셋의 운영 정확도가 아니다.

파일명에 `V0`, `V1`, `V2.1`이 포함된 것은 산출물 또는 실험 버전이다. 원천기관 공식 버전으로 해석하지 않는다.

## 공통 상태 규칙

- `candidate`, `draft`, `pending`, `review`는 자동 확정이 아님을 뜻한다.
- `config/facet_taxonomy_v2_2.json`은 현재 기준 Taxonomy 계약이지만, 신규/변경 Facet은 Human Review 없이 승인하지 않는다.
- `data/processed/backend_seed_v5/`의 Category/Catalog ID는 Backend 실DB ID가 아닌 Seed ID다.
- `data/raw`, `data/interim`, `data/processed`, `data/reports`의 대용량·개인 산출물은 로컬 전용이며 Git에 커밋하지 않는다.
