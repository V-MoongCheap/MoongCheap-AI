# Model 1 Alias Human Review Guide

이 문서는 Naver Shopping Expression Reference에서 생성된 Alias 후보를 사람이 검수하기 위한 작업지다. 후보를 자동 승인하지 않으며 기존 Taxonomy에도 반영하지 않는다.

## Input and Review Policy
- input: `data\processed\expression_reference\naver_shopping_facet_alias_candidates.csv`
- total Alias Candidate: 66
- source_type: `KOREAN_SHOPPING_REVIEW_EXPRESSION_REFERENCE`
- category_id/category_name: 원본에 Category 정보가 없어 `NOT_AVAILABLE_SOURCE_HAS_NO_CATEGORY`로 기록
- reviewer_decision initial value: `PENDING_REVIEW`
- 승인값은 별도 Apply 단계에서만 Taxonomy에 병합 가능

## Structure Clarification
- 실제 Facet 종류 수: 8
- Review-supported 조합 수: 14
- 이 14개 조합은 Category-Facet 조합이 아니다.
- 기존 `facet_review_queue_v2.csv`에서 Review source count가 있는 행의 `facet_candidate + value_candidate` 고유 조합 수다.
- Category 정보가 없는 Naver Corpus를 사용했으므로 식별 가능한 Category-Facet 조합 수는 0이다.

## Review Columns
- `example_sentence_1`~`example_sentence_5`: 후보 표현이 실제로 포함된 원문 예시
- `naver_rating_distribution`: 별점별 문장 수. HFF 선호도나 HFF 중요도 지표가 아님
- `risk_flags`: TOO_SHORT, TOO_GENERIC, PRODUCT_OR_BRAND_CONTEXT, MEDICAL_OUTCOME, CONTEXT_AMBIGUOUS
- `CROSS_FACET_CONFLICT`: 동일 표현이 둘 이상의 Facet에 걸린 후보

## Summary
- Cross-facet conflict: 0
- Generic risk: 9
- Medical risk: 11
- Human review pending: 66

## Allowed Reviewer Decisions
`APPROVE_ALIAS`, `REJECT_TOO_GENERIC`, `REJECT_DIFFERENT_MEANING`, `REJECT_PRODUCT_SPECIFIC`, `REJECT_NON_HFF_CONTEXT`, `REJECT_MEDICAL_OUTCOME`, `NEEDS_REVIEW`

## Review Order
Occurrence count와 semantic similarity가 높은 후보를 우선 배치했다. Conflict와 Medical risk는 우선순위를 높여 먼저 확인하도록 했다.
