# Model 1 / Model 2 비교 및 MVP 선택 결과 V1

## 1. 문서 목적

Model 1과 Model 2 후보를 비교한 결과와 현재 MVP의 실행 구성을 기록한다.
여기서 말하는 **MVP 선택**은 지금 배포할 구성의 결정이다. 실제 사용자 수요로
사람이 확정한 Gold Set이 아직 없으므로, 어떤 LLM이 일반적으로 더 정확한지를
최종 확정한 연구 결론은 아니다.

## 2. 현재 MVP 결정

| 대상 | MVP 결정 | 근거 |
| --- | --- | --- |
| Model 1 Facet Discovery | Rule/통계 기반 후보 + Evidence Gate + Human Review | 상품 근거 없는 LLM 후보를 자동 Taxonomy에 넣지 않기 위함 |
| Model 2 Demand Labeling | 최신 Part A Rule/Alias Runtime | 제한 평가에서 구조화 요구 53건 중 typed constraint 52건 일치, 전체 상태 79/80건 일치 |
| Qwen 2.5 7B | 배포·자동 fallback 제외 | 같은 80건에서 요구 코드 충족 33/53, Taxonomy 검증 경고 3건, 약 168초 |
| Embedding | B/C에서 별도 선택 | Demand Labeling과 역할·평가셋이 다름 |
| Seller Demand Analysis 생성 | SQL/Python 집계 + Template 우선 | 수치·사실을 모델이 생성하지 않도록 하기 위함 |

현재 배포 구조는 다음과 같다.

```text
Model 1 = Rule/통계 근거 → Evidence Gate → Human Review → Taxonomy
Model 2 = Rule/Alias Part A Runtime → PARSED/NONE/NOT_APPLICABLE은 라벨 저장, 모호·충돌은 Review
LLM     = 실험·검토 보조만 허용, 자동 Label/Taxonomy 확정에는 사용하지 않음
```

`키토산 또는 키토올리고당을 피하고 싶어요`처럼 결합값 전체 제외인지 각 성분
개별 제외인지 불명확한 사례는 자동 Label하지 않고 `REVIEW`로 남긴다.

## 3. Model 1: Facet Discovery

### 3.1 비교 결과

Kanana(`kakaocorp/kanana-nano-2.1b-instruct`)로 16개 Category, 210개
Product/Demand 관련 행을 실험했다.

| 항목 | 결과 |
| --- | ---: |
| 원시 LLM 후보 행 | 105 |
| 실패 행 | 20 |
| Rule 후보 | 246 |
| Hybrid 후보 | 256 |
| Rule 근거로 자동 승격된 Model 후보 | 0 |
| Model-only 검토 후보 | 10 |

실패에는 JSON 형식 오류, 입력에 없는 Evidence ID, 미정의 Facet ID가 포함됐다.
따라서 LLM 후보는 사람이 검토할 후보를 넓히는 데만 쓰며, Rule/통계 근거가 없는
항목은 Taxonomy에 자동 반영하지 않는다.

### 3.2 현재 데이터 반영

- `config/facet_taxonomy_v2_2.json`은 현재 승인된 런타임 Taxonomy다.
- 상품 Facet mapping 검토 결과 중 Taxonomy 코드와 값이 모두 검증된 `EDIT` 44건만
  적용할 수 있다.
- `UNCERTAIN` 310건은 여러 값이 같은 상품 근거에서 관측된 경우라 추측으로 한 값을
  고르지 않고 보류한다.

## 4. Model 2: Demand Labeling

### 4.1 배포 판단에 사용한 최신 비교

최신 Taxonomy v2.2 및 Part A Runtime으로 AI 검토를 거쳐 평가에 채택한 80건을
재실행했다. 이 데이터는 사람 Gold가 아니므로 일반화 정확도로 해석하지 않는다.

| 방식 | 결과 | 배포 판단 |
| --- | --- | --- |
| Rule/Alias Runtime | 구조화 요구 53건 중 typed constraint 52건, 전체 상태 79/80건 일치 | MVP 기본 |
| Qwen 2.5 7B model-only | 요구 코드 충족 33/53, 3건 경고, 19회 호출 약 168초 | 제외 |

Rule 결과가 모호하거나 충돌하면 LLM으로 덮어쓰지 않는다. `PASSTHROUGH`,
`CONFLICT`, `REVIEW`, `TAXONOMY_AMBIGUOUS`는 Review 상태로 보존한다.

85개 Gold 후보를 현재 Runtime으로 다시 실행한 회귀 확인에서는 82건이 수정 기대
조건과 구조적으로 일치했다. 나머지 3건은 2개의 같은 Facet 충돌과 1개의
대안형 제외 범위 사례로, 자동 Label 대신 각각 `CONFLICT` 또는 `REVIEW`가 나온
의도된 보수 처리다.

### 4.2 과거 실험의 해석

Qwen, Llama, EXAONE, Phi 계열의 100/200건 smoke·비교는 모델의 형식 준수,
실행 시간, 실패 형태를 파악한 탐색 실험이다. 당시 일부 Qwen Hybrid 수치가
Rule-only보다 높았더라도, 제품 기본 Facet 맥락과 부정 조건을 충분히 검증하지
못했고 최신 80건 재평가에서도 Rule Runtime보다 낮았다.

따라서 과거의 “Qwen fallback 후보” 표현은 현재 결론이 아니며, Qwen을 자동
fallback이나 운영 의존성으로 추가하지 않는다.

## 5. 평가 데이터 상태와 최종 확정 조건

현재 `model2_gold_v1`에는 150건의 검토 resolution이 있다.

| 구분 | 건수 | 현재 의미 |
| --- | ---: | --- |
| `READY_FOR_HUMAN_SIGNOFF` | 85 | AI 검토·검증을 통과한 Gold 후보. 사람 최종 승인은 아직 아님 |
| `EXCLUDED` | 65 | 근거·시나리오·카테고리 문제가 있어 Gold에서 제외 |

Model 2의 최종 비교를 확정하려면 85건에서 사람이 승인한 행만 Gold로 표시하고,
정책 보류 사례를 해결해야 한다. 같은 확정 Gold로 다음 세 방식을 재측정한다.

```text
Rule-only
Rule-first Hybrid
Model-only (비교용, 배포 후보 아님)
```

## 6. 재현 가능한 실행 경로

### Model 1 검토 반영

```bash
PYTHONPATH=src python scripts/data/apply_product_facet_review.py \
  --mapping data/processed/model2_catalog_v0/product_facet_mapping_v0.csv \
  --review /path/to/product_facet_mapping_review_queue_reviewed_high.csv \
  --taxonomy config/facet_taxonomy_v2_2.json \
  --output data/processed/model2_catalog_v0/product_facet_mapping_v0_reviewed.csv \
  --report data/reports/product_facet_mapping_review_apply_v1.json
```

### Model 2 비교

동일한 사람 확정 Gold 입력, Taxonomy와 Runtime 결과를 준비한 뒤
`scripts/evaluation/compare_demand_labeling_models.py`로 비교한다. 모델 가중치나
Ollama 실행 환경이 없으면 성공으로 기록하지 않고 `NOT_RUN` 또는
`BLOCKED_NO_EXECUTABLE_MODEL`로 기록한다.

## 7. 남은 작업

1. 85개 Gold 후보를 사람 기준으로 최종 승인·수정·제외한다.
2. 확정 Gold로 Model 2 비교 결과를 다시 기록한다.
3. Model 1의 `UNCERTAIN` mapping은 상품 원문 근거로 재검토하되, 근거가 없으면
   보류를 유지한다.
4. Backend 실제 Catalog/Category ID로 교체한 뒤 A DB write를 검증한다.
5. B의 실제 Cluster 결과와 C Seller Offer를 결합해 E2E를 검증한다.
6. 인프라 환경에서 Docker, CronJob, DB Secret 주입, CI/CD를 검증한다.
