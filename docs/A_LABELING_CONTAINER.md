# A Labeling Container / CronJob 전달 계약

## 실행 형태

파트 A Labeling은 HTTP Service가 아니라 PostgreSQL 직접 저장형 CronJob이다.

```text
CronJob
  → 미처리 demand 조회
  → product_catalog.category_id 조회
  → category.facet 전체 JSON 조회·Python parsing
  → extra_requirement Rule/Alias Labeling
  → demand.label / demand.processed_at UPDATE
```

## Build

```bash
docker build \
  -f docker/Dockerfile.a-labeling \
  -t moongcheap/ai-labeling:<git-sha> .
```

Runtime entrypoint는 `a-labeling-batch --write-db --output /tmp/a-labeling-output.csv`다. 이미지에는 Raw data, `.env`, DB Secret, 모델 가중치를 포함하지 않는다. `/tmp`는 컨테이너의 유일한 쓰기 경로다.

## CI/CD handoff

```yaml
repository: V-MoongCheap/MoongCheap-AI
branch: develop
build_command: "docker build -f docker/Dockerfile.a-labeling -t moongcheap/ai-labeling:<git-sha> ."
test_command: "PYTHONPATH=src .venv/bin/python -m pytest -q"
dockerfile_path: docker/Dockerfile.a-labeling
container_image_name: ai-labeling
application_port: null
health_check_path: null
metrics_path: null
cpu_request: "1"
memory_request: "2Gi"
cpu_limit: "2"
memory_limit: "3Gi"
gpu: false
external_dependencies:
  - PostgreSQL
secret_variables:
  - name: A_DATABASE_URL
    purpose: "A 전용 PostgreSQL read/write DSN"
```

Cloud `develop` GitOps 기준 ECR은 다음과 같이 AI 공용 저장소와 컴포넌트별 태그를 사용한다.

```text
840851421204.dkr.ecr.ap-northeast-2.amazonaws.com/moongcheap/ai:<component>-<environment>-<git-sha>
```

현재 A 컴포넌트 예시는 `labeling-develop-<git-sha>`이며, 최종 태그 생성은 Cloud Jenkins 설정을 따른다.

## Kubernetes

- 기본 매니페스트: `k8s/base/a-labeling-job`
- 초기 `suspend: true`
- `concurrencyPolicy: Forbid`
- 실패 Job은 자동 재시도하지 않고 다음 배치에서 미처리 Demand를 재조회
- Secret 이름: `ai-labeling-database`, key: `url`
- NodeSelector: `workload=backend-ai`, `kubernetes.io/os=linux`, `kubernetes.io/arch=amd64`
- Namespace와 실제 Secret 공급 방식은 Cloud GitOps overlay에서 지정
- HTTP Service/Ingress/Probe는 만들지 않음

Cloud `develop`에는 기존 `A_MODEL2_*` 환경변수 이름이 남아 있을 수 있다. A 런타임은
현재 표준인 `A_LLM_*` 이름을 우선 사용하면서 해당 Cloud 별칭도 호환한다. 모델을 A Pod
내부에 포함할지, sidecar로 둘지, 별도 Worker Pod에서 호출할지는 아직 미정이다.

현재 A 이미지에는 모델 가중치나 Ollama를 포함하지 않는다. 배포 방식이 확정되면
선택한 방식에 따라 다음 값을 반영해야 한다.

- `A_LLM_ENABLED=true`
- `A_LLM_MODEL=qwen2.5:7b-instruct` (현재 운영 후보)
- 원격 Worker 방식을 선택하는 경우 `A_LLM_ENDPOINT=<실제 Worker Service endpoint>`
- A CronJob이 참조하는 `ai-labeling-database` Secret과 `url` key

Cloud develop의 현재 예시에는 `A_MODEL2_FALLBACK_ENABLED=false`와
`A_MODEL2_OLLAMA_BASE_URL=http://ollama:11434`가 남아 있고, 이 저장소가 확인한
GitOps 파일에는 해당 Worker Service 정의가 없다. 이는 현재 배포 방식이 미정인
상태에서 확인된 정합성 보류 사항이며, 방식을 확정한 뒤 Cloud 설정을 맞춰야 한다.

실제 Dev 반영 시 Cloud가 다음 placeholder를 교체한다.

1. Namespace
2. ECR Image 경로와 Commit SHA tag
3. `ai-labeling-database` Secret 공급
4. CronJob `suspend: false` 전환
5. PostgreSQL Network/Firewall 허용
