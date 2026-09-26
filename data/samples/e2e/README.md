# 로컬 E2E 스모크 입력 (합성)

`scripts/e2e/run_mvp_local_e2e.py` 를 저장소만 받은 상태에서 한 바퀴 돌려보기 위한
**합성 데이터**다. 실제 수요·판매 공고가 아니며 평가에 쓰지 않는다.

## 왜 넣었나

수요 CSV 와 판매 공고 CSV 는 커밋하지 않는 방침이라, 새로 받은 사람은 E2E 를
CLI 로 돌려볼 방법이 없었다. 이 파일들은 합성이라 그 방침에 걸리지 않는다.

## demands_sample.csv

`demand_clustering.baseline.REQUIRED_COLUMNS` 6개 열을 그대로 쓴다.

⚠️ **A→B 생성기(`scripts/demand/build_part_a_b_clustering_input.py`)의 출력과는 다른 계약이다.**
그쪽은 19개 feature 열을 낸다. 이 파일은 B 클러스터링이 요구하는 최소 열만 담는다.

| 묶임 | 내용 |
|---|---|
| 홍삼정 (대체 가능 3건) | 수량 10, 참여 3명 |
| 비타민C (대체 가능 2건) | 수량 5, 참여 2명 |
| 비타민C (대체 불가 1건) | 수량 2, 참여 1명 — `catalog_id` 로 따로 묶인다 |

## offers_sample.csv

| 공고 | 기대 결과 |
|---|---|
| `O-1001` 홍삼정 MOQ 5 | **CANDIDATE** — 카테고리·MOQ·가격 모두 통과 |
| `O-1002` 홍삼정 MOQ 20 | REVIEW — MOQ 가 수요 10 보다 크다 |
| `O-1003` 비타민C MOQ 3 | **CANDIDATE** — 대체 가능 묶음(수량 5)에서 통과 |
| `O-1004` 유산균 | REVIEW — 카테고리 불일치 |

## 실행

```bash
python scripts/e2e/run_mvp_local_e2e.py --example --output-dir /tmp/e2e-smoke
```

`--example` 없이 `--input` · `--offers` 중 하나만 주거나, `--example` 과 섞으면 종료 코드 2 로 거부한다.
기대 결과 전체(3묶음 × 4공고 = 12판정)는 `tests/test_mvp_local_e2e.py` 가 고정한다.
