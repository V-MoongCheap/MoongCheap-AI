# KuaiSearch 번역 교정 V2

기존 한국어 번역에는 원문 복사, 기호뿐인 응답, 상품 종류 오역이 포함되어 있습니다.
`repair_kuaisearch_translation.py`는 이 항목들을 실제 로컬 모델로 재번역합니다.

프로젝트 루트의 가상환경에서 실행합니다. 코드가 `.git_upload_workspace`에 있는
현재 로컬 배치에서는 아래 경로를 사용합니다.

```powershell
.\.venv\Scripts\python.exe .git_upload_workspace/scripts/facet/repair_kuaisearch_translation.py --model qwen3:4b --passes 1
```

일반 저장소 체크아웃에서는 `scripts/facet/repair_kuaisearch_translation.py` 경로를 사용합니다.
모델은 설치된 모델명을 지정하며, 기본값은 `qwen3:4b`입니다.

- 입력: `data/interim/facet_evidence/kuaiseach_health_queries_ko.parquet`
- 별도 결과: `data/interim/facet_evidence/kuaiseach_health_queries_ko_v2.parquet`
- 진행 상태: 출력 파일의 `.progress.json`
- 변경 전후: 출력 파일의 `.changes.csv`
- 미해결 항목: 출력 파일의 `.review.csv`
- 호출 응답 및 거절 사유: 출력 파일의 `.attempts.jsonl`
- 원본 버전: 출력 파일의 `.metadata.json`에 입력 SHA-256 기록

같은 명령으로 이어서 실행하면 이미 자동 검증을 통과한 행은 건너뜁니다.
실행은 동시에 하나만 진행해야 합니다. `--limit`은 재번역 대상 수만 제한하며
출력에는 전체 행을 보존합니다. `--passes 2`는 첫 배치에서 통과하지 못한 항목을
한 건씩 다시 호출합니다. 호출 오류가 세 번 연속 발생하면 중단하고 결과를 보존합니다.

V2에는 `translation_original`, `repair_candidate`, `repair_status`, `repair_flags`,
`repair_model`, `repair_attempts`를 기록합니다. 검증에 실패한 후보는 원래 번역을
덮어쓰지 않으며 `NEEDS_REVIEW`로 남습니다. 기호뿐인 원문도 별도 검토 대상으로 남깁니다.

자동 검증 통과는 번역 정확도 보증이 아닙니다. 용어 검사는 제한된 사전 기준이며,
한자 이름이나 정상 동의어도 검토 대상으로 잡힐 수 있습니다. 기존 파셋 입력을 V2로
자동 전환하지 않습니다. 도메인 재분류와 번역 품질 검토는 별도 단계입니다.

체크포인트와 CSV/JSON 산출물은 로컬 데이터입니다. 원문 및 결과 데이터를 커밋하지 않습니다.
