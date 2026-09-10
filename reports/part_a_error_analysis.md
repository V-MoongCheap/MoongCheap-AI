# Part A Parser Error Analysis

## 상태

`GOLD_200_STATUS = NOT_FOUND`

이번 분석의 기준이 되는 Grounded Demand 200건 원본과 정답 라벨을 저장소에서 확인하지 못했다. 따라서 현재 단계에서는 기존 파서의 오류 사례를 재구성하거나 규칙을 수정하지 않는다.

## 조사 범위

- 현재 작업 트리의 `data/`, `evaluation/`, `tests/`, `reports/`, `scripts/`, `archive/`
- 추적 중인 모든 Git ref와 이력
- Git unreachable object에 남아 있는 파일 경로
- 저장소 상위 작업공간의 관련 CSV/JSON/JSONL 파일

## 확인된 관련 산출물

| 자료 | 확인 내용 | Gold 200으로 사용할 수 없는 이유 |
|---|---|---|
| `data/processed/downstream_v2_2/taxonomy_v2_2_demand_regression.csv` | 200행에 대한 집계 결과와 `diagnostic_agreement=0.725` | 구매요청 원문, 행별 정답, 행별 파서 결과가 없음 |
| `reports/taxonomy_v2_2_demand_regression.md` | 동일한 회귀 집계 요약 | 원본 입력과 expected label이 없음 |
| `data/processed/mvp_e2e_v2_2/part_a_runtime_v2_2.csv` | 20건 Smoke 입력/결과 | 200건 Gold Set이 아님 |
| `handoff/mvp_shared/smoke/demands_v2_2.csv` | 20건 공유 Smoke 입력 | 200건 Gold Set이 아니며 정답 기준도 아님 |

기존 `0.7250 (145/200)`은 과거 실행의 집계값으로만 기록한다. 원본 Gold 200이 없는 현재 상태에서는 이를 재현 가능한 현재 기준선으로 주장하지 않는다.

## 분석 결과

- `BASELINE_STATUS`: `NOT_REPRODUCIBLE_WITHOUT_GOLD_200`
- `ERROR_CASE_DATASET`: 생성하지 않음. 입력과 정답이 없는 상태에서 사례를 만들면 임의의 Gold를 합성하게 됨
- `diagnostic_agreement`: 현재 재계산하지 않음
- 오류 유형별 건수: 현재 계산하지 않음
- MUST/PREFER/EXCLUDE, 부정 범위, OR/ANY_OF, 다중 절, Alias 규칙: 수정하지 않음
- Taxonomy, Alias, A→B Contract, B/C 구현: 수정하지 않음

오류 검수용 CSV 스키마는 `data/evaluation/part_a_error_cases.csv`에 헤더만 준비되어 있다. 데이터 행은 실제 Gold 200을 확보한 뒤에만 추가한다.

## 재개에 필요한 입력

다음 조건을 만족하는 원본 파일 또는 저장소 위치가 필요하다.

- 200개 구매요청의 원문 텍스트
- `demand_id`, `category_id` 또는 category 식별자
- expected status
- expected facet/value 또는 비교 가능한 정답 제약
- 가능하면 작성 기준과 라벨 버전

원본을 받으면 현재 Part A 런타임으로 재실행하고, 실제 결과를 기준으로 `expected_*`와 `actual_*`를 행 단위로 비교한다. 이후에만 오류 분류, 우선순위화, 규칙 개선, 회귀 테스트를 진행한다.

## 결론

현재는 품질 개선 작업이 데이터 부재로 차단된 상태다. 20건 Smoke 데이터나 과거 집계표를 Gold 200으로 대체하지 않았으며, 새로 생성한 200건도 Gold로 취급하지 않았다.
