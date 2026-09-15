# 작업 인수인계

## 현재 상태

이 저장소는 MoongCheap의 데이터·AI 영역입니다. 현재 MVP 범위는 다음과 같습니다.

1. Consumer Demand Clustering
2. Demand Cluster–Seller Offer Matching
3. Seller Demand Analysis

현재 작업 Branch에는 AI-Hub 점검, 관측된 KAN Category 처리, 상품 staging 및 식별, MFDS 수집·파싱, Rule 기반 Facet 후보 도출 V0가 포함되어 있습니다. Clustering과 Seller Matching은 아직 구현하지 않았습니다.

Implementation lives under `src/moongcheap_ai`; data, Category, Facet, and Labeling additions belong under `src/moongcheap_ai/data_foundation/`, with matching tests under `tests/data_foundation/`.

## 기준 원칙

동작을 변경하기 전 프로젝트 소유자가 전달한 최신 지시를 확인합니다. Naver Shopping, GobizKorea, Open Icecat, K-FIND, Domeggook, Consumer RAG 또는 AI 전용 DB는 다시 도입하지 않습니다.

- Backend and AI share PostgreSQL.
- `category.facet` is TEXT containing JSON; parse it in Python.
- Backend owns original Demand and transaction state.
- Raw data is immutable; never fabricate missing fields.
- Do not add DB migrations without reporting the problem and alternatives first.

## 주요 경로

```text
data/raw/aihub/logistics_product/  # user-provided AI-Hub files
data/raw/aihub/product_image/      # user-provided AI-Hub files
data/raw/kan/                      # optional official KAN codebook
data/raw/mfds/I0030/
data/raw/mfds/I2710/
```

## 실행 방법

```powershell
Copy-Item .env.example .env
$env:MFDS_API_KEY = "..."
./run_data_pipeline.ps1 -Stage all
```

AI-Hub 데이터가 없으면 Catalog 단계는 `SKIPPED`로 남겨야 합니다. 성공을 표시하기 위한 가상 데이터를 만들지 않습니다. MFDS 수집에는 `MFDS_API_KEY`가 필요하며, 기존 원본 페이지를 재사용할 수 있습니다.

## 주요 산출물

- `data/interim/products/product_staging.parquet`
- `data/processed/product_catalog/product_catalog_v1.parquet`
- `data/processed/product_catalog/product_catalog_source.csv`
- `data/interim/facet_discovery/i0030_products_clean.parquet`
- `data/interim/facet_discovery/i2710_reference.csv`
- `data/processed/facet_discovery/facet_review_queue.csv`
- `data/processed/facet_discovery/facet_taxonomy_v0.json`
- `data/reports/TODAY_RESULT.md`

변경 후 `pytest -q`를 실행합니다. 명확한 조건과 수치 처리는 Rule/SQL/Python으로 구현하고, 언어 모델은 측정 가능한 실험 근거가 있을 때만 사용합니다.
