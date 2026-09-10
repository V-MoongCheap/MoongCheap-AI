# 네이버 쇼핑인사이트 수집 V1

네이버 쇼핑인사이트는 검색 클릭 추이의 상대값을 제공한다. 구매 건수나 원시 검색량이 아니므로 `CONSUMER_SEARCH_TREND` Evidence로만 사용한다.

## 실행 전 준비

내부 Category와 네이버 쇼핑 카테고리 코드의 매핑을 직접 확인해 JSON으로 만든다. 네이버 카테고리 코드는 상품 페이지 URL의 `cat_id`를 사용하며, 코드가 확인되지 않으면 임의로 작성하지 않는다.

```json
{
  "health-functional-food:vitamin_mineral": "네이버 cat_id"
}
```

환경 변수:

```text
NAVER_API_HUB_CLIENT_ID
NAVER_API_HUB_CLIENT_SECRET
```

## 실행

먼저 요청만 검토한다.

```powershell
python .git_upload_workspace/scripts/facet/collect_naver_shopping_insight.py `
  --category-map data/config/naver_category_map.json `
  --dry-run
```

실제 호출:

```powershell
python .git_upload_workspace/scripts/facet/collect_naver_shopping_insight.py `
  --category-map data/config/naver_category_map.json
```

결과:

- `data/processed/facet_discovery/naver_shopping_insight/naver_facet_keyword_trends_preview.csv`
- `data/processed/facet_discovery/naver_shopping_insight/naver_facet_keyword_trends.parquet`
- `data/processed/facet_discovery/naver_shopping_insight/naver_shopping_insight_failures.json`

수집 결과는 파셋을 자동 승인하는 데 사용하지 않고, 한국 소비자 관심도와 Alias 후보를 검토하는 보조 근거로 사용한다.
