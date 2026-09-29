# Part A Labeling Smoke Test

## 실행일

2026-09-14

## 검증 범위

```text
Local PostgreSQL
  → A Labeling Python runtime
  → demand.label / demand.processed_at UPDATE
  → Docker image runtime
  → 동일 배치 재실행 멱등성
```

## Fixture DB

로컬 Docker PostgreSQL에 테스트 Fixture를 Seed했다.

| 항목 | 건수 |
| --- | ---: |
| category | 17 |
| product_catalog | 1,024 |
| demand | 5,000 |

운영 DB와 무관한 테스트 데이터이며, 접속 정보는 로컬 환경변수로만 주입했다.

## Python 직접 실행 결과

```text
처리 rows: 5,000
DB updatedCount: 5,000
label 저장: 5,000
processed_at 저장: 5,000
빈 label: 0
```

결과 상태:

```text
LABELED: 4,275
LABELED_WITH_REVIEW: 725
```

`LABELED_WITH_REVIEW`는 규칙으로 결과를 생성했지만 확인되지 않은 자연어 조건이 남은 정상적인 검토 상태다. DB 저장 정책상 Label 결과는 저장되며, 별도 경고 정보는 결과 CSV에 남긴다.

## Docker 실행 결과

```text
Image: moongcheap/ai-labeling:local-smoke
Build: 성공
Runtime user: UID/GID 65534/65534
Container DB connection: 성공
Container DB updatedCount: 5,000
```

컨테이너는 `category.facet`을 DB에서 조회한 뒤 Python에서 JSON parsing한다. 따라서 DB 직접 저장 모드에서는 Taxonomy 파일을 이미지에 포함하지 않는다. `category.facet`이 없는 환경에서는 실행 전에 Backend/DB 계약을 확인해야 한다.

## 재실행 결과

동일 DB와 동일 이미지를 다시 실행했다.

```text
처리 rows: 0
DB updatedCount: 0
```

`processed_at IS NULL` 조건으로 이미 처리된 Demand를 건너뛰므로 중복 Labeling/중복 UPDATE가 발생하지 않았다.

## Kubernetes 확인

- `k8s/base/a-labeling-job` Kustomize render: 성공
- `k8s/overlays/dev` Kustomize render: 성공
- CronJob: `suspend: true`
- `concurrencyPolicy`: `Forbid`
- `backoffLimit`: `0`
- HTTP Port/Probe/Ingress: 없음
- Resource request: CPU 1 / Memory 2Gi
- Resource limit: CPU 2 / Memory 3Gi

## Cloud 반영 전 확인사항

1. ECR 이미지 경로와 Git Commit SHA tag를 확정한다.
2. `A_DATABASE_URL`을 `ai-labeling-database` Secret으로 주입한다.
3. PostgreSQL 계정에 필요한 Demand 조회 및 Label 결과 UPDATE 권한을 부여한다.
4. `product_catalog.category_id`와 `category.facet` 조회가 가능한지 확인한다.
5. PostgreSQL Network/Firewall을 허용한다.
6. Dev 환경에서 먼저 CronJob `suspend: false`로 전환한다.
7. 첫 실행 후 `demand.label`, `demand.processed_at`, 빈 Label, REVIEW 건수를 확인한다.

## 아직 수행하지 않은 항목

- 실제 EKS 클러스터에서의 Job 실행
- 실제 Cloud Secret 주입
- 운영 PostgreSQL에 대한 연결
- ECR Push 및 ArgoCD 배포

위 항목은 Cloud GitOps/운영 환경 권한이 필요하다.

## ERD v5 Mock 재검증

ERD v5 원본을 `docs/erd/v5/`에 저장한 뒤 로컬 Mock schema를 재생성하여 다시 실행했다.
`demand.pay_method_id`는 결제 파트가 없는 로컬 fixture에서 기본값 `1`로만 채우며, Part A는 이 값을 읽거나 변경하지 않는다.

```text
category: 17
product_catalog: 1,024
demand: 5,000

첫 실행 updatedCount: 5,000
재실행 updatedCount: 0
processed_at 저장: 5,000
빈 label: 0
전체 pytest: 492 passed, 26 skipped
```

실제 DB 계정, Secret, 네트워크, CronJob 실행은 아직 확정되지 않았으므로 위 결과는 ERD v5 구조를 반영한 로컬 Mock 검증 결과다.
