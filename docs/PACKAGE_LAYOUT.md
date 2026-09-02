# 패키지 구조

```text
src/moongcheap_ai/
├── data_foundation/      # 상품 데이터, Category, Catalog, Facet, Labeling
├── demand_clustering/    # Consumer Demand clustering
├── seller_matching/      # Seller Offer 매칭과 scoring
├── seller_analysis/      # 판매자용 수요 분석과 E2E 연결
├── pipeline.py           # 단계 실행 orchestration
└── erd_contract.py       # ERD 계약 검증

tests/
├── data_foundation/
├── demand_clustering/
├── seller_matching/
└── seller_analysis/
```

기능 구현은 해당 domain 패키지에 추가하고, 테스트는 같은 이름의 테스트 패키지에 둔다.
기능 구현은 해당 domain 패키지에 직접 추가한다. 별도 `parts` 패키지는 사용하지 않는다.
