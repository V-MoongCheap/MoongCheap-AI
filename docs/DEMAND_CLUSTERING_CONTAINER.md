# 수요 클러스터링 컨테이너 인계

이 이미지는 `demand-clustering-batch`를 한 번 실행하고 종료하는 CPU 배치다.
HTTP 서버가 아니므로 Service, Ingress, 애플리케이션 포트, HTTP health check는
필요하지 않다. 성공은 종료 코드 0, 실행 실패는 1, 설정 오류는 2다.

AI는 Dockerfile·기본 CronJob 매니페스트·실행 계약·자원 측정 자료를 제공한다.
Jenkins/ECR 이미지 배포, GitOps 갱신, ArgoCD/EKS 연결과 환경별 운영 설정은 인프라
측에서 구성한다. [Kubernetes 안내](../k8s/README.md)에 Secret·BE·AI 노드 배치
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
- 이미지에는 Python 의존성, 앱, 규칙·별칭, 상품 profile·taxonomy와 고정 E5 모델을 포함한다.
  전용 `.dockerignore`는 소스와 확정된 `runtime-assets/`만 허용한다. 비밀 값·원재료·
  로컬 모델 cache는 제외한다. E5는 빌드 중 Hugging Face에서 다운로드하고 SHA256을 검증한다.
- 모델 다운로드를 포함한 빌드에는 인터넷이 필요하다. 실행 중 모델 다운로드·PVC는 필요 없다.
  Dockerfile은 Kaniko에서도 해석할 수 있도록 BuildKit 전용 cache mount 문법을 제거했다.
  Cloud와 같은 Kaniko v1.23.2의 로컬 `--no-push` 빌드도 검증했다. 실제 Jenkins/ECR 연결은 별도다.
- UID/GID는 `65534:65534`다. 루트 파일시스템을 읽기 전용으로 실행할 수 있으며
  임시 파일용 `/tmp`는 쓰기 가능해야 한다.

## 모델·데이터·환경 변수 공급

| 입력 | 컨테이너 기본 경로 | 공급 방식 |
| --- | --- | --- |
| Part A 상품도감 기준의 상품 profile | `/artifacts/catalog_profiles.csv` | 이미지에 포함 |
| profile과 일치하는 taxonomy | `/artifacts/taxonomy.json` | 이미지에 포함 |
| CPU multilingual-e5-small 모델 | `/models/multilingual-e5-small` | 빌드 때 다운로드하여 이미지에 포함 |
| 자연어 규칙 | `/app/config/demand_constraint_rules.json` | 이미지에 포함 |
| 선택 A V2.2 승인 별칭 | `/app/config/model1_aliases_reviewed_v2.json` | 이미지에 포함 |
| 필수 B 기본 별칭 | `/app/config/demand_constraint_aliases.json` | 이미지에 포함, A 승인과 별도 관리 |

경로는 Dockerfile과 ConfigMap에 같은 값으로 지정돼 있다. 이 경로 위에 외부 볼륨을
마운트하지 않는다. 이미지의 파일은 UID 65534가 읽을 수 있다.
상품 profile·taxonomy·release manifest는 저장소의
`packaging/demand-clustering/runtime-assets/`에서 가져와 빌드 시 검증·포함한다.
현재 `v2_2_20260921_image`는 45,996건의 V2.2 profile과 최신 A 분류표를 묶는다.
`catalog_id`는 기존 MFDS ID를 보존하며 배포 대상 DB와의 ID 계약은 바뀌지 않는다.

자료 갱신은 B 담당자가 [자료 갱신 안내](../packaging/demand-clustering/runtime-assets/README.md)에
따라 확정본을 커밋하고 이미지를 재빌드하는 작업이다. 인프라 팀은 별도 CSV·모델 선택이나
PVC 공급을 하지 않는다. [V2.2 연계 안내](PART_B_V22_INTEGRATION.md)에 생성·검증 명령이 있다.

`DEMAND_CONSTRAINT_ALIASES_PATH`는 A 승인 별칭, `DEMAND_CONSTRAINT_COMPAT_ALIASES_PATH`는
필수 B 기본 별칭이다. B는 항상 읽고, A에 없는 표현·카테고리도 계속 활용한다.
같은 카테고리·표현은 A가 우선한다. A 경로를 비우거나 설정하지 않으면 B만 사용하며,
A에서 삭제된 표현도 B에 남아 있으면 사용한다. A 경로를 설정했다면 파일 누락,
잘못된 JSON·버전·코드/값, 읽기 권한 오류를 모두 설정 오류로 보고 중단한다.
B 경로를 비우거나 B 파일이 없으면 설정 오류다. `partAIntegration.aliasMode`와
`primaryAliasLoadStatus`로 A 사용·미사용 이유를 구분한다.
배치 출력의 `partAIntegration`에서 적용 버전·파일 해시를 확인한다.
profile 생성과 별칭 변경 검증은 [V2.2 연계 안내](PART_B_V22_INTEGRATION.md)를 따른다.

E5는 `model.json`에 고정한 `intfloat/multilingual-e5-small` revision
`614241f622f53c4eeff9890bdc4f31cfecc418b3`를 빌드 중 다운로드한다.
가중치·tokenizer·설정은 symlink 없는 실제 파일로 이미지에 들어간다.
`HF_HUB_OFFLINE=1`과 `TRANSFORMERS_OFFLINE=1`을 유지한다.

외부 네트워크·모델/자료 마운트 없이 다음 검증으로 전체 profile·별칭·실제 E5 임베딩을
확인한다. DB·Backend에는 연결하지 않으며 내부에서 테스트용 설정만 사용한다.

```bash
docker run --rm -i --network none --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=256m \
  --cap-drop ALL --security-opt no-new-privileges \
  --cpus 2 --memory 4g --memory-swap 4g \
  --entrypoint python demand-clustering-job:local - \
  < scripts/deployment/verify_demand_clustering_image.py
```

2026-09-21 로컬 검증에서 Docker 이미지 빌드, Kaniko v1.23.2 `--no-push` 빌드와
위 오프라인 검증이 통과했다. Kaniko는 비밀 값·로컬 자료가 없는 빌드 입력만으로 실행했다.
UID 65534, 읽기 전용 root, 네트워크 차단, 모델·데이터 볼륨 없음 조건에서
45,996개 profile·A+B 별칭 로드와 실제 E5 query/passage 임베딩을 확인했다.
배포 매니페스트·자료 검증 및 관련 runtime/profile/alias 테스트는 212개 통과했다.
이는 실제 DB·Backend 호출이나 ECR push 결과를 뜻하지 않는다.

별도로 주입할 필수 값은 `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`, `BACKEND_BASE_URL`,
`BACKEND_INTERNAL_KEY`다. 기본 K8s 설정은 `backend-env`의 기존 DB 세 항목을 받아
앱에서 PostgreSQL DSN을 조합한다. Backend DB 계정을 공유하되 B의 세션은 읽기 전용이다.
기존 `SHARED_DATABASE_URL`도 지원하며, 비어 있지 않으면 DB 세 변수보다 우선한다.
B 전용 개발 overlay는 `BACKEND_BASE_URL=http://backend`를 주입한다. 같은
`moongcheap-develop`의 Backend Service 80번 포트가 Pod의 8080번 포트로 전달한다.
이 주소는 클러스터 내부용이며 로컬 Docker 실행에서는 접근 가능한 Backend 주소를 사용한다.
내부 키의 원본 저장소는
Backend와 합의한 AWS Parameter Store `SecureString`이다. 배포 환경이 이를
`BACKEND_INTERNAL_KEY`로 주입하며 앱은 `X-Internal-Api-Key` 헤더로 전송한다.
매니페스트는 `backend-env/MOONGCHEAP_INTERNAL_API_KEY`를 참조하지만, 확인한 Cloud
`develop` (`8fd7e20`)의 ExternalSecret 템플릿에는 이 항목이 매핑돼 있다. 실제 AWS
원본 값과 클러스터 동기화 성공 여부를 확인하고 DB·Backend 연동 검증을 마치기 전까지
배포를 활성화하지 않는다. 앱은 AWS 자격 증명이나 직접적인 AWS API 호출을 요구하지 않는다.
실제 Secret 값은 이미지·Git·로그에 넣지 않는다.

DB 조회 대상에는 `demand`, `demand_board`, `reject_history`가 포함된다.
Backend가 거절 이력 테이블을 배포하고 사용자 거절을 저장해야 하며, AI 계정에
해당 테이블의 SELECT 권한도 필요하다. 이력 조회 실패 시 배치를 중단한다.

다음은 접속 정보가 든 전용 환경 파일을 준비한 후 사용하는 **실제 배치 실행** 예시다.
DB를 읽고 Backend 상태 변경 API를 호출하므로 smoke test로 사용하지 않는다.
모델·자료 마운트는 없다. `.env.demand-clustering`은 Git에 넣지 않는다.

```bash
docker run --rm --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=256m \
  --cap-drop ALL --security-opt no-new-privileges \
  --env-file .env.demand-clustering \
  demand-clustering-job:local
```

## 인프라에 전달할 Pod·스케줄 조건

| 항목 | 초기 전달안 |
| --- | --- |
| 실행 형태 | 시간별 CronJob, 컨테이너 기본 entrypoint 그대로 사용 |
| 기본 매니페스트 | `k8s/base/demand-clustering-job`, B 전용 개발 예시 `k8s/overlays/demand-clustering-dev` |
| 개발 Namespace | Cloud GitOps 기준 `moongcheap-develop`; 기존 공용 overlay 및 A Namespace는 유지 |
| 초기 스케줄·제한 | 매시간 45분, `Asia/Seoul`, 실행 제한 30분, `suspend: true` |
| 노드 배치 | `workload=backend-ai` + Linux amd64 선택, AI 전용 taint 허용 없음 |
| 중첩·재실행 | `concurrencyPolicy: Forbid`, `backoffLimit: 0`, `restartPolicy: Never` |
| CPU | requests `1`, limits `2` |
| 메모리 | requests `3Gi`, limits `4Gi` |
| GPU | 사용하지 않음 |
| CPU 스레드 | 이미지 기본 `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1` |
| 보안 | non-root, read-only root, 권한 상승 금지, capabilities drop ALL |
| 쓰기 공간 | `/tmp`용 `emptyDir`, 초기 `sizeLimit: 256Mi`; checkpoint 볼륨 없음 |
| 네트워크 | PostgreSQL에 읽기 전용 세션으로 연결하고 Backend 내부 API 호출; 모델 다운로드 불필요 |

자원 값은 아래 측정에 여유를 둔 **초기 제안값**이지 운영 최대 부하 보장이 아니다.
스케줄·제한 시간과 자원 값은 실제 배치 부하에 맞게 인프라와 조정한다. BE·AI 노드 선택은
특정 한 대에 대한 고정이 아니며 Backend·다른 AI·시스템 Pod의 자원을 합산해 배치 여유를 확인한다.
노드 라벨·Namespace와 Helm 전환은 배포 설정에 해당하므로 현재 CPU 배치 Dockerfile은 그대로 사용한다.
Cloud Jenkins 템플릿의 `DOCKERFILE_PATH`는 `docker/Dockerfile.demand-clustering`으로
지정해야 한다. Python/uv/kubectl 준비와 Jenkins에서의 ECR push는 CI 연동 시 확인한다.
Secret 공급은 인프라가 준비하고, 모델·상품 자료는 이미지에 포함한다. 첫 배포는 실제 연동 검증이 끝날 때까지 자동 실행을
중지한 상태로 준비한다. 실패한 요청은 즉시 재시도하지 않고 다음 정기 배치에서
최신 DB 상태로 재계산한다. 수동 실행도 기존 배치와 겹치지 않도록 운영해야 한다.

## 오프라인 자원 측정

측정 스크립트는 DB·Backend에 연결하지 않는다. 실제 profile을 읽어 운영 parser와
proposal planner를 초기화한 뒤, 합성 자연어 입력을 해석하고 실제 E5로 query와
상품 profile 문장을 임베딩한다. 원상품 클러스터링, 전체 후보 순회와 API 왕복은
측정하지 않는다. 출력의 `processPeakRssMiB`는 프로세스 최대 RSS,
`cgroupPeakMiB`는 읽을 수 있는 경우 컨테이너 cgroup의 최대 메모리다.

현재 이미지는 자료와 모델을 포함하므로 측정 스크립트만 연결한다. 아래의 과거 측정은
당시 자료 기준이며 현재 이미지의 측정값으로 간주하지 않는다.

```bash
docker run --rm --network none --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=256m \
  --cap-drop ALL --security-opt no-new-privileges \
  --cpus 1 --memory 4g --memory-swap 4g \
  --mount "type=bind,src=$PWD/scripts/inspect/probe_demand_clustering_runtime.py,dst=/probe.py,readonly" \
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
| 이미지·E5 | 빌드, 오프라인 CPU 실행 검증 완료 | 인프라의 이미지 배포; 현재 모델은 이미지에 포함 |
| 상품 profile | 현재 Part A 분류 기준으로 재생성한 45,719건·15개 필드가 기존 profile과 모두 일치 | 현재 이미지에는 V2.2 45,996건을 포함; DB ID 계약 확인은 별도 |
| taxonomy | 테스트 fixture가 현재 profile의 16개 카테고리를 포함하며 runtime 로드 확인 | 현재 profile·taxonomy를 이미지에 함께 포함 |
| 연결 설정 | 실제 배포 연동 미검증; backend-env DB 세 항목 재사용, 내부 키 항목 공급 대기 | DB·Backend 연결 확인, 내부 키 주입과 헤더 이름 정합성 확인 |
| Backend API | 합의한 두 API가 동작하는 배포 대상은 미확인 | 대상 환경에서 API 1·2 및 `X-Internal-Api-Key` 계약 지원 여부 확인 |
| 거절 이력 | 갱신 ERD 이미지 기준 `reject_history` 조회·후보 제외 구현 | 실제 테이블 배포, 거절과 상태 복귀의 원자적 저장, SELECT 권한 및 API 2의 동시성 재검증 확인 |

상품도감과 catalog ID의 기준은 Part A이며 Part B가 별도 ID를 만들거나 Backend
ERD 변경을 요구하지 않는다. 위 2026-09-09 측정에서는 Part A 입력 45,996건에서 분류 제외 277건을 빼면
profile 45,719건이다. 이 중 claim 근거를 사용할 수 있는 44,919건은 후보 인덱스에
들어가며, 근거 부족 800건은 제외된다. 현재 이미지는 2026-09-11 V2.2 생성 경로와 같이 45,996건을 보존한다. Part A의
후속 변경은 profile·taxonomy 재생성 및 이미지 갱신으로 반영한다.

실제 연동 때는 PostgreSQL 수요·보드의 catalog ID가 이 상품도감과 일치하고 profile에
존재하는지 확인한다. 현재 파일 재현 검증이 실제 DB의 ID 일치까지 확인한 것은 아니다.

준비가 완료되면 읽기 전용 세션 및 입력 ID 일치 여부부터 확인한다. 실제 API
반영 검증은 대상 환경과 사용할 테스트 수요를 명시적으로 정한 뒤 별도로 수행한다.
현재까지 실제 DB 조회, Backend 상태 변경 API 호출, EKS 배포는 수행하지 않았다.
