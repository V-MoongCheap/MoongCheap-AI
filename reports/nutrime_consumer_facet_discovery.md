# Nutrime Consumer Facet Discovery 최종 QA

기존 Discovery 결과를 재탐색하지 않고 Human Review 전 검증만 수행한 보고서다.
Taxonomy와 Alias 66개는 수정하지 않았다.

## Count Definition
- TOTAL_UNIQUE_REVIEWS_ANALYZED: 423
- EXTRACTED_ANALYSIS_ROWS: 607
- One review can produce multiple expressions, so discovery-type analysis row totals can exceed 423.

## Discovery Type Counts
| discovery_type | analysis_row_count | unique_review_count |
|---|---:|---:|
| EXISTING_FACET | 316 | 181 |
| NEW_ALIAS | 32 | 29 |
| NEW_FACET_CANDIDATE | 29 | 28 |
| NON_FACET | 161 | 161 |
| SUBJECTIVE_MEDICAL_OUTCOME | 69 | 69 |

## Intake Frequency Product Verification
- Product corpus rows: 45921
- Rows with daily_frequency_candidate: 41801
- Unique products with the field: 41801
- Product source fields: intake_method, 섭취방법, daily_frequency_candidate, amount_per_intake_candidate, dose_unit_candidate.
- Conclusion: the related fields exist in the Product Corpus. Nutrime remains NOT_VERIFIABLE because no verified crosswalk exists between Nutrime source_product_id and the MFDS Product Corpus; this is not a missing verifier field.
- Individual Nutrime product verification therefore remains unresolved; only Product Corpus field availability is verified.

## Candidate QA
| proposed_facet | strength | analysis rows | unique reviews | products | categories | taxonomy relation | review action | product verifiability |
|---|---|---:|---:|---:|---:|---|---|---|
| digestive_tolerance | WEAK_CANDIDATE | 2 | 2 | 1 | 1 | UNRESOLVED | REVIEW_AFTER_SOURCE_CHECK | NOT_VERIFIABLE |
| intake_frequency | STRONG_CANDIDATE | 19 | 19 | 8 | 1 | VALUE_OF_EXISTING_FACET | REVIEW_FOR_VALUE | NOT_VERIFIABLE_NUTRIME_CROSSWALK_MISSING_FIELD_AVAILABLE |
| mixability | WEAK_CANDIDATE | 3 | 3 | 0 | 0 | VALUE_OF_EXISTING_FACET | REVIEW_FOR_VALUE | NOT_VERIFIABLE |
| opening_convenience | MODERATE_CANDIDATE | 3 | 3 | 1 | 1 | RELATED_BUT_DISTINCT | REVIEW_AS_NEW_FACET | NOT_VERIFIABLE |
| storage_convenience | MODERATE_CANDIDATE | 2 | 1 | 1 | 1 | RELATED_BUT_DISTINCT | REVIEW_AS_NEW_FACET | NOT_VERIFIABLE |

## Digestive Tolerance
- Classification: CONSUMER_USAGE_EXPERIENCE
- The source text describes an individual experience after intake. It does not provide sufficient basis for a disease outcome or an explicit adverse-reaction classification.
- It remains a WEAK_CANDIDATE and is not eligible for automatic Facet approval.

## Mixability Mapping Detail
- 상세 파일: `data/review/model1_mixability_review_details.csv`
- All three rows have an empty source_product_id. This is an unmapped input record, not evidence that Product information was lost in the pipeline.
- HFF status is therefore not confirmed from source mapping and is marked HFF_UNCERTAIN_UNMAPPED.

## Human Review Rule
- reviewer_decision remains PENDING_REVIEW for every candidate.
- recommended_review_action is a review hint, not an automatic approval.
