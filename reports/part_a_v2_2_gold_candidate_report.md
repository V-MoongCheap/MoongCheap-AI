# Part A V2.2 Gold Candidate Report

이 산출물은 고정 Gold Set이 아니라 Human Review 전 후보 세트다.
모든 행은 `PENDING_REVIEW`이며, proposed 값은 정답으로 확정되지 않았다.

## Summary

- Candidate rows: 200
- Standard candidates: 150
- Challenge candidates: 50
- Reused human-reviewed reference rows: 129
- Newly composed candidates: 71
- Category count: 16
- Pending review rows: 200

## Candidate Partition

evaluation_partition_candidate
CHALLENGE     50
DEV          100
HOLDOUT       50

## Candidate Provenance

candidate_origin
EXISTING_REVIEWED_FIXTURE    129
NEW_CHALLENGE_CANDIDATE       50
NEW_STANDARD_CANDIDATE        21

## Parser Exposure

parser_exposure
KNOWN_TO_EXISTING_TESTS    129
NEW_UNSEEN_CANDIDATE        71

## Provenance

- Existing 200-row Legacy Gold: `NOT_FOUND`.
- Existing 72.50% metric remains `LEGACY_EXPERIMENT_REFERENCE` and is not used as a baseline here.
- 129 rows come from the tracked human-reviewed v042 evaluation fixture.
- Remaining rows are deterministic candidate compositions from V2.2 category-local canonical values.
- MFDS raw product facts were not available in the tracked workspace, so they are not claimed as grounding for these rows.
- No row is automatically finalized as Gold.

## Review Policy

Reviewer must verify category, status, mode, constraints, and whether the expression is supported by the selected grounding source.
After review, only an explicit finalization script may export STANDARD 150 and CHALLENGE 50 as fixed evaluation sets.

## Scenario / Category Distribution

split_candidate  scenario_type                            
CHALLENGE        ANY_OF_CANDIDATE                              8
                 CONFLICT_CANDIDATE                            6
                 MULTI_CONSTRAINT_CANDIDATE                   15
                 NONE_CANDIDATE                                5
                 NOT_APPLICABLE_CANDIDATE                      5
                 PASSTHROUGH_CANDIDATE                         6
                 REVIEW_CANDIDATE                              5
STANDARD         GROUNDED_EXCLUDE_CANDIDATE                    7
                 GROUNDED_MUST_CANDIDATE                       7
                 GROUNDED_PREFER_CANDIDATE                     7
                 MULTI_FACET_NOMINAL_PROHIBITION_LOCALITY      8
                 NEGATED_REMOVAL_ALTERNATIVE_DELIBERATION     30
                 NEGATED_REMOVAL_SAME_TARGET_FINAL_CONTROL    12
                 NEGATIVE_COMPARATIVE_FINAL_HARD_CONTROL       8
                 NOMINAL_PROHIBITION_ORDER_VARIATION          36
                 POSITIVE_NOMINAL_INCLUSION_CONTROL           17
                 REPORTED_NOMINAL_PROHIBITION_ONLY             9
                 SOFT_NEGATIVE_COMPARATIVE_CONTROL             9

