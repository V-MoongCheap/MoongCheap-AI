# LG U+ 건강기능식품 융합데이터 분석

## Raw Snapshot
- filename: `건강기능식품  융합데이터_시장지표_21년 12월.CSV`
- file_size_bytes: 192644
- sha256: `5fc954acc662eb2afe70fa3a9bcac64e8df6f553bd3804cce46e6edd3807573f`
- encoding: `utf-8-sig`
- delimiter: `,`
- row_count: 1134
- column_count: 13
- source_type: `KOREAN_HFF_PURCHASE_AGGREGATE`

## 실제 Schema
| column | missing ratio | unique count | sample values |
|---|---:|---:|---|
| INDEX_KEY | 0.00% | 1134 | LI122200040001LI12220004000123381 / LI122200040001LI12220004000123382 / LI122200040001LI12220004000123383 |
| CRTR_YM | 0.00% | 1 | 202112 / 202112 / 202112 |
| CTPV_CD | 0.00% | 3 | 41 / 41 / 41 |
| CTPV_NM | 0.00% | 3 | 경기도 / 경기도 / 경기도 |
| SGG_CD | 0.00% | 77 | 41111 / 41111 / 41111 |
| SGG_NM | 0.00% | 76 | 수원시 장안구 / 수원시 장안구 / 수원시 장안구 |
| DONG_CD | 0.00% | 1134 | 4111156000 / 4111156600 / 4111157100 |
| DONG_NM | 0.00% | 1100 | 파장동 / 율천동 / 정자1동 |
| MOAV_DYNMC_PUL_CNT | 0.00% | 1134 | 289495.3616 / 262479.8816 / 156503.3358 |
| MOAV_LIVE_PUL_CNT | 0.00% | 1134 | 65493.6581 / 60070.28281 / 45701.10565 |
| HMDLV_NOCS | 0.00% | 946 | 1455 / 2728 / 1779 |
| OFLNE_SLS_AMT | 0.00% | 1097 | 20453533.02 / 18759824.16 / 14272360.19 |
| SHOP_SLS_AMT | 0.00% | 407 | 73621998 / 0 / 0 |

## 의미 해석
- `CRTR_YM`: 기준년월
- `CTPV_NM`, `SGG_NM`, `DONG_NM`: 지역
- `HMDLV_NOCS`: 온라인/택배 지표로 사용
- `OFLNE_SLS_AMT`: 오프라인 판매금액 지표
- `SHOP_SLS_AMT`: 전문매장/쇼핑 판매금액 지표
- 유동·생활인구 지표는 구매금액·주문건수와 구분해 원본 분석 정보로만 보존
- 제품명·상품분류·성별·연령대가 없어 Product/MFDS Mapping과 Category Mapping은 `NOT_APPLICABLE`

## Quality
- duplicate_rows: 0
- period_distribution: `{'202112': 1134}`
- region_distribution: `{'sido': 3, 'sigungu': 76, 'dong': 1100}`
- numeric_stats: `{'online_order_count': {'numeric_parse_success': 1134, 'negative_value_count': 0, 'missing_count': 0}, 'offline_mart_purchase_amount': {'numeric_parse_success': 1134, 'negative_value_count': 0, 'missing_count': 0}, 'specialty_store_purchase_amount': {'numeric_parse_success': 1134, 'negative_value_count': 0, 'missing_count': 0}}`

## Model 1 사용 범위
- 구매활동 존재 여부와 시장 Evidence로 사용한다.
- 구매금액·주문건수 자체를 Facet Candidate로 생성하지 않는다.
- 개별 소비자 Transaction, Product-level sales, MFDS SKU 판매량으로 해석하지 않는다.
