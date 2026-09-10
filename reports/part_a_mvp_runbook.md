# Part A MVP 실행 안내

## CSV dry-run

```powershell
$env:PYTHONPATH = "src"
python scripts/labeling/run_part_a_runtime.py `
  --input path/to/demands.csv `
  --output data/processed/part_a_runtime.csv `
  --summary data/processed/part_a_runtime.summary.json
```

필수 입력은 `demand_id`, `catalog_id`, `extra_requirement`, `is_substitutable`이며, 가능하면 `category_id`, `quantity`, `desired_price_min`, `desired_price_max`, `processed_at`을 함께 제공한다. `processed_at`이 비어 있지 않은 행은 중복 처리를 막기 위해 건너뛴다.

## 운영 연결 전제

운영에서는 `A_DATABASE_URL`을 Secret으로 주입하고 read-only PostgreSQL adapter로 미처리 Demand를 읽는다. Backend 전송에는 `A_BACKEND_BASE_URL`, `A_BACKEND_INTERNAL_KEY`, `A_LABEL_RESULT_ENDPOINT`가 필요하다. Secret 값과 자연어 원문은 로그에 기록하지 않는다.

## 출력 확인

`status`, `effectiveRequirementMode`, `constraints`, `preferenceGroups`, `passthroughText`, `reasonCodes`, `taxonomyVersion`, `parserVersion`을 우선 확인한다. `label`은 B legacy baseline 호환용이며 PREFER/ANY_OF의 유일한 진실 원천으로 사용하지 않는다.

현재 실제 운영 endpoint와 200건 원본 fixture가 없으므로 운영 POST와 200건 회귀를 로컬에서 가장하지 않는다.

