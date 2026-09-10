# Demand Labeling Model Selection V1

## Evaluation Scope

- Input: 200 grounded synthetic Consumer Demand rows
- Taxonomy: `taxonomy_candidate_v2_1.json`
- Compared methods: Rule-only, Rule-first Hybrid, Qwen 2.5 3B, Qwen 3 1.7B, Qwen 3 8B, Llama 3.2 3B, EXAONE 3.5 2.4B, Phi-4 Mini
- The expected facet profile is generated evaluation metadata, not human-annotated production gold data.
- Model failures and omitted rows are counted as failures; every method is evaluated against the same 200 demand IDs.

## Results

| Method | Diagnostic agreement | Model failures | Review rows | Runtime seconds | HP rate | HN rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| RULE_ONLY | 72.50% | 0 | 36 | 0 | 100.00% | 74.63% |
| HYBRID_RULE_FIRST | 72.50% | 22 fallback failures | 36 | not isolated | 100.00% | 74.63% |
| Qwen 2.5 3B | 12.06% | 1 | 23 | 424.08 | 100.00% | 38.37% |
| Qwen 3 1.7B | 3.06% | 4 | 168 | unavailable | 100.00% | 16.21% |
| Qwen 3 8B | 57.02% of 121 successful rows | 79 | 79 | 1226.41 | 0.00% | 75.07% |
| Llama 3.2 3B | 8.08% of 99 successful rows | 101 | 194 | unavailable | unavailable | 43.23% |
| EXAONE 3.5 2.4B | 13.57% | 1 | 33 | 549.69 | 100.00% | 41.40% |
| Phi-4 Mini | 4.00% | 0 | 83 | 329.23 | 0.00% | 27.72% |

HP means same-profile rows received the same label. HN means different profiles in the same category received different labels. Pair metrics are supplementary because this 200-row sample has very few repeated hard-positive pairs.

## Decision

Adopt `RULE_FIRST_HYBRID` as the MVP production structure:

1. Load the product's category and default facet values.
2. Apply deterministic Rule/Alias matching to `extra_requirement`.
3. Return a label immediately when the request is resolved without conflict.
4. Call an LLM only for unresolved, ambiguous, or conflicting requirements.
5. Accept only facet names and numeric codes present in the taxonomy.
6. Preserve the rule result when the model fails, returns an unknown code, omits a demand, or conflicts with the validation schema.
7. Route unresolved cases to a review queue.

No tested LLM-only model is promoted as the primary labeling method. Qwen 3 8B had the highest agreement among successful LLM rows, but its 79/200 failure rate and 1,226-second runtime make it unsuitable for the MVP fallback without further batching and prompt/validator work. Qwen 2.5 3B was operationally more stable than the other small models, but its agreement was too low for unrestricted labeling.

## Artifacts

- Comparison script: `scripts/evaluation/compare_demand_labeling_models.py`
- Generated metrics: `data/processed/demand_5000_v1/demand_labeling_model_comparison_v2.csv`
- Generated report: `data/processed/demand_5000_v1/demand_labeling_model_comparison_v2.md`
