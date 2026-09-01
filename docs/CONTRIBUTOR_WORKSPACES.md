# 역할별 개발 공간

## 역할 구분

| 역할 | 담당 영역 | 주요 경로 | Branch 접두사 |
|---|---|---|---|
| A | 데이터·Category·Facet | `src/moongcheap_ai/parts/aihub/`, `catalog.py`, `facet.py`, 데이터 처리 스크립트 | `feat/a-` |
| B | Demand Clustering | `src/moongcheap_ai/parts/demand_clustering/` | `feat/b-` |
| C | Seller Matching·Seller Analysis | `src/moongcheap_ai/parts/seller_matching/`, `src/moongcheap_ai/parts/seller_analysis/` | `feat/c-` |

역할 담당자 계정은 확정 전까지 임의로 연결하지 않는다. 담당자 확정 후 `.github/CODEOWNERS`에 계정을 추가한다.

## 작업 규칙

- 각 역할은 자신의 `parts/<domain>/`와 대응하는 `tests/<domain>/` 아래에 코드를 추가한다.
- 공통 모듈 변경 시 영향받는 역할의 검토 필요 여부를 PR 본문에 적는다.
- `main`과 `develop`에는 직접 Push하지 않고 역할 Branch에서 PR을 만든다.
- 작업 Branch는 `feat/<role>-<short-description>` 형식을 사용한다.
- 최종 통합과 충돌 해결은 Admin 담당자가 수행한다.

## GitHub 보호 규칙

- PR 승인 1개 필요
- 마지막 Push 승인 필요
- 대화 해결 필요
- 삭제 및 강제 Push 금지
- Admin 계정만 필요 시 Ruleset 바이패스 가능

바이패스는 긴급 수정이나 보호 규칙 조정 때만 사용한다. 일반 변경은 PR로 남겨 검토 이력을 보존한다.
