# AI 파트 Day 1 완료 보고

## 범위

Day 1은 특정 LLM 모델을 선정하는 날이 아니라, ERD v5와 Mock 실행 환경을 기준으로
AI 파트의 실행 계약·검증 경계·재현 가능한 테스트 기반을 고정하는 단계로 마무리한다.

## 완료 항목

- ERD v5 기준 AI 데이터 경로 확인
  - `demand.catalog_id`
  - `product_catalog.category_id`
  - `category.facet`
- A 파트의 DB 직접 쓰기 범위 확인
  - `demand.label`
  - `demand.processed_at`
- 로컬 Mock PostgreSQL 구성 및 Labeling Smoke Test
- Facet Taxonomy 계약 확인
  - 모든 Facet의 `ALL = code 0`
  - Facet Value code 결정론적 정렬
  - Human Review 전 상태 `DRAFT_PENDING_HUMAN_REVIEW`
- Model 1 후보와 Model 2 Labeling 평가 입력·출력 범위 분리
- Rule-first Hybrid의 Evidence Gate와 Model-only Review 경계 확인
- Kimi·Kanana 등 후보 모델의 실행 환경을 기본 프로젝트 환경과 분리
- 전체 테스트 및 이상 입력 검증 완료

## Day 1에서 확정하지 않는 항목

- Model 1 최종 LLM
- Model 2 fallback LLM
- DB 계정·Secret 발급 주체
- 실제 Infra 자원과 배포 endpoint

위 항목은 Day 2 이후 동일 평가셋과 운영 조건으로 비교한다.

## 다음 단계 진입 조건

Day 2부터 Model 1과 Model 2를 별도 평가한다.

- Model 1: Facet 후보 품질·근거성·계약 준수율
- Model 2: Label 정확도·fallback 안정성·API 응답시간·DB 멱등성

이 문서는 모델 선정 결과를 의미하지 않으며, Day 1의 기반 작업 완료 상태만 기록한다.
