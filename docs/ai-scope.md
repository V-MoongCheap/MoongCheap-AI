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
   - 신규 Board는 높은 Price Band의 인접 window부터 결정론적으로 판정합니다.
   - 인접 Band는 낮은 Band 참여자가 높은 Band 참여자 이상일 때 묶고, Board 가격은 낮은 Band를 사용합니다.
   - 기존 Board 자동 편입은 동일 `catalog_id`와 동일 Price Band에만 허용하며, 기존 Board가 없는 Demand만 신규 Board 형성 대상으로 사용합니다.
   - 인접 Price Band 결합은 신규 Board 형성 시에만 적용합니다. 소비자의 기존 Board 직접 참여는 Backend 기능입니다.
   - PostgreSQL 입력 조회는 `pay_method_id IS NOT NULL`인 Demand만 대상으로 하며 DB 상태를 변경하지 않습니다.
   - `reject_history`의 동일 `(demand_id, demand_board_id)`는 대체 보드 재제안에서 제외합니다. 다른 수요나 같은 상품의 다른 보드는 이 이력만으로 제외하지 않습니다.
   - Part A의 `label`과 `processed_at` 완료를 runtime 진입조건으로 기다리지 않습니다. 원본 `extra_requirement`를 읽고 대체상품 동의자에게 필요한 typed constraint를 배치 안에서 해석합니다.
   - 최소 참여자 수는 `CLUSTER_MIN_PARTICIPANTS`로 주입하며 기본값은 5명입니다.
   - 미배정 Demand는 등록 후 최대 2일 동안 신규 Board 형성 대상입니다.
   - 운영 요청 경로에는 외부 LLM API나 자체 LLM 서버를 두지 않습니다. 외부
     LLM은 오프라인 평가·관계 후보 검수에만 사용합니다. 검증된 CPU embedding은
     운영 순위 계산에도 사용할 수 있으며, 정적 데이터는 사전 계산한 artifact를
     우선 조회합니다.
   - 현재 배치 CLI는 활성 보드 catalog의 동일 카테고리와 claim ID 포함관계를
     검사합니다. CPU E5는 PASSTHROUGH 자연어 선호 점수 계산에만 사용합니다.
     E5 기능문구 Top-10/20과 승인 relation 검색은 별도 오프라인 평가 경로입니다.
   - 생성·편입 계획과 대체 제안을 순서대로 두 Backend 내부 API에 전달합니다.
     Backend가 현재 수요·보드·가격·대체 동의를 다시 확인하며, 제안 시 참가자 수는
     증가시키지 않습니다. 실패한 요청은 재전송하지 않으며, 다음 정기 배치에서
     PostgreSQL의 최신 상태를 조회해 유효한 미편입 수요를 새로 계산합니다.

3. **Seller Offer Matching and Seller Demand Analysis**
   - Seller Offer는 `product`, 매칭 결과는 `product_award_evaluation`을 사용합니다.
   - Matching은 Rule/Score 기반으로 재현 가능해야 합니다.
   - 분석 수치는 SQL/Python 집계가 원천이고, LLM은 필요 시 설명만 생성합니다.

## 담당 범위

- AI와 Backend는 동일 PostgreSQL을 사용합니다.
- AI는 허용된 원본을 조회하고 AI 파생 결과만 기록합니다.
- 상품도감과 catalog ID는 Part A를 기준으로 하며 수요·보드 입력도 같은 ID를 사용해야 합니다.
- 수요 클러스터링은 원본 DB를 읽기 전용으로 조회하며 재전송용 요청 파일을 저장하지 않습니다.
- Consumer/Seller 원본, 인증·권한, 거래 상태는 Backend 소유입니다.
- AI는 수요·응찰·낙찰 상태를 변경하지 않습니다.
- Consumer RAG 챗봇은 MVP에서 제외합니다.

## B파트 후속 연동·협의 항목

- Part A 상품도감 기준 profile·taxonomy와 CPU E5 모델 파일 공급·버전 관리
- 두 내부 API의 합의한 계약에 대한 Backend 구현 확인과 실연동 검증
- Parameter Store 키 주입, Docker 이미지·스케줄 배포
- Backend의 `reject_history` 테이블 배포·거절 저장, AI SELECT 권한과 API 2 동시성 재검증 확인
- 별도 평가 경로의 relation 승인·artifact 발행 및 오프라인 E5 catalog embedding 갱신

## 아직 확정하지 않은 항목

아래는 공통·타 파트의 협의 항목이며, B파트의 현재 실행 계약은 위에 별도로 정리합니다.

- Embedding 사용 여부와 모델
- Vector DB 및 모델 서버 구성
- Facet/Label/Cluster/Matching Weight
- Cluster Threshold와 가격 Compatibility 공식
- Seller Analysis 생성 모델 사용 여부

모든 변경은 Gold Set과 재현 가능한 실험 결과를 기준으로 판단합니다.
