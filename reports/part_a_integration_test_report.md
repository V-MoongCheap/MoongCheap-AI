# Part A 통합 테스트 보고서

## 결과 요약

현재 checkout 기준 Part A 로컬 통합은 **PASS**, 운영 DB/API 연결은 **BLOCKED_EXTERNAL_CONTRACT**다.

## 테스트

| 구분 | 결과 |
| --- | --- |
| Part A parser unit/contract | PASS |
| Taxonomy v2.2 / reviewed Alias 로드 | PASS |
| Category-local value code 출력 | PASS |
| PASSTHROUGH 원문 보존 | PASS |
| conflict/ambiguity 상태 보존 | PASS |
| 행 단위 실패 격리 | PASS |
| A -> B -> C local smoke | PASS, 20 -> 19 -> 3,800 |
| PostgreSQL read/write | 입력 adapter만 구현, 운영 연결 미실행 |
| Backend result API | endpoint 미확정 |
| 200 Grounded Demand regression | 원본 200행 파일 부재로 BLOCKED |

## 상태 및 모드

20건 스모크에서 `PARSED 11`, `PASSTHROUGH 2`, `NONE 2`, `CONFLICT 1`, `NOT_APPLICABLE 4`, `REVIEW 0`이었다. `processed_at`이 이미 존재하는 행은 기본적으로 건너뛰며, 파싱 예외 행은 성공 timestamp를 기록하지 않는다.

기존 집계 보고서의 200건 진단 agreement `0.7250`은 생성된 expected profile과의 진단 일치율이며 Human Gold Accuracy가 아니다. 새 런타임으로 200건을 재실행할 원본은 현재 checkout에 없다.

## 명령

```powershell
$env:PYTHONPATH = "src"
python scripts/labeling/run_part_a_runtime.py `
  --input handoff/mvp_shared/smoke/demands_v2_2.csv `
  --output data/processed/mvp_e2e_v2_2/part_a_runtime_v2_2.csv

python scripts/e2e/run_mvp_local_e2e.py `
  --input data/processed/mvp_e2e_v2_2/part_a_runtime_v2_2.csv `
  --offers handoff/mvp_shared/smoke/seller_offers_smoke.csv `
  --output-dir data/processed/mvp_e2e_v2_2/full
```

전체 테스트는 아래 명령으로 실행했다.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

