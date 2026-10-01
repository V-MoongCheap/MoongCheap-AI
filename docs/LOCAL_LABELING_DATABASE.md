# 로컬 A Labeling 데이터베이스

운영 PostgreSQL과 연결하기 전에 Backend와 유사한 로컬 PostgreSQL에서 A Labeling을 검증한다.

## 구성

- `docker/docker-compose.local-db.yml`: PostgreSQL 16, 호스트 Port `5433`
- `local_db/schema.sql`: `category`, `product_catalog`, `demand` 축소 Schema
- `scripts/local_db/seed_labeling_db.py`: 기존 5,000건 smoke 데이터를 Fixture로 삽입
- 입력: `data/processed/a_labeling_runtime_smoke.csv` (로컬 전용·Git 미포함; 새 checkout에는 별도 전달 필요)
- Taxonomy: `config/facet_taxonomy_v2_2.json`

운영 DB 비밀번호·Secret·Raw data는 사용하지 않는다. Seed는 테스트 데이터이며 실제 사용자 수요가 아니다.

## 실행

```bash
docker compose -f docker/docker-compose.local-db.yml up -d

A_DATABASE_URL="postgresql://moongcheap:moongcheap@localhost:5433/moongcheap_ai_local" \
PYTHONPATH=src \
.venv/bin/python scripts/local_db/seed_labeling_db.py
```

예상 결과:

```json
{"status": "SEEDED", "category_count": 17, "catalog_count": 1024, "demand_count": 5000}
```

## A Labeling 직접 저장 실행

> 현재 seed 입력은 이전 평가용 합성 데이터다. `catalog_id`가
> `catalog-seed-*` 형식이고, 실제 Backend ID로 연결된 Product Facet profile이
> 없다. 따라서 이 파일만 seed한 DB에 현행 A runtime을 실행하면 원상품 기본값을
> 검증할 수 없으며, 미처리로 남는 것이 정상이다. 이 fixture를 현재 A의 E2E로
> 부르지 않는다. 아래 실행은 `local_product_facets.csv`를 같은 local DB의
> `product_catalog.id`로 명시적으로 연결해 별도 준비한 경우에만 유효하다.

```bash
A_WRITE_DATABASE=true \
A_DATABASE_URL="postgresql://moongcheap:moongcheap@localhost:5433/moongcheap_ai_local" \
PYTHONPATH=src \
.venv/bin/python -m moongcheap_ai.data_foundation.runtime_job \
  --taxonomy config/facet_taxonomy_v2_2.json \
  --write-db
```

실행 시 `processed_at IS NULL`인 Demand와 Category Taxonomy를 읽고 Product Facet mapping CSV를 사용한다. 운영에서는 실제 Backend `product_catalog.id`를, 이 로컬 fixture에서는 DB에 seed된 local catalog ID를 써야 한다. 긍정 요구로 안정 해석된 Facet만 상품 기본값을 덮어쓴다. 일부 상품 Facet이 미확인이면 확인된 값은 유지하고 빠진 label 위치만 `ALL(0)`으로 둔다. 전체 상품 profile 누락, 잘못된 확정값, 중복/충돌, Category 불일치는 추정하지 않고 해당 Demand를 미처리 상태로 둔다.

`--write-db` 실행에는 `A_PRODUCT_FACETS_PATH`가 필수다(0건 batch도 동일). 예:

```bash
A_PRODUCT_FACETS_PATH=/path/to/local_product_facets.csv \
A_WRITE_DATABASE=true \
A_DATABASE_URL="postgresql://moongcheap:moongcheap@localhost:5433/moongcheap_ai_local" \
PYTHONPATH=src \
.venv/bin/python -m moongcheap_ai.data_foundation.runtime_job \
  --taxonomy config/facet_taxonomy_v2_2.json --write-db
```

CSV는 local `product_catalog.id`에 맞아야 한다. 운영용 Backend ID CSV를 그대로 local DB에 쓰지 말 것. 현재 저장소에는 `catalog-seed-*` fixture와 실제 Backend ID를 잇는 authoritative mapping이 없으므로, local profile이 따로 준비되지 않았다면 위 실행은 하지 않는다.

## 재실행 검증

같은 명령을 다시 실행하면 이미 처리된 행은 `processed_at IS NULL` 조건에 걸리지 않는다. 초기화가 필요하면 다음 명령으로 로컬 Volume을 삭제한 뒤 다시 시작한다.

```bash
docker compose -f docker/docker-compose.local-db.yml down -v
```

이 명령은 로컬 Fixture만 삭제하며 운영 데이터에는 영향을 주지 않는다.
