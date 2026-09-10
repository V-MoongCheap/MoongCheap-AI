# Model 1 Multi-source 입력 구조 V1

Model 1은 원본 파일을 직접 모델에 넘기지 않는다. 각 Source Loader가 공통 컬럼으로 변환한 뒤 Category별 샘플을 JSONL로 만들고, 모델은 그 샘플과 Evidence만 읽는다.

## 입력 파일

| Source | 기본 경로 | 사용 목적 | 주요 필드 |
|---|---|---|---|
| MFDS_PRODUCT | `data/interim/facet_discovery/i0030_products_clean_dedup.csv` | 상품의 규제·제형·원료 사실 | `product_name`, `product_form`, `functional_ingredients`, `regulated_function` |
| SELLER_LISTING | `data/processed/domeggook/seller_offers_core.csv` | 판매 공고의 상품 표현·가격·MOQ | `product_name`, `package_spec`, `ingredients_raw`, `functionality_raw`, `intake_raw`, `base_unit_price`, `moq` |
| GROUNDED_DEMAND_SYNTHETIC | `data/synthetic/consumer_reference/grounded_demand_v2_1000.csv` | 상품 데이터에 근거한 가상 구매 요청 | `catalog_id`, `extra_requirement`, `facet_requirements`, `price_option`, `quantity` |
| DEMAND_BOARD_SYNTHETIC | `F:\downloadF\demand_board_snapshot_5000.json` | 가상 수요 보드의 조건 집계 | `catalogId`, `priceMin`, `priceMax`, `participantCount`, `status` |
| CONSUMER_SEARCH | `data/interim/facet_evidence/kuaiseach_health_queries_ko_reviewed_v27.parquet` | 번역된 검색 표현·관심 신호 | `query_translated`, `source_record_id` |

## 공통 입력 컬럼

각 Source는 다음 구조로 변환된다.

- `category_key`: V2.1 서비스 Category 키
- `category_name`: 표시용 이름
- `source_product_id`: 원본 제품·요청·공고를 추적하는 ID
- `product_name`: 상품명 또는 요청의 기준 상품
- `source_category`: 원본 Category 또는 판매 분류
- `product_form`: 제형·포장 형태
- `functional_ingredients`: 기능성 원료 표현
- `regulated_function`: MFDS 기능성 문장 또는 구매 요청 문장
- `intake_method`: 섭취 방법 표현
- `price_text`, `quantity_text`, `seller_condition`: 가격·수량·판매 조건
- `evidence_text`: 모델이 인용할 수 있는 원문
- `source_type`: Source 종류

## 샘플링과 모델 호출

- MFDS와 판매 공고는 Category별 최대 8건을 샘플링한다.
- Demand는 Category별 최대 8건을 사용한다.
- 소비자 검색은 Category별 최대 4건을 사용한다.
- Source ID 중복을 제거한 뒤 Category별로 한 번씩 모델을 호출한다.
- 실행 시 생성되는 실제 모델 입력은 `data/processed/model1_multisource_v1/multisource_model_input_v1.jsonl`이다.

## Source 해석 원칙

- MFDS 상품 필드: 상품 사실과 규제 근거
- 판매 공고: 시장에서 사용되는 상품명·조건 표현
- 합성 Demand: 구매 조건의 형식 확인용이며 실제 시장 인기도로 해석하지 않음
- Demand Board: 가격·참여자 수가 시뮬레이션 값이므로 실제 수요 통계로 해석하지 않음
- 소비자 검색: 검색 표현 신호일 뿐 구매 확정이나 상품 적합성의 증거가 아님

## 검토 흐름

```text
원본 Source
→ 공통 컬럼 변환
→ Category별 샘플 JSONL
→ Model 1 후보·Evidence 생성
→ Schema/Evidence 검증
→ 중복·언어·규제 문장 정규화
→ review_queue에서 사람 결정
→ human_accepted 결과
```
