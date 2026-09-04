# Consumer Demand Clustering

Labeling 결과를 받아 Catalog, Facet, 가격·수량, 대체 가능성을 기준으로 Demand Cluster를 만든다.

현재 구현은 다음 범위만 담당한다.

- Backend ERD v2 형태의 Demand와 DemandBoard 입력 변환
- 클러스터링 가능 Demand 및 기존 Board 후보 필터링
- 확정 Price Band 기반의 결정론적 기존 Board 편입·신규 Board 생성 계획
- 공유 PostgreSQL에서 적격 입력을 읽는 read-only adapter

계획 반영 시 잠금, 상태 재검증, Board 생성 및 Demand 상태 변경의 소유 주체는
Backend 협의 후 결정하며 이 패키지는 아직 DML을 실행하지 않는다.
