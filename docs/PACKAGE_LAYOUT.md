# 패키지 구조

```text
src/moongcheap_ai/
├── data_foundation/      # 상품 데이터, Category, Catalog, Facet, Labeling
├── demand_constraints/   # extra_requirement typed constraint parser
├── demand_clustering/    # 운영 배치, domain 규칙, 공통 artifact 계약
│   └── evaluation/      # 오프라인 근거 생성, 리뷰, 검색 평가, 시뮬레이션 변환
├── seller_matching/      # Seller Offer 매칭과 scoring
├── seller_analysis/      # 판매자용 수요 분석과 E2E 연결
├── pipeline.py           # 단계 실행 orchestration
└── erd_contract.py       # ERD 계약 검증

tests/
├── data_foundation/
├── demand_constraints/
├── demand_clustering/
├── seller_matching/
└── seller_analysis/
```

기능 구현은 해당 domain 패키지에 추가하고, 테스트는 같은 이름의 테스트 패키지에 둔다.
기능 구현은 해당 domain 패키지에 직접 추가한다. 별도 `parts` 패키지는 사용하지 않는다.

`demand_clustering`의 운영 코드와 공통 계약은 `evaluation`이나 `scripts`를
import하지 않는다. 평가 코드는 운영 domain 규칙과 계약을 재사용할 수 있다.
공통 profile 상태는 `profile_contract.py`, relation ID·컬럼·fingerprint는
`function_relation_contract.py`에서 관리한다. CPU 임베딩 helper도 운영/평가
공용이며 모델 라이브러리는 실제 사용 시에만 로드한다.

평가 기능은 `moongcheap_ai.demand_clustering.evaluation.<module>`에서 명시적으로
import한다. 상위 패키지는 평가 함수를 재노출하지 않는다. 별도 리뷰 앱이 쓰는
`demand_clustering.substitute_annotation`만 기존 경로 호환용으로 유지하며
운영 코드에서는 사용하지 않는다. 경계는
`tests/demand_clustering/test_package_boundaries.py`로 검증한다.
