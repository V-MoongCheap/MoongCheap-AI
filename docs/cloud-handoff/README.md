# 인프라 인계 — 생성형 AI 파트

Cloud 저장소에 직접 올리지 않고, 인프라가 그대로 가져다 쓸 수 있는 형태로 이 폴더에 둔다.
기준은 **Cloud `develop` `57cd52e`** (2026-09-21 열람)이다.

## 1. 어느 파일을 어디에

| 이 폴더 | Cloud 저장소 위치 | 성격 |
|---|---|---|
| `values-ai.yaml` | `gitops/values/services/ai.yaml` | **교체** — 지금 값으로는 서비스가 뜨지 않는다 |
| `externalsecret-ai.yaml` | `gitops/platform/external-secrets/resources/externalsecret-ai.yaml` | **신규** — `external-secret-backend.yaml` 과 같은 구조 |
| `job-ai-awarding.yaml` | (정해진 자리 없음) | **논의용** — 차트에 Job/CronJob 템플릿이 없다 |
| (저장소 최상위 `Jenkinsfile`) | 애플리케이션 저장소에 둔다 | 템플릿 안내대로 최상위에 두었다. 아래 확인 요청 1번 참고 |

## 2. 지금 바로 걸리는 것 두 가지

**① 포트가 맞지 않는다.** `gitops/values/services/ai.yaml` 의 `containerPort` 가 `8000` 인데,
판매자 수요 분석 이미지는 `docker/Dockerfile.seller-analysis` 에서 **8081** 로 고정이다
(`EXPOSE 8081`, uvicorn `--port 8081`). 환경 변수로 바꿀 수 없다.

**② 이미지 태그 방식이 다르다.** `gitops/values/overrides/develop/ai.yaml` 은 `image.tag: "develop"` 인데
backend 는 `develop-89a4935`, frontend 는 `develop-c943131` 처럼 커밋 SHA 태그를 쓴다.
ECR 저장소가 `IMMUTABLE` 이라 고정 태그는 두 번째 푸시부터 실패한다.
`ai` 는 `applicationset-services-develop.yaml` 목록에 이미 들어 있어 ArgoCD 가 동기화 대상으로 잡고 있다.

## 3. 확인 요청

**1. 한 저장소에 이미지가 네 개인데 파이프라인을 어떻게 나눌까요**
`Jenkinsfile.template` 안내대로 최상위에 `Jenkinsfile` 을 두었다. 다만 이 파일이 만드는 이미지는
판매자 수요 분석 API 하나다. 이 저장소에는 파트별 이미지가 넷이다 —
`seller-analysis`(C) · `awarding`(C) · `a-labeling`(A) · `demand-clustering`(B).
잡을 여러 개 두는 방식 / 파라미터로 이미지를 고르는 방식 중 어느 쪽이 좋을지 알려 주시면
그 형태로 맞추겠다. 나머지 셋은 각 파트와 함께 정해야 한다.

**2. ECR 저장소를 하나 더 만들까요**
`terraform/modules/ecr/variables.tf` 의 `services` 기본값은 `["frontend","backend","ai"]` 다.
낙찰 배치는 판매자 분석 API 와 **다른 이미지**다. `moongcheap/ai-awarding` 을 추가할지,
`moongcheap/ai` 안에서 태그로 나눌지 정해 주세요.

**3. 낙찰 배치를 어디에 태울까요**
`moongcheap-service` 차트에는 Deployment·Service·HPA·Ingress·PDB 만 있다.
낙찰 배치는 포트를 열지 않는 일회 실행이라 Deployment 로는 맞지 않는다.
`job-ai-awarding.yaml` 은 CronJob 예시이며, 주기와 실패 알림은 아직 정해진 게 없다.
⛔ **지금 붙이면 안 된다** — Backend 조회 응답에 판정 조건 필드가 아직 없어 전건이 계약 오류가 된다
(Backend develop `89a4935`, 2026-09-21 확인). 자리만 먼저 정해 두고 연결은 나중에 한다.

**4. 빌드 컨텍스트 제외 규칙이 Kaniko 에서도 먹는지**
이 저장소는 `docker/Dockerfile.*.dockerignore` 방식을 쓴다. BuildKit 규칙이라
Kaniko(`v1.23.2`)가 이 이름을 읽는지 확인하지 못했다. 안 읽어도 이미지 내용물은 안전하다 —
두 Dockerfile 모두 `COPY` 로 파일을 하나씩 지정한다. 컨텍스트 크기만 커진다.

## 4. 함께 보면 되는 문서

| 문서 | 내용 |
|---|---|
| `docs/ci-cd-seller-analysis-handoff.yml` | 판매자 수요 분석 API — 빌드·테스트 명령, 이미지 크기, 키 |
| `docs/ci-cd-awarding-handoff.yml` | 낙찰 배치 — 실행 계약, 종료 코드, 확인 대기 항목 |
| `docs/AWARDING_INTEGRATION.md` | 낙찰 연동 경로와 로컬 확인 방법 |
