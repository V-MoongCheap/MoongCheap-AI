# 오늘 결과

AI-Hub 원본을 배치하고 MFDS API Key를 설정한 뒤 `run_data_pipeline.ps1`을 실행합니다.

## 현재 구현

- AI-Hub zip/json/jsonl/csv/xlsx/parquet Inspector
- AI-Hub Product Staging 및 원본 스키마 보존
- Barcode 기반 Identity Resolution과 conflict 기록
- Observed KAN Category Master 초안
- Canonical Product Catalog 및 source provenance
- MFDS I0030/I2710 재개 가능한 수집과 최소 표준화
- Repeated Terms와 Structured Value Distribution
- Rule 기반 Facet Taxonomy V0 초안 및 Human Review Queue
- 재실행 가능한 report와 `SKIPPED` 상태 기록

## 미실행 사유

- 현재 환경에 AI-Hub 원본과 `MFDS_API_KEY`가 없습니다.
- 따라서 실제 row count는 아직 기록하지 않았습니다.

## 다음 확인 항목

- MFDS 실제 응답 필드명과 표준 컬럼 매핑
- 건강기능식품 Pilot Category 선정
- Facet 후보 Human Review
- KAN과 MFDS Category 수준 Mapping
- 실제 AI-Hub/MFDS Schema 기반 필드 매핑 보정
