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

Cloud의 최종 ECR 이름은 `moongcheap/{service}` 규칙에 맞춰 확정한다. 현재 Kubernetes 예시는 `moongcheap/ai-labeling:replace-with-git-sha`를 사용한다.

## Kubernetes

- 기본 매니페스트: `k8s/base/a-labeling-job`
- 초기 `suspend: true`
- `concurrencyPolicy: Forbid`
- 실패 Job은 자동 재시도하지 않고 다음 배치에서 미처리 Demand를 재조회
- Secret 이름: `ai-labeling-database`, key: `url`
- Namespace와 실제 Secret 공급 방식은 Cloud GitOps overlay에서 지정
- HTTP Service/Ingress/Probe는 만들지 않음

실제 Dev 반영 시 Cloud가 다음 placeholder를 교체한다.

1. Namespace
2. ECR Image 경로와 Commit SHA tag
3. `ai-labeling-database` Secret 공급
4. CronJob `suspend: false` 전환
5. PostgreSQL Network/Firewall 허용
