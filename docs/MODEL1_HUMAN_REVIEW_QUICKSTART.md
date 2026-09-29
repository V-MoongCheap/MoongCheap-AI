# Model 1 Facet 후보 빠른 검수

CSV를 직접 찾아가며 수정하지 않고, 후보를 한 건씩 확인하면서 검수한다.

```bash
PYTHONPATH=src .venv/bin/python scripts/model1/review_queue_interactive.py \
  --queue data/processed/model1_review_kanana_210_fixed/multisource_candidate_review_queue_v1.csv \
  --output data/processed/model1_review_kanana_210_fixed/multisource_candidate_review_queue_reviewed_v1.csv
```

각 행에서 다음 키를 입력한다.

| 입력 | 의미 | 입력 후 결과 |
|---|---|---|
| `a` | 승인 | 현재 Facet·Value를 승인 |
| `e` | 수정 | Facet, Value, 수정 사유 입력 |
| `r` | 반려 | 반려 사유 입력 |
| `u` | 보류 | 판단이 어려운 상태로 저장 |
| `s` | 건너뛰기 | 결정하지 않고 다음 행으로 이동 |
| `q` | 종료 | 현재까지 즉시 저장하고 종료 |

검수 중인 원본 queue는 수정하지 않는다. 결과는 `--output`으로 지정한 새 CSV에 저장하고, 각 결정 직후에도 자동 저장한다. 중단된 경우 같은 명령을 다시 실행하면 아직 결정하지 않은 행부터 이어서 검수한다.

처음부터 다시 검수하려면 마지막에 `--restart`를 추가한다.

검수 결과를 Taxonomy 생성에 사용하기 전에 `human_decision`을 확인한다. `APPROVE`와 `EDIT`만 후보로 반영되며, `REJECT`와 `UNCERTAIN`은 반영되지 않는다.
