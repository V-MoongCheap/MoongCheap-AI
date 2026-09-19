# 낙찰 판정 연동 (AI → Backend)

AI 가 Backend 의 판정 대기 board 를 조회해 낙찰을 판정하고 결과를 돌려주는 경로다.
기준 문서는 「AI 실행 및 Backend/Frontend 통합 인터페이스 명세」 10-1절이다.

```
Backend  모집 종료 배치 → board GB_AWARDING · product AWARDING
   ↓
AI       GET  /api/awarding/pending?size=N      (조회)
   ↓
AI       조건 검사 → 총액 최저 1건 낙찰, 없으면 유찰
   ↓
AI       POST /api/awarding/internal/result     (평가 전건 전송)
   ↓
Backend  평가 이력 저장 + 상태 반영 + 공동구매 생성
```

## 구성

| 파일 | 역할 |
|---|---|
| `src/moongcheap_ai/seller_matching/offer_ranking.py` | 판정 엔진. 표준 라이브러리만 쓰는 순수 계산이다 |
| `src/moongcheap_ai/seller_matching/awarding_batch.py` | 조회 응답 해석 · 결과 본문 생성 · HTTP 호출 |
| `scripts/awarding/run_awarding_test_drive.py` | 한 번 실행하고 보고서를 내는 시험 운전 |
| `scripts/awarding/mock_backend.py` | 로컬 가짜 Backend |
| `scripts/awarding/sample_pending.json` | 예시 조회 응답 |

## 판정 규칙

「백로그 · 우선순위 P0–P3 · 스프린트 계획」 FSYS-04 *"낙찰 판정 — 총액 최저 + 최소 성사 수량"* 과
「평가 / Gold Set 세부 정의」 6-2절 *"동률은 공고 ID로 확정"* 을 따른다.

```
조건 검사 (요구사항 Product-01 의 판매자 입력값)
  최소 성사 수량   ≤ 현재 총수요
  최소 성사 인원   ≤ 현재 참여 인원
  현재 총수요      ≤ 총 판매 수량
  최대 개별 요청량 ≤ 1인 최대 구매 수량 (미설정이면 총 판매 수량)
  단가             ≤ 희망 가격 상한
→ 조건을 모두 충족한 공고 중 총액(단가 × 총수요 + 배송비) 오름차순, 동률은 productId 오름차순
→ 1위 낙찰. 조건을 충족한 공고가 없으면 유찰 (요구사항 Product-08)
```

- `score` = 1위 총액 ÷ 자기 총액, 소수 넷째 자리 내림. 낙찰 1.0000, 조건 미충족 0.0000
- `reason` 은 사람이 읽는 문장이다. 「낙찰 결과」 화면의 사유로 쓰일 수 있어 **다른 판매자의 금액을 담지 않는다**
- **판정을 보류하지 않는다.** 필수 판정 필드가 빠진 board 만 판정하지 않고 계약 오류로 기록한다 (명세 10-1.4절)

## 실행

### Docker로 바로 시험하기

저장소 루트에서 실행한다. Docker 데몬이 켜져 있어야 하며 최초 빌드는 이미지·패키지 다운로드가 필요하다.
아래 실행은 모두 합성 데이터만 사용하고 외부 통신을 차단한다. 실제 Backend 키는 필요 없다.

```bash
bash scripts/awarding/build_image.sh moongcheap/ai-awarding:local linux/amd64
docker run --rm --platform linux/amd64 --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges moongcheap/ai-awarding:local
```

기본 실행은 파일 판정만 한다. 예상 요약은 조회 4, 판정 3, 계약 오류 1, 낙찰 2이며 `sent: false`다.
Mock 서버까지 포함한 자동 테스트 드라이브:

```bash
docker run --rm --platform linux/amd64 --network none --read-only \
  --tmpfs /tmp:rw,nosuid,noexec,size=16m --cap-drop ALL \
  --security-opt no-new-privileges --entrypoint python \
  moongcheap/ai-awarding:local scripts/awarding/container_smoke.py
```

마지막 `status: PASS`와 종료 코드 0이 성공 기준이다. 키 누락/오류, dry-run 무전송,
정상 3건 반영, 명시적 중복 전송의 stale 3건, 재조회 시 오류 board 1004 한 건,
잘못된 HTTP 200 본문의 실패 처리·재전송 없음, 미반영(stale) 응답의 종료 코드 4,
UTC→KST 변환을 검사한다. 검사는 `assert` 를 쓰지 않아 `python -O` 에서도 지워지지 않는다.
매 실행마다 Mock 상태를 새로 만들고 종료 시 버린다. 실제 DB 상태 전이를 검증하는 시험은 아니다.

이미지는 비루트 사용자로 실행하며 포트를 열지 않는 일회 배치다. 기본 정책 인자는
`PER_BOARD`/`UNIT_PRICE`라는 **시험값**이며 PM 승인값이 아니다.
키·원천 데이터가 빌드 컨텍스트에 들어가지 않도록 허용 파일만 보내는 빌드 스크립트를 사용한다.
로컬 구형 빌더 검증 기준이며 BuildKit/Kaniko·CI 배포 검증은 별도다.
실행 계약과 인프라 확인 사항은 `docs/ci-cd-awarding-handoff.yml`을 참고한다.

### Python으로 직접 실행하기

**1) 파일로만 판정** — 네트워크·전송 없음

```bash
python scripts/awarding/run_awarding_test_drive.py \
  --pending-file scripts/awarding/sample_pending.json \
  --shipping-fee-unit PER_BOARD --price-cap-basis UNIT_PRICE
```

**2) 가짜 Backend 로 조회·전송까지** — 다른 터미널에서 서버를 먼저 띄운다

```bash
python scripts/awarding/mock_backend.py --pending-file scripts/awarding/sample_pending.json --key local-test-key
```

```bash
BACKEND_INTERNAL_API_KEY=local-test-key python scripts/awarding/run_awarding_test_drive.py \
  --backend-url http://127.0.0.1:18080 \
  --shipping-fee-unit PER_BOARD --price-cap-basis UNIT_PRICE --send
```

**3) 실제 Backend** — 먼저 `--send` 없이 조회·판정만 확인한다.
⛔ `--send` 는 board · product · demand 상태를 바꾸고 공동구매를 만든다.

| 종료 코드 | 뜻 |
|---|---|
| 0 | 정상 |
| 1 | 조회·실행 실패 또는 결과 응답 계약 오류(반영 여부 미확인) |
| 2 | `BACKEND_INTERNAL_API_KEY` 가 비어 있음 |
| 3 | 조회는 됐는데 **한 건도 판정하지 못함** (전부 계약 오류) |
| 4 | 전송은 됐는데 **Backend 가 반영하지 않은 board 가 있음** (stale) |

## 설정

| 항목 | 값 | 비고 |
|---|---|---|
| 인증 헤더 | `X-Internal-Api-Key` | Backend `InternalApiKeyFilter` 기준. 실패 시 401 |
| 키 전달 | 환경변수 `BACKEND_INTERNAL_API_KEY` | 명령줄에 남기지 않는다. 오류 메시지에서 가린다 |
| 조회 `size` | 1~100, 기본 50 | |
| 배송비 부과 단위 | `PER_BOARD` / `PER_PARTICIPANT` | **미확정 정책** — 실행할 때 지정한다 |
| 가격 상한 비교 금액 | `UNIT_PRICE` / `TOTAL_WITH_SHIPPING` | **미확정 정책** — 실행할 때 지정한다 |

두 정책은 「평가 / Gold Set 세부 정의」 11절에 미확정으로 남아 있다. 지정한 값은 보고서 `policy` 에 남는다.
위 판정 도식의 단가 상한·배송비 1회 계산은 `UNIT_PRICE`/`PER_BOARD` 선택 예시다.
다른 정책을 선택하면 해당 정책의 비교 금액·배송비 계산을 따른다. 도식만으로 정책 확정을 뜻하지 않는다.

결과 응답은 HTTP 200, `status: APPLIED`, 음이 아닌 정수 `appliedCount`/`staleRejectedCount`,
두 건수의 합이 제출 board 수와 같아야 수용한다. `APPLIED`여도 stale 건수를 실제 반영 건수로 세지 않는다.
응답 오류·유실은 미반영 확정이 아니다. 자동 재전송하지 말고 Backend 조회/이력으로 확인한다.
`judgedAt`은 입력 시간대를 KST로 변환한 뒤 시간대 표기를 제거한다.

⛔ **`staleRejectedCount` 는 두 가지가 섞여 있다.** 이미 처리된 board 뿐 아니라, Backend 가 10개 묶음을
통째로 롤백한 경우(`DemandBoardService.applyAwardingResult` 의 예외 처리)도 같은 건수에 합산된다.
응답만으로는 구분되지 않으므로 이 값이 0 이 아니면 종료 코드 4 와 경고로 알리고 보고서 `reflection` 에 남긴다.
**다시 보내지 않는다.** 반영 여부는 Backend 조회·이력으로 확인한다.

## 연동 전에 필요한 것

아래 외부 구현 상태는 2026-09-19 Backend develop `b56d963` 확인 기준이다. 실연동 직전에 다시 확인한다.

| 항목 | 담당 | 상태 |
|---|---|---|
| 조회 응답의 판정 조건 필드 — `shippingFee` · `minQuantity` · `minParticipantCount` · `maxQuantityPerMember` · `maxDemandQuantityPerMember` | Backend | **없음.** 명세 10-1.5절에는 있으나 구현 응답에는 아직 없다. 지금 응답으로 실행하면 모든 board 가 계약 오류가 된다 |
| dev Backend 주소 · 내부 키 | Backend · 인프라 | 미확보 |
| 판정 대기 board 테스트 데이터 | Backend | 미확보 |
| 배송비 부과 단위 · 가격 상한 비교 금액 | PM | 미확정 |

## 이 경로에 없는 것

- 주기 실행(CronJob), 이미지 게시, CI/CD·Cloud 배포 — 후속 작업이다. 로컬 낙찰 전용 이미지는 위 명령으로 검증 가능하다
- `hasNext` 가 `true` 일 때 이어서 조회하는 반복 — 한 번 실행만 한다
- 가짜 Backend 는 실제 Backend 의 10개 묶음 트랜잭션 · DB 상태 전이 · 공동구매 생성을 흉내 내지 않는다
