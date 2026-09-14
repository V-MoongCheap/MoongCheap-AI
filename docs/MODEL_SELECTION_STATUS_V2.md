# Model 1 / Model 2 선택 상태 V2

## 결론 요약

현재 확정된 것은 실행 구조이며, 특정 LLM 모델명은 아직 최종 확정하지 않았다.

- Model 1: 상품 데이터에서 Facet 후보를 도출한다. Rule/통계 근거가 승격 gate이고, LLM 후보는 Human Review 전까지 후보로만 둔다.
- Model 2: Demand 자연어를 Label로 변환한다. `Rule-first Hybrid`를 기본 구조로 사용하되, LLM fallback 모델은 비교 후 결정한다.
- LLM 단독 결과를 운영 Label 또는 최종 Taxonomy로 자동 승인하지 않는다.

## 현재까지의 측정

### Model 2 Rule baseline

현재 검토 Gold 200건을 Dev 100 / Holdout 50 / Challenge 50으로 평가했다.

| Partition | Row pass |
| --- | ---: |
| DEV | 100/100 (100%) |
| HOLDOUT | 50/50 (100%) |
| CHALLENGE | 50/50 (100%) |
| Overall | 200/200 (100%) |

이 Gold는 합성·검토 데이터이므로 실제 사용자 정확도의 증명으로 사용하지 않는다. LLM fallback은 이 baseline을 안정적으로 개선하는 경우에만 채택한다.

### Model 1 Hybrid smoke

동일한 Model 1 입력과 기존 후보 결과를 Rule/Model/Hybrid로 비교했다.

| 항목 | 건수 |
| --- | ---: |
| Rule 후보 | 56 |
| Model 후보 | 12 |
| Hybrid 후보 | 67 |
| Rule 근거로 승격된 Model 후보 | 1 |
| Model 단독 Review 후보 | 11 |

현재 결과는 Model 1 LLM을 자동 확정할 만큼의 근거가 아니다. Rule 근거가 없는 Model-only 후보는 모두 검토 대기로 유지한다.

## 최종 선택 기준

### Model 1

후보 모델별로 동일 입력·Prompt·출력 Schema를 사용하고 다음을 비교한다.

1. 구조화 출력 성공률
2. 입력에 존재하는 Evidence ID/원문 인용률
3. 실제 데이터에 없는 Facet·Value 생성률
4. 중복·과도한 세분화 비율
5. Category 간 일관성
6. Human Review 승인률
7. 실행 시간·메모리·재현성

LLM 후보가 Rule/통계 근거를 개선하지 못하면 Model 1은 Rule/통계 기반으로 운영하고 LLM은 탐색 보조로만 둔다.

### Model 2

다음 세 구조를 같은 Gold와 이상 입력에 대해 비교한다.

```text
RULE_ONLY
RULE_FIRST_HYBRID
LLM_ONLY
```

필수 지표:

- 구조화 Facet Label 정확도
- 상태/모드/제약조건 정확도
- Unknown·Abstention 적절성
- Schema 실패율
- 미응답·누락률
- Rule 대비 개선폭
- 처리 시간과 비용

Rule-first Hybrid가 Rule-only보다 유의미하게 개선되지 않으면 Model 2 LLM fallback은 사용하지 않는다.

## 다음 실행 순서

1. Model 1 후보 모델을 동일한 multisource 입력으로 실행
2. Model 1 후보 결과를 Evidence gate와 Human Review queue로 평가
3. Model 2 후보 모델을 동일한 Dev/Holdout/Challenge 입력으로 실행
4. Rule-only와 Hybrid의 개선폭 비교
5. Model 1과 Model 2의 최종 모델 또는 비사용 결론 결정
6. 승인된 Taxonomy와 Labeling policy를 `category.facet` 및 런타임 문서에 반영

실제 모델 가중치·Ollama/Hugging Face/API 환경이 없는 경우에는 모델을 실행한 것처럼 처리하지 않고, 해당 후보를 `NOT_RUN`으로 기록한다.
