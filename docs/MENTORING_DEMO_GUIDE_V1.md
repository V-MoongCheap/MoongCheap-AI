# AI 파트 멘토링 시연 가이드

## 시연 목표

실제 DB, 외부 API, Ollama, AWS 없이 저장된 검증 산출물을 사용해 다음 흐름을 보여준다.

```text
상품·Taxonomy 근거
→ A Demand Labeling
→ B Demand Clustering
→ C Seller Matching / Seller Demand Analysis
```

## 사전 조건

- Python 가상환경이 준비되어 있어야 한다.
- 저장소 루트는 `moongcheap-ai`이다.
- 외부 API Key와 DB 계정은 필요하지 않다.
- 이 Demo는 검증된 로컬 산출물을 재사용하며 휴먼 리뷰를 실행하지 않는다.

## 실행 명령

```bash
cd /path/to/moongcheap-ai
PYTHONPATH=src .venv/bin/python scripts/demo/run_ai_mvp_demo.py --show-samples
```

파트별 시연:

```bash
# A: 자연어 요구사항 → 상태·Label
PYTHONPATH=src .venv/bin/python scripts/demo/run_ai_mvp_demo.py --stage a

# B: Label·상품조건 → Cluster
PYTHONPATH=src .venv/bin/python scripts/demo/run_ai_mvp_demo.py --stage b

# C: Cluster·Seller Offer → 후보 판정·분석
PYTHONPATH=src .venv/bin/python scripts/demo/run_ai_mvp_demo.py --stage c
```

## 예상 결과

- A Labeling: 5,000건
- B Cluster: 863개
- C Seller Offer 비교: 2,397,414건의 Cluster-Offer 비교 (원본 Offer 2,778건)
- C 분석: 863개 Cluster
- Model 2 Gold 최종 후보: 85건
- 현재 Taxonomy 호환 Gold: 15건
- Out-of-Taxonomy Gold: 70건

## 설명 순서

1. 상품 데이터와 Category/Facet Taxonomy를 기준으로 Demand의 명시적 요구조건을 Label로 변환한다.
2. 같은 Category·Label·상품 조건을 기준으로 B가 Demand를 Cluster로 묶는다.
3. C가 Cluster와 판매자 Offer를 비교하고, 조건을 만족하는 후보와 수요 분석을 출력한다.
4. 숫자 집계는 Rule/Python으로 수행하고, 타 판매자 가격은 낙찰 사유에 노출하지 않는다.
5. Gold Set은 최종 85건으로 확정했지만, 현재 Taxonomy에 없는 조건 70건은 성능 평가에서 분리했다.

## 파트별 설명 포인트

- A의 `PARSED`는 조건을 Label로 만들었다는 뜻이고, `CONFLICT`와 `PASSTHROUGH`는 억지로 확정하지 않고 상태를 보존한 결과다.
- B는 같은 Category·Label·상품 대체 조건을 기준으로 수요를 묶고, `participant_count`와 `total_quantity`를 집계한다.
- C는 현재 후보 판매자의 단가·MOQ·수량 조건과 통과 여부를 보여준다. 타 판매자 가격은 표시하지 않는다.
- 현재 C Demo의 `score=100`은 로컬 Rule baseline의 조건 통과 점수이며 최종 낙찰 확정이 아니다. 배송비·단가 상한 정책은 실제 C 정책 반영 단계에서 별도로 검증한다.

## 최근 2주 작업 요약

### 완료한 작업

- 실제 건강기능식품 상품·성분 근거를 정리하고 Category별 Facet 후보를 생성했다.
- Kanana 모델 결과와 Rule/Evidence를 결합해 Facet 후보를 정제했다.
- Facet 후보와 상품 Facet Mapping을 사람 검수 및 자동 정책으로 정리했다.
- `ALL=0`, 결정론적 Value Code, `UNKNOWN/UNMAPPED` 정책을 적용했다.
- 5,000건 Demand를 기준으로 A Labeling, B Clustering, C Matching/Analysis E2E를 실행했다.
- Model 2 검수 결과를 85건 Gold와 65건 Excluded로 확정했다.
- 전체 테스트 `861 passed, 26 skipped`를 확인했다.

### 현재 한계와 다음 작업

- Gold 85건 중 70건은 현재 Taxonomy에 없는 조건을 포함하므로 평가에서 별도 분리했다.
- 다음 실험은 Taxonomy 정합성을 정리한 뒤 Rule-only, Model-only, Hybrid를 동일 Gold에서 비교한다.
- Backend 실제 ID와 Cloud 배포는 각 파트의 환경이 준비된 뒤 통합 검증한다.
