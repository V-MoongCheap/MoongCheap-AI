# Part A V2.2 Gold Review Schema

The candidate file is not a finalized Gold Set. Every row starts as
`PENDING_REVIEW`.

## Review fields

- `proposed_expected_mode`: parser-level constraint mode such as `MUST`,
  `PREFER`, `MIXED`, or `ANY_OF`.
- `proposed_expected_effective_requirement_mode`: runtime mode:
  `STRUCTURED`, `SEMANTIC_TEXT`, or `NONE`.
- `corrected_expected_preference_groups`: corrected JSON for `ANY_OF` groups.
- `proposed_expected_passthrough_text` and
  `corrected_expected_passthrough_text`: expected semantic text for
  `PASSTHROUGH` rows.

When a corrected field is populated, finalization uses it. Otherwise the
proposed value remains the review baseline.

## Evaluation partitions

- `DEV`: 100 expressions reused from the reviewed fixture.
- `HOLDOUT`: 50 newly composed expressions with no existing-test exposure.
- `CHALLENGE`: 50 newly composed policy-edge expressions.

`ANY_OF` candidates are generated within one facet. Cross-facet alternatives
require a separate contract decision and must not be silently approved.
