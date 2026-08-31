# 뭉치 AI (MoongCheap AI)

수요 주도형 공동구매 플랫폼의 AI 파트 저장소입니다.

## AI MVP

1. **상품 Facet Discovery 및 Demand Labeling**
   - 상품 원문에서 Facet/Value/Alias 후보를 도출하고 Human Review 후 taxonomy를 확정
   - Backend가 저장한 Demand의 `extra_requirement`를 승인된 Facet Value와 Label로 변환
   - 자연어 처리는 실시간 요청이 아닌 비동기 Batch를 기본으로 함

2. **Demand Clustering**
   - 동일 `catalog_id`를 우선으로 Facet/가격/수량/대체상품 조건을 비교
   - `demand_board`를 Cluster로 사용
   - V0는 Rule 기반으로 시작하고 Embedding/Hybrid는 Gold Set 실험 후 선택

3. **Seller Offer Matching 및 Seller Demand Analysis**
   - Seller Offer는 `product`, 매칭 결과는 `product_award_evaluation`을 사용
   - 최종 매칭은 재현 가능한 Rule/Score 기반으로 처리하며 LLM의 임의 판단에 맡기지 않음
   - 수요 분석 수치는 SQL/Python 집계가 원천이며 LLM은 선택적 설명만 담당

## System boundaries

- AI와 Backend는 동일한 PostgreSQL을 사용합니다.
- AI는 Backend가 생성한 원본 Demand를 조회하고 AI 파생 결과만 기록합니다.
- AI는 인증·권한, 원본 데이터, 수요·응찰·낙찰 상태를 관리하지 않습니다.
- AI 전용 DB, 임의의 테이블/컬럼/상태 추가를 전제로 하지 않습니다.
- Consumer RAG 챗봇은 현재 MVP에서 제외합니다.
- 특정 모델(Qwen3 등), Vector DB, 상시 모델 서버는 확정하지 않습니다.

## Repository structure

- `src/moongcheap_ai`: AI 서비스 및 데이터 파이프라인 구현
- `docs`: AI 설계, Facet taxonomy, API contract, 평가 및 실험 문서
- `.github`: PR/이슈 템플릿 및 협업 설정

## Development workflow

1. `main`에서 작업 브랜치를 생성합니다.
2. 작업 Branch에서 기존 AI Commit Convention을 따릅니다.
3. `develop` 대상 PR로 개발 통합 및 Dev 배포를 진행합니다.
4. 검증 후 `main`에 반영하여 Demo/Production 배포를 진행합니다.
5. 작성자가 아닌 팀원 1명의 승인과 CI 통과 후 squash merge합니다.

자세한 규칙은 [CONTRIBUTING.md](CONTRIBUTING.md)를 참고하세요.
