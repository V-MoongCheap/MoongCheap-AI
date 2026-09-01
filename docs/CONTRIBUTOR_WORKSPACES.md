# 역할별 개발 공간

## 역할 구분

| 담당 영역 | 주요 책임 | 주요 경로 | Branch 접두사 |
|---|---|---|---|
| 데이터·Category·Facet·Demand Labeling | 상품 데이터 수집·전처리, Category/Catalog 후보, Facet 도출, Demand Labeling, Clustering 입력 생성 | `src/moongcheap_ai/parts/aihub/`, `catalog.py`, `facet.py`, 데이터 처리 스크립트 | `feat/data-` |
| Consumer Demand Clustering | Labeling 결과 기반 수요 묶음, Facet·가격·수량·대체 조건 비교, Cluster 집계 | `src/moongcheap_ai/parts/demand_clustering/` | `feat/clustering-` |
| Seller Matching·Demand Analysis·E2E | Cluster와 Seller Offer 비교, 평가·순위, 판매자용 분석, 전체 로컬 연결 | `src/moongcheap_ai/parts/seller_matching/`, `src/moongcheap_ai/parts/seller_analysis/` | `feat/seller-` |

담당자 계정은 문서에 기록하지 않는다. 담당자별 검토 정책이 필요해지면 `.github/CODEOWNERS`에 계정을 추가한다.

## 작업 규칙

- 각 역할은 자신의 `parts/<domain>/`와 대응하는 `tests/<domain>/` 아래에 코드를 추가한다.
- 공통 모듈 변경 시 영향받는 역할의 검토 필요 여부를 PR 본문에 적는다.
- `main`과 `develop`에는 직접 Push하지 않고 역할 Branch에서 PR을 만든다.
- 작업 Branch는 `feat/<area>-<short-description>` 형식을 사용한다.
- DB 연결은 각 기능의 로컬 CSV/JSON 입출력 구현과 검증이 끝난 뒤 통합 단계에서 진행한다.
- 최종 통합과 충돌 해결은 Admin 담당자가 수행한다.

## GitHub 보호 규칙

- PR 승인 1개 필요
- 마지막 Push 승인 필요
- 대화 해결 필요
- 삭제 및 강제 Push 금지
- Admin 계정만 필요 시 Ruleset 바이패스 가능

바이패스는 긴급 수정이나 보호 규칙 조정 때만 사용한다. 일반 변경은 PR로 남겨 검토 이력을 보존한다.
