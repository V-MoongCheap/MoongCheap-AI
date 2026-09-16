# 로컬 A Labeling 데이터베이스

운영 PostgreSQL과 연결하기 전에 Backend와 유사한 로컬 PostgreSQL에서 A Labeling을 검증한다.

## 구성

- `docker/docker-compose.local-db.yml`: PostgreSQL 16, 호스트 Port `5433`
- `local_db/schema.sql`: `category`, `product_catalog`, `demand` 축소 Schema
- `scripts/local_db/seed_labeling_db.py`: 기존 5,000건 smoke 데이터를 Fixture로 삽입
- 입력: `data/processed/a_labeling_runtime_smoke.csv`
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

```bash
A_WRITE_DATABASE=true \
A_DATABASE_URL="postgresql://moongcheap:moongcheap@localhost:5433/moongcheap_ai_local" \
PYTHONPATH=src \
.venv/bin/python -m moongcheap_ai.data_foundation.runtime_job \
  --taxonomy config/facet_taxonomy_v2_2.json \
  --write-db
```

실행 시 `processed_at IS NULL`인 Demand를 읽고, 완료된 Label만 `demand.label`과 `demand.processed_at`에 저장한다. `REVIEW` 결과는 저장하지 않는다.

## 재실행 검증

같은 명령을 다시 실행하면 이미 처리된 행은 `processed_at IS NULL` 조건에 걸리지 않는다. 초기화가 필요하면 다음 명령으로 로컬 Volume을 삭제한 뒤 다시 시작한다.

```bash
docker compose -f docker/docker-compose.local-db.yml down -v
```

이 명령은 로컬 Fixture만 삭제하며 운영 데이터에는 영향을 주지 않는다.
