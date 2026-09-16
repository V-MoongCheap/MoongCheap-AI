# Consumer Demand Clustering

원본 Demand를 읽고 Catalog, Facet, 가격·수량, 대체 가능성을 기준으로 계획을 만든다.
Part A의 Labeling 완료를 기다리지 않고 필요한 자연어 조건을 배치 안에서 해석한다.

현재 구현은 다음 범위만 담당한다.

- Backend ERD v2 형태의 Demand와 DemandBoard 입력 변환
- 클러스터링 가능 Demand 및 기존 Board 후보 필터링
- 확정 Price Band 기반의 결정론적 기존 Board 편입·신규 Board 생성 계획
- 서비스 입력 조건을 반영한 대체상품 동의자의 기존 Board 제안 계획
- 공유 PostgreSQL에서 적격 입력을 읽는 read-only adapter
- API 1 적용 후 PostgreSQL을 재조회하고 API 2를 호출하는 순차 실행기
- 실패 시 이전 요청을 재전송하지 않고 다음 정기 실행에서 최신 DB 상태로 재계산

계획 반영 시 잠금, 상태 재검증, Board 생성 및 Demand 상태 변경은 Backend가
소유한다. 이 패키지는 PostgreSQL을 읽기 전용으로 조회하고 계획 JSON을 만들며
상태 변경 DML을 실행하지 않는다. 저장소 내 연결 계약은
`docs/contracts/demand_board_assignment_plan_v01.schema.json`과
`docs/contracts/substitute_offer_plan_v01.schema.json`을 참고한다. 점수와 판정
근거가 포함된 AI 내부 산출물은
`docs/contracts/substitute_board_admission_plan_v01.schema.json`에 별도로 남기며,
Backend mutation 요청에는 전송하지 않는다.

대체상품 경로는 원상품 계획에 포함되지 않은 미편입 수요에 대해 실행한다.
현재 CLI는 활성 보드 catalog의 동일 서비스 카테고리와 claim ID 포함관계를
`IdentityClaimContainmentIndex`로 검사한다. 원상품의 모든 claim이 후보에 있어야
통과하며, E5 Top-K 검색이나 방향성 relation 확장은 이 운영 경로에 연결하지 않는다.
상품명·수출표식·record type으로 판매 가능 여부를 판단하지 않는다. 이후
MUST/EXCLUDE는 board hard gate, PREFER는 순위,
PASSTHROUGH는 주입형 text scorer에 사용하고, CONFLICT/NONE은 자연어 조건으로
보드를 차단하지 않는다. 선택 결과는 `SUBSTITUTE_OFFERED` 후보 한 건이며 확정
참가자 수는 사용자 수락 이후에만 증가한다. 불충분한 근거는 REVIEW가 아니라
미제안으로 처리한다. 상세 계약은 `docs/SUBSTITUTE_BOARD_ADMISSION.md`를 참고한다.

별도 오프라인 상품쌍 평가 경로에서는 서로 다른 주기능 코드를 방향성 relation JSON으로
`load_function_relation_registry`로 로드해 상품쌍 gate에 주입한다. loader는
`deploymentStatus=APPROVED`와 fingerprint를 기본으로 강제한다. identity 또는
명시적 `source → candidate` edge만 허용하며 역방향·전이·미등록 관계를 추론하지
않는다. 310개 relation 후보는 승인 전이므로 운영에 넣을 수 없다.
E5 기능문구 Top-10/20은 오프라인 검색 평가·시뮬레이션에서 사용한 방식이다.

상품쌍 gold 평가와 review는 모델 개발용 오프라인 절차이며 실서비스 상태가
아니다. 실행 결과와 평가 보고서는 프로젝트 저장소에 포함하지 않는다.

## 운영·평가 코드 경계

운영 배치와 domain 규칙은 이 패키지에, 근거 산출물 생성·리뷰·검색 평가는
[`evaluation/`](evaluation/README.md)에 둔다. 운영 코드는 평가 패키지를
import하지 않는다. 공통 profile 상태와 relation fingerprint 계약은 각각
`profile_contract.py`, `function_relation_contract.py`를 양쪽에서 재사용한다.

시뮬레이션을 dry-run Backend 요청 묶음으로 변환하는 함수는
`evaluation.backend_requests`에 있다. 운영 API 클라이언트는 실제 배치 요청
생성·검증·전송만 담당한다. `demand-clustering-batch` 진입점과
`scripts/evaluation/`, `scripts/demand/`의 CLI 경로는 그대로 유지한다.

## 운영 실행 흐름

운영 실행 순서는 `execute_demand_clustering_batch`가 보장한다. 최초 조회에서
원상품 계획을 세우고 API 1을 적용한 뒤 PostgreSQL을 다시 읽는다. 이번 API 1의
처리 대상과 두 조회 사이에 새로 들어온 수요는 같은 실행의 대체상품 후보에서
제외한다. Backend가 생성했다고 응답한 보드가 재조회에서 보이지 않으면 API 2를
호출하지 않는다. 자연어 parser, 상품 profile, claim 인덱스와 선호 점수기를
결합하는 proposal planner를 주입한다. DB 연결과 1회 실행 CLI, 전용 Dockerfile은
구현되어 있으며, 이미지 배포와 시간별 스케줄 등록은 인프라 측 작업이다.
빌드·실행 방법은 [컨테이너 안내](../../../docs/DEMAND_CLUSTERING_CONTAINER.md)를 참고한다.

Backend 호출 인증은 `X-Internal-Key: {internal-key}`를 사용한다. 공유 키는
AWS Parameter Store의 `SecureString`으로 관리하고 배포 환경에서
`BACKEND_INTERNAL_KEY` 환경 변수로 주입한다. 애플리케이션이 요청마다 AWS에
조회하지 않으며 AWS 자격 증명을 직접 요구하지 않는다. 키 조회 권한, 주입과
키 교체 시 양쪽 서비스의 갱신은 배포 환경이 담당한다. 키를 요청 로그에 남기지
않고 운영 통신에는 HTTPS와 내부 API 접근 제한을 적용한다.
`BACKEND_BASE_URL`은 일반 설정으로 주입한다. 기존 `BACKEND_SERVICE_TOKEN`은
사용하지 않는다. 운영 최소 참가자 수 `CLUSTER_MIN_PARTICIPANTS`는 5 이상이어야 한다.

`ClaimIndexedSubstituteProposalPlanner`는 재조회된 활성 보드 catalog만 대상으로
같은 서비스 카테고리와 claim ID 포함관계를 먼저 검사한다. 통과한 보드는 기존
가격·MUST·EXCLUDE gate와 PREFER·PASSTHROUGH 순위 계산을 거쳐 API 2 제안 행이
된다. PASSTHROUGH 의미 점수기는 `E5RuntimeTextSimilarityScorer`로 주입한다.
이 점수기는 PASSTHROUGH 수요와 후보가 있는 배치에서만 CPU 모델을 지연 로드하고,
해당 배치의 중복 제거된 수요 문장과 상품 profile을 묶어 임베딩한 뒤 캐시한다.
운영 설정은 `E5_MODEL_PATH`, 선택값 `E5_MODEL_REVISION`, 기본값 32인
`E5_BATCH_SIZE`로 주입한다. CPU용 선택 의존성은 저장소 루트에서 다음과 같이 설치한다.
개발·검증 환경 구성은 [B파트 패키징 안내](../../../packaging/demand-clustering/README.md)를 참고한다.

```bash
uv sync --project packaging/demand-clustering --locked --extra embeddings
```

planner에 로드하는 profile의 `catalog_id`는 PostgreSQL 입력의
`product_catalog.id`와 같아야 한다. 상품도감과 ID는 Part A를 기준으로 하며,
Part B가 별도 ID를 만들지 않는다. 현재 Part A 산출물로 profile을 검증하고 후속
산출물은 버전 갱신으로 반영한다. 실제 DB 연동 시에는 입력 수요·보드가 같은
상품도감 ID를 사용하는지 확인한다.

## 1회 배치 실행

로컬과 컨테이너의 운영 진입점은 `demand-clustering-batch`이다. 실행 시 최초
PostgreSQL 조회, API 1 호출, PostgreSQL 재조회, 대체상품 계획, API 2 호출 순서를
한 번 수행하고 요약 JSON을 표준 출력에 남긴 뒤 종료한다. DB 연결에는
`default_transaction_read_only=on`과 autocommit을 함께 적용한다. DB role 자체의
SELECT 전용 권한도 별도로 유지해야 한다.

필수 운영 설정은 다음과 같다.

- 비밀 설정: `SHARED_DATABASE_URL`, `BACKEND_INTERNAL_KEY`
- 일반 설정: `BACKEND_BASE_URL`, `MFDS_CATALOG_PROFILES_PATH`,
  `DEMAND_TAXONOMY_PATH`, `DEMAND_CONSTRAINT_RULES_PATH`,
  `DEMAND_CONSTRAINT_COMPAT_ALIASES_PATH` (B 기본 별칭), `E5_MODEL_PATH`
- 선택 설정: `DEMAND_CONSTRAINT_ALIASES_PATH` (A 승인 별칭; 없으면 B만 사용),
  `CLUSTER_MIN_PARTICIPANTS`, `E5_MODEL_REVISION`,
  `E5_BATCH_SIZE`, `BACKEND_HTTP_TIMEOUT_SECONDS`,
  `POSTGRES_CONNECT_TIMEOUT_SECONDS`

`SHARED_DATABASE_URL`은 Python PostgreSQL driver가 읽을 수 있는 DSN이어야 하며
Spring의 `jdbc:postgresql://...` 형식을 사용하지 않는다. `BACKEND_BASE_URL`에는
경로가 아닌 Backend 서비스의 HTTP(S) base URL을 넣는다. artifact와 모델 경로가
존재하지 않거나 PostgreSQL 입력의 catalog ID가 profile에 없으면 Backend mutation
전에 실패한다.

로컬에서는 환경 파일을 명시해 실행할 수 있다.

```bash
uv run --project packaging/demand-clustering --no-sync demand-clustering-batch --env-file .env
```

운영 CLI의 `plannedAt`은 실제 실행 시작 시각이며 시간대가 포함된다.
이전 시간 슬롯으로 내림하거나 과거 실행 시각을 재사용하지 않는다.
과거 요청 재생용 `--batch-id`, `--planned-at` 옵션은 제공하지 않는다.
`clientBoardKey`는 `new-board:1`처럼 한 요청 안에서 신규 보드 항목과 응답을
연결하는 키일 뿐, 배치 식별자나 중복 처리 방지 키가 아니다.

## 실패 후 다음 배치 처리

API는 한 번씩만 호출한다. 오류가 발생하면 해당 실행을 실패로 종료하며,
이전 요청을 파일에 보존하거나 자동 재전송하지 않는다. 다음 정기 배치는
PostgreSQL의 최신 상태를 조회하여 유효한 `UNASSIGNED` 수요를 다시 계산한다.

- API 1에서 실패하거나 응답을 확인하지 못하면 같은 실행에서 API 2를 호출하지 않는다.
- API 2에서 실패하거나 응답을 확인하지 못해도 이전 제안 요청을 다시 보내지 않는다.
- 실제 반영된 `ASSIGNED` / `SUBSTITUTE_OFFERED` 수요는 다음 조회에서 제외된다.
- 거절이나 제안 보드 종료로 `UNASSIGNED`에 복귀한 수요는 유효기간이 남아 있다면
  원상품 경로부터 다시 검토한다. 대체 제안은 API 1 이후 다시 조회한
  `reject_history(demand_id, demand_board_id)`에 있는 조합을 후보에서 제외한다.
  같은 상품의 다른 보드와 다른 수요에는 해당 제외를 적용하지 않는다.
- 다음 실행까지 처리가 지연될 수 있으며, 그 사이 만료된 수요는 제외된다.

`reject_history`의 테이블 배포·거절 저장과 AI 계정의 SELECT 권한이 필요하다.
현재 수요·활성 보드에 해당하는 이력을 일괄 조회하며, 실행 시작 이후 기록된
거절도 포함한다. 이력 조회 실패 시 해당 배치를 중단한다. 모든 후보를 거절한
수요에는 대체 제안을 보내지 않는다. 상세 계약은
[거절 이력 처리](../../../docs/SUBSTITUTE_BOARD_ADMISSION.md#거절-이력에-따른-재제안-제외)를 참고한다.

Backend 요청·응답은 `batchId`를 요구하지 않는다. 응답은 현재 요청의 상태
재검증 결과이며 `APPLIED`를 사용한다. 신규 보드별 결과는 `CREATED` 또는
`STALE_REJECTED`다. 같은 제안이 현재 저장되어 있으면 `alreadyAppliedCount`에
포함할 수 있지만, 과거 실행의 결과를 복원하는 `REPLAYED` 계약은 사용하지 않는다.

신규 보드의 종료 시각은 Backend가 실제 생성 시각 + 5일로 정하며 AI는
`saleEndAt`을 전송하지 않는다. 수요 만료 및 수락·거절에 따른 상태 변경도
Backend가 담당하며 AI는 조회 결과에 따라 다음 배치 대상을 결정한다.

`BATCH_STATE_DIR`과 checkpoint 볼륨은 더 이상 필요하지 않다. 과거 버전의
요청 파일은 읽거나 재생하지 않으며, 배포 시 자동으로 삭제하지도 않는다.
오프라인 시뮬레이션의 `batchId`는 분석용 메타데이터로 남지만 Backend 요청에는
전송하지 않는다.

## 스케줄러 설정

운영 CronJob은 `concurrencyPolicy: Forbid`, Job은 `backoffLimit: 0`,
Pod는 `restartPolicy: Never`로 설정한다. 실패한 실행을 즉시 재시도하지 않고
다음 정기 실행에 맡기며, 외부 워크플로의 자동 재시도도 비활성화한다.
이 저장소는 `k8s/base`의 기본 CronJob과 `k8s/overlays/dev`의 중지된 개발 환경 예시를
제공한다. 실제 환경별 설정과 배포는 인프라 GitOps에서 관리한다.
[Kubernetes 안내](../../../k8s/README.md)에 AI 노드 선택, Secret·artifact 공급과
오프라인 검증 방법을 정리했다.

새 실행에는 파일 잠금을 사용하지 않으므로 스케줄러에서 배치 중첩을 제한한다.
다만 스케줄러 설정만으로 중복 실행이 완전히 배제되는 것은 아니며, 최종 상태
재검증과 동시성 제어·원자적 변경은 계속 Backend가 담당한다.
