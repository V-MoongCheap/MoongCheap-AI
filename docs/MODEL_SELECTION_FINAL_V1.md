# Model 1 / Model 2 비교 및 MVP 선택 결과 V1

## 1. 문서 목적

Model 1과 Model 2의 후보 방식을 같은 평가 원칙으로 정리하고, 현재 통합 프로젝트 MVP에서 사용할 실행 구조를 결정한다.

이 문서의 정확도 수치는 실제 운영 사용자 Gold가 아니라 프로젝트용 합성·검토 데이터 기준이다. 따라서 모델의 절대적인 일반화 성능을 의미하지 않는다.

## 1. 최신 MVP 결정

이 절은 아래의 초기 200건 후보 비교 결과보다 우선한다. 최신 Part A Runtime과
Taxonomy v2.2로, AI 검토를 거쳐 평가에 채택한 80건을 다시 실행했다. 이 데이터는
독립적인 사람 Gold가 아니므로 일반화 성능 수치로 사용하지 않는다. 대신 현재 MVP
구성에서 Rule과 LLM 중 무엇을 배포할지 결정하는 회귀 검증으로 사용한다.

| 대상 | 결과 | 결정 |
| --- | --- | --- |
| Model 1 Facet Discovery | Kanana의 미승인 후보 4건은 실제 MFDS 기능성 원문에는 있었지만 기존 Facet 계약과 맞지 않았다. | Rule/통계 근거만 Taxonomy 후보로 사용한다. LLM 결과는 Human Review 보조로만 유지한다. |
| Model 2 Rule/Alias | 구조화 요구 53건 중 typed constraint 일치 52건, 전체 상태 일치 79/80건 | MVP Labeling 본체로 사용한다. |
| Qwen 2.5 7B | 구조화 요구 53건 중 요구 코드 충족 33건, 3건 Taxonomy 검증 경고, 19회 호출에 약 168초 | Model-only와 자동 fallback으로 배포하지 않는다. |

Model 2의 남은 1건은 `키토산 또는 키토올리고당`의 제외 범위가 하나의 결합값인지
각 성분의 개별 제외인지 확정되지 않은 정책 사례다. `REVIEW`로 보존한다.

따라서 현재 배포 결정은 다음과 같다.

```text
Model 1 = Rule/통계 기반 Facet 후보 + Evidence Gate + Human Review
Model 2 = 최신 Rule/Alias Part A Runtime + Review Queue
Qwen 2.5 7B = 재평가 대상 보조 후보, 배포하지 않음
```

## 2. 역할 구분

| 구분 | 역할 | 핵심 출력 |
| --- | --- | --- |
| Model 1 | 상품 데이터에서 Facet 후보를 발견 | Facet 후보, 근거, Human Review Queue |
| Model 2 | 소비자 `extra_requirement`를 Facet Label로 변환 | Demand Label, 처리 상태, 검토 사유 |
| Embedding | 수요 클러스터 후보 검색 및 판매자 매칭 보조 | 유사도 후보 |

Model 2는 Embedding 모델이 아니다. Embedding은 B/C 통합 영역의 후보 검색·매칭에 사용하며 Model 2의 Demand Labeling과 분리한다.

## 3. Model 1 비교

### 3.1 최신 Kanana 전체 입력 결과

대상 모델:

```text
kakaocorp/kanana-nano-2.1b-instruct
```

입력은 16개 Category, 210개 Product/Demand 관련 행이다.

| 항목 | 결과 |
| --- | ---: |
| 입력 행 | 210 |
| Category | 16 |
| 원시 후보 행 | 105 |
| 실패 행 | 20 |
| 실행 시간 | 약 627.93초 |
| Rule 후보 | 246 |
| Hybrid 후보 | 256 |
| Rule 근거로 승격된 Model 후보 | 0 |
| Model-only 검토 후보 | 10 |

주요 실패 유형은 invalid JSON, 입력에 없는 Evidence ID, 인식할 수 없는 Facet ID였다.

### 3.2 Model 1 선택

Model 1은 LLM-only로 사용하지 않는다.

```text
Rule/통계 근거 생성
→ LLM 후보 보조
→ Evidence 검증
→ Human Review
→ Taxonomy 확정
```

현재 Kanana는 한국어 후보 생성 보조 모델로만 둔다. Rule 근거가 없는 Model-only 후보는 자동 Taxonomy에 포함하지 않는다.

## 4. Model 2 비교

비교 방식:

```text
RULE_ONLY
RULE_FIRST_HYBRID
MODEL_ONLY
```

평가 대상은 동일한 검토용 200건이다. 기대 Facet Profile은 합성 평가 메타데이터이며 실제 사용자 Gold가 아니다.

| 방식/모델 | 진단 일치율 | 실패/검토 | 실행 시간 |
| --- | ---: | ---: | ---: |
| Rule-only | 72.50% | 검토 36건 | 즉시 |
| Rule-first Hybrid | 72.50% | fallback 실패 22건 | 증가 |
| Qwen 2.5 3B | 12.06% | 실패 1건 | 424초 |
| Qwen 3 1.7B | 3.06% | 실패 4건 | 측정 불가 |
| Qwen 3 8B | 성공 행 기준 57.02% | 실패 79건 | 1,226초 |
| Llama 3.2 3B | 성공 행 기준 8.08% | 실패 101건 | 측정 불가 |
| EXAONE 3.5 2.4B | 13.57% | 실패 1건 | 550초 |
| Phi-4 Mini | 4.00% | 실패 0건 | 329초 |

추가로 현재 보존된 5,000건 Rule Labeling 결과에서는 다음을 확인했다.

| 항목 | 결과 |
| --- | ---: |
| 전체 | 5,000건 |
| 기대 Profile과의 진단 일치 | 73.66% |
| 정상 Label | 4,275건 |
| 검토 필요 | 725건 (14.5%) |

### 4.1 Model 2 선택

Model 2의 기본 구조는 `Rule-first Hybrid`로 한다.

```text
Rule/Alias 처리
→ 명확하면 즉시 Label 확정
→ 미해결·모호·충돌 건만 LLM 호출
→ Taxonomy/Schema 검증
→ 실패 또는 충돌은 NEEDS_REVIEW
```

LLM fallback을 반드시 사용해야 한다면 현재 로컬 100건 추가 비교에서는 Qwen 2.5 7B를 1차 후보로 둔다. 다만 이 결과는 별도 100건 샘플에 대한 결과이므로 자동 확정 모델로 채택하지 않으며, 미해결·충돌 건에만 제한적으로 호출한다.

Qwen 3 8B는 성공 응답의 일치율은 가장 높았지만 실패율과 실행 시간이 MVP 운영 조건에 맞지 않는다.

### 4.2 현재 Ollama Live Smoke

현재 기기의 Ollama 설치 모델을 동일한 5건으로 추가 확인했다. 제품 기본 Facet 매핑 파일이 없는 환경이므로 모든 모델에 빈 `product_defaults`를 넣고 `extra_requirement`와 Taxonomy만 비교했다.

| 방식/모델 | 5건 응답 | 진단 일치 | 비고 |
| --- | ---: | ---: | --- |
| Rule-only | 5 | 5/5 | 기존 저장 Label 기준 |
| Qwen 2.5 7B | 5 | 5/5 | smoke 결과 |
| Llama 3.2 3B | 5 | 1/5 | 잘못된 Category/Facet 코드 출력 포함 |
| EXAONE 3.5 7.8B | 5 | 0/5 | 유효 응답이나 대부분 ALL 처리 |
| EXAONE 3.5 2.4B | 0 | 측정 불가 | Ollama HTTP 500 |

이 결과는 5건 smoke이므로 최종 모델 선택 지표로 승격하지 않는다. 다만 현재 로컬 런타임에서 Qwen은 응답·Taxonomy 적용이 가능했고, EXAONE 2.4B는 실행 오류가 발생했다. 최종 선택은 동일 200건 전체 비교 결과와 Rule-first 정책을 우선한다.

### 4.3 Ollama 100건 전체 추가 비교

현재 저장된 5,000건 입력의 앞 100건을 동일하게 사용했다. 모든 모델은 1건씩 호출했으며, 제품 기본 Facet 매핑이 없는 환경이므로 `product_defaults`는 비워 두었다. Hybrid는 Rule 결과가 명확하면 유지하고, 검토 대상에만 Taxonomy 검증을 통과한 모델 결과를 적용하는 방식으로 계산했다.

| 방식 | 응답/커버리지 | 진단 일치 | 경고·검토 | 실행 시간 |
| --- | ---: | ---: | ---: | ---: |
| Rule-only | 100/100 | 66/100 (66%) | 14건 | 즉시 |
| Qwen 2.5 7B Model-only | 100/100 | 60/100 (60%) | 2건 | 약 210초 |
| Qwen 2.5 7B Hybrid | 100/100 | 68/100 (68%) | 0건 | 약 210초 |
| Llama 3.2 3B Model-only | 100/100 | 11/100 (11%) | 78건 | 약 91초 |
| Llama 3.2 3B Hybrid | 100/100 | 66/100 (66%) | 12건 | 약 91초 |
| EXAONE 3.5 7.8B Model-only | 100/100 | 1/100 (1%) | 1건 | 약 446초 |
| EXAONE 3.5 7.8B Hybrid | 100/100 | 64/100 (64%) | 1건 | 약 446초 |

이 100건은 기존 200건 비교와 다른 샘플·모델 크기이므로 기존 결과를 대체하지 않는다. 그러나 현재 로컬 환경의 추가 근거로는 Qwen 2.5 7B를 제한적 Hybrid fallback 후보로 올릴 수 있다. Model-only는 운영 방식으로 채택하지 않는다.

### 4.4 동일 200건 최종 추가 비교

앞서 실행한 100건과 이어서 실행한 100건을 합쳐 동일한 200건 전체를 평가했다. Qwen 2.5 7B는 모든 행에 응답했으며, 각 요청을 1건 단위로 호출했다.

| 방식 | 응답/커버리지 | 진단 일치 | 경고·검토 | 실행 시간 |
| --- | ---: | ---: | ---: | ---: |
| Rule-only | 200/200 | 138/200 (69%) | 28건 | 즉시 |
| Qwen 2.5 7B Model-only | 200/200 | 118/200 (59%) | 5건 | 약 433초 |
| Qwen 2.5 7B Hybrid | 200/200 | 142/200 (71%) | 0건 | 약 433초 |

동일 200건 기준으로 Qwen Model-only는 Rule-only보다 낮았지만, Rule-first Hybrid는 Rule-only보다 2%p 높았다. 따라서 Qwen 2.5 7B는 제한된 fallback 후보로 채택하고, Model-only 방식은 배제한다.

## 5. 최종 MVP 선택

```text
Model 1:
  Rule/통계 기반 Facet 후보 생성
  + Kanana LLM 후보 보조
  + Evidence Gate
  + Human Review

Model 2:
  Rule-first Hybrid Demand Labeling
  + 필요 시 Qwen 2.5 7B fallback 후보
  + Taxonomy/Schema 검증
  + 실패·충돌 Review Queue

Embedding:
  Model 2와 분리
  B/C의 Cluster 후보 검색 및 Seller Matching에서 별도 평가
```

## 6. 현재 한계

- Model 1 결과는 Human Review 승인율까지 확정되지 않았다.
- Model 2 평가 Gold는 합성·검토 데이터이며 실제 사용자 데이터가 아니다.
- 현재 환경에서는 Ollama 서버가 실행되지 않아 Model 2 신규 모델 실행을 재현하지 못했다.
- 최신 Model 2 비교를 새로 실행하려면 동일한 200건 입력, Taxonomy, Ollama 모델 가중치가 필요하다.
- LLM이 Rule-only보다 개선되는지 확인되기 전까지 LLM 결과를 자동 확정하지 않는다.

## 7. 재현 명령

### Model 1 Hybrid 평가

```bash
PYTHONPATH=src .venv/bin/python scripts/model1/run_hybrid_facet_benchmark.py \
  --input data/processed/model1_multisource_v2/multisource_model_input_v1.jsonl \
  --model-candidates /tmp/model1-kanana-210-fixed/kanana_candidates_210_fixed.csv \
  --output-dir data/processed/model1_hybrid_kanana_210_fixed
```

### Model 1 Taxonomy 초안

```bash
PYTHONPATH=src .venv/bin/python scripts/model1/build_hybrid_taxonomy_draft.py \
  --hybrid data/processed/model1_hybrid_kanana_210_fixed/hybrid_candidates_v1.csv \
  --input data/processed/model1_multisource_v2/multisource_model_input_v1.jsonl \
  --output-dir data/processed/model1_hybrid_kanana_210_fixed \
  --min-support 2 --min-ratio 0.1
```

### Model 2 비교

Model 2 비교는 동일한 200건 평가 입력과 Rule/Hybrid/Model-only 산출물을 준비한 뒤 `scripts/evaluation/compare_demand_labeling_models.py`로 실행한다. 모델이 없거나 Ollama가 실행되지 않으면 성공으로 기록하지 않고 `NOT_RUN` 또는 `BLOCKED_NO_EXECUTABLE_MODEL`로 기록한다.

## 8. 다음 단계

1. Model 1 Human Review 결과를 반영해 Taxonomy를 확정한다.
2. Model 2는 Rule-first Hybrid를 런타임 기본값으로 연결한다.
3. 필요한 경우 EXAONE fallback을 제한된 검토 대상에만 연결한다.
4. Embedding 후보 모델은 B/C의 Cluster·Matching 입력과 동일한 평가 세트로 별도 비교한다.
5. 최종 Label·Taxonomy 결과를 A 파트 DB 쓰기 배치와 E2E에 연결한다.
