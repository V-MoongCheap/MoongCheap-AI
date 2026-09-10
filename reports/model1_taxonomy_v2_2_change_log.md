# Model 1 Taxonomy V2.2 변경 이력

- V2.1의 16개 Category, 48개 Facet, 413개 Value Code를 그대로 보존했다.
- 신규 전역 Facet은 추가하지 않았다.
- `intake_frequency`는 기존 `daily_frequency`로 병합했다.
- `opening_convenience`, `storage_convenience`는 `DEFERRED_V2_3`이다.
- `digestive_tolerance`, `mixability`는 `REJECTED_NOT_FACET`이다.
- Alias와 Taxonomy canonical 정의는 별도 파일로 유지한다.

## Category별 변경 요약

| Category | 기존 Facet | 추가 | 병합 | 보류/기각 | Code 변경 |
|---|---:|---:|---:|---:|---|
| `health-functional-food:blood_sugar_metabolic` | 3 | 0 | 0 | 0 | 없음 |
| `health-functional-food:dietary_fiber` | 3 | 0 | 0 | 0 | 없음 |
| `health-functional-food:eye_health` | 3 | 0 | 0 | 0 | 없음 |
| `health-functional-food:heart_blood` | 3 | 0 | 0 | 0 | 없음 |
| `health-functional-food:joint_health` | 3 | 0 | 0 | 0 | 없음 |
| `health-functional-food:liver_health` | 3 | 0 | 0 | 0 | 없음 |
| `health-functional-food:male_health` | 3 | 0 | 0 | 0 | 없음 |
| `health-functional-food:omega_fatty_acid` | 3 | 0 | 0 | 0 | 없음 |
| `health-functional-food:other_functional` | 3 | 0 | 0 | 0 | 없음 |
| `health-functional-food:probiotics` | 3 | 0 | 0 | 0 | 없음 |
| `health-functional-food:propolis` | 3 | 0 | 0 | 0 | 없음 |
| `health-functional-food:protein` | 3 | 0 | 0 | 0 | 없음 |
| `health-functional-food:red_ginseng` | 3 | 0 | 0 | 0 | 없음 |
| `health-functional-food:skin_collagen` | 3 | 0 | 0 | 0 | 없음 |
| `health-functional-food:theanine_sleep` | 3 | 0 | 0 | 0 | 없음 |
| `health-functional-food:vitamin_mineral` | 3 | 0 | 0 | 0 | 없음 |

전 Category에서 기존 Facet/Value를 보존했으며, 신규 후보 결정은 Taxonomy metadata와 결정 보고서에 기록했다.
