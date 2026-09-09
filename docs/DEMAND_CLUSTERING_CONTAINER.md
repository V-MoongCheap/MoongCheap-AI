# 수요 클러스터링 컨테이너 인계

이 이미지는 `demand-clustering-batch`를 한 번 실행하고 종료하는 CPU 배치다.
HTTP 서버가 아니므로 Service, Ingress, 애플리케이션 포트, HTTP health check는
필요하지 않다. 성공은 종료 코드 0, 실행 실패는 1, 설정 오류는 2다.

AI는 Dockerfile·기본 CronJob 매니페스트·실행 계약·자원 측정 자료를 제공한다.
Jenkins/ECR 이미지 배포, GitOps 갱신, ArgoCD/EKS 연결과 환경별 운영 설정은 인프라
측에서 구성한다. [Kubernetes 안내](../k8s/README.md)에 Secret·볼륨·AI 노드 배치
설정과 배포 전 준비 사항을 정리했다.
전달용 필드는 [B파트 인계서](ci-cd-demand-clustering-handoff.yml)에 있다.

## 빌드 및 기본 검증

저장소 루트에서 실행한다. 현재 검증 대상은 Linux amd64, Python 3.13.12다.

```bash
uv sync --project packaging/demand-clustering --locked --extra data --extra dev
uv run --project packaging/demand-clustering --no-sync pytest -c packaging/demand-clustering/pyproject.toml
docker build -f docker/Dockerfile.demand-clustering -t demand-clustering-job:local .
docker run --rm --network none --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=256m \
  --cap-drop ALL --security-opt no-new-privileges \
  demand-clustering-job:local --help
```

- `packaging/demand-clustering/`의 `pyproject.toml`과 `uv.lock`으로 B파트 의존성을 고정한다. PyTorch는 CPU 전용 index를 사용한다.
- 빌드용 uv와 캐시는 최종 이미지에 복사하지 않는다. 패키지는 non-editable로 설치한다.
- 이미지에는 Python 의존성, 애플리케이션 패키지, 자연어 규칙·별칭 JSON만 포함한다.
  전용 `.dockerignore`의 allowlist로 `.env`, 테스트, 데이터와 모델을 빌드 입력에서 제외한다.
- UID/GID는 `65534:65534`다. 루트 파일시스템을 읽기 전용으로 실행할 수 있으며
  임시 파일용 `/tmp`는 쓰기 가능해야 한다.

## 모델·데이터·환경 변수 공급

| 입력 | 컨테이너 기본 경로 | 공급 방식 |
| --- | --- | --- |
| Part A 상품도감 기준의 상품 profile | `/artifacts/catalog_profiles.csv` | 읽기 전용 파일 |
| profile과 일치하는 taxonomy | `/artifacts/taxonomy.json` | 읽기 전용 파일 |
| CPU multilingual-e5-small 모델 | `/models/multilingual-e5-small` | 읽기 전용 디렉터리 |
| 자연어 규칙·별칭 | `/app/config/demand_constraint_*.json` | 이미지에 포함 |

기본 경로는 기존 `MFDS_CATALOG_PROFILES_PATH`, `DEMAND_TAXONOMY_PATH`,
`E5_MODEL_PATH` 등의 환경 변수로 바꿀 수 있다. 마운트 파일·디렉터리는 UID 65534가
읽고 탐색할 수 있어야 한다. Kubernetes 기본안은 기존 PVC를 읽기 전용으로 마운트하고,
profile·taxonomy를 `/artifacts/releases/<artifact-version>/`에서 함께 읽도록 경로를
덮어쓴다. PVC 생성·파일 공급과 실제 release 버전 반영은 인프라 배포 과정에 연결한다.

모델은 런타임에 다운로드하지 않는다. `HF_HUB_OFFLINE=1`이 기본이며 모델 가중치,
tokenizer, SentenceTransformer 설정 파일이 모두 필요하다. Hugging Face cache를
사용하면 snapshot만 마운트하지 말고 `blobs/`를 포함한 모델 cache 전체를 마운트한다.
이때 `E5_MODEL_PATH`는 마운트 내부의 `snapshots/<revision>`으로 지정한다.

별도로 주입할 필수 값은 `SHARED_DATABASE_URL`, `BACKEND_BASE_URL`,
`BACKEND_INTERNAL_KEY`다. DB 계정은 SELECT 전용이며 내부 키는 배포 환경이
AWS Parameter Store에서 Kubernetes Secret으로 공급한 뒤 Pod에 주입한다.
Secret 동기화 구성은 기본 매니페스트에 포함하지 않는다. 앱은 AWS 자격 증명이나 직접적인 SSM 호출을
요구하지 않는다. 실제 Secret 값은 이미지·Git·로그에 넣지 않는다.

DB 조회 대상에는 `demand`, `demand_board`, `reject_history`가 포함된다.
Backend가 거절 이력 테이블을 배포하고 사용자 거절을 저장해야 하며, AI 계정에
해당 테이블의 SELECT 권한도 필요하다. 이력 조회 실패 시 배치를 중단한다.

다음은 대상 환경에 맞는 artifact와 전용 환경 파일을 준비한 후 사용하는 **실제 배치 실행** 예시다.
DB를 읽고 Backend 상태 변경 API를 호출하므로 smoke test로 사용하지 않는다.
세 경로 변수에는 호스트의 절대 경로를 넣는다. `.env.demand-clustering`은 Git에 넣지 않는다.

```bash
docker run --rm --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=256m \
  --cap-drop ALL --security-opt no-new-privileges \
  --env-file .env.demand-clustering \
  --mount "type=bind,src=${CLUSTERING_PROFILES_FILE:?},dst=/artifacts/catalog_profiles.csv,readonly" \
  --mount "type=bind,src=${CLUSTERING_TAXONOMY_FILE:?},dst=/artifacts/taxonomy.json,readonly" \
  --mount "type=bind,src=${CLUSTERING_E5_DIRECTORY:?},dst=/models/multilingual-e5-small,readonly" \
  demand-clustering-job:local
```

## 인프라에 전달할 Pod·스케줄 조건

| 항목 | 초기 전달안 |
| --- | --- |
| 실행 형태 | 시간별 CronJob, 컨테이너 기본 entrypoint 그대로 사용 |
| 기본 매니페스트 | `k8s/base`, 개발 환경 예시 `k8s/overlays/dev` |
| 초기 스케줄·제한 | 매시간 15분, `Asia/Seoul`, 실행 제한 30분, `suspend: true` |
| 노드 배치 | `workload=ai` + Linux amd64 선택, `workload=ai:NoSchedule` taint 허용 |
| 중첩·재실행 | `concurrencyPolicy: Forbid`, `backoffLimit: 0`, `restartPolicy: Never` |
| CPU | requests `1`, limits `2` |
| 메모리 | requests `3Gi`, limits `4Gi` |
| GPU | 사용하지 않음 |
| CPU 스레드 | 이미지 기본 `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1` |
| 보안 | non-root, read-only root, 권한 상승 금지, capabilities drop ALL |
| 쓰기 공간 | `/tmp`용 `emptyDir`, 초기 `sizeLimit: 256Mi`; checkpoint 볼륨 없음 |
| 네트워크 | SELECT 전용 PostgreSQL과 Backend 내부 API에 연결; 모델 다운로드 불필요 |

자원 값은 아래 측정에 여유를 둔 **초기 제안값**이지 운영 최대 부하 보장이 아니다.
스케줄·제한 시간과 자원 값은 실제 배치 부하에 맞게 인프라와 조정한다. AI 노드 선택은
특정 한 대에 대한 고정이 아니며 AI Node Group이 한 대일 때 그 노드에 모인다.
Secret과 artifact 공급은 인프라가 준비한다. 첫 배포는 실제 연동 검증이 끝날 때까지 자동 실행을
중지한 상태로 준비한다. 실패한 요청은 즉시 재시도하지 않고 다음 정기 배치에서
최신 DB 상태로 재계산한다. 수동 실행도 기존 배치와 겹치지 않도록 운영해야 한다.

## 오프라인 자원 측정

측정 스크립트는 DB·Backend에 연결하지 않는다. 실제 profile을 읽어 운영 parser와
proposal planner를 초기화한 뒤, 합성 자연어 입력을 해석하고 실제 E5로 query와
상품 profile 문장을 임베딩한다. 원상품 클러스터링, 전체 후보 순회와 API 왕복은
측정하지 않는다. 출력의 `processPeakRssMiB`는 프로세스 최대 RSS,
`cgroupPeakMiB`는 읽을 수 있는 경우 컨테이너 cgroup의 최대 메모리다.

위 세 경로 변수를 설정한 뒤 다음처럼 재현한다. 모델 cache를 마운트했다면
`--model` 뒤를 실제 snapshot 경로로 바꾼다.

```bash
docker run --rm --network none --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=256m \
  --cap-drop ALL --security-opt no-new-privileges \
  --cpus 1 --memory 4g --memory-swap 4g \
  --mount "type=bind,src=$PWD/scripts/inspect/probe_demand_clustering_runtime.py,dst=/probe.py,readonly" \
  --mount "type=bind,src=${CLUSTERING_PROFILES_FILE:?},dst=/artifacts/catalog_profiles.csv,readonly" \
  --mount "type=bind,src=${CLUSTERING_TAXONOMY_FILE:?},dst=/artifacts/taxonomy.json,readonly" \
  --mount "type=bind,src=${CLUSTERING_E5_DIRECTORY:?},dst=/models/multilingual-e5-small,readonly" \
  --entrypoint python demand-clustering-job:local /probe.py \
  --profiles /artifacts/catalog_profiles.csv --taxonomy /artifacts/taxonomy.json \
  --model /models/multilingual-e5-small --query-count 1000 --passage-count 1000
```

### 2026-09-09 로컬 측정

- Docker Desktop/WSL2 Linux amd64, CPU quota 1, swap 비활성, E5 batch size 32.
- profile 45,719건 전체 로드, claim 인덱스 대상 44,919건, 16개 카테고리.
- taxonomy는 `tests/demand_constraints/fixtures/v042_taxonomy.json`을 사용했다.
  현재 입력에 대한 구성요소 측정이며 실제 DB 연동이나 운영 부하 검증을 대체하지 않는다.
  상품도감·ID는 Part A를 기준으로 하며 실제 입력 수요·보드도 같은 ID를 사용해야 한다.
- E5 revision: `614241f622f53c4eeff9890bdc4f31cfecc418b3`, PyTorch `2.14.0+cpu`.
- 100 query / 100 passage: 30.65초, 최대 RSS 2,063.05 MiB,
  cgroup 최대 2,033.89 MiB. 컨테이너 메모리 한도 3 GiB에서 완료했다.
- 1,000 query / 1,000 passage: 134.98초, 최대 RSS 2,375.41 MiB,
  cgroup 최대 2,226.61 MiB. 컨테이너 메모리 한도 4 GiB에서 완료했다.

100건 측정만으로도 512 MiB나 1 GiB를 잡을 근거는 없다. 실제 배포 artifact와 예상
배치 수요·활성 보드 수를 기준으로 전체 배치를 다시 측정해 requests/limits와
실행 제한 시간을 조정해야 한다.

## 실제 연동 전 준비 상태 — 2026-09-09 로컬 확인

| 항목 | 확인 결과 | 다음에 필요한 것 |
| --- | --- | --- |
| 이미지·E5 | 빌드, 오프라인 CPU 실행 검증 완료 | 인프라의 이미지 배포 및 모델 파일 공급 |
| 상품 profile | 현재 Part A 분류 기준으로 재생성한 45,719건·15개 필드가 기존 profile과 모두 일치 | 같은 상품도감 ID를 사용하는 배포 입력 공급; 후속 산출물은 버전 갱신 |
| taxonomy | 테스트 fixture가 현재 profile의 16개 카테고리를 포함하며 runtime 로드 확인 | 배포에 사용할 profile·taxonomy 파일을 같은 release로 공급 |
| 연결 설정 | 확인한 로컬 환경 파일과 실행 환경에 배치용 DB 주소·Backend 주소·내부 키 미설정 | 테스트 대상 주소와 SELECT 전용 DB 계정, 내부 키의 안전한 주입 |
| Backend API | 합의한 두 API가 동작하는 배포 대상은 미확인 | 대상 환경에서 API 1·2 및 `X-Internal-Key` 계약 지원 여부 확인 |
| 거절 이력 | 갱신 ERD 이미지 기준 `reject_history` 조회·후보 제외 구현 | 실제 테이블 배포, 거절과 상태 복귀의 원자적 저장, SELECT 권한 및 API 2의 동시성 재검증 확인 |

상품도감과 catalog ID의 기준은 Part A이며 Part B가 별도 ID를 만들거나 Backend
ERD 변경을 요구하지 않는다. 현재 Part A 입력 45,996건에서 분류 제외 277건을 빼면
profile 45,719건이다. 이 중 claim 근거를 사용할 수 있는 44,919건은 후보 인덱스에
들어가며, 근거 부족 800건은 제외된다. 현재 산출물로 개발·검증을 진행하고 Part A의
후속 변경은 profile·taxonomy 재생성 및 release 갱신으로 반영한다.

실제 연동 때는 PostgreSQL 수요·보드의 catalog ID가 이 상품도감과 일치하고 profile에
존재하는지 확인한다. 현재 파일 재현 검증이 실제 DB의 ID 일치까지 확인한 것은 아니다.

준비가 완료되면 SELECT 전용 연결 및 입력 ID 일치 여부부터 확인한다. 실제 API
반영 검증은 대상 환경과 사용할 테스트 수요를 명시적으로 정한 뒤 별도로 수행한다.
현재까지 실제 DB 조회, Backend 상태 변경 API 호출, EKS 배포는 수행하지 않았다.
