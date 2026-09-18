# 판매자 수요 분석 API 컨테이너 실행 안내

판매자 수요 분석 내부 API(`POST /internal/v1/seller/bid-guide`)를 컨테이너로 띄우는 절차다.
이미지 push, GitOps 갱신, ArgoCD/EKS 연결과 환경별 운영 설정은 인프라 측에서 구성한다.

배치(Part A 라벨링 · Part B 수요 클러스터링)와는 **다른 이미지**다. 이 이미지는 상주 서버다.

## 빌드

저장소 루트에서 실행한다. 검증 대상은 Linux amd64, Python 3.13.12다.

```bash
docker build --platform linux/amd64 \
  -f docker/Dockerfile.seller-analysis \
  -t moongcheap/ai-seller-analysis:develop-$(git rev-parse --short HEAD) .
```

빌드는 `requirements-api.txt` 의 고정 버전만 설치한다 — `fastapi==0.115.6`, `uvicorn==0.34.0`, `httpx==0.28.1`.
계산 계층(`bid_guide.py`)과 계약 검증은 표준 라이브러리만 쓰므로 추가 의존성이 없다.

이미지에 담는 것은 `src/` 와 `docs/contracts/` 두 가지다. `api.py` 가 OpenAPI 를 계약 파일에서
직접 읽으므로 두 경로의 상대 위치를 유지한다.

**Cloud Jenkins(Kaniko)로 빌드할 때** — `Jenkinsfile.template` 은 `--context=`pwd`` 와
`--dockerfile=`pwd`/Dockerfile` 로 루트 `Dockerfile` 을 빌드한다. 이 이미지는 빌드 입력을 저장소 루트로 두고
`--dockerfile` 만 `docker/Dockerfile.seller-analysis` 로 바꾼다.
`docker/Dockerfile.seller-analysis.dockerignore` 는 BuildKit 의 Dockerfile 별 제외 규칙이라 Kaniko 가 읽지 않을 수 있다.
그 경우 `COPY src` 가 `__pycache__` 같은 작업 공간의 생성 파일까지 담을 수 있다. **이미지 내용이 같다고 보장하지 않는다.** **Kaniko 빌드는 검증하지 않았다.**

아래 검증 기록의 빌드도 BuildKit 없이(구형 빌더) 했으므로 **Dockerfile 별 제외 규칙이 적용되는지는 확인하지 못했다.** 실제로 작업 폴더의 `__pycache__` 가 이미지에 함께 들어갔다. CI 가 같은 작업 공간에서 테스트를 먼저 돌리면 CI 에서도 생긴다 — 빌더·빌드 입력 검증 대기다.

## 테스트

CI 에서 실행하는 명령이다. 테스트는 pytest 와 pandas 가 필요하다 — `requirements-api.txt` 만 설치하면 수집 단계에서 실패한다.

```bash
pip install -r requirements-api.txt "pytest>=8,<9" "pandas>=2.2,<3"
pytest tests/seller_analysis
```

## 실행

```bash
docker run --rm -p 8081:8081 \
  -e SELLER_ANALYSIS_INTERNAL_KEY=<주입값> \
  moongcheap/ai-seller-analysis:<tag>
```

| 항목 | 값 |
|---|---|
| 포트 | 8081 (컨테이너 내부·노출 동일). 실행 명령에 고정하며 환경 변수로 바꾸지 않는다 |
| 헬스체크 | `GET /health` — `{"status":"ok","metrics_version":...,"internal_key_required":true}` |
| 인증 | 요청 헤더 `X-Internal-Key`. 값이 없거나 다르면 `403 UNAUTHORIZED` |
| 실행 사용자 | 65534 (비루트) |
| 쓰기 필요 경로 | 없음 — 읽기 전용 루트 파일시스템으로 띄울 수 있다 |

키는 환경 변수로만 받는다. 이미지·소스·로그에는 값을 넣지 않는다.

⛔ `SELLER_ANALYSIS_INTERNAL_KEY` 없이는 **기동하지 않는다.** 인증이 빠진 채 떠 있으면 헬스체크와
정상 응답이 모두 통과해 조용히 고장 난다. 인증 없이 띄우는 것이 의도라면
`SELLER_ANALYSIS_ALLOW_UNAUTHENTICATED=1` 을 명시한다.

## 환경 변수

| 변수 | 구분 | 용도 |
|---|---|---|
| `SELLER_ANALYSIS_INTERNAL_KEY` | Secret | 내부 호출 인증 키. **환경 변수로 주입받는다.** 값의 공급 경로(Secret Store → Kubernetes Secret 등)는 배포 환경이 정하며 앱은 관여하지 않는다 |
| `SELLER_ANALYSIS_ALLOW_UNAUTHENTICATED` | 선택 | 인증 없이 기동할 때만 `1`. 운영에서는 쓰지 않는다 |

## Kubernetes 배포 (Cloud Helm 차트에 반영할 값)

이 저장소에는 Kustomize 매니페스트를 두지 않는다. Cloud `moongcheap-service` 차트가 이미 Deployment·Service 를
렌더링하고, ApplicationSet 에 `ai` 서비스가 있으므로 `gitops/values/services/ai.yaml` 에 아래 값을 반영하는 것을 제안한다.
⚠️ 그 `ai` 서비스가 **판매자 수요 분석 API 전용인지는 확인하지 않았다.** 다른 AI 구성요소와 공유하는 값이면 배포 방식을 인프라와 먼저 정한다.
아래 「Cloud 현재값」 은 MoongCheap-Cloud develop `4f450fb` 기준이다.

| 항목 | 이 이미지 | Cloud 현재값 | 조치 |
|---|---|---|---|
| `containerPort` | **8081** | 8000 | ⚠️ **8081 로 변경 필요** |
| `service.port` | — | 80 | 그대로 |
| `readinessProbe` · `livenessProbe` | `/health` | `/health`, `enabled: false` | 켜는 시점은 인프라 판단. `/health` 는 프로세스 기동만 확인한다 |
| `nodeSelector` | `workload: backend-ai` | 같음 | 그대로 |
| Namespace | — | `moongcheap-develop` (ApplicationSet) | 그대로 |
| 환경 변수 · Secret | `SELLER_ANALYSIS_INTERNAL_KEY` | 없음 | `env` 에 Secret 참조 추가 |

**보안 설정** — 권장값은 비루트(65534) · 읽기 전용 루트 · 권한 상승 금지 · capabilities 전부 제거 · seccomp `RuntimeDefault` 다.
현재 차트의 `deployment.yaml` 은 `securityContext` 를 렌더링하지 않는다. 이미지의 `USER 65534` 는 차트와 무관하게 적용되지만,
읽기 전용 루트 등 나머지는 차트가 지원해야 적용된다.

## 리소스 제안

| 항목 | 값 | 근거 |
|---|---|---|
| requests | cpu `100m` · memory `128Mi` | 컨테이너 실측 79 MiB, 로컬 실행 RSS 44.6 MiB |
| limits | cpu `500m` · memory `256Mi` | 모델·외부 호출이 없고 계산이 결정적 산술이다 |

⚠️ 컨테이너 실측 79 MiB 는 **arm64 호스트에서 amd64 이미지를 에뮬레이션**한 값이라 실제 amd64 노드보다 클 수 있다.
동시 요청 수와 워커 수가 정해지면 다시 잰다. 워커를 늘리면 메모리도 워커 수만큼 늘어난다.

## 검증 기록 (2026-09-17)

위 「빌드」 명령으로 빌드 성공 (디스크 220MB · 내용 52.9MB). `--read-only --user 65534:65534` 로 실행해 아래를 확인했다.

| 확인 | 결과 |
|---|---|
| `GET /health` | `200` · `internal_key_required: true` |
| 인증 헤더 없음 / 잘못된 키 | 둘 다 `403` |
| 올바른 키를 `X-Internal-Api-Key` 헤더로 보냄 | `403` — 이 API 는 `X-Internal-Key` 만 읽는다 |
| 정상 요청 | `200` · 지표·근거 문장 정상 |
| 개인정보 필드(`user_id`) 포함 요청 | `400` |
| `GET /openapi.json` | `200` — 이미지에 담은 계약 파일로 생성 |
| 키 없이 기동 | 기동 실패 (의도된 동작) |
| `SELLER_ANALYSIS_ALLOW_UNAUTHENTICATED=1` | 기동 후 `internal_key_required: false` |
| 실행 사용자 | `uid=65534(nobody)` |
| 읽기 전용 루트 파일시스템 | 정상 동작 (쓰기 경로 없음) |
| 테스트 명령 (위 「테스트」) | Python 3.13 · 3.11 각각 121 passed |

## 확인 대기

| 항목 | |
|---|---|
| Cloud `containerPort` | Cloud values 는 8000, 이 이미지는 8081. 인프라 설계서의 `[AI API Port 확정 필요]` 에 8081 을 제안했다 |
| 인증 헤더 이름 | 이 API 는 합의대로 `X-Internal-Key` 만 읽는다. Backend → AI 호출 클라이언트는 Backend 저장소에서 찾지 못해 **Backend 가 보낼 헤더 이름은 미확인**이다. Backend develop 의 `InternalApiKeyFilter`(`X-Internal-Api-Key`)는 Backend 가 **받는** 요청용이라 이 API 와 방향이 다르다 |
| 내부 키 공유 | B 배치(AI → Backend)의 키와 같은 값을 쓸지 방향별로 나눌지 미정. Secret 이름도 인프라 확정 |
| ECR 리포지토리 | 네이밍 규약은 `moongcheap/{service}` 다. AI 파트는 배치와 API 두 이미지를 내므로 리포지토리를 나눌지 태그로 구분할지 확인 필요 |
| Kaniko 빌드 · 차트 보안 설정 | 미검증 · 미지원 (위 「빌드」 · 「Kubernetes 배포」) |
| 기능 존폐 | 판매자 수요 분석 기능 자체가 PM 결정 대기다. 배포 대상 포함 여부는 파트장·PM 확인이 필요하다 |
