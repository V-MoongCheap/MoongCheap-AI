# A 전체 점검 후 실행·평가 기준

## 실행 경로

- 현행 A Labeling은 `data_foundation.runtime_job.run_batch`를 사용한다. `mvp_pipeline.label_batch`도 같은 함수를 호출하며, 검증 없는 substring alias 덮어쓰기는 금지한다.
- 로컬 상품 프로필은 운영과 동일하게 양의 정수 `backend_catalog_id`를 사용한다. Seed/source ID를 Backend ID로 가장하지 않는다.
- 원상품의 확정된 Facet을 유지하고 명확한 긍정 조건만 덮어쓴다. 없는·모호한·실패한 요구는 원상품 기준을 유지한다. 불확실한 상품 속성을 임의로 확정하지 않는다.
- `mvp_pipeline`의 B 부분은 옛 CSV 그룹화다. `group_count`는 보드 생성 건수가 아니며 `substitution_consent_count`는 편입 건수가 아니다. `created_new`와 `substitute_joined`는 실제 수행하지 않았으므로 0이다. B 운영 검증은 해당 planner로 별도 수행한다.

## DB checkpoint와 시간 예산

- `--write-db`는 기본 5건씩 해석하고 완료된 묶음마다 저장한다. `A_DB_CHUNK_SIZE`로 양의 정수 크기를 지정할 수 있다.
- `A_BATCH_TIME_BUDGET_SECONDS` 기본값은 1500초다. Cloud의 1800초 deadline에 여유를 남긴다. 남은 시간이 부족하면 새 묶음을 시작하지 않고 `deferredRows`를 기록한다. 미시작 수요는 `processed_at`을 쓰지 않아 다음 실행 대상이다.
- 모델 대상 100건을 버리는 제한이 아니다. 읽기 snapshot은 기본 최대 10,000건이며 이후 수요는 DB pending으로 남는다. 이는 무한 메모리 사용을 방지하는 읽기 범위다.
- 첫 읽기 transaction은 모델 호출 전에 종료한다. 저장은 기존 id/status/processed_at 조건에 더해 읽었던 catalog_id와 extra_requirement가 동일한 경우에만 적용한다. 새 UPDATE 컬럼이나 스키마 변경은 필요 없다.
- 뒤쪽 chunk가 실패해도 앞쪽 완료 chunk는 유지된다. 동일 요청 재실행 시 이미 완료된 행은 기존 SQL 조건으로 다시 쓰지 않는다. 전 배치 원자성 대신 **chunk 단위 원자성**이다.
- deadline·Ollama 종료·프로세스 강제 종료를 완전히 예방한다는 보장은 아니다. 아직 실행 중인 chunk는 재시도될 수 있다. 상품 프로필이 없어 REVIEW인 행도 여전히 미처리 상태로 남는다.
- CSV 출력은 전체 DB snapshot과 달리 완료한 chunk의 결과다. 시간 제한 시 `rows`와 `deferredRows`를 함께 확인해야 한다. 전체 커밋과 CSV 파일 생성은 하나의 transaction이 아니다.

## 평가와 Gold

- `evaluate_part_a_gold_v2_2.py`와 `evaluate_model2_gold_v1.py`는 현행 A와 같은 `build_a_parser`/A 전용 정책을 사용한다.
- 이들은 typed parser 구성요소 평가다. 원상품 적용 후 최종 Label 정확도·실제 Qwen 호출 품질·DB 적용 검증과 구분한다.
- 지원 Gold의 exact 비교는 Facet 이름·Facet 코드·Value 이름·Value 코드·조건 유형을 모두 확인한다. 의미 일치와 숫자 계약 일치를 분리한다.
- `--align-gold-codes`는 별도 폴더에 선택 release의 정확한 canonical 의미로 코드만 재연결한다. 사람 정답 원본·의미·검토 결정은 변경하지 않는다. 의미가 없거나 복수로 매칭되면 실패한다. Challenge는 그대로 복사하고 hash와 변경 이력을 기록한다.
- 예시: `PYTHONPATH=src .venv/bin/python scripts/evaluation/evaluate_model2_gold_v1.py --align-gold-codes --output-dir /tmp/a-gold-release-new`.
- 원본 Gold와 다른 release를 비교해 생긴 오류를 모델의 의미 오류로 보고하지 않는다. 코드를 맞춘 사본의 성공을 모델 성능 개선이라고 보고하지 않는다.

## Model 1 실험

- consistency 투표는 공용 `model1_consensus.select_consensus` 기준이다. 생성 1회당 같은 후보는 최대 1표, 실패한 생성도 분모에 포함, 엄격 과반수 필요, 무합의 fallback 금지.
- 합의 후보는 첫 응답에 없어도 전체 생성에서 수집한다. 근거가 여러 행이라는 사실을 독립 모델 생성 횟수로 세지 않는다.
- 원본 source ID와 해당 원문의 Value를 함께 확인한다. 검증 단계에서 넣은 `DRAFT_CANDIDATE`나 다른 상품의 원문으로 후보를 정당화하지 않는다.
- 수정 전 consistency 실험 기록은 과거 구현의 결과다. 수정 후 수치로 재인용하지 않는다. few-shot/summary 등 투표를 사용하지 않는 모든 과거 점수가 잘못됐다는 뜻은 아니다.

## 설치·CI·artifact

- A 재현 설치는 `uv sync --project packaging/a-labeling --locked --extra dev`가 기준이다. 루트 optional API/data와 C requirements는 A 배포 설치 기준이 아니다. 다른 파트 의존성을 이번 A 수정에서 변경하지 않았다.
- A 테스트·Model 1 실험 스크립트만 변경한 PR도 Jenkins A 검증 대상으로 잡는다. 공유 `src/` 변경은 기존 CI에 따라 B/C 이미지 빌드를 유발할 수 있다.
- A 이미지는 상품 Facet CSV와 Taxonomy의 SHA를 빌드에서 검사하고 OCI label로 남긴다. Jenkins가 기존 A ECR 태그를 재사용할 때도 지문을 확인한다. 다른 지문 또는 지문 없음이면 실패시키고 새 commit/tag를 요구한다.
- 승인 artifact 변경 시 Dockerfile의 SHA 기본값과 Jenkins 공급/기존 이미지 검사 SHA를 같은 commit에서 갱신한다. 외부 파일만 교체해 동일 태그에 새 release가 반영됐다고 주장하지 않는다.
- 현재 Jenkins Trivy는 취약점 검출만으로 실패하지 않는 설정이다. Jenkins SUCCESS는 취약점 없음 판정이 아니다. 공용 보안 예외 정책은 A가 임의 변경하지 않았다.

## A 수정 밖에 남은 문제

B의 복수 성분 프로필 정보 손실/EXCLUDE 우회와 C 최소 참가자 수 정책 충돌은 이번에 수정하지 않았다. Cloud 설정·B/C 로직·가중치도 변경하지 않았다. A의 로컬 회귀 통과를 전체 AI 프로젝트 종료 판정으로 사용하지 않는다.

## 재평가 지표 해석

### 추가 재점검

- Model 1 합의 결과의 Alias/Evidence가 list/dict일 때 `drop_duplicates`가 TypeError로 종료되는 경로를 제거했다. 구조화 셀을 보존하고 직렬화 지문으로 동일 행만 제거한다.

- DB 원본 카테고리 연결과 `category.facet`도 저장 직전에 비교한다. 분석 중 변경되면 업데이트 0건으로 남겨 다음 배치에서 재분석한다. JSON 공백/키 순서 변화는 의미 변화로 취급하지 않는다. 구형 스키마의 외부 매핑 경로에는 없는 `pc.category_id`를 조회하지 않는다.
- 시간 예산은 LLM 실패 시 재시도뿐 아니라 singleton까지 재귀 분할하는 최악 호출 수를 포함한다. 이는 socket timeout 예산이며 OS 스케줄링·DB 대기까지 포함한 엄격한 wall-clock 보증은 아니다.
- chunk size/time budget의 boolean·소수·0·음수 및 누락 demand ID 컬럼은 DB 쓰기 전에 명시적으로 거부한다.

2026-10-04 A 전용 parser 정책으로 200건을 재평가한 전체 행 일치는 144/200이다(Dev 100/100, Holdout 30/50, Challenge 14/50). 원래 공용 parser의 146/200과 평가 대상이 다르며, 이 숫자도 최종 Label/LLM 운영 정확도가 아니다. 신규 표현의 의미 해석 품질이 모두 해결됐다고 주장하지 않는다.

지원 Gold는 원본과 다른 release의 숫자 코드를 비교하면 5/15, 의미만 비교하면 15/15다. 원본을 보존하고 코드만 재연결한 별도 사본에서는 Facet 코드까지 포함한 계약 비교 15/15다. 이는 평가 데이터의 release 정합화다.
