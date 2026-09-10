# Part A → Part B Runtime Contract

## 범위

Part A는 Consumer Demand의 `extra_requirement`를 Approved Taxonomy V2.2와
검수 완료된 APPLIED Alias로 결정적으로 정규화한다. 이 계약은 Part B가
클러스터링을 시작하기 전에 사용할 입력을 정의한다.

이번 Runtime은 클러스터, Demand Board, 대체상품 후보, 임베딩, 판매자 매칭,
LLM 호출을 수행하지 않는다.

## 입력

최소 입력 필드:

- `demand_id`
- `catalog_id`
- `category_id` 또는 Catalog를 통한 Category 조회
- `extra_requirement`
- `is_substitutable`

Category가 없거나 Catalog에서도 확인되지 않으면 임의의 Category-local Code를
생성하지 않고 진단 상태로 남긴다.

## 출력

```json
{
  "demandId": 123,
  "categoryId": "health-functional-food:probiotics",
  "taxonomyVersion": "v2.2",
  "status": "PARSED",
  "effectiveRequirementMode": "STRUCTURED",
  "constraints": [
    {
      "facetKey": "product_form",
      "canonicalValue": "캡슐",
      "facetCode": 1,
      "valueCode": 2,
      "constraintType": "MUST",
      "evidence": "반드시 캡슐"
    }
  ],
  "preferenceGroups": [],
  "passthroughText": null,
  "reasonCodes": [],
  "parserVersion": "part-a-runtime.v2.2"
}
```

`facetCode`와 `valueCode`는 전역 코드가 아니다. 항상 현재 `categoryId`의
Taxonomy에서 함께 해석해야 한다. 같은 값이 다른 Category에서 다른
`valueCode`를 가질 수 있다.

## 상태와 모드

| status | effectiveRequirementMode | 의미 |
|---|---|---|
| `PARSED` | `STRUCTURED` | Taxonomy 조건으로 구조화됨 |
| `PASSTHROUGH` | `SEMANTIC_TEXT` | 유효한 선호이나 현재 Taxonomy로 구조화할 수 없음 |
| `NONE` | `NONE` | 추가 요구 없음 |
| `CONFLICT` | `NONE` | 같은 Facet에 양립할 수 없는 조건 |
| `TAXONOMY_AMBIGUOUS` | `NONE` | Category-local Target을 단일 값으로 정할 수 없음 |
| `REVIEW` | `NONE` | 규칙만으로 안전하게 해석할 수 없음 |
| `NOT_APPLICABLE` | `NONE` | `is_substitutable=false`라 추가 요구를 적용하지 않음 |

`MUST`, `EXCLUDE`, `PREFER`는 `constraints[].constraintType`에 기록한다.
대안 선호는 `preferenceGroups`에 `ANY_OF`/`MAX` 구조로 보존하며, Part B가
임의로 AND 조건으로 바꾸면 안 된다.

## Deferred Alias

APPLIED Alias만 구조화 매칭에 사용한다. DEFERRED/REJECTED Alias는 Runtime
Codebook에 넣지 않는다. 의미 있는 문장이지만 구조화할 수 없는 경우에는
`PASSTHROUGH`로 원문을 보존한다.

## 실행

```powershell
$env:PYTHONPATH = "src"
python scripts/labeling/run_part_a_runtime.py `
  --input <demand.csv> `
  --output data/processed/demands/part_a_runtime_v2_2.csv
```

이 실행은 CSV만 읽고 CSV/JSON을 생성한다. PostgreSQL 조회와 Backend 쓰기는
별도 Adapter가 계약을 검증한 뒤 수행한다.
