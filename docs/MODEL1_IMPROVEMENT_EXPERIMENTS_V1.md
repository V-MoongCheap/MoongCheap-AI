# Model 1 고도화 실험 결과 V1

## 실험 범위

동일한 1,200개 Domeggook 상품 코퍼스를 기준으로, 현재 저장소에 남아 있는 재현 가능한 Model 1 고도화 결과를 비교했다.

주의: 아래의 카테고리 성공률·후보 수·처리시간은 운영 지표다. 후보의 의미적 정확도(Precision/Recall)를 의미하지 않는다. 최종 품질 비교에는 승인된 Facet Gold Set이 필요하다.

## 비교 결과

| 실험 | 모델/방식 | 성공 카테고리 | 호출 수 | 실패 행 | 실행시간 |
|---|---|---:|---:|---:|---:|
| 단일 생성 | Qwen3 4B | 17/30 (56.7%) | 38 | 7 | 264.9초 |
| 단일 생성 | Qwen2.5 7B Instruct | 17/30 (56.7%) | 40 | 12 | 359.8초 |
| Self-consistency 3회, 2표 이상 채택 | Qwen3 4B | 21/30 (70.0%) | 90 | 7 | 461.0초 |

### Self-consistency

단일 생성 대비 카테고리 처리 성공률은 56.7%에서 70.0%로 상승했다. 그러나 호출 수는 38회에서 90회, 실행시간은 264.9초에서 461.0초로 증가했다.

따라서 오프라인 재시도나 중요 카테고리 검증에는 유효하지만, 현재 기본 실행 경로에 항상 적용하지 않는다. 품질 Gold Set에서 의미적 정확도 개선이 확인될 때만 선택적으로 활성화한다.

### 모델 크기 비교

Qwen2.5 7B Instruct는 Qwen3 4B와 성공 카테고리 수가 같았지만 실행시간이 더 길고 실패 행이 많았다. 현재 데이터와 실행 조건에서는 기본 모델로 채택할 근거가 없다.

## Hybrid 결과

규칙 기반 관찰 증거를 자동 승격의 필수 조건으로 두고, LLM 후보는 관찰된 상품 데이터와 일치하는 경우에만 Hybrid 후보로 편입했다.

| 실험 | 상품 수 | 증거 기반 커버리지 | 미해결 상품 | Hybrid LLM 행 |
|---|---:|---:|---:|---:|
| Hybrid V2 | 1,200 | 65.83% | 410 | 3 |
| Hybrid V5 | 1,200 | 65.83% | 410 | 5 |

Strict gate 결과는 다음과 같다.

- 입력 상품: 1,200개
- 증거 기반 커버 상품: 769개(64.08%)
- 미해결 상품: 431개
- Grounded model 행: 8개
- 자동 게이트 통과: 5개
- 자동 보류: 8개
- 관찰 증거가 없는 Model-only 후보 자동 승격: 0개

Hybrid V2와 V5 사이에 커버리지 개선은 없었다. 따라서 LLM 후보 수가 늘어난 것만으로 V5를 우월하다고 판단하지 않는다.

## 실제 기법 벤치마크 결과

동일한 모델·동일한 카테고리 입력에서 프롬프트·추론 기법만 바꿔 재실행했다. 1.7B는 전체 30개 카테고리, 4B는 대표 6개 카테고리로 먼저 검증했다.

| 기법 | 성공 카테고리 | 값 근거율 | 중복률 | 실행시간 |
|---|---:|---:|---:|---:|
| Baseline | 3/30 (10.0%) | 100.0% | 0.0% | 80.2초 |
| Strict grounding | 8/30 (26.7%) | 100.0% | 0.0% | 49.3초 |
| Few-shot + grounding | 17/30 (56.7%) | 94.12% | 0.0% | 71.5초 |
| Evidence retrieval | 12/30 (40.0%) | 83.33% | 0.0% | 62.6초 |
| Self-consistency 3회 | 18/30 (60.0%) | 100.0% | 0.0% | 148.3초 |

Qwen3 4B 대표 6개 검증 결과:

| 기법 | 성공 카테고리 | 값 근거율 | 실행시간 |
|---|---:|---:|---:|
| Baseline | 0/6 (0.0%) | 측정 불가 | 45.4초 |
| Strict grounding | 5/6 (83.3%) | 80.0% | 38.5초 |
| Few-shot + grounding | 5/6 (83.3%) | 100.0% | 38.6초 |
| Evidence retrieval | 5/6 (83.3%) | 100.0% | 33.0초 |
| Self-consistency 3회 | 5/6 (83.3%) | 80.0% | 73.7초 |

4B 결과는 6개 대표 표본이므로 1.7B의 30개 전체 결과와 직접 동일 비교하지 않는다. 다만 작은 모델에서 관찰된 낮은 성공률이 모델 크기와 프롬프트 양쪽의 영향을 받는다는 점은 확인했다.

Qwen3 4B 전체 30개 최종 검증 결과:

| 기법 | 성공 카테고리 | 값 근거율 | 실행시간 |
|---|---:|---:|---:|
| Baseline | 2/30 (6.7%) | 100.0% | 197.6초 |
| Strict grounding | 26/30 (86.7%) | 92.31% | 186.6초 |
| Few-shot + grounding | 28/30 (93.3%) | 92.86% | 208.5초 |
| Evidence retrieval | 27/30 (90.0%) | 96.30% | 176.0초 |
| Self-consistency 3회 | 28/30 (93.3%) | 89.29% | 440.6초 |

Few-shot + grounding과 Self-consistency의 성공률은 동일했지만 Self-consistency는 약 2.1배 느리고 값 근거율도 낮았다. Evidence retrieval은 가장 빠르고 값 근거율이 높았지만 성공 카테고리 수가 낮아 기본 방식으로 채택하지 않는다.

## 추가 고도화 기법 검증

Qwen3 4B 대표 6개 카테고리에서 추가 기법을 검증했다.

| 기법 | 성공 카테고리 | 호출 수 | 값 근거율 | 판단 |
|---|---:|---:|---:|---|
| Adaptive fallback | 6/6 (100.0%) | 7 | 83.33% | 성공률은 높지만 근거율 저하로 기본 미적용 |
| Prompt ensemble 교집합 | 0/6 (0.0%) | 12 | 측정 불가 | 너무 보수적이라 미적용 |
| Category evidence summary | 5/6 (83.3%) | 6 | 100.0% | Few-shot 전체 결과보다 개선 없음 |
| Two-stage verifier | 5/6 (83.3%) | 11 | 100.0% | 중복 후보와 호출 비용으로 미적용 |
| Evidence support gate | 5/6 (83.3%) | 6 | 100.0% | 후보 승격 전 안전성 검사로 유지 |

추가 기법 중 전체 30개에서 확인된 Few-shot + grounding의 28/30(93.3%)을 넘은 방식은 없었다. 따라서 새로운 기법을 기본 경로에 추가하지 않고, Evidence support gate만 안전성 단계로 유지한다.

Two-stage verifier를 전체 30개로 재검증한 결과는 28/30(93.3%), 58회 호출, 389.0초였다. Few-shot + grounding의 28/30(93.3%), 208.5초와 성공률은 같았지만 실행비용이 커서 기본 경로에 적용하지 않는다.

## 기법 조합 반복 검증

Qwen3 4B 대표 6개 카테고리에 조합별 3회 반복 실행했다.

| 조합 | 평균 성공률 | 최저 성공률 | 평균 값 근거율 | 평균 호출 |
|---|---:|---:|---:|---:|
| Few-shot + Evidence Gate | 83.33% | 83.33% | 100.0% | 6.0 |
| Few-shot + Category Summary + Gate | 72.22% | 66.67% | 100.0% | 6.0 |
| Adaptive Fallback + Gate | 88.89% | 83.33% | 87.78% | 7.33 |
| Few-shot + Self-consistency + Gate | 72.22% | 66.67% | 100.0% | 18.0 |

Adaptive Fallback은 성공률 평균은 높았지만 값 근거율이 낮아 기본 적용하지 않는다. 반복 결과가 가장 안정적이고 근거율이 100%인 조합은 Few-shot + Evidence Gate였다.

### 전체 30개 × 3회 최종 반복 검증

Qwen3 4B로 전체 30개 카테고리에 조합별 3회 실행했다. 성능은 카테고리별 유효 후보 생성 성공률이며, 값 근거율은 후보 값이 실제 입력 원문에 존재하는 비율이다.

| 조합 | 평균 성공률 | 최저 성공률 | 평균 값 근거율 | 평균 실행시간 | 평균 호출 |
|---|---:|---:|---:|---:|---:|
| Few-shot + Evidence Gate | 85.55% | 80.0% | 100.0% | 141.9초 | 30.0 |
| Few-shot + Category Summary + Gate | 85.55% | 83.33% | 100.0% | 264.7초 | 30.0 |
| Adaptive Fallback + Gate | 90.0% | 90.0% | 92.59% | 277.0초 | 35.33 |
| Few-shot + Self-consistency + Gate | 76.67% | 73.33% | 100.0% | 459.0초 | 90.0 |

Adaptive Fallback은 성공률만 보면 높지만 근거율이 100%가 아니므로 Taxonomy 자동 승격 기본값으로 채택하지 않는다. Category Summary는 성능이 같고 약 1.9배 느리며, Self-consistency는 성능이 오히려 낮고 약 3.2배 느리다.

초기 파일럿 기준 기본값은 `Few-shot + Evidence Gate`였다. 이후 전체 30개 카테고리 × 3회 재실험의 최종 판정은 아래 `최종 전체 재실험 결과` 절을 우선한다.

초기 파일럿에서는 유효 source ID와 원문 증거 복사 비율을 별도로 확인했다. 최종 반복 실험에서는 방식별 값 근거율 차이가 확인됐으므로, 자동 승격에는 최종 Evidence Gate를 적용한다.

## 적용할 방식

- 규칙 기반 상품 증거 추출을 Baseline으로 유지한다.
- LLM은 Facet 이름과 값을 생성하는 보조 역할로만 사용한다.
- 상품 데이터에서 관찰되지 않은 값은 자동 Taxonomy에 넣지 않는다.
- 구조 검증, 카테고리 검증, 자기참조 Facet명 제거, 모호 후보 abstention을 적용한다.
- 일반 상품 Facet Discovery는 Few-shot + strict grounding 프롬프트를 기본값으로 사용한다.
- Self-consistency는 실패·애매 카테고리의 재검증에만 `--consistency-attempts 3`으로 선택 적용한다.
- 모든 카테고리에 Self-consistency를 강제하지 않는다. 전체 결과에서 Few-shot과 성공률이 같고 비용만 증가했다.

## 적용하지 않는 방식

- Model-only Taxonomy 자동 확정: 관찰 증거가 없어 오탐 위험이 크다.
- Qwen2.5 7B 기본 채택: 동일 성공률에 더 긴 시간과 더 많은 실패가 발생했다.
- Evidence retrieval 축소: 성공률은 40.0%였고 값 근거율이 83.33%로 낮아 기본 적용하지 않는다.
- Prompt ensemble, category summary, two-stage verifier: Few-shot + grounding 대비 유의미한 개선이 없어 기본 적용하지 않는다.

## 아직 정량 확정할 수 없는 방식

- Fine-tuning: 승인된 Facet Gold Set과 안정적인 Train/Validation/Test 분할이 부족하다.
- Embedding reranking: Facet 후보 관련성 Gold 라벨이 없어 품질 비교가 불가능하다.
- 최종 Precision/Recall: 현재 검토 산출물은 후보 검토 자료이며 완전한 승인 Gold Set이 아니다.

## 재현 명령

```bash
PYTHONPATH=src .venv/bin/python \
  scripts/evaluation/build_model1_improvement_report.py \
  --output-dir /tmp/model1_improvement_experiments_v1
```

원본 결과는 report 생성기가 참조하는 `data/processed/model1_*` 산출물에 보존되어 있다. 생성된 데이터 산출물은 저장소에 커밋하지 않는다.

## 최종 전체 재실험 결과 (2026-09-27)

앞의 대표 6개 카테고리 및 초기 전체 실행 표는 탐색 단계 결과다. 최종 비교를 위해 동일한 입력 코퍼스(`model1_domeggook_comparison_v6_clean_large`, 30개 카테고리), 동일한 로컬 모델(`qwen3:4b`)로 각 방식을 3회씩 다시 실행했다. 아래 수치는 카테고리별 유효 출력 생성 여부와 입력 증거에 존재하는 값의 비율을 측정한 운영 지표이며, 의미적 정답률(Precision/Recall)이 아니다.

### 단일 기법 5종 × 3회

| 기법 | 평균 성공률 | 최저~최고 | 평균 값 근거율 | 평균 시간 | 평균 호출 |
|---|---:|---:|---:|---:|---:|
| Baseline | 6.67% | 6.67~6.67% | 100.00% | 217.8초 | 30 |
| Strict grounding | 86.67% | 86.67~86.67% | 89.74% | 192.8초 | 30 |
| Few-shot grounding | 93.33% | 93.33~93.33% | 92.86% | 199.8초 | 30 |
| Evidence retrieval | 90.00% | 90.00~90.00% | 96.30% | 171.2초 | 30 |
| Self-consistency | 91.11% | 90.00~93.33% | 91.49% | 428.9초 | 90 |

### 고급 기법 5종 × 3회

| 기법 | 평균 성공률 | 평균 값 근거율 | 평균 시간 | 평균 호출 | 판단 |
|---|---:|---:|---:|---:|---|
| Adaptive fallback | 100.00% | 92.22% | 192.2초 | 34 | 근거 게이트 없이는 자동 승격 불가 |
| Prompt ensemble | 6.67% | 100.00% | 307.9초 | 60 | 교집합이 과도하게 보수적 |
| Category summary | 90.00% | 96.30% | 264.2초 | 30 | 추가 비용 대비 개선 제한 |
| Two-stage verifier | 93.33% | 92.86% | 407.0초 | 58 | 비용과 중복 후보 증가 |
| Evidence support gate | 86.67% | 100.00% | 126.6초 | 30 | 안전성 검사로 유지 |

### 조합 7종 × 3회

| 조합 | 평균 성공률 | 최저 성공률 | 평균 값 근거율 | 평균 시간 | 평균 호출 |
|---|---:|---:|---:|---:|---:|
| Few-shot + Evidence Gate | 82.22% | 76.67% | 98.72% | 123.1초 | 30.0 |
| Few-shot + Category Summary + Gate | 87.78% | 83.33% | 100.00% | 260.4초 | 30.0 |
| Adaptive Fallback + Gate | 92.22% | 90.00% | 96.39% | 228.6초 | 34.3 |
| Few-shot + Self-consistency + Gate | 71.11% | 66.67% | 100.00% | 443.7초 | 90.0 |
| Adaptive Fallback + Support Gate | 97.78% | 96.67% | 93.14% | 225.4초 | 34.3 |
| Few-shot + Summary + Self-consistency + Gate | 71.11% | 66.67% | 100.00% | 511.9초 | 90.0 |
| Few-shot + Verifier + Gate | 83.33% | 80.00% | 98.72% | 409.3초 | 57.7 |

### 현재 적용 판정

- 오프라인 품질 우선 기본 후보는 `Few-shot + Category Summary + Evidence Gate`로 둔다. 평균 성공률 87.78%, 값 근거율 100%이며, 단순 Few-shot + Gate보다 성공률이 높다.
- 실행시간을 우선하는 경량 경로는 `Few-shot + Evidence Gate`로 둔다.
- `Adaptive Fallback + Support Gate`는 가장 높은 운영 성공률을 보였지만 값 근거율이 93.14%이므로 자동 Taxonomy 승격 경로로 사용하지 않는다. 실패 카테고리 재시도 후보로만 사용할 수 있으며, 최종 Evidence Gate와 보류(abstention)를 거쳐야 한다.
- Self-consistency와 verifier 조합은 성공률 개선이 없거나 낮고 실행시간이 크게 증가해 기본 경로에서 제외한다.

이번 재실험은 모든 방식을 30개 카테고리에서 3회씩 실행했다는 점에서 이전 파일럿 표보다 비교 근거가 강해졌다. 다만 `success_rate`와 `value_evidence_rate`는 형식·근거 기반 지표다. 사람 검수 Gold Set(`facet_gold_set_v1.csv`)에 대한 후보별 의미 일치 Precision/Recall은 별도 평가기로 연결해야 최종 품질 수치로 보고할 수 있다. 따라서 이 문서의 결과만으로 “의미적 정확도 최종 확정”이라고 해석하지 않는다.

재현 산출물:

- `data/processed/model1_technique_benchmark_full_3repeats_qwen3_4b/`
- `data/processed/model1_advanced_benchmark_full_3repeats_qwen3_4b/`
- `data/processed/model1_combination_benchmark_full_7x3_qwen3_4b/`
