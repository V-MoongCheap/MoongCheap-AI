# Pipeline scripts

재실행 가능한 단계별 CLI는 `src/moongcheap_ai/pipeline.py`에서 제공하며, 향후 단계별 운영 스크립트는 아래 영역에 둡니다.

- `collect/`: MFDS raw 수집 및 AI-Hub 파일 확인
- `inspect/`: AI-Hub ZIP/JSON/JSONL/CSV/XLSX/Parquet 구조 검사
- `preprocess/`: 원본 최소 정규화
- `category/`: 관찰된 KAN Category 산출
- `catalog/`: Product Staging, Identity Resolution, Canonical Catalog
- `facet/`: Facet evidence와 taxonomy 후보
- `labeling/`: Demand label과 typed constraint batch 처리
- `demand/`: 합성 Demand와 Part C용 수요보드 mechanics snapshot 생성
- `evaluation/`: MFDS 근거·리뷰셋 생성, 방향성 relation·상품 검색·제안 품질 평가
- `audit/`: row count, completeness, conflict 검사

`demand/`의 시뮬레이션 변환과 `evaluation/`의 구현은
`moongcheap_ai.demand_clustering.evaluation`을 사용한다. CLI 경로는 유지하며,
운영 진입점 `demand-clustering-batch`에서는 이 평가 패키지를 불러오지 않는다.

5천 건 기반 수요보드 시뮬레이션은
`demand/simulate_demand_board_handoff.py`를 사용한다. catalog facet과 가격을
합성한다는 명시적 확인 옵션이 필요하며, 생성 데이터와 결과 보고서는 프로젝트
저장소에 포함하지 않는다.

실제 시간 흐름을 포함하는 기준 시나리오는
`demand/simulate_hourly_demand_board_handoff.py`를 사용한다. 실제 등록시각이 없는
Part A 입력을 명시된 시간 구간에 결정론적으로 분산하고, 1시간 배치와 48시간
미배정 만료를 반복한다.
