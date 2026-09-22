# Model 1 / Model 2 선택 상태 V2

## 결론 요약

현재 운영 구조와 기본 모델 사용 정책을 확정한다. LLM 후보의 탐색 결과를
최종 Taxonomy나 Label의 자동 승인 근거로 사용하지 않는다.

- Model 1: `kakaocorp/kanana-nano-2.1b-instruct`를 오프라인 후보 생성기로 사용한다. Rule/통계 근거가 승격 gate이고, LLM 후보는 Human Review 전까지 후보로만 둔다.
- Model 2: `Rule/Alias`를 서버 운영 방식으로 확정한다. 현재 배포 리소스와 품질 검증을 통과한 LLM fallback이 없으므로 운영 경로에서는 LLM을 호출하지 않는다.
- LLM 단독 결과를 운영 Label 또는 최종 Taxonomy로 자동 승인하지 않는다.

### 현재 로컬 후보의 범위

Kimi 계열을 전체 제외하지 않는다. 공식 Moonshot 후보인
`moonshotai/Moonlight-16B-A3B-Instruct`는 총 16B 파라미터의 MoE 모델이며
활성 파라미터가 약 3B인 별도 비교 후보로 둔다. 다만 24GB Apple Silicon에서는
원본 BF16 가중치가 현실적인 기본 경로가 아니므로, 4-bit MLX/GGUF 양자화판을
별도 런타임에서 평가한다. `Kimi-K2/K2.6/K3` 같은 초대형 계열은 현재 로컬
MPS 평가 범위에서 제외한다. Kimi-VL은 멀티모달 모델이므로 현재 텍스트 전용
Facet/Label 비교의 기본 후보로 사용하지 않는다.

Kanana는 기존 Transformers 4 계열 환경에서 평가한다. Transformers 5 계열
환경으로 옮겨서 판단하지 않는다.

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

Rule-first Hybrid가 Rule-only보다 유의미하게 개선되지 않으면 Model 2 LLM fallback은 사용하지 않는다. 현재 최신 Gold 15건에서는 Rule-first의 의미 일치가 15/15였으므로, fallback은 기본 비활성 상태로 유지한다.

### 서버 배포 제약을 반영한 추가 모델 평가

현재 A labeling CronJob은 CPU 1 / Memory 2Gi request, CPU 2 / Memory 3Gi limit이며,
Docker 이미지에 Ollama와 모델 가중치를 포함하지 않는다. 따라서 로컬 GPU에서
정상 실행되는 것만으로는 서버 후보로 승격하지 않는다.

| 후보 | 양자화/크기 | 동일 Gold 및 샘플 측정 | 결론 |
| --- | --- | --- | --- |
| `qwen2.5:7b-instruct` | Q4_K_M / 4.7GB | 85건 153초, 실패 0건. 현재 Pod 리소스 초과 | 제외 |
| `qwen3:4b` | Q4_K_M / Ollama 상주 약 2.9GB | Gold 15건 성공. 조건 포함 10건 중 비기본 결과 2건. 200건 303초 | 품질 부족으로 제외 |
| `llama3.2:3b` | Q4_K_M / 2.0GB | Gold 15건 중 6건 실패 및 Taxonomy 오류 | 제외 |
| `exaone3.5:2.4b` | Q4_K_M / 1.6GB | Gold 15건 전건 HTTP 500 | 제외 |

Qwen 3 4B의 200건 결과는 Mac GPU 실행이라 Kubernetes CPU 처리량을 보장하지
않는다. 또한 응답 성공률과 조건 해석 정확도는 별개다. 현재 후보 중 서버
리소스와 품질을 동시에 만족한 LLM은 없다.

따라서 최종 Model 2 운영 방식은 다음과 같다.

1. Rule/Alias 기반 Labeling을 기본 서버 경로로 사용한다.
2. `ALL`, 부정 조건, 충돌 조건, Taxonomy 외 조건은 규칙에 따라 처리하고 불확실한 행은 `REVIEW`로 남긴다.
3. 로컬 LLM fallback은 현재 배포하지 않는다.
4. LLM을 다시 도입하려면 별도 Worker/Pod와 별도 리소스, CPU 환경 재평가가 선행되어야 한다.

## 다음 실행 순서

1. Model 1 후보 모델을 동일한 multisource 입력으로 실행
2. Model 1 후보 결과를 Evidence gate와 Human Review queue로 평가
3. Model 2 후보 모델을 동일한 Dev/Holdout/Challenge 입력으로 실행
4. Rule-only와 Hybrid의 개선폭 비교
5. Model 1 Evidence Gate와 Model 2 Rule-first 회귀 결과를 CI에서 검증
6. 승인된 Taxonomy와 Labeling policy를 `category.facet` 및 런타임 문서에 반영

## 자동 검증 명령

Model 1 후보는 아래 Evidence Gate를 통과한 뒤에만 검토 큐로 보낸다.

```bash
PYTHONPATH=src .venv/bin/python scripts/model1/audit_multisource_quality.py \
  --input <multisource_model_input.jsonl> \
  --candidates <multisource_model_candidates.csv> \
  --output <model1_quality_audit.json>
```

Model 2 5천 건 생성기의 LLM fallback은 `LABELING_LLM_FALLBACK_ENABLED=false`가
기본값이며, 현재 서버 운영에서는 활성화하지 않는다. 후보 재실험이 필요할 때만
`--enable-llm-fallback`을 명시한다.

실제 모델 가중치·Ollama/Hugging Face/API 환경이 없는 경우에는 모델을 실행한 것처럼 처리하지 않고, 해당 후보를 `NOT_RUN`으로 기록한다.
