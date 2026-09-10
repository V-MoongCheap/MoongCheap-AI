# Part A V2.2 Gold 후보 검수 가이드

이 문서는 `data/review/part_a_v2_2_gold_human_review.csv`를 검수하기 위한 안내서다.
현재 200건은 모두 후보이며 `PENDING_REVIEW` 상태다. 검수 전에는 성능 수치나 Gold 정확도를 계산하지 않는다.

## 검수 순서

각 행에서 다음 순서로 확인한다.

1. `category_id`가 요청의 대상 Category와 맞는지 확인한다.
2. `extra_requirement`를 읽고 `proposed_expected_status`가 적절한지 판단한다.
3. `proposed_expected_mode`와 제약 JSON을 확인한다.
4. 여러 조건이면 `proposed_expected_constraints`와 `proposed_expected_preference_groups`를 함께 확인한다.
5. `is_substitutable=false`이면 추가 조건을 적용하지 않는 `NOT_APPLICABLE`이 맞는지 확인한다.
6. `reviewer_status`를 `APPROVED`로 바꾸거나, 수정이 필요하면 `CORRECTED`로 표시하고 corrected 필드를 채운다.
7. 판단 근거를 `reviewer_note`에 짧게 남긴다.

## 상태 판단 기준

| 상태 | 의미 | 예시 |
|---|---|---|
| `PARSED` | Taxonomy의 facet/value로 구조화 가능 | 특정 제형을 반드시 원함 |
| `PASSTHROUGH` | 의미 있는 요구지만 현재 Taxonomy value로 구조화하지 않음 | 먹기 편한 제품 |
| `NONE` | 추가 요구가 없음 | 빈 문자열 |
| `CONFLICT` | 같은 facet에 동시에 양립할 수 없는 조건 | 캡슐과 분말을 모두 같은 우선도로 요구 |
| `TAXONOMY_AMBIGUOUS` | 후보가 있으나 어느 canonical value인지 확정하기 어려움 | 표현이 여러 value에 걸침 |
| `REVIEW` | 자동 구조화보다 사람 판단이 필요한 문장 | 문맥이 불명확함 |
| `NOT_APPLICABLE` | `is_substitutable=false`로 추가 조건을 적용하지 않음 | 대체품 불허 요청 |

## 조건 유형 판단 기준

- `MUST`: 반드시, 꼭, 필수 등 강제 조건
- `PREFER`: 가능하면, 선호, 좋겠어요 등 선호 조건
- `EXCLUDE`: 제외, 빼기, 원하지 않음, 포함 금지 등 배제 조건
- `ANY_OF`: “A 또는 B”, “A나 B”처럼 대안 중 하나를 허용하는 선호 그룹

부정 표현은 문장 전체가 아니라 해당 절의 대상에만 적용한다. 예를 들어 “분말은 제외하고 캡슐은 꼭”이면 분말은 `EXCLUDE`, 캡슐은 `MUST`다.

## 메타데이터 읽는 법

- `candidate_origin`: 기존 검수 Fixture 재사용인지, 새 Standard/Challenge 후보인지
- `source_reference`: 후보를 만든 원본 파일
- `existing_test_case_id`: 기존 Fixture에서 온 경우의 원래 case ID
- `parser_exposure`: 기존 테스트에서 확인된 표현인지, 새 표현인지
- `evaluation_partition_candidate`: 검수 후 DEV/HOLDOUT/CHALLENGE로 내보낼 후보 구분

`proposed_*` 값은 제안값일 뿐이다. `PENDING_REVIEW` 행은 Gold로 finalize할 수 없다.

## Finalize 조건

검수가 끝난 뒤 모든 행에 대해 `reviewer_status`가 승인 또는 수정 완료 상태여야 한다. 하나라도 `PENDING_REVIEW`이면 finalize 스크립트는 실패해야 한다. 확정 후에만 다음 파일을 생성한다.

- `part_a_v2_2_dev_gold.csv`
- `part_a_v2_2_holdout_gold.csv`
- `part_a_v2_2_challenge_gold.csv`

Legacy `72.50%`는 재현 불가능한 과거 참고값이므로 이 Gold Set의 Before 성능으로 사용하지 않는다.
