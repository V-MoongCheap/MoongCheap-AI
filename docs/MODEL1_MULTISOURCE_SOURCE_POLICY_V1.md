# Model 1 멀티소스 입력 정책 V1

## 파셋 도출에 사용하는 데이터

| 소스 | 경로 | 사용하는 정보 | 해석 범위 |
|---|---|---|---|
| MFDS 상품 | `data/interim/facet_discovery/i0030_products_clean_dedup.csv` | 상품명, 제형, 기능성 성분, 규제 기능 문장 | 공식 상품 속성과 기능성 표현 |
| 판매자 공고 | `data/processed/domeggook/seller_offers_core.csv` | 상품명, 포장·제형, 성분, 기능성 표현, 섭취법 | 실제 판매 현장에서 쓰이는 상품 표현 |
| 소비자 검색 | `data/interim/facet_evidence/kuaiseach_health_queries_ko_reviewed_v27.parquet` | 번역·검토된 검색어 | 소비자가 상품을 찾을 때 사용하는 표현 |

MFDS와 판매자 공고는 상품 속성의 주 근거다. 소비자 검색어는 표현 보강 자료이며, 검색량이나 검색어 자체를 상품 속성으로 확정하지 않는다.

## 파셋 도출에서 제외하는 데이터

`data/synthetic/consumer_reference/grounded_demand_v2_1000.csv`와 `F:\downloadF\demand_board_snapshot_5000.json`은 구매 요청 생성, 수요 라벨링, 클러스터링 검증에 사용한다. 현재 Model 1 파셋 도출 입력에는 넣지 않는다.

가상 구매 요청의 자연어 조건, 참여자 수, 시뮬레이션 가격, 상태값은 실제 상품의 고유 속성이나 실제 시장 수요량을 의미하지 않기 때문이다.

## 판매자 데이터 추가 확보 판단

현재 판매자 공고 2,778건은 초기 보강 자료로 사용할 수 있다. 추가 수집은 다음 조건을 만족할 때 의미가 있다.

- 기존 공고와 다른 상품·브랜드·제형·포장 표현이 포함될 것
- `ingredients_raw`, `functionality_raw`, `intake_raw`, `package_spec` 중 실제 값이 충분할 것
- 동일 상품의 반복 공고보다 새로운 상품 표현의 비율이 높을 것
- 가격·재고·배송·MOQ는 별도 거래 조건으로 보존하고 상품 파셋과 섞지 않을 것

따라서 다음 단계는 공고 수를 무작정 늘리는 것이 아니라, 카테고리별 신규 상품 비율과 핵심 필드 채움률을 확인한 뒤 부족한 카테고리만 추가 확보하는 것이다.

## 파이프라인 분리

```text
MFDS 상품 + 판매자 공고 + 소비자 검색
        -> Model 1 Facet Discovery
        -> 후보 정규화 / 검토

상품·카테고리 + 합성 구매 요청
        -> Model 2 Demand Labeling
        -> Clustering 입력
```
