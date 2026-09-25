# 수요 클러스터링 Kubernetes 실행 계약

이 디렉터리는 AI가 제공하는 **기본 매니페스트와 개발 환경 예시**다.
실제 배포 설정의 기준은 인프라의 GitOps 저장소이며, Jenkins의 이미지 배포·GitOps
갱신과 ArgoCD/EKS 연결을 이 디렉터리가 대신하지 않는다. 인프라는 이 실행 계약을
GitOps에 반영하고, 이후 계약 변경도 함께 반영한다.

이 문서와 B 전용 overlay의 범위는 수요 클러스터링 CronJob 하나다. 기존 공용
`base`와 `overlays/dev`에는 A도 포함되므로 B만 전달할 때는 아래 전용 경로를 사용한다.
B 전용 경로는 다른 AI 파트의 Deployment/CronJob, EKS Node Group, Namespace,
Secret과 Secret 동기화 리소스를 생성하지 않는다. B는 PVC를 사용하지 않는다.
이미지 빌드·실측 자료는 [컨테이너 안내](../docs/DEMAND_CLUSTERING_CONTAINER.md),
전달 항목은 [B파트 인계서](../docs/ci-cd-demand-clustering-handoff.yml)를 참고한다.

## 파일 구성과 초기값

```text
k8s/
├── base/
│   ├── kustomization.yaml       # 기존 A+B 공용 진입점
│   ├── a-labeling-job/          # A 기존 구성 유지
│   └── demand-clustering-job/   # B 전용 base
│       ├── kustomization.yaml   # 일반 설정 ConfigMap 생성
│       ├── cronjob.yaml
│       └── serviceaccount.yaml
└── overlays/
    ├── dev/kustomization.yaml   # 기존 공용 예시, moongcheap-ai-dev 유지
    └── demand-clustering-dev/kustomization.yaml  # B만, moongcheap-develop
```

- B 전용 개발 Namespace는 Cloud `develop` (`57cd52e`)의 GitOps 기준인
  `moongcheap-develop`이다. 같은 공간에 Secret을 준비한다. 기존 공용 예시의
  `moongcheap-ai-dev`와 A의 설정은 바꾸지 않는다.
- 매시간 45분, `Asia/Seoul`, `suspend: true`로 시작한다.
- `concurrencyPolicy: Forbid`, `backoffLimit: 0`, `restartPolicy: Never`다.
  실패한 실행은 즉시 재시도하지 않고 다음 정기 배치에서 최신 DB 상태로 재계산한다.
- 시작 지연 허용은 5분, Job 실행 제한은 30분이며 초기 제안값이다.
- 성공/실패 Job 보관 상한은 각각 1개/3개이며, 완료 후 TTL은 24시간이다.
- CPU requests/limits는 `1`/`2`, 메모리는 `3Gi`/`4Gi`, GPU는 사용하지 않는다.
- non-root `65534:65534`, 읽기 전용 root, 권한 상승 금지, capabilities 제거를 적용한다.
  `/tmp`만 `emptyDir`로 쓰기 가능하며 초기 한도는 `256Mi`다.
- 전용 ServiceAccount는 Cloud의 `{service-or-component}-sa` 규약에 맞춘
  `demand-clustering-sa`이며, CronJob의 `serviceAccountName`에서 참조한다.
  Kubernetes API를 호출하지 않으므로 ServiceAccount 토큰을 마운트하지 않는다.
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

기본값 `https://backend.invalid`는 미설정 상태를 나타내는 자리표시자다. B 전용
`overlays/demand-clustering-dev`는 ConfigMap을 병합해 `BACKEND_BASE_URL=http://backend`로
덮어쓴다. 같은 `moongcheap-develop`의 Service 이름 `backend`를 사용하며, HTTP 기본
포트 `80`에서 Backend Pod의 `8080`으로 전달된다. Service에 요청하므로 URL에
Pod 포트 `8080`이나 Pod IP를 넣지 않는다. 두 내부 API의 경로는 앱이 base URL 뒤에 붙인다.
다른 Namespace에서 호출할 때는 `http://backend.moongcheap-develop`처럼 Namespace를
포함한다. 기존 공용 `overlays/dev`는 Namespace가 다르므로 자리표시자를 유지한다.
([Backend values](https://github.com/V-MoongCheap/MoongCheap-Cloud/blob/57cd52e/gitops/values/services/backend.yaml),
[Service 템플릿](https://github.com/V-MoongCheap/MoongCheap-Cloud/blob/57cd52e/gitops/charts/moongcheap-service/templates/service.yaml))

현재 B 매니페스트는 Backend의 Kubernetes Secret `backend-env`에서 필요한 네 항목만
참조한다. Pod와 같은 Namespace에 Secret과 해당 key가 모두 있어야 한다.
B 전용 overlay는 Cloud와 같은 `moongcheap-develop`을 사용한다. 기존 공용
`overlays/dev`를 사용하면 `moongcheap-ai-dev`에도 별도 Secret 공급이 필요하다.
([Kubernetes Secret](https://kubernetes.io/docs/concepts/configuration/secret/))

| Pod 환경 변수 | Kubernetes Secret | key | 용도 |
| --- | --- | --- | --- |
| `DB_URL` | `backend-env` | `DB_URL` | Backend JDBC URL; 앱에서 `jdbc:` 제거 |
| `DB_USERNAME` | `backend-env` | `DB_USERNAME` | Backend와 같은 DB 계정 |
| `DB_PASSWORD` | `backend-env` | `DB_PASSWORD` | 해당 DB 계정 비밀번호 |
| `BACKEND_INTERNAL_KEY` | `backend-env` | `MOONGCHEAP_INTERNAL_API_KEY` | Backend와 공유하는 `X-Internal-Api-Key` 값; Cloud 템플릿 매핑 완료, 실제 동기화 확인 필요 |

앱은 DB 세 값을 읽어 PostgreSQL DSN을 조합한다. 계정·비밀번호는 공백을 보존하고
URL 인코딩하며, IPv6 주소와 libpq 호환 query(`sslmode` 등)는 유지한다. `DB_URL`에
별도 계정·비밀번호가 포함되면 설정 오류로 중단한다. `backend-env` 전체를 `envFrom`으로
가져오지 않으므로 OAuth·암호화 키 등 다른 Backend 비밀 값은 AI에 전달하지 않는다.
기존 로컬 실행의 `SHARED_DATABASE_URL`도 지원하며, 비어 있지 않으면 DB 세 값보다
우선한다. 이 직접 DSN에는 JDBC URL을 넣을 수 없다. 기본 매니페스트는 직접 DSN을
주입하지 않으며, Cloud에 새 DB 환경변수나 AI 전용 DB Secret을 요구하지 않는다.

이 구성은 Backend DB 계정을 공유한다. AI의 PostgreSQL 연결은 기존대로
`default_transaction_read_only=on`을 적용하지만, DB role 자체를 SELECT 전용으로
바꾸지는 않는다.

AI DB 계정에는 `demand`, `demand_board`, `reject_history`의 SELECT 권한이 필요하다.
`reject_history`는 Backend가 배포·기록하며, 거절한 수요·보드 조합은 재제안에서
제외한다. 테이블 누락이나 권한 오류로 이력을 조회하지 못하면 배치가 실패한다.

Backend와 합의한 내부 키의 원본은 **AWS Parameter Store `SecureString`**이며,
HTTP 헤더 이름은 Backend `InternalApiKeyFilter`와 같은 **`X-Internal-Api-Key`**다. Cloud의 일반 Secrets Manager 정책이나
RDS 계정 저장 방식을 이 내부 키의 별도 합의에 그대로 적용하지 않는다.

앱의 입력 계약은 `BACKEND_INTERNAL_KEY` 환경 변수다. 배포 환경이 Parameter Store를
조회해 `backend-env`의 `MOONGCHEAP_INTERNAL_API_KEY` 항목을 공급해야 한다.
2026-09-23 확인한 Cloud `develop` (`8fd7e20`)의 ExternalSecret 템플릿에는
DB 세 항목과 내부 인증 키 항목이 모두 매핑돼 있다. 다만 실제 AWS 원본 값, 조회 권한과
클러스터의 ExternalSecret 동기화 성공 여부는 별도 확인이 필요하다. 실제 DB·Backend
연동 검증을 완료하기 전까지 `suspend: true`를 유지한다. 앱은 SSM을 직접 호출하지 않으며,
`secretKeyRef` 자체가 SSM을 조회하지도 않는다.
([Cloud ExternalSecret](https://github.com/V-MoongCheap/MoongCheap-Cloud/blob/8fd7e20/gitops/platform/external-secrets/resources/external-secret-backend.yaml))

Secret 공급 주체의 AWS 권한과 ECR 이미지 pull 권한은 별도의 인프라 설정이다.
실제 비밀 값과 `.env`는 Git·이미지·로그에 넣지 않는다. 키 교체 시 Backend와 AI의
반영 시점을 맞추고, 이미 실행 중인 프로세스의 환경 변수가 자동 교체된다고 가정하지 않는다.

## 모델과 v5 상품 시드는 이미지에 포함

B 담당자가 확정한 Backend v5 상품 시드·taxonomy와 E5 모델을 Dockerfile이 이미지에 넣는다.
인프라는 이미지 빌드·배포를 수행하며 별도의 PVC 생성, 데이터 복사 Job이나 모델 선택이 필요 없다.
`packaging/demand-clustering/runtime-assets/`에 v5 시드 압축본·분류표와 검증 manifest가 있다.
모델은 `model.json`의 고정 revision을 빌드 때 다운로드하고 파일별 SHA256을 검사한다.

| 이미지 내부 경로 | 내용 |
| --- | --- |
| `/artifacts/product_catalog_seed_v5.csv` | Backend에 적재하는 도매꾹 v5 상품 시드 |
| `/artifacts/category_seed_v5.csv` | Backend category 시드와 상품 FK 검증 기준 |
| `/artifacts/taxonomy.json` | 문장 구조화와 상품명 facet 추출에 사용하는 V2.2 분류표 |
| `/models/multilingual-e5-small` | E5 가중치·tokenizer·SentenceTransformer 설정 |

ConfigMap은 위 경로를 그대로 지정한다. `/artifacts`와 `/models` 위에 볼륨을 마운트하면
이미지에 들어 있는 파일을 가리므로 마운트하지 않는다. CronJob에는 `/tmp`용 `emptyDir`만 남긴다.
파일은 non-root UID 65534가 읽을 수 있으며 실행 중 다운로드하지 않는다.
자료 버전은 이미지 안의 `/artifacts/manifest.json`, 모델의 `image-model-manifest.json`에 기록된다.
자료 갱신은 B 담당자가 [runtime-assets 갱신 절차](../packaging/demand-clustering/runtime-assets/README.md)에
따라 커밋하고 이미지를 재빌드한다. DB가 생성한 `product_catalog.id`는
이미지에 고정하지 않고, UNIQUE인 `product_catalog.name`을 v5 시드와 정확히
일치시켜 런타임에 결합한다. 시드에 없는 사용자 추가 상품은 기본 보드
처리는 계속하고 대체상품 제안만 건너뛴다.

## 공유 BE·AI Worker에 배치

Cloud `be-ai` NodePool의 Backend·AI 공유 노드를 선택한다. ArgoCD·Karpenter·Jenkins
Controller용 `workload=system` 고정 노드는 별도로 구성되어 있다.
`nodeSelector`는 이미 존재하는 노드의 라벨을 검사하는 조건이며 Node Group을 생성하지 않는다.

```yaml
nodeSelector:
  workload: backend-ai
  kubernetes.io/os: linux
  kubernetes.io/arch: amd64
tolerations: []
```

기존 AI 전용 `workload=ai:NoSchedule` taint 허용은 제거했다. 공유 노드에 별도 taint가
추가되면 실제 정책에 맞는 toleration을 GitOps에서 설정한다. toleration만으로 특정
노드를 선택할 수는 없다. ([노드 선택](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/),
[taint와 toleration](https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/))

- 인프라가 BE·AI 노드에 `workload=backend-ai` Kubernetes 라벨을 제공해야 한다.
  EKS Node Group의 AWS `tags`는 이 라벨을 대신하지 않는다.
- 이 조건에 맞는 노드가 없거나 남은 자원이 부족하면 Pod는 `Pending` 상태가 될 수 있다.
  한 Pod의 요청 CPU `1` / 메모리 `3Gi`를 수용할 노드가 필요하며 여러 노드의 여유를 합쳐
  한 Pod를 실행할 수는 없다. 해당 노드의 Backend·다른 AI·노드별 시스템 Pod 등을 함께 계산한다.
- 메모리 한도 `4Gi`는 구성요소 측정에 여유를 둔 초기안이다. 공용 차트의 `512Mi` 기본값으로
  낮추지 않고 실제 배치 전체 부하를 측정해 조정한다.
- 특정 hostname이나 `nodeName`으로 고정하지 않는다. 노드 교체 시에도 같은 label을
  가진 노드에서 실행할 수 있도록 한다. 이 매니페스트는 노드 수를 정하지 않는다.

## Cloud Helm 차트로 옮길 때

Dockerfile은 실행 이미지의 내용과 시작 명령을 정하고, Kubernetes 매니페스트는
그 이미지를 어느 노드에서 어떤 일정·자원·설정으로 실행할지 정한다. Helm은
`templates/`의 매니페스트 틀에 `values.yaml`과 환경별 값을 넣어 최종 매니페스트를
만든다. 따라서 노드 라벨·Namespace 변경은 Dockerfile 수정 사유가 아니다.
([Helm values](https://helm.sh/docs/chart_template_guide/values_files/))

2026-09-21 확인 기준 Cloud `develop` (`57cd52e`)에는 GitOps와
`moongcheap-service` Helm 차트가 병합되어 있다. 현재 차트는 실행 리소스로
Deployment를 렌더링한다. `env`, `envFrom`, 자원과 노드 선택 설정은 지원하지만,
CronJob, ConfigMap 생성, ServiceAccount, 명시적인 `command`/`args`, 볼륨과
보안 컨텍스트는 아직 지원하지 않는다. `values.yaml`에 항목을 추가할 때는
해당 값을 사용하는 템플릿도 필요하다.
([차트 템플릿](https://github.com/V-MoongCheap/MoongCheap-Cloud/blob/57cd52e/gitops/charts/moongcheap-service/templates/deployment.yaml))

개발 ApplicationSet은 `destination.namespace: moongcheap-develop`을 사용하고,
AppProject는 `moongcheap-*` Namespace를 허용한다. B 전용 overlay를 이 기준에 맞췄다.
설계 문서의 `ai` Namespace를 적용하려면 ArgoCD 정책까지 함께 바꿔야 하므로 여기서
임의로 사용하지 않는다. CronJob, ConfigMap, ServiceAccount, 외부 Secret은
같은 Namespace에 둔다.
([개발 ApplicationSet](https://github.com/V-MoongCheap/MoongCheap-Cloud/blob/57cd52e/gitops/argocd/applicationset-services-develop.yaml),
[AppProject](https://github.com/V-MoongCheap/MoongCheap-Cloud/blob/57cd52e/gitops/argocd/projects/services-project.yaml))

B는 `demand-clustering-batch`가 종료되는 배치이므로 **CronJob 템플릿이 필요**하다.
Deployment로 감싸면 완료한 컨테이너가 반복 시작될 수 있다. Cloud 차트에서 배치 유형을
지원하도록 확장하거나 B용 CronJob 차트로 옮기고 다음 계약을 보존한다.
현재 ApplicationSet의 `ai` 항목은 하나의 Deployment용 설정이므로 B 배치를
별도 워크로드로 관리할 수 있도록 차트와 ApplicationSet 구성을 함께 정한다.

| 기존 매니페스트의 항목 | Helm 반영 대상 |
| --- | --- |
| `schedule`, `timeZone`, `suspend`, `concurrencyPolicy` | CronJob의 `spec` |
| 재시도·실행 제한·완료 후 정리 | CronJob의 `jobTemplate.spec` |
| 노드 선택·ServiceAccount·Pod 보안·`restartPolicy: Never`·볼륨 | Job의 Pod 템플릿 |
| 이미지·명령·환경 변수·Secret 참조·자원·마운트·컨테이너 보안 | Pod의 컨테이너 설정 |
| Kustomize의 `configMapGenerator` | Helm ConfigMap 템플릿과 일치하는 `envFrom` 참조 |
| B 전용 개발 Namespace `moongcheap-develop` | ArgoCD `destination.namespace` 및 해당 Namespace의 Secret |

HTTP 포트·Service·Ingress·HTTP probe·HPA는 B에 적용하지 않는다. 이 배치는
PostgreSQL을 조회한 뒤 Backend 내부 API를 호출하므로 `BACKEND_BASE_URL`에는 실제
Backend Service 주소를 넣는다. B 자체의 수신 Service를 만드는 흐름은 아니다.
개발 환경은 B 전용 overlay와 동일하게 `http://backend`를 사용한다.

Cloud Terraform은 FE·system Managed Node Group과 BE·AI용 Karpenter를 구성한다.
GitOps에는 Karpenter controller 설정과 `be-ai` NodePool/EC2NodeClass 정의가 있다.
NodePool의 `workload=backend-ai`, Linux amd64, taint 없음은 현재 B 설정과 일치한다.
현재 인스턴스 유형은 `t3.large`, NodePool 전체 자원 상한은 CPU `8` / 메모리 `32Gi`다.
이 상한은 한 Pod가 사용할 수 있는 자원을 뜻하지 않는다. 실제 노드에서 배치를 실행할
CPU·메모리 여유는 Cloud가 확인해야 한다. 이 대조는 실제 EKS 상태 확인이 아니다.
([FE·system 노드](https://github.com/V-MoongCheap/MoongCheap-Cloud/blob/57cd52e/terraform/modules/eks/node_groups.tf),
[BE·AI NodePool](https://github.com/V-MoongCheap/MoongCheap-Cloud/blob/57cd52e/gitops/platform/karpenter/resources/nodepool-be-ai.yaml))

Cloud의 `Jenkinsfile.template`은 `DOCKERFILE_PATH`의 파일을 Kaniko로 빌드한다.
B에 연결할 때는 저장소 루트를 build context로 유지하고 이 값을 `docker/Dockerfile.demand-clustering`으로
지정한다. 현재 `python-builder`는 Python 3.11이므로 B의 Python 3.12 이상 요구사항과
`uv`, `kubectl` 준비를 CI 쪽에서 맞춘다. 이미지의 Python 3.13.12, 비밀 값 미포함 정책,
배치 entrypoint는 유지한다. 2026-09-21 Docker/BuildKit 및 Cloud와 같은 Kaniko v1.23.2의
로컬 `--no-push` 빌드를 통과했다. 실제 Jenkins 기동과 ECR push 권한·연결은 별도 확인 대상이다.
([Jenkins 템플릿](https://github.com/V-MoongCheap/MoongCheap-Cloud/blob/57cd52e/gitops/jenkins/pipelines/Jenkinsfile.template),
[빌드 에이전트](https://github.com/V-MoongCheap/MoongCheap-Cloud/blob/57cd52e/gitops/platform/jenkins/values.yaml))

Backend `develop` (`89a4935`)에는 합의한 두 internal API와 `reject_history` migration이
있다. AI도 Backend 인증 필터와 같은 `X-Internal-Api-Key`를 보내도록 맞췄다. AI의 `BACKEND_INTERNAL_KEY`와
Backend의 `MOONGCHEAP_INTERNAL_API_KEY`에는 같은 키 값을 각각 주입해야 한다.
([Backend 인증 필터](https://github.com/V-MoongCheap/MoongCheap-Backend/blob/89a4935/src/main/java/com/moongcheap_backend/auth/infrastructure/InternalApiKeyFilter.java))

Cloud의 ExternalSecret이 RDS Secret의 host/port/dbname/username/password를 Backend용
`DB_URL`, `DB_USERNAME`, `DB_PASSWORD`로 바꾼다. B는 이 세 값을 재사용해 자체 DSN을
만든다. 실제 DB 접속·SSL 조건과 `demand`, `demand_board`, `reject_history` 조회 권한은
검증하지 않았으며, 공유 계정에서도 B의 읽기 전용 세션 설정은 유지한다.

실제 배포 매니페스트는 Cloud GitOps에서 관리한다. 이 저장소의 Kustomize 예시와
Cloud Helm으로 같은 CronJob을 각각 배포하지 않는다. 기존 공용 `overlays/dev`와
B 전용 overlay도 동시에 배포하지 않는다. Namespace가 다르면 `Forbid`가 중복 실행을
막지 못한다. 차트 작성 후에는 `helm lint`와
`helm template`으로 렌더링하고 위 계약 및 기존 Secret 참조, PVC 미사용을 확인한다.

## 로컬·CI 검증 및 배포 전 교체 항목

저장소 루트에서 실행한다. `kubectl`의 Kustomize 기능과 dev 의존성이 필요하다.

```bash
uv sync --project packaging/demand-clustering --locked --extra data --extra dev
kubectl kustomize k8s/base/demand-clustering-job
kubectl kustomize k8s/overlays/demand-clustering-dev
tools/verify_kubernetes_manifests.sh
uv run --project packaging/demand-clustering --no-sync pytest -c packaging/demand-clustering/pyproject.toml
```

검증 스크립트는 base, 기존 공용 dev, B 전용 dev의 렌더링 결과를 파싱해
Secret·노드·재시도·보안·이미지 내부 경로·PVC 미사용과 A 비포함 경계를 검사한다.
렌더링과 검증 스크립트는 클러스터에 접속하거나 리소스를 적용하지 않는다. 전체 pytest는
`kubectl`이 없으면 배포 테스트를 건너뛰므로, CI에는 누락 시 실패하는 위 검증 스크립트도
등록한다. 이는 API 서버의 스키마·admission 검증이나 실제 Pod 기동 시험을 대체하지 않는다.

인프라의 환경별 GitOps 설정에서는 다음 값을 채운다.

1. 실제 Namespace와 ECR 이미지 경로·Git SHA 태그.
2. ConfigMap의 Backend Service 주소(개발 예시는 `http://backend` 반영 완료).
   v5 시드·taxonomy·모델 경로는 이미지 기본값을 유지한다.
3. `backend-env`의 DB 세 항목과 Parameter Store 내부 키 항목 공급.
4. BE·AI NodePool의 실제 라벨·taint 정책, 합산 CPU/메모리 여유와 DB·Backend 네트워크 연결.
5. 테스트 데이터로 실제 연동 검증 후 스케줄·제한 시간을 확인하고 `suspend: false`로 전환.

현재의 `replace-with-git-sha`와 base·공용 dev의
`https://backend.invalid`는 배포 값이 아닌 자리표시자다. B 전용 dev의 Backend 주소만
채운 상태이며 Secret 공급·연동 검증은 필요하다. 모델·상품 자료는 이미지에 포함한다. `suspend: true`는 정기 실행을 막지만 수동 Job 생성까지
막지는 않으므로, 실제 DB 상태를 바꾸는 수동 실행은 별도 승인된 대상에서만 수행한다.
