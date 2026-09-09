# 수요 클러스터링 Kubernetes 실행 계약

이 디렉터리는 AI가 제공하는 **기본 매니페스트와 개발 환경 예시**다.
실제 배포 설정의 기준은 인프라의 GitOps 저장소이며, Jenkins의 이미지 배포·GitOps
갱신과 ArgoCD/EKS 연결을 이 디렉터리가 대신하지 않는다. 인프라는 이 실행 계약을
GitOps에 반영하고, 이후 계약 변경도 함께 반영한다.

현재 범위는 수요 클러스터링 CronJob 하나다. 다른 AI 파트의 Deployment/CronJob,
EKS Node Group, Namespace, Secret, PVC와 Secret 동기화 리소스는 생성하지 않는다.
이미지 빌드·실측 자료는 [컨테이너 안내](../docs/DEMAND_CLUSTERING_CONTAINER.md),
전달 항목은 [B파트 인계서](../docs/ci-cd-demand-clustering-handoff.yml)를 참고한다.

## 파일 구성과 초기값

```text
k8s/
├── base/
│   ├── kustomization.yaml
│   └── demand-clustering-job/
│       ├── kustomization.yaml   # 일반 설정 ConfigMap 생성
│       ├── cronjob.yaml
│       └── serviceaccount.yaml
└── overlays/dev/kustomization.yaml
```

- 개발 Namespace 예시는 `moongcheap-ai-dev`이며, 실제 Namespace 이름은 인프라가 정한다.
- 매시간 15분, `Asia/Seoul`, `suspend: true`로 시작한다.
- `concurrencyPolicy: Forbid`, `backoffLimit: 0`, `restartPolicy: Never`다.
  실패한 실행은 즉시 재시도하지 않고 다음 정기 배치에서 최신 DB 상태로 재계산한다.
- 시작 지연 허용은 5분, Job 실행 제한은 30분이며 초기 제안값이다.
- CPU requests/limits는 `1`/`2`, 메모리는 `3Gi`/`4Gi`, GPU는 사용하지 않는다.
- non-root `65534:65534`, 읽기 전용 root, 권한 상승 금지, capabilities 제거를 적용한다.
  `/tmp`만 `emptyDir`로 쓰기 가능하며 초기 한도는 `256Mi`다.
- Kubernetes API를 호출하지 않으므로 ServiceAccount 토큰을 마운트하지 않는다.
  HTTP 서버가 아니므로 Service·Ingress·포트·HTTP probe를 추가하지 않는다.

`Forbid`는 같은 CronJob이 만든 Job 사이에만 적용된다. 다른 AI CronJob이나 수동
Job과의 중첩을 막는 전체 AI 잠금은 아니다. 또한 스케줄러 설정만으로 정확히 한 번의
실행을 보장하지는 않으므로 Backend의 상태 재검증·동시성 제어는 계속 필요하다.
([Kubernetes CronJob](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/))

클러스터링은 자체 자연어 parser를 사용하며 별도 labeling Job의 완료를 기다리지 않는다.

## 환경 변수와 Secret 주입

일반 설정은 `base/demand-clustering-job/kustomization.yaml`의
`configMapGenerator`로 만들고 `envFrom`으로 주입한다. Backend 주소, artifact·모델
경로, 최소 참가자 수, timeout, CPU 스레드·오프라인 설정이 여기에 해당한다.
내용에 따른 ConfigMap 이름 해시를 유지하므로 설정 변경은 새 Job의 Pod에 반영된다.

비밀 값은 다음 두 항목만 이름과 key로 참조한다. Secret은 Pod와 같은 Namespace에
먼저 준비되어 있어야 한다. ([Kubernetes Secret](https://kubernetes.io/docs/concepts/configuration/secret/))

| Pod 환경 변수 | Kubernetes Secret | key | 용도 |
| --- | --- | --- | --- |
| `SHARED_DATABASE_URL` | `ai-batch-reader-database` | `url` | SELECT 전용 PostgreSQL DSN; JDBC URL 아님 |
| `BACKEND_INTERNAL_KEY` | `ai-backend-internal-key` | `internal-key` | Backend와 공유하는 `X-Internal-Key` 값 |

AI DB 계정에는 `demand`, `demand_board`, `reject_history`의 SELECT 권한이 필요하다.
`reject_history`는 Backend가 배포·기록하며, 거절한 수요·보드 조합은 재제안에서
제외한다. 테이블 누락이나 권한 오류로 이력을 조회하지 못하면 배치가 실패한다.

내부 키의 공급 경로는 **Parameter Store → 배포 환경의 Secret 동기화 → Kubernetes
Secret → Pod 환경 변수 → 요청의 `X-Internal-Key` 헤더**다. 이 매니페스트에
`secretKeyRef`를 쓰는 것만으로 Parameter Store와 자동 연결되지는 않는다.
실제 Parameter 경로, 조회 권한 및 동기화 방식은 인프라가 구성한다. 예를 들어
External Secrets를 사용할 수 있지만, 이 저장소에는 해당 구성이나 운영자를 설치하지 않는다.

배치 앱은 SSM을 직접 호출하지 않으며 AWS Access Key나 SSM용 IAM 역할을 요구하지
않는다. Secret 공급 주체의 AWS 권한과 ECR 이미지 pull 권한은 별도의 인프라 설정이다.
실제 비밀 값과 `.env`는 Git·이미지·로그에 넣지 않는다. 키 교체 시 Backend와 AI의
반영 시점을 맞추고, 이미 실행 중인 프로세스의 환경 변수가 자동 교체된다고 가정하지 않는다.

## 모델과 상품 profile 공급

기본안은 **이미 채워진 PVC를 읽기 전용으로 마운트**하는 방식이다. 아래 PVC는
Pod와 같은 Namespace에 필요하다. StorageClass, 크기, access mode, 볼륨 채우기와
갱신 작업은 여기서 생성하지 않으며 인프라가 실제 저장소에 맞게 정한다.

| PVC 이름 | 마운트 경로 | 필요한 내용 |
| --- | --- | --- |
| `demand-clustering-artifacts` | `/artifacts` | `releases/<artifact-version>/catalog_profiles.csv`와 `taxonomy.json` |
| `demand-clustering-e5-model` | `/models/multilingual-e5-small` | E5의 `blobs/`와 `snapshots/<revision>/`을 포함한 모델 cache |

현재 E5 경로는 검증한 revision
`614241f622f53c4eeff9890bdc4f31cfecc418b3`의 snapshot을 가리킨다.
snapshot만 복사하면 `blobs/`를 향한 심볼릭 링크가 끊어질 수 있으므로 cache 전체를
공급한다. 모델은 실행 중 다운로드하지 않는다. 모든 파일과 상위 디렉터리는 UID
65534가 읽고 탐색할 수 있어야 한다. PVC의 AZ·접근 모드도 AI 노드 배치와 호환되어야 한다.

상품도감과 catalog ID의 기준은 Part A다. 현재 Part A 입력 기준의 profile 검증을
활용해 진행하고, 후속 산출물은 새 release 경로에 공급한 뒤 profile·taxonomy 경로를
함께 변경한다. 실행 중인 배치가 읽는 기존 release를 덮어쓰지 않는다. 코드 이미지의
CI/CD만으로 외부 PVC의 파일까지 자동 갱신되지는 않으므로 artifact 게시·버전 반영을
배포 과정에 연결해야 한다. 실제 DB 연동에서는 수요·보드의 ID와 이 상품도감의 ID가
일치하는지 확인한다.

## 하나의 AI 전용 노드에 배치하려면

Pod에는 다음 두 설정을 함께 적용했다.

```yaml
nodeSelector:
  workload: ai
  kubernetes.io/os: linux
  kubernetes.io/arch: amd64
tolerations:
  - key: workload
    operator: Equal
    value: ai
    effect: NoSchedule
```

`nodeSelector`는 조건에 맞는 AI 노드만 후보로 제한하고, toleration은 그 노드의
`workload=ai:NoSchedule` taint를 허용한다. toleration만으로 AI 노드에 배치되는 것은
아니다. ([노드 선택](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/),
[taint와 toleration](https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/))

- 인프라가 이 label·taint를 가진 AI Node Group을 한 대로 운영하면 해당 노드에 모인다.
  AI 노드가 여러 대면 여러 노드로 나뉠 수 있다. 이 매니페스트는 노드 수를 정하지 않는다.
- 다른 AI Pod도 같은 배치 규칙을 가져야 한다. 이번 변경은 클러스터링 Pod에만 적용된다.
- AI 노드에 자원이 부족하면 일반 노드로 옮겨 실행하지 않고 `Pending` 상태가 될 수 있다.
  한 노드의 크기는 다른 AI Pod와 시스템 Pod의 동시 자원 사용량까지 합산해서 정해야 한다.
- 특정 hostname이나 `nodeName`으로 고정하지 않는다. 노드 교체 시에도 같은 label을
  가진 노드에서 실행할 수 있도록 한다.

## 로컬·CI 검증 및 배포 전 교체 항목

저장소 루트에서 실행한다. `kubectl`의 Kustomize 기능과 dev 의존성이 필요하다.

```bash
uv sync --project packaging/demand-clustering --locked --extra data --extra dev
kubectl kustomize k8s/base
kubectl kustomize k8s/overlays/dev
tools/verify_kubernetes_manifests.sh
uv run --project packaging/demand-clustering --no-sync pytest -c packaging/demand-clustering/pyproject.toml
```

검증 스크립트는 base/dev 렌더링 결과를 파싱해 Secret·노드·재시도·보안·볼륨 계약을
검사한다. 렌더링과 검증 스크립트는 클러스터에 접속하거나 리소스를 적용하지 않는다. 전체 pytest는
`kubectl`이 없으면 배포 테스트를 건너뛰므로, CI에는 누락 시 실패하는 위 검증 스크립트도
등록한다. 이는 API 서버의 스키마·admission 검증이나 실제 Pod 기동 시험을 대체하지 않는다.

인프라의 환경별 GitOps 설정에서는 다음 값을 채운다.

1. 실제 Namespace와 ECR 이미지 경로·Git SHA 태그.
2. ConfigMap의 `BACKEND_BASE_URL`과 profile·taxonomy release 경로.
3. 같은 Namespace의 두 Secret과 데이터·모델이 들어 있는 두 PVC.
4. AI Node Group label·taint, CPU/메모리 여유와 DB·Backend 네트워크 연결.
5. 테스트 데이터로 실제 연동 검증 후 스케줄·제한 시간을 확인하고 `suspend: false`로 전환.

현재의 `replace-with-git-sha`, `replace-with-artifact-version`, `https://backend.invalid`는
배포 값이 아닌 자리표시자다. `suspend: true`는 정기 실행을 막지만 수동 Job 생성까지
막지는 않으므로, 실제 DB 상태를 바꾸는 수동 실행은 별도 승인된 대상에서만 수행한다.
