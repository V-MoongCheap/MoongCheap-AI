# 기능별 작업 공간

이 저장소는 기능별 패키지와 테스트 디렉터리를 같은 이름으로 맞춘다.

| 기능 | 구현 위치 | 테스트 위치 | 브랜치 접두사 |
|---|---|---|---|
| 상품 데이터·Category·Facet·Demand Labeling | `src/moongcheap_ai/data_foundation/` | `tests/data_foundation/` | `feat/data-` |
| Consumer Demand Clustering | `src/moongcheap_ai/demand_clustering/` | `tests/demand_clustering/` | `feat/clustering-` |
| Seller Matching | `src/moongcheap_ai/seller_matching/` | `tests/seller_matching/` | `feat/seller-` |
| Seller Demand Analysis·E2E | `src/moongcheap_ai/seller_analysis/` | `tests/seller_analysis/` | `feat/seller-` |

## 작업 규칙

- 상품 데이터, Category, Catalog, Facet, Labeling 관련 새 구현은 `data_foundation` 아래에 둔다.
- `src/moongcheap_ai/` 바로 아래의 같은 이름 모듈은 기존 import를 위한 호환 facade다. 새 로직은 이 위치에 추가하지 않는다.
- AI-Hub 원본 형식 처리는 `src/moongcheap_ai/parts/aihub/`에 둔다. 이 패키지는 형식 어댑터와 공통 입력 변환만 담당한다.
- 기능 패키지와 같은 이름의 `tests/<기능>/`에 테스트를 둔다.
- 공통 실행 흐름은 `pipeline.py`, ERD 계약은 `erd_contract.py`에서 관리한다.
- DB 연결 전까지는 CSV/JSON 로컬 I/O 계약을 유지한다.
- `main`과 `develop`에는 직접 Push하지 않고 기능 브랜치에서 PR로 반영한다.

## 브랜치 예시

```text
feat/data-category-validation
feat/data-model1-normalization
feat/clustering-facet-baseline
feat/seller-matching-v0
```
