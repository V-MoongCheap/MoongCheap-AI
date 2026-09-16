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

## 실행

```bash
docker run --rm -p 8081:8081 \
  -e SELLER_ANALYSIS_INTERNAL_KEY=<주입값> \
  moongcheap/ai-seller-analysis:<tag>
```

| 항목 | 값 |
|---|---|
| 포트 | 8081 (컨테이너 내부·노출 동일) |
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

## 리소스 제안

| 항목 | 값 | 근거 |
|---|---|---|
| requests | cpu `100m` · memory `128Mi` | 컨테이너 실측 79 MiB, 로컬 실행 RSS 44.6 MiB |
| limits | cpu `500m` · memory `256Mi` | 모델·외부 호출이 없고 계산이 결정적 산술이다 |

⚠️ 컨테이너 실측 79 MiB 는 **arm64 호스트에서 amd64 이미지를 에뮬레이션**한 값이라 실제 amd64 노드보다 클 수 있다.
동시 요청 수와 워커 수가 정해지면 다시 잰다. 워커를 늘리면 메모리도 워커 수만큼 늘어난다.

## 검증 기록 (2026-09-16)

`docker build` 성공 (이미지 220MB, 약 24초). `--read-only --user 65534:65534` 로 실행해 아래를 확인했다.

| 확인 | 결과 |
|---|---|
| `GET /health` | `200` · `internal_key_required: true` |
| 인증 헤더 없음 / 잘못된 키 | 둘 다 `403` |
| 정상 요청 | `200` · 지표·근거 문장 정상 |
| 개인정보 필드(`user_id`) 포함 요청 | `400` |
| `GET /openapi.json` | `200` — 이미지에 담은 계약 파일로 생성 |
| 키 없이 기동 | 기동 실패 (의도된 동작) |
| `SELLER_ANALYSIS_ALLOW_UNAUTHENTICATED=1` | 기동 후 `internal_key_required: false` |
| 실행 사용자 | `uid=65534(nobody)` |
| 읽기 전용 루트 파일시스템 | 정상 동작 (쓰기 경로 없음) |

## 확인 대기

| 항목 | |
|---|---|
| ECR 리포지토리 | 네이밍 규약은 `moongcheap/{service}` 다. AI 파트는 배치와 API 두 이미지를 내므로 리포지토리를 나눌지 태그로 구분할지 확인 필요 |
| 서비스 포트 | 인프라 설계서에 `[AI API Port 확정 필요]` 로 남아 있다. 저장소 기동 예시를 따라 8081 을 제안한다 |
| 노드 배치 | Kubernetes 배포 설정에서 인프라가 정한다 (2026-09-16 인프라 확인). 이미지는 BE·AI Worker Node Group(t3.large) 기준 `linux/amd64` 로 빌드한다 |
| 기능 존폐 | 판매자 수요 분석 기능 자체가 PM 결정 대기다. 배포 대상 포함 여부는 파트장·PM 확인이 필요하다 |
