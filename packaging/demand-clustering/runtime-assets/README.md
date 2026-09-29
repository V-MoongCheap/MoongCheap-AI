# B 이미지에 포함할 실행 자료

이 디렉터리는 Backend가 실제로 사용하는 도매꾹 v5 도감과 같은 상품 집합을
`demand-clustering` 이미지에 넣는다. 배치가 DB를 시드하거나 MFDS 상품으로
Backend 도감을 교체하지 않는다.

| 파일 | 역할 |
| --- | --- |
| `product_catalog_seed_v5.csv.gz` | 도매꾹 v5 상품 1,989건의 결정적 gzip |
| `category_seed_v5.csv.gz` | Backend category 시드 42건과 상품 카테고리 FK를 검증하는 gzip |
| `taxonomy.json` | 문장 구조화와 명시적 상품명 facet 추출에 사용하는 V2.2 분류표 |
| `catalog.json` | 행 수, 해시, DB 결합 방식과 대체상품 정책 |
| `model.json` | E5 저장소·고정 revision·파일별 SHA256 |

빌드하면 `/artifacts/product_catalog_seed_v5.csv`,
`/artifacts/category_seed_v5.csv`와
`/artifacts/taxonomy.json`이 생성된다. Backend `product_catalog.id`는 DB가
생성하므로 이미지에 고정하지 않는다. 런타임은 Backend의 UNIQUE 상품명과 v5
상품명을 정확히 비교해 현재 DB ID에 결합한다.

상품명이 v5에 없거나 v5 카테고리가 taxonomy에 매핑되지 않은 경우에도 동일상품
보드 편입과 신규 보드 생성은 진행한다. 해당 상품의 대체상품 제안만 건너뛴다.
대체상품 후보는 동일 v5 말단 카테고리로 제한하며 MFDS claim ID를 사용하지 않는다.
`extra_requirement`의 MUST/PREFER/EXCLUDE 문장 구조화는 기존 B 파서를 유지한다.

함께 전달된 `01_category_seed_v5.sql`과 `02_product_catalog_seed_v5.sql`은 각각
두 CSV의 Backend 적재용 projection이다. 현재 항목별 비교에서 42행·1,989행이
각각 일치했다. AI 이미지는 SQL을 실행하지 않고 두 CSV를 검증·조회하며,
Backend DB 적재는 category 후 product_catalog 순서로 별도 수행한다.

## 자료 갱신

Backend에 적용할 v5 CSV가 확정되면 저장소 루트에서 실행한다.

```bash
python scripts/deployment/prepare_demand_clustering_assets.py pack-seed \
  --seed /path/to/product_catalog_seed_v5.csv \
  --category-seed /path/to/category_seed_v5.csv \
  --taxonomy config/facet_taxonomy_v2_2.json \
  --release backend-v5-domeggook-YYYYMMDD \
  --assets packaging/demand-clustering/runtime-assets
```

두 CSV gzip, `taxonomy.json`, `catalog.json`을 함께 커밋한다. 빌드 단계는
압축본·복원 CSV·taxonomy 해시, 행 수, 상품명·Seed ID·도매꾹 ID의
유일성, category 부모 계층, 상품→category FK·경로·taxonomy 매핑을 다시
검증한다.
