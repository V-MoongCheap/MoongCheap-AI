# Part A V2.2 Gold 평가 결과

이 평가는 finalized Gold의 기대값과 현재 수요 조건 파서의 결과를 비교한다.
각 행은 status, parser-level mode, effective mode, constraints, preference groups, passthrough를 독립적으로 비교한다.

- 전체 행: 200
- 전체 row pass: 200/200

## 파티션별 결과

| Partition | Rows | Status | Parser Mode | Effective Mode | Constraints | Groups | Passthrough | Row Pass |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| DEV | 100 | 100/100 | 100/100 | 100/100 | 100/100 | 100/100 | 100/100 | 100/100 |
| HOLDOUT | 50 | 50/50 | 50/50 | 50/50 | 50/50 | 50/50 | 50/50 | 50/50 |
| CHALLENGE | 50 | 50/50 | 50/50 | 50/50 | 50/50 | 50/50 | 50/50 | 50/50 |

## 실패 사례

없음

## 산출물

- 상세 결과: `reports/part_a_v2_2_gold/part_a_v2_2_gold_evaluation_results.csv`
- 요약 JSON: `reports/part_a_v2_2_gold/part_a_v2_2_gold_evaluation_summary.json`

참고: Gold의 expected 값은 정답 기준이며, 실패 행은 파서 또는 Gold 기대값의 추가 검토 대상이다. 자동으로 수정하지 않는다.
