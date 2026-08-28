# Pipeline scripts

재실행 가능한 단계별 CLI는 `src/moongcheap_ai/pipeline.py`에서 제공하며, 향후 단계별 운영 스크립트는 아래 영역에 둡니다.

- `collect/`: MFDS raw 수집 및 AI-Hub 파일 확인
- `preprocess/`: 원본 최소 정규화
- `facet/`: Facet evidence와 taxonomy 후보
- `audit/`: row count, completeness, conflict 검사
