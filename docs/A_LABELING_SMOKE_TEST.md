# Part A Labeling Smoke Test

## 2026-10-02 최신 확인 범위

- 전체 로컬 회귀: `1189 passed`, 실패·skip 0건. FastAPI HTTP 의존성을 갖춘
  환경에서 실행해 과거 HTTP skip도 해소했다. Mock 서버 계약 검증과 실제 서비스
  품질 평가는 구분한다.
- 실제 A 배포 이미지: `labeling-develop-567a99e`, image digest
  `sha256:868276c6a547f61e0a890b39994c13996115bbf2dcd8073f00866258b788c108`.
- 같은 배포 이미지를 `moongcheap-ai-test`에서 실행해 runtime UID/GID `65534:65534`,
  `/artifacts/product_facets.csv` 소유자 `65534:65534`, 권한 `0400`, 크기
  `414665` bytes 및 SHA-256
  `508ba2d9b49a48dfad06342ff29384dfc0d8f9d7c6d1974e26a3b57a2c3bef9f`를 확인했다.
  non-root 실행 계정이 실제 파일을 읽고 해시를 계산할 수 있다.
- 같은 이미지의 batch CLI를 합성 빈 요구사항 1건으로 실행했다:
  `rows=1`, `LABELED=1`, `label=3-0-0`, `backend=DRY_RUN`.
  DB 쓰기와 LLM 호출을 비활성화한 원상품 기본값 검사다.
- 실제 A DB 계정 `ai_labeling`의 demand SELECT와 `label`, `processed_at` UPDATE
  권한을 확인했다. 이미 처리된 실제 수요는 재조회 적격 0건이며 실제 writer를
  같은 결과로 호출해 UPDATE 0건과 저장값 불변을 확인했다. 수요를 초기화하거나
  새 DB 행을 생성하지 않았다.
- 전날 비영 운영 배치 1건·DB 저장 1건 기록은 과거 실행 기록으로 구분했다.
  이번 DB 재조회로 해당 label과 처리 시각은 확인했지만 그날의 원본 Job 로그를
  새로 확보한 것은 아니다. 10월 2일 14:15 KST 최신 확인 Job은 `rows=0`,
  `updatedCount=0`으로 완료했다. 빈 성공을 새 비영 DB·LLM 연동 시험으로 세지 않는다.
- 아래 10월 1일 로컬 검증 당시의 '배포 미확인', 'HTTP skip'은 당시 상태다.
  이미지 포함·읽기 권한 확인은 위 결과로 갱신되었으며 최신 이미지/설정으로
  다시 배포하면 같은 검사를 반복한다.

## 2026-10-01 product-baseline policy update

Current behavior supersedes the historical REVIEW persistence statements below:

- The reader loads the actual selected Backend catalog's Category taxonomy and
  looks up its explicit Product Facet profile by `backend_catalog_id`, which
  contains the actual Backend `product_catalog.id`.
- Product profiles need not confirm every Taxonomy Facet. Confirmed mapped values
  are retained; missing or unresolved Facets use code `0` (`ALL`) only in that
  label position. This is not a claim about the product's actual property.
  Conflicting duplicates, invalid mapped values, a missing whole profile, or
  category mismatch remain unprocessed.
- The runtime does not infer product Facets from `name`, `spec_summary`, or
  `description`. Unconfirmed individual product Facets do not block other known
  values or the Demand; code `0` fills only the corresponding unconstrained label
  dimension.
- Demands whose catalog has no Backend `category_id` are outside the current
  A taxonomy scope and are excluded by the DB reader join. A categorized row
  with missing/malformed `category.facet` is still a configuration/data error.
- Empty requirements, ambiguous/failed analysis, and explicit exclusions retain
  the product baseline. A stable positive consumer constraint overrides only
  its own Facet.
- When the configured Ollama service/model is unavailable at batch preflight,
  the run fails before DB access/write so the next schedule can retry. This is
  distinct from a per-demand interpretation failure, which retains the product
  baseline as specified above.
- A category-matched product profile with any number of confirmed Facets is a
  valid baseline: confirmed values are used and unknown dimensions receive
  `ALL(0)`. A missing whole product profile or Category/taxonomy remains
  retryable. Parser `status` is diagnostic; `label_status` controls persistence.
- At the time of this local run, deployment verification was pending. The
  dated 2026-10-02 section above records subsequent deployed-image and DB checks.
- A locally prepared artifact is present at `artifacts/product_facets.csv`
  (SHA-256 `508ba2d9b49a48dfad06342ff29384dfc0d8f9d7c6d1974e26a3b57a2c3bef9f`),
  but `.gitignore` excludes it. A Git checkout/Jenkins build therefore will not
  receive it unless it is separately staged in the build input. The deployed
  image's contents were not inspected in this historical local run; the newer
  section above confirms the deployed hash. Verify the release artifact
  hash at `/artifacts/product_facets.csv` inside each new image before running
  any database batch, including an empty batch.
- The older 5,000-row smoke results below predate this product-baseline policy
  and do not verify the current rule that product Facets seed each label.

## 2026-10-01 local regression verification (historical)

- A-focused regression (runtime, product mapping, and DB reader): `127 passed`.
- Full repository regression, rerun with localhost mock-server permission:
  `1158 passed, 31 skipped`. The initial sandboxed run blocked loopback binds;
  the affected seller-awarding test file passed separately (`20 passed`) after
  allowing its local mock servers. The 31 Seller Analysis HTTP tests skip because
  FastAPI is not installed in this local environment; they still need a
  dependency-complete CI run.
- Ruff on changed Python files and `git diff --check` passed.
- The local 1,890-product Facet artifact (5,670 rows; SHA-256
  `508ba2d9b49a48dfad06342ff29384dfc0d8f9d7c6d1974e26a3b57a2c3bef9f`) was
  processed offline: all 1,890 profiles produced a full baseline, with unknown
  Facet dimensions represented by `ALL(0)` and confirmed values retained.
- The B runtime taxonomy checksum currently matches `catalog.json`'s
  `taxonomySha256` (`807a9e8055286812ec2b4350070af8a750d81eb0be573701f83e80c9fad30b6f`).
- Local A Docker image build succeeded. Running the built image as its configured
  non-root user reported the same artifact SHA-256 shown above, and the batch CLI
  starts and prints help. The Dockerfile now refuses to build a deployable A
  image when the required CSV is absent/empty. This image was not pushed to ECR;
  live Ollama/DB writes and deployed-image inspection remain unverified. CI still
  needs an approved method to stage the Git-ignored artifact.

## 2026-09-30 EKS/RDS 검증 (당시 저장 정책의 역사 기록)

- 배포 이미지 `labeling-develop-f1222f4`의 수동 Job 정상 종료 확인.
- 배치 로그: 입력 27건, LLM 요약 calls 2 / applied 0 / failed 0, DB updatedCount 0.
- 조회 시점의 미처리 27건은 모두 UNASSIGNED가 아니었다. 정상 종료만으로 새 라벨 저장 성공을 판정하지 않는다.
- A 계정의 `demand.label`, `demand.processed_at` UPDATE 권한 확인.
- 실제 RDS 세션 전용 임시 테이블에 기존 UNASSIGNED 수요 2건을 복사하여 검증:
  첫 저장 2건, label 및 processed_at 확인, 동일 결과 재저장 0건, 처리 후 조회 0건.
  공용 demand 테이블은 수정하지 않았으며 임시 테이블은 세션 종료로 제거됐다.
- 현재 조회/저장 대상은 `status = 'UNASSIGNED' AND processed_at IS NULL`이다.
- 저장 가능한 결과 상태는 LABELED이며 REVIEW는 저장하지 않는다.
- LLM 결과 채택 경로도 LABELED로 정규화한다. 기존 PARSED 반환은 DB 저장기와 불일치하여 수정했다.
- 배포 이미지에서 합성 입력(제형 요구/빈 요구/배송 요구)으로 PARSED 저장 실패를 재현했다.
  첫 fallback이 보류한 배송 요구를 두 번째 호출이 제형으로 채택하는 사례도 발견했다.
  이미 fallback이 검증한 행은 중복 호출하지 않으며, 호출/채택/실패 요약은 첫 경로까지 합산한다.
- 모델이 Taxonomy Value를 선택했지만 원문에 해당 Value/alias 근거가 없으면 `REVIEW`로 보류한다.
  모델이 고른 각 Value에 대해 그 Value 또는 해당 Value의 alias가 원문에 있는지 확인한다.
  배송 요구를 제형으로 잘못 반환한 실제 Ollama 응답과, 다른 Facet 값만 언급된 문장을 보류하는 것을 확인했다.
- `EXCLUDE` 값은 typed constraints에 보존하지만 긍정 압축 `label`에는 넣지 않는다.
  부정·대조·대안 문장은 LLM 호출 후보에서 제외하고, 모델 결과의 중복/누락/예상 밖 Demand ID,
  Taxonomy Facet 누락, 한 Facet의 복수 후보는 실패 또는 `REVIEW`로 처리한다.
- 추가 극단 입력 점검에서 같은 Facet의 서로 다른 값이 함께 언급된 조건을
  규칙 파서에 의해 반대 값으로 확정될 수 있음을 재현했다. A 전용 입력 정책에서 해당 문장을
  `MULTIPLE_VALUES_SAME_FACET_UNRESOLVED` / `REVIEW`로 보류하며, `processed_at`은 비워 재처리 가능하게 한다.
  명시적인 단일 `EXCLUDE`는 계속 typed constraints에 보존하고 압축 label에는 긍정값으로 넣지 않는다.
- 단일 Facet 다중값 부정·대조·비교·긍정 입력 9종 회귀 테스트와 단일 제외 조건 테스트 통과.
- Job 완료 로그에 `labelingStatusCounts`와 `reviewCount`를 남겨, REVIEW가 포함된 실행을
  단순 성공 건수와 구분한다. 요구 원문은 로그에 출력하지 않는다.
- REVIEW는 자동 label이나 `processed_at`으로 위장하지 않는다. 현재 스키마에는 A의 보류 상태를
  지속 저장하는 별도 칼럼/테이블이 없어 매 실행에서 다시 조회된다. 사람 검수를 운영하지 않는다면
  반복 실행을 막을 영속 보류 상태 저장소가 추가로 필요하다.
- 최종 코드로 실제 Ollama 호출 및 RDS 세션 임시 테이블 검증:
  배송 요구 `REVIEW`/미저장, 빈 요구 `ALL` 저장, 저장 1건, 재저장 0건.
- 실제 Ollama/RDS 검증은 `moongcheap-ai-test`의 세션 전용 임시 테이블을 사용했으며,
  공용 `demand` 데이터는 변경하지 않았다.
- 현재 배포 중인 CronJob 이미지에는 이 PR의 수정이 아직 포함되지 않았다.
  병합 후 이미지 재빌드·배포가 필요하며, 운영 CronJob의 마지막 확인 실행은 rows 0이라
  새 실제 수요를 대상으로 한 비영(非零) 처리 결과는 아직 확인되지 않았다.
- 2026-10-01 검증: A 집중 회귀와 변경 파일 Ruff, `git diff --check` 통과.
  전체 저장소 테스트에서 seller-awarding mock HTTP 서버의 localhost bind가
  `PermissionError`로 막혀 setup 단계 11건이 실행되지 않았다. 해당 파일을 제외한
  저장소 전체 회귀 수치는 아래 최신 로컬 검증 항목을 참조한다.
- 2026-10-01 EKS 재확인은 현재 환경에서 Cluster API hostname DNS 조회가 실패해 완료하지 못했다.
  따라서 이 날짜의 배포 이미지 및 비어 있지 않은 운영 batch 결과는 확인된 것으로 간주하지 않는다.

아래 9월 14일 결과는 당시 구현의 과거 기록이다. REVIEW 저장 정책, 이미지 구성 및 미수행 항목은 현재 운영 정책으로 해석하지 않는다.

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
