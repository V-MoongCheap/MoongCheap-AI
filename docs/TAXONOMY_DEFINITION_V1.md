# Facet Taxonomy 정의

## 한 문장 정의

이 프로젝트의 Taxonomy는 **건강기능식품 Category별로 소비자 수요를 구분하기
위해 허용하는 Facet과 Facet Value의 버전이 있는 기준표**다.

Taxonomy는 상품 Category 자체를 새로 분류하는 모델이 아니며, 상품명이나 자연어
요구사항을 그대로 저장하는 사전도 아니다. Model 1이 상품·MFDS 속성·검색/리뷰
근거에서 Facet 후보를 제안하고, Rule/Evidence와 Human Review를 거쳐 확정하는
Labeling 계약이다.

## 구성

```text
Taxonomy
├─ version
├─ status
└─ categories
   └─ category
      └─ facets
         └─ values
            ├─ code
            ├─ value
            └─ aliases
```

각 Category는 다음을 가진다.

- `category_id`: AI 내부의 안정적인 Category key. 실제 Backend `category.id`와
  동일하다고 가정하지 않는다.
- `facets`: 해당 Category에서 수요를 구분할 수 있는 속성 목록
- `values`: Facet에 허용되는 정규 값과 숫자 Code
- `aliases`: 자연어 표현을 정규 값으로 연결하는 승인 별칭
- `status`: 초안·검토·승인 상태

현재 저장 기준은 `config/facet_taxonomy_v2_2.json`이며, Backend의
`category.facet`에는 같은 구조의 JSON 문자열을 저장한다. DB에서는 JSON 내부를
조회 조건으로 사용하지 않고 전체 TEXT를 읽어 Python에서 파싱한다.

## 코드 규칙

- 모든 Facet에서 `ALL`은 `code=0`이다.
- `ALL`은 Demand가 해당 Facet을 언급하지 않았다는 뜻이다.
- 상품 또는 판매자 정보에서 Facet을 확인할 수 없는 `UNKNOWN`은 `ALL`과 다르다.
  현재 Demand Label codebook에 임의의 `UNKNOWN` code를 추가하지 않는다.
- Value code와 Facet order는 결정론적으로 정렬한다. Taxonomy 버전이 바뀌지
  않으면 같은 입력에서 같은 code가 나온다.
- 가격, 수량, MOQ, 배송조건은 Taxonomy Facet이 아니라 별도 정형 조건이다.

## 생성과 사용의 경계

```text
상품·MFDS·검색/리뷰 근거
        ↓
Model 1 후보 생성
        ↓
Evidence / Rule 검증
        ↓
Human Review
        ↓
승인 Taxonomy version
        ↓
Model 2 Demand Labeling
        ↓
label + facet_values
```

Model 1은 서버 실시간 기능이 아니라 오프라인 Taxonomy 생성·개선 작업이다.
Model 2는 승인된 Taxonomy에 존재하는 Facet/Value만 사용해 `extra_requirement`를
해석한다. Taxonomy에 없는 요구사항은 임의의 기존 Value로 매핑하지 않고
`PASSTHROUGH` 또는 `REVIEW`로 보존한다.

## 업데이트 정책

새 상품·리뷰·검색어를 추가로 분석했다고 매번 Taxonomy version을 올리지 않는다.
다음 조건을 만족할 때만 새 버전을 만든다.

1. 기존 Facet/Value로 표현되지 않는 반복 근거가 확인됨
2. 중복·모호·과도한 세분화 여부를 검토함
3. Alias와 Value code 변경 영향을 확인함
4. Human Review를 거쳐 승인됨
5. 새 Taxonomy와 Model 2 Gold 회귀를 실행함

단순한 Demand 재실행이나 B/C 전달 파일 생성은 Taxonomy 업데이트가 아니다.
따라서 B/C에는 매 실행마다 새 Taxonomy를 요구하지 않고, 승인된 Taxonomy
version과 hash를 함께 전달한다.
