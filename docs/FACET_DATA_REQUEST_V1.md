# Model 1 Facet 실험 데이터 요청서 V1

추가 데이터를 제공받기 위한 입력 계약이다. API Key, 비밀번호, `.env`, 원본
인증정보는 전달하지 않는다.

## 0. 사용자가 지금 전달할 것

현재 보유 데이터로 우선 실험을 진행할 수 있으므로, 외부 Dataset을 새로
선정해 달라는 요청은 하지 않는다.

사용자에게 필요한 추가 입력은 다음 하나다.

1. 네이버 Shopping Insight를 실행할 카테고리의 공식 Category URL 또는
   `cat_id`

리뷰를 더 추가하고 싶은 경우에만 아래 2개 파일을 선택적으로 전달한다.

2. `reviews.csv`
3. 상품 ID가 리뷰에 없을 때의 `review_product_mapping.csv`와 출처·라이선스 파일

WANDS, MFDS I0030/I2710, 현재 보유한 Nutrime 리뷰는 별도 전달하지 않아도
된다. WANDS는 로컬 원본을 확보했고, MFDS와 Nutrime은 현재 저장소의 기존
데이터를 사용한다.

키 발급이 필요한 경우의 공식 경로:

- 네이버 API HUB: https://console.ncloud.com/ → NAVER API HUB → Application
- 네이버 API HUB 안내: https://api.ncloud-docs.com/docs/naver-api-hub-overview
- 식품안전나라 데이터활용서비스: https://www.foodsafetykorea.go.kr/api/

네이버는 `NAVER_API_HUB_CLIENT_ID`와 `NAVER_API_HUB_CLIENT_SECRET` 두 값을
발급한다. 식품안전나라는 `MFDS_API_KEY` 하나를 발급한다. 실제 값은 `.env`에만
입력하고 Git이나 채팅에 붙여넣지 않는다.

## 1. 외부 Dataset

일반 상품 Facet 일반화 실험에는 `Wayfair WANDS`를 1순위로 사용한다.

- 공식 저장소: https://github.com/wayfair/WANDS
- LICENSE 파일을 확인한 로컬 연구용 원본만 사용
- 건강기능식품 Taxonomy에 Value를 직접 추가하지 않음

받을 파일:

```text
dataset/product.csv
dataset/query.csv
dataset/label.csv
LICENSE
```

사용 필드:

```text
product_id,product_name,product_class,category_hierarchy,
product_description,product_features,query_id,query,label
```

WANDS에서 실제로 사용할 범위:

```text
furniture
home_decor
kitchen_and_tabletop
```

WANDS는 Wayfair의 가구·홈 상품 중심 데이터다. 화장품, 스포츠, 반려동물,
패션 상품 데이터로 간주하지 않으며, 해당 도메인의 Facet을 검증하는 데
사용하지 않는다. WANDS의 목적은 상품명·설명·구조화 속성에서 Facet 후보를
추출하는 일반화 실험과 검색어-상품 관련성 검증이다.

또한 원본 파일은 확장자가 `.csv`이지만 탭(`\\t`) 구분 형식이므로 일반 CSV
쉼표 파서로 읽지 않는다.

## 2. 일반 상품 내부 Export

현재 내부 일반 상품 데이터가 없다면 WANDS로 먼저 실험한다. 이후 내부 Export가
생기면 다음 컬럼만 받는다.

```text
source_product_id,name,category_path,description,spec_summary,
structured_attributes,brand,manufacturer,source_url,snapshot_date
```

권장량은 Category별 100~300개 상품이다. 다만 현재는 내부 일반상품 Export를
새로 요구하지 않고, WANDS로 먼저 실험한다.

## 3. 리뷰 데이터

리뷰는 상품과 연결되지 않으면 Facet 근거로 사용하지 않는다.

받을 파일:

```text
reviews.csv
review_product_mapping.csv   # 리뷰에 상품 ID가 없을 때만
source_license.txt
```

`reviews.csv` 필수 컬럼:

```text
source_review_id,source_product_id,review_text,rating,review_date,
source_name,collection_date
```

Mapping 파일 필수 컬럼:

```text
source_review_product_key,source_product_id,mapping_method,
mapping_confidence,mapping_note
```

권장량은 건기식 핵심 Category 8개, Category별 상품 10~20개, 상품별 리뷰
20~50개다. 매핑되지 않은 리뷰는 표현 참고용으로만 분리한다.

## 4. Naver Shopping Insight

입력 파일은 다음 위치에 만들어 두었다.

```text
data/config/naver_category_map.json
```

모든 ID는 빈 값이다. 네이버 쇼핑 Category URL에서 `cat_id`를 확인한 뒤
`naver_cat_id`만 입력한다. ID를 임의로 만들지 않는다.

21개 항목을 전부 채울 필요는 없다. 실제 실험할 Category만 채우면 된다.
최소 권장 범위는 건강식품 상위 Category 1개와 일반상품 5개이며, 세부
건강기능식품 Facet Category마다 별도 ID가 확인되는 경우에만 추가한다.

```json
"non-health:cosmetics": {
  "naver_cat_id": "확인한_cat_id",
  "status": "VERIFIED",
  "category_url": "확인한_URL"
}
```

검증 후 실행:

```bash
PYTHONPATH=src .venv/bin/python scripts/facet/collect_naver_shopping_insight.py \
  --input data/processed/model1_review_kanana_210_fixed/multisource_candidate_readable_v1.csv \
  --category-map data/config/naver_category_map.json \
  --output-dir data/raw/consumer_reference/naver_shopping_insight \
  --dry-run
```

Shopping Insight는 상품 목록·구매량이 아니라 Category·키워드별 상대 클릭
추이를 제공하므로 보조 근거로만 사용한다.

## 5. 사용하지 않는 데이터

- 출처·라이선스가 없는 리뷰 크롤링 결과
- 상품 ID와 연결되지 않은 리뷰
- 검색량만으로 확정한 Facet
- WANDS/ESCI/xPQA 결과를 건강기능식품 사실 데이터로 사용하는 것
- 다른 상품 Category의 Value를 건강기능식품 Taxonomy에 직접 병합하는 것

## 6. 제공 후 실험군

```text
MFDS-only
MFDS + Seller
MFDS + Review
MFDS + Shopping Insight
WANDS-only
```

모든 결과는 `source_type`, `source_record_id`, `snapshot_date`를 유지하며,
근거 없는 Model-only 후보는 Taxonomy로 승격하지 않는다.

## 7. 현재 확보 상태와 미확보 상태

| 항목 | 상태 | 비고 |
|---|---|---|
| MFDS I0030 | 부분 수집 완료 | 2026-09-23 스냅샷 19,700건. 공식 전체 건수보다 적고 API `INFO-320`에서 중단됨 |
| MFDS I2710 | 수집 완료 | 548건 |
| Nutrime 리뷰 | 기존 보유분 사용 가능 | 423건 원본, 348건 건강기능식품 확인분. 19개 상품에 집중되어 대표성은 제한적 |
| WANDS | 로컬 확보 완료 | `data/raw/external/wands/`, Git에는 커밋하지 않음 |
| Naver Shopping Insight | 실행 대기 | 카테고리별 공식 `cat_id`가 필요하며, 상대 클릭 추이 보조 근거로만 사용 |
| 추가 일반상품 Export | 현재 요청하지 않음 | WANDS로 비건강 일반화 실험을 먼저 수행 |
