# Part A 통합 현재 상태

## 범위

이번 문서는 Part A의 Consumer Demand 추가 요구사항 정규화와 Facet Labeling만 기록한다. Category, Taxonomy, Alias 승인 결과는 변경하지 않았고, Part B 클러스터링 규칙과 Part C 판매자 매칭 규칙도 변경하지 않았다.

## 실제 실행 경로

- 권장 로컬/배치 진입점: `scripts/labeling/run_part_a_runtime.py`
- 핵심 런타임: `src/moongcheap_ai/data_foundation/part_a_runtime.py`
- 입력: Backend Demand CSV 또는 `data_foundation.postgres_reader.read_unprocessed_demands()` 결과
- Taxonomy: `config/facet_taxonomy_v2_2.json` (`v2.2`, APPROVED)
- 규칙: `config/demand_constraint_rules.json`
- Alias: `config/model1_aliases_reviewed_v2.json`
- 외부 LLM 호출: 없음

기존 `data_foundation/runtime_job.py`는 이전 `label/facet_values` 전송 계약을 유지하는 호환 진입점이다. 새 V2.2 상태·제약 계약 검증에는 Part A 런타임을 사용한다.

## 입력 필드 확인

현재 저장소의 read-only SQL adapter는 `demand`와 `product_catalog`에서 다음을 읽는다.

`demand_id`, `catalog_id`, `category_id`, `extra_requirement`, `desired_price_min`, `desired_price_max`, `quantity`, `is_substitutable`, `processed_at`

Backend 소유 원본 상태와 가격·수량은 A가 재작성하지 않는다. A는 category가 입력에 없을 때 제공된 catalog mapping으로만 보완한다.

## 처리 결과

Part A는 `PARSED`, `PASSTHROUGH`, `NONE`, `CONFLICT`, `TAXONOMY_AMBIGUOUS`, `REVIEW`, `NOT_APPLICABLE`을 유지한다. `effectiveRequirementMode`는 구조화 결과면 `STRUCTURED`, 원문 전달이면 `SEMANTIC_TEXT`, 나머지는 `NONE`으로 내려간다.

행 단위 파서 예외는 전체 배치를 중단하지 않고 `REVIEW`와 `PARSER_EXCEPTION`으로 격리한다. 성공적으로 처리된 행만 `processed_at`을 기록하며 예외 행은 빈 값으로 남긴다.

## 실행 확인

로컬 20건 입력 결과:

- `PARSED`: 11
- `PASSTHROUGH`: 2
- `NONE`: 2
- `CONFLICT`: 1
- `NOT_APPLICABLE`: 4
- `REVIEW`: 0
- 외부 LLM 호출: 0

200건 회귀 원본 Demand 파일은 현재 checkout에 존재하지 않았다. `taxonomy_v2_2_demand_regression.csv`는 이미 생성된 집계 결과이며 Demand 입력으로 재실행하지 않았다.

