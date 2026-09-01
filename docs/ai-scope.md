# AI 범위 및 인수인계

이 문서는 현재 AI MVP의 기준 문서입니다.

## MVP 기능

1. **Facet Discovery and Demand Labeling**
   - 상품 원문에서 Facet/Value/Alias 후보를 생성하고 Human Review 후 승인합니다.
   - Backend가 저장한 Demand의 `extra_requirement`를 승인된 Facet Value와 Label로 변환합니다.
   - 요청마다 실시간 호출하지 않고 비동기 Batch로 처리합니다.

2. **Demand Clustering**
   - 동일 `catalog_id`를 우선하고 Facet 호환성, 가격, 수량, `is_substitutable`을 비교합니다.
   - Cluster는 `demand_board`로 표현합니다.
   - V0는 Rule 기반이며 Embedding/Hybrid는 평가 결과가 있을 때만 도입합니다.

3. **Seller Offer Matching and Seller Demand Analysis**
   - Seller Offer는 `product`, 매칭 결과는 `product_award_evaluation`을 사용합니다.
   - Matching은 Rule/Score 기반으로 재현 가능해야 합니다.
   - 분석 수치는 SQL/Python 집계가 원천이고, LLM은 필요 시 설명만 생성합니다.

## 담당 범위

- AI와 Backend는 동일 PostgreSQL을 사용합니다.
- AI는 허용된 원본을 조회하고 AI 파생 결과만 기록합니다.
- Consumer/Seller 원본, 인증·권한, 거래 상태는 Backend 소유입니다.
- AI는 수요·응찰·낙찰 상태를 변경하지 않습니다.
- Consumer RAG 챗봇은 MVP에서 제외합니다.

## 아직 확정하지 않은 항목

- Embedding 사용 여부와 모델
- Vector DB 및 모델 서버 구성
- Facet/Label/Cluster/Matching Weight
- Cluster Threshold와 가격 Compatibility 공식
- Seller Analysis 생성 모델 사용 여부

모든 변경은 Gold Set과 재현 가능한 실험 결과를 기준으로 판단합니다.
