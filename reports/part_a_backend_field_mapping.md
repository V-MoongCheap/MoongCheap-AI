# Part A Backend 필드 매핑

## 읽기 계약

| Backend 원본 | Part A 내부 | 처리 |
| --- | --- | --- |
| `demand.id` | `demand_id` / `demandId` | 원본 식별자 보존 |
| `demand.catalog_id` | `catalog_id` / `catalogId` | 원본 식별자 보존 |
| `product_catalog.category_id` | `category_id` / `categoryId` | Catalog에서 조회, 없으면 검토 상태 |
| `demand.extra_requirement` | `extra_requirement` | 규칙/Alias 정규화 또는 원문 보존 |
| `demand.desired_price_min/max` | 동일 | A가 Facet으로 변환하지 않음 |
| `demand.quantity` | 동일 | A가 변경하지 않음 |
| `demand.is_substitutable` | 동일 | false이면 요구사항은 `NOT_APPLICABLE`/`NONE` 정책 |
| `demand.processed_at` | 동일 | NULL/빈 값만 입력 대상으로 선별 |

## A 출력 계약

각 결과는 다음을 포함한다.

`demandId`, `catalogId`, `categoryId`, `taxonomyVersion`, `status`, `effectiveRequirementMode`, `constraints`, `preferenceGroups`, `passthroughText`, `parserVersion`, `reasonCodes`

기존 B 로컬 baseline과의 연결을 위해 `label`과 `facet_values`도 함께 유지한다. `PREFER`와 ANY_OF는 단일 label로 손실시키지 않고 typed `constraints`/`preferenceGroups`를 기준으로 전달한다.

## DB 쓰기

현재 A adapter는 PostgreSQL을 read-only로 열고 Backend 결과 API에 단일 POST하는 구조다. AI 코드가 `demand`를 직접 UPDATE하지 않는다. 실제 Backend URL, endpoint, migration, 응답 계약이 이 checkout에 없으므로 운영 DB 쓰기 테스트는 수행하지 않았다.

