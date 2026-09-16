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
