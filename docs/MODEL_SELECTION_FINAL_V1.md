# Model 1 / Model 2 비교 및 MVP 선택 결과 V1

## 1. 결론

현재 MVP에서 사용할 방식은 다음과 같이 확정한다. 이 결정은 프로젝트용 합성·검토 데이터와 제한된 로컬 실행 결과에 근거한 구현 결정이며, 실제 운영 사용자에 대한 일반화 성능을 보증하는 최종 연구 결론은 아니다.

| 대상 | MVP 적용 방식 | 역할 |
| --- | --- | --- |
| Model 1 Facet Discovery | Rule/통계 근거 + Qwen3 4B 보조 후보 + Evidence Gate + Human Review | 상품 근거가 있는 Facet 후보를 만들고 사람이 Taxonomy를 확정 |
| Model 2 Demand Labeling | Rule-first Hybrid + Qwen 2.5 7B fallback | 명확한 요청은 Rule/Alias로 처리하고 미해결 양성 요청만 Qwen에 위임 |
| Model 2 Model-only | 사용하지 않음 | Taxonomy 밖 값·누락·오판 위험이 Rule-only보다 큼 |
| Embedding | Model 2에는 사용하지 않음 | B/C의 Cluster·Seller Matching에서 별도 평가 |
| Seller Demand Analysis | SQL/Python 집계 + Template 우선 | 숫자와 사실은 코드가 계산 |

운영 흐름은 다음과 같다.

```text
Model 1: Rule/통계 → Qwen3 4B 후보 보조 → Evidence 검증 → Human Review → Taxonomy
Model 2: Rule/Alias → 명확하면 즉시 Label
                  → 미해결 양성 요청만 Qwen 2.5 7B
                  → Taxonomy/typed constraint 검증
                  → 실패·충돌·근거 부족은 원상품 Facet 기본값 유지
```

Qwen fallback은 `A_MODEL2_FALLBACK_ENABLED=false`가 기본값이다. Ollama가 준비된 환경에서만 명시적으로 켜며, 기본 CronJob은 모델 없이도 결정론적인 Rule 경로로 동작한다. 실제 연결 코드는 `runtime_job.py`에 있다. 모델 응답이 실패하거나 검증되지 않으면 그 응답은 적용하지 않고, 검증된 원상품 기본 label은 DB에 기록한다.

## 2. 선택 근거

동일한 200건 비교에서 Rule-only는 138/200(69%), Qwen model-only는 118/200(59%), Rule-first Hybrid는 142/200(71%)이었다. 따라서 Model-only는 제외하고, Rule의 안전한 Taxonomy 제한을 유지하면서 Rule이 처리하지 못한 일부를 보완하는 Hybrid를 선택했다. 별도의 80건 최신 실행은 Qwen model-only만 검증한 결과이므로 Hybrid를 반박하는 수치로 해석하지 않는다. Ollama가 없는 환경에서는 최신 Hybrid 재실행을 성공으로 기록하지 않는다.

### Model 1

`qwen3:4b`는 Model 1 고도화 기법 비교에서 전체 30개 Category × 3회 실행을 수행했고,
동일한 축소 smoke 입력에서도 4회 호출·4건 후보·실패 0건·33.00초를 기록했다.
Kanana는 동일 smoke에서 4회 호출·후보 0건·JSON 실패 4건·180.27초였다.
따라서 MVP 보조 모델은 Qwen3 4B로 확정한다. Kanana는 비교·재현용 후보로만 보존한다.
최종 Taxonomy는 상품 원문·반복 통계·Evidence 검증과 Human Review 없이 만들어지지 않는다.

### Model 2

Qwen 2.5 7B는 전체 Model-only 품질이 아니라 fallback 개선폭과 재현 가능한 Ollama 실행을 기준으로 채택했다. fallback은 명시적 제외·충돌을 임의로 긍정 조건으로 바꾸지 않으며, 현재 Taxonomy에 완전히 매핑되고 원문 근거가 확인된 양성 constraint만 해당 Facet의 검증된 상품 기본값을 덮어쓴다. 모델을 쓸 수 없거나 결과가 모호하면 검증된 원상품 기본 label을 유지한다. Product Facet profile 또는 Category/Taxonomy가 없거나 불완전하면 추정 없이 처리 보류한다.

## 3. 현재 산출물 및 검증 상태

- 최신 Part A runtime v2.2.6: 5,000건, `PARSED 3,200`, `NONE 1,000`, `PASSTHROUGH 500`, `CONFLICT 250`, `TAXONOMY_AMBIGUOUS 50`
- B 전달용 clustering input: 5,000건, `LABELED 4,200`, `LABELED_WITH_REVIEW 800`
- 상품 Facet mapping 최신 로컬 결과: 2,778 catalog, `MAPPED 1,934`, `UNKNOWN 5,804`, `AMBIGUOUS 269` mapping rows
- 150건 Gold 검토 결과는 사람 최종 승인 전 후보 데이터다. `READY_FOR_HUMAN_SIGNOFF` 85건과 `EXCLUDED` 65건을 Gold 확정으로 혼동하지 않는다.

## 4. 남은 검증

1. 사람이 85개 Gold 후보의 최종 승인·수정·제외를 확정한다.
2. 확정 Gold와 실제 상품 Facet mapping을 사용해 Rule-only, Hybrid, Model-only를 같은 입력으로 재측정한다.
3. Ollama/Qwen이 준비된 환경에서 fallback 호출·timeout·재처리·DB 멱등성을 검증한다.
4. Backend 실제 Catalog/Category ID와 DB Secret을 받은 뒤 write 경로를 검증한다.
5. B의 실제 Cluster와 C의 Seller Offer를 결합해 전체 E2E를 검증한다.
