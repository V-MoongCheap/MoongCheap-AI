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

이미지의 `config/`에는 reviewed alias, compatibility alias, constraint rules,
`facet_taxonomy_v2_2.json`을 포함한다. DB 실행에서는 `category.facet`을 사용하고,
번들 Taxonomy는 파일 입력 검증용이다. Dockerfile의 COPY 목록을 변경할 때는
`Dockerfile.a-labeling.dockerignore`의 허용 목록도 함께 갱신한다.

Jenkins 보안 검사 단계는 전용 Trivy/Gitleaks 컨테이너를 자체 Pod 설정으로
선언한다. Cloud의 기본 `python-builder`에 이 컨테이너들이 있다고 가정하지 않는다.
Python 테스트는 `uv sync --python 3.13.12`로 이미지와 같은 버전을 선택한다.

## Model 2 fallback

기본 실행은 결정론적인 Rule/Alias 경로다. 운영에서 Qwen fallback을 사용하려면
별도의 Ollama 서비스가 먼저 준비되어야 하며, 다음 환경변수를 ConfigMap 또는
Secret 정책에 맞게 주입한다.

```text
A_MODEL2_FALLBACK_ENABLED=true
A_MODEL2_FALLBACK_MODEL=qwen2.5:7b-instruct
A_MODEL2_OLLAMA_BASE_URL=http://ollama:11434
A_MODEL2_FALLBACK_TIMEOUT_SECONDS=300
A_MODEL2_FALLBACK_BATCH_SIZE=5
```

LLM을 활성화한 실행은 DB 처리 전에 Ollama `/api/tags`에서 위 모델의 존재를 확인한다.
모델이 없거나 Ollama가 준비되지 않았으면 실패 종료하며 `demand.processed_at`을 기록하지
않는다. 따라서 다음 스케줄 실행에서 해당 Demand가 다시 조회된다.

fallback은 Rule 결과를 대체하지 않고 `PASSTHROUGH`, `TAXONOMY_AMBIGUOUS`,
또는 명시적 제외/충돌이 아닌 `REVIEW`만 대상으로 한다. 응답이 현재 Taxonomy의
Facet/Value로 완전히 검증되고 typed constraint를 만들 수 있을 때만 `PARSED`로
승격한다. 호출 실패, 누락 결과, Taxonomy 밖 값, 정보가 없는 결과는 기존 결과를
유지하고 `REVIEW`로 남긴다. 따라서 Ollama가 없는 환경에서도 기본 CronJob은
정상적으로 Rule-only로 동작한다.

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
내부에 포함하지 않고 Cloud가 준비하는 Ollama 서비스로 호출하는 방향이다. Cloud는
LLM workload를 `m6i.xlarge` CPU NodePool에 배치할 계획이며, 최종 Kubernetes label·
taint·toleration과 Ollama Service 주소는 Cloud가 확정 후 GitOps에 반영한다.

Cloud의 fallback 활성화 값이 `false`이면 A는 Rule/Alias만 실행하고 Ollama를 호출하지
않는다. Model 2 fallback을 실제 배포에 사용할 때는 Cloud ConfigMap에서
`A_LLM_ENABLED=true`, `A_LLM_MODEL=qwen2.5:7b-instruct`,
`A_LLM_ENDPOINT=http://ollama:11434`를 공급하거나, 호환 설정으로
`A_MODEL2_FALLBACK_ENABLED=true`를 공급해야 한다. 이 값이 적용되기 전에는
`/api/tags` preflight도 실행되지 않는다.

현재 A 이미지에는 모델 가중치나 Ollama를 포함하지 않는다. Ollama 서비스와 모델이
준비된 뒤 다음 값을 배포 환경에 주입한다.

- `A_LLM_ENABLED=true`
- `A_LLM_MODEL=qwen2.5:7b-instruct` (현재 운영 후보)
- `A_LLM_ENDPOINT=http://ollama:11434` (Cloud develop의 Ollama API 기준)
- A CronJob이 참조하는 `ai-labeling-database` Secret과 `url` key

Model 2 호출은 현재 Ollama `/api/generate` 계약을 사용한다. vLLM/OpenAI
호환 endpoint로 변경하려면 별도 Adapter와 계약 검증이 필요하다.

Cloud develop의 현재 예시에는 `A_MODEL2_FALLBACK_ENABLED=false`와
`A_MODEL2_OLLAMA_BASE_URL=http://ollama:11434`가 남아 있다. A 런타임은 이 이름을
과도기 호환하며, 배포 시 모델 사용을 활성화해야 한다.

실제 Dev 반영 시 Cloud가 다음 placeholder를 교체한다.

1. Namespace
2. ECR Image 경로와 Commit SHA tag
3. `ai-labeling-database` Secret 공급
4. CronJob `suspend: false` 전환
5. PostgreSQL Network/Firewall 허용
