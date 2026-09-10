# Taxonomy V2.2 Demand Regression

동일한 grounded 200건을 사용했으며 LLM benchmark는 재실행하지 않았다.

```
              method  dataset_rows  labeled_rows  review_rows  unresolved_rows  model_failure_rows  model_intervention_rows  diagnostic_agreement_rows  diagnostic_comparable_rows  diagnostic_agreement  normal_scenario_rows  ambiguous_scenario_rows  conflict_scenario_rows  out_of_taxonomy_rows  model_calls  hp_pairs  hp_correct  hp_rate  hn_pairs  hn_correct  hn_rate  tp  tn  fp  fn  pair_precision  pair_recall  pair_f1  pair_accuracy  pair_error_rate  pair_coverage  alias_hit  corrected_alias_hit
      V2.1_RULE_ONLY           200           200           36               16                   0                        0                        145                         200                 0.725                    32                       16                      17                    16            0         1           1      1.0      1151         859   0.7463   1 859 292   0          0.0034          1.0   0.0068         0.7465           0.2535         0.0579          0                    0
V2.2_RULE_ALIAS_ONLY           200           200           36               16                   0                        0                        145                         200                 0.725                    32                       16                      17                    16            0         1           1      1.0      1151         859   0.7463   1 859 292   0          0.0034          1.0   0.0068         0.7465           0.2535         0.0579        116                   87
```

- V2.1 Rule-only diagnostic agreement: 0.7250
- V2.2 Rule/Alias-only diagnostic agreement: 0.7250
- Alias hit: 116
- Corrected alias hit: 87
- V2.2 unresolved / conflict / invalid code: 16 / 17 / 16
