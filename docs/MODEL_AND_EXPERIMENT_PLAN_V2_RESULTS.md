# Model & Experiment Plan

## 10. 실험 결과

본 문서는 기존 `Model & Experiment Plan`의 10번 이후 결과를 최신 실험 기준으로 갱신한 보고서다.

평가 데이터는 프로젝트용 합성·검토 데이터다. 실제 운영 사용자로부터 수집한 Gold Set이 아니므로, 아래 수치는 모델의 일반화 성능을 증명하는 수치가 아니라 현재 MVP 방식의 상대 비교 결과로 해석한다.

### 10.1 최종 선정 결과

| Task | 선정 Model / Method | 주요 결과 | 선정 이유 |
| --- | --- | --- | --- |
| Facet Discovery | Rule/통계 기반 + Kanana 후보 보조 + Evidence Gate | Kanana 210행 실행, 후보 105행, 실패 20행, Rule 승격 0행 | Model-only 자동 확정 근거가 부족하며 Rule 근거와 Human Review가 안전함 |
| 자연어 해석 | Rule-first Hybrid + Qwen 2.5 7B 제한적 fallback | 동일 200건에서 Rule-only 69%, Model-only 59%, Hybrid 71% | Model-only보다 안전하고 Rule-only보다 2%p 개선 |
| Clustering | 동일 Catalog + Facet Compatibility + 가격 Rule | MVP 기준 적용 | 명확한 조건을 Rule로 통제하고 Embedding은 후보 검색 보조로 분리 |
| Seller Matching | Structured Rule + Weighted Scoring | Category, Facet, 가격, 수량, MOQ 중심 | 필수조건 위반을 명시적으로 통제할 수 있음 |
| Seller Demand Analysis | SQL/Python 집계 + Template 우선 | 수치 계산은 코드가 담당 | 숫자 오류와 근거 없는 설명 생성을 방지 |

### 10.2 Model 1: Facet Discovery 결과

대상 모델:

```text
kakaocorp/kanana-nano-2.1b-instruct
```

동일한 16개 Category, 210개 입력으로 실행했다.

| 항목 | 결과 |
| --- | ---: |
| 입력 행 | 210 |
| Category | 16 |
| 원시 후보 행 | 105 |
| 실패 행 | 20 |
| 실행 시간 | 약 627.93초 |
| Rule 후보 | 246 |
| Hybrid 후보 | 256 |
| Rule 근거로 자동 승격된 Model 후보 | 0 |
| Model-only 검토 후보 | 10 |

주요 실패 유형은 다음과 같다.

- `Transformers returned invalid JSON`
- 입력 데이터에 존재하지 않는 Evidence ID
- Taxonomy에 없는 Facet ID
- 숫자 Facet ID와 이름의 불일치

Model 1 결과는 다음 단계로 자동 확정하지 않는다.

```text
Rule/통계 근거 생성
→ LLM 후보 추가
→ Evidence ID·원문 검증
→ Human Review
→ Taxonomy 확정
```

### 10.3 Model 2: 전체 후보 비교 결과

#### 기존 200건 후보 비교

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

#### 동일 200건 Qwen 2.5 7B 재검증

기존 5,000건 입력의 앞 200건을 동일하게 사용하고, 각 요청을 1건씩 호출했다. 제품 기본 Facet 매핑 파일이 없는 환경이므로 `product_defaults`는 비워 두었다.

| 방식 | 응답/커버리지 | 진단 일치 | 경고·검토 | 실행 시간 |
| --- | ---: | ---: | ---: | ---: |
| Rule-only | 200/200 | 138/200 (69%) | 28건 | 즉시 |
| Qwen 2.5 7B Model-only | 200/200 | 118/200 (59%) | 5건 | 약 433초 |
| Qwen 2.5 7B Hybrid | 200/200 | 142/200 (71%) | 0건 | 약 433초 |

Qwen 2.5 7B는 Model-only에서는 Rule-only보다 낮았지만, Rule이 처리하지 못하는 대상에 제한적으로 적용한 Hybrid에서는 2%p 개선을 보였다.

#### Model 2 최종 운영 구조

```text
Rule/Alias 처리
→ 명확하면 즉시 Label 확정
→ 미해결·모호·충돌 건만 Qwen 2.5 7B 호출
→ Facet 이름·Value code·Schema 검증
→ 실패·충돌·근거 부족은 NEEDS_REVIEW
```

Model-only는 운영 방식으로 채택하지 않는다.

### 10.4 5,000건 Rule Baseline 확인

보존된 5,000건 Runtime Smoke 데이터에서 Rule 결과를 확인했다.

| 항목 | 결과 |
| --- | ---: |
| 전체 | 5,000건 |
| 기대 Profile과 진단 일치 | 73.66% |
| 정상 Label | 4,275건 |
| 검토 필요 | 725건 (14.5%) |

이 데이터도 합성·검토 데이터이므로 실제 사용자 정확도로 해석하지 않는다.

## 11. 제외된 후보 및 사유

| 후보 | 적용 대상 | 제외 또는 제한 사유 |
| --- | --- | --- |
| Model 1 LLM-only | Facet Discovery | 근거 없는 Facet·Value와 invalid JSON 발생, 자동 확정 불가 |
| Qwen 2.5 7B Model-only | Demand Labeling | 응답은 안정적이나 200건 일치율이 Rule-only보다 낮음 |
| Qwen 3 8B Model-only | Demand Labeling | 성공 응답 품질은 높지만 실패 79건, 실행시간 1,226초 |
| Llama 3.2 3B | Demand Labeling | 기존 비교와 추가 실행에서 Taxonomy 오류·낮은 일치율 발생 |
| EXAONE 3.5 2.4B | Demand Labeling | 기존 비교의 일치율이 낮고 현재 Ollama에서 HTTP 500 발생 |
| EXAONE 3.5 7.8B | Demand Labeling | 100건 추가 비교에서 Model-only 1% 일치, 실행시간 약 446초 |
| Model 2 Embedding 적용 | Demand Labeling | Model 2 역할이 자연어 Labeling이므로 Embedding과 분리 |
| LLM 숫자 계산 | Seller Demand Analysis | 수치와 집계는 SQL/Python으로 계산해야 함 |

## 12. 실험 해석 및 선택 이유

### 12.1 Rule-first를 선택한 이유

Rule-only는 다음 장점이 있다.

- Taxonomy에 존재하는 값만 반환하도록 통제 가능
- `ALL`, 미언급 Facet, 검토 상태를 명확하게 처리 가능
- 응답시간과 비용이 낮음
- 결과 재현성이 높음
- DB Batch와 실패 재처리가 쉬움

LLM은 자연어 표현의 확장성과 애매한 요청 처리에 유리하지만, Model-only에서는 Taxonomy 외부의 값, 잘못된 Facet 이름, 누락 응답이 발생할 수 있다. 따라서 LLM은 Rule 결과를 대체하는 주 처리기가 아니라 제한적 fallback으로 사용한다.

### 12.2 Qwen 2.5 7B를 fallback 후보로 둔 이유

- 동일 200건 전체에서 200건 응답 성공
- Model-only 59%로 Rule-only보다 낮지만, Hybrid 71%로 Rule-only보다 2%p 높음
- 소형 모델 후보 중 현재 Ollama 환경에서 재현 가능
- 요청 단위 호출과 Taxonomy 검증을 적용할 수 있음

이는 Qwen이 최종 정답 모델이라는 뜻이 아니다. 실제 운영에서는 실패·충돌·검토 대상에만 제한적으로 호출하며, 모델 결과가 Rule 결과를 덮어쓸 조건을 엄격히 제한한다.

## 13. 재현 명령

### 13.1 Model 1 Hybrid 평가

```bash
PYTHONPATH=src .venv/bin/python scripts/model1/run_hybrid_facet_benchmark.py \
  --input data/processed/model1_multisource_v2/multisource_model_input_v1.jsonl \
  --model-candidates /tmp/model1-kanana-210-fixed/kanana_candidates_210_fixed.csv \
  --output-dir data/processed/model1_hybrid_kanana_210_fixed
```

### 13.2 Model 2 전체 실행 전제

```bash
ollama list
export MODEL2_MODEL=qwen2.5:7b-instruct
```

Model 2 실행에는 동일한 Taxonomy, Demand 입력, Product Facet 매핑, Ollama 모델이 필요하다. 제품 기본 Facet 매핑이 없으면 본 보고서와 같이 빈 `product_defaults`를 사용한 비교가 가능하지만, 최종 운영 성능으로 해석하면 안 된다.

## 14. 한계 및 재검토 조건

- 현재 평가 데이터는 실제 사용자 Gold가 아니다.
- Model 1은 Human Review 승인율까지 확정되지 않았다.
- Model 2 200건은 프로젝트용 합성·검토 데이터다.
- Product Facet 매핑이 없는 Model 2 재검증에서는 제품 기본값을 비워 두었다.
- Qwen fallback은 현재 비교에서 개선을 보였지만, 데이터 분포가 바뀌면 재평가해야 한다.
- Rule-only가 충분히 개선되거나 LLM 호출 비용·지연이 커지면 LLM fallback을 제거할 수 있다.

## 15. 다음 실험 및 구현 단계

1. Model 1 Facet Review Queue를 Human Review하여 Taxonomy V0를 확정한다.
2. 확정 Taxonomy와 Product Facet 매핑을 기준으로 Model 2를 재평가한다.
3. Model 2의 `NEEDS_REVIEW` 입력만 Qwen fallback으로 호출하는 배치 경로를 구현한다.
4. A 파트 DB 직접 쓰기 배치와 멱등성·재처리 정책을 연결한다.
5. B 파트 Clustering 입력 계약에 Label과 상태 필드만 전달한다.
6. Embedding 모델 비교는 Model 2와 분리하여 B/C의 Cluster·Seller Matching 평가 세트로 진행한다.
