# 대체상품 후보 제안 문제 정의

상태: 기존 활성 수요보드 제안 범위 확정
근거: 기능명세서 v2.8 `FN-B09-03`, `FN-B09-04`, `FN-B16-01` 및 최신 Backend 구현
이 문서는 알고리즘·모델·점수·평가셋을 정의하지 않는다.

## 1. 해결할 사용자 문제

구매자가 선택한 원상품으로는 수요보드에 들어가지 못했더라도, 사전에 대체상품
추천에 동의했다면 가격 조건을 넘지 않는 유사 상품의 공동구매 기회를 한 번에
확인하고 직접 수락할 수 있어야 한다.

서비스가 사용자 동의 없이 다른 상품의 확정 참여자로 집계해서는 안 되며,
적합한 후보가 없다는 이유로 추가 질문이나 운영 `REVIEW`를 만들어서도 안 된다.

## 2. 기능 범위

이 기능은 다른 `catalog_id`를 대표하는 **기존 활성 수요보드 한 건**에 원
Demand를 편입 후보로 제안하는 문제다.

`demand_board`는 하나의 `catalog_id`에 귀속된다. 명세에는 서로 다른 원상품
요청으로 신규 Board를 만들 때 대표 상품을 정하는 규칙이나 상태 절차가 없다.
따라서 대체상품 요청끼리 신규 교차상품 Board를 만드는 기능은 이 문제에
포함하지 않는다.

기능명세서의 “유사 상품과 묶인 클러스터”는 원상품과 다른 상품을 대표하는
기존 수요보드를 뜻하는 것으로 해석한다. 동일 상품 요청으로 새 Board를 만드는
일반 Clustering은 별도 정상 경로이며 대체상품 후보 제안이 아니다.

## 3. 시작 조건

아래 조건을 모두 만족한 Demand만 1차 대체상품 경로에 진입한다.

- `status = UNASSIGNED`
- 동일 `catalog_id`의 일반 Clustering 경로를 먼저 적용했지만 여전히 미배정
- `is_substitutable = true`
- 접수 후 미배정 유효기간 2일이 지나지 않음
- 다른 상품의 후보가 연결된 적이 없거나, 별도로 확정될 재제안 정책상 허용됨

`is_substitutable = false`이면 `extra_requirement` 내용과 무관하게 다른 상품
후보 탐색을 실행하지 않는다. 자연어 미입력과 대체상품 동의만 있는 요청도
유효한 진입 대상이다.

수요보드에 직접 참여한 `ASSIGNED` Demand는 이 경로의 시작 대상이 아니다.
`FN-B12-02`에서 받은 대체상품 동의값의 후속 사용 시점은 별도 확인 사항이다.

## 4. 후보 모집단

후보는 판정 시점에 존재하는 수요보드 중 다음 조건을 만족하는 행이다.

- 원상품과 다른 `catalog_id`
- `status = GB_GATHERING`
- Board 모집 종료 전
- Board의 가격 상한이 원 Demand의 희망 가격 상한 이하
- 후보 상품과 원상품의 대체 가능성을 검토할 수 있는 상품 근거가 존재

동일 `catalog_id` Board는 일반 편입 경로의 대상이며 대체상품 제안으로 세지
않는다. 판매자의 응찰 및 낙찰 가능성은 Part C의 책임이므로 후보 생성 조건에
넣지 않는다.

## 5. 시스템이 내려야 하는 결정

하나의 대상 Demand에 대해 결과는 둘 중 하나다.

### 후보 있음

- 기존 수요보드 한 건만 선택
- 선택 이유를 재현 가능한 근거와 함께 Backend 계획에 포함
- Backend가 최신 상태를 재검증한 뒤 `demand_board_id`를 선반영
- Demand를 `SUBSTITUTE_OFFERED`로 전이
- 이 시점의 Board 확정 참여자 수 변화는 0

### 후보 없음

- Demand를 `UNASSIGNED`로 유지
- 사용자에게 추가 조건을 묻지 않음
- 실서비스 `REVIEW` 상태나 운영자 큐를 생성하지 않음
- 원래의 미배정 2일 만료 시각까지 계속 대기

## 6. 제안과 확정 편입의 구분

`SUBSTITUTE_OFFERED`에서는 `demand_board_id`가 기록되지만 확정 참여는 아니다.
이는 B-16에서 보여줄 제안 대상을 연결한 상태다.

```text
UNASSIGNED
  └─ 후보 제안 → SUBSTITUTE_OFFERED
       ├─ 수락 → ASSIGNED, participant_count +1
       ├─ 거절 → UNASSIGNED, demand_board_id = NULL
       └─ 기한 내 미응답 → EXPIRED
```

수락 시 원 Demand의 수량과 자동결제 동의를 그대로 승계한다. 후보가 제안된
시점부터 새로운 2일을 부여하지 않고 원 Demand의 만료 시각을 따른다.

상세 기능행과 2026-09-04 이후 Backend 구현은 명시적 거절을 `UNASSIGNED`
복귀로 정의한다. 2026-08-27 상태 보존 문서의 `거절 → EXPIRED` 표기는 이들과
상충하므로 이 문제 정의의 정본으로 사용하지 않는다.

## 7. 주체별 책임

### AI Batch

- 처리 가능한 Demand와 후보 Board snapshot을 입력으로 받음
- 후보 없음 또는 후보 Board 한 건의 부작용 없는 계획을 생성
- 선택 근거와 사용한 버전을 기록
- Demand·Board 상태 및 참여자 수를 직접 변경하지 않음

### Backend

- 계획 적용 직전에 Demand·Board·가격·만료 상태를 잠금 후 재검증
- 멱등하게 `SUBSTITUTE_OFFERED`와 `demand_board_id`를 반영
- 수락 시에만 참여자 수 증가 및 `ASSIGNED` 전이
- 거절·미응답 상태 전이 처리

### Frontend

- B-16에 후보 한 건만 표시
- 원 요청과 후보 Board 조건을 함께 표시
- 수락·거절 입력만 전달
- 후보가 없을 때 추가 질문 화면을 만들지 않음

## 8. 입력과 출력

### 최소 입력

- Demand: ID, 원 `catalog_id`, 가격 범위, 수량, 대체 동의, 자연어 조건 및 구조화
  결과, 상태, 원 만료 시각
- Candidate Board: ID, `catalog_id`, 가격 범위, 상태, 모집 종료 시각, 현재 확정
  참여자 수
- Product Evidence: 원상품과 후보상품의 객관적 비교에 필요한 상품 사실정보

### 최소 출력

후보가 있으면 다음을 포함한다.

- `demandId`
- `demandBoardId`
- `originalCatalogId`
- `substituteCatalogId`
- `proposedStatus = SUBSTITUTE_OFFERED`
- `requiresUserConfirmation = true`
- `participantCountDeltaOnProposal = 0`
- 선택 근거와 판정 버전

후보가 없으면 Demand ID, 미선택 결과, 재현 가능한 미선택 사유만 반환한다.

## 9. 업무 수용 조건

알고리즘과 무관하게 다음 조건을 모두 만족해야 한다.

- 미동의 Demand에 다른 상품을 제안하지 않는다.
- 이미 배정되거나 만료된 Demand를 대상으로 하지 않는다.
- 같은 상품 Board를 대체상품으로 제안하지 않는다.
- 비활성·마감 Board를 제안하지 않는다.
- 후보 Board 가격 상한이 원 Demand 가격 상한을 넘지 않는다.
- 한 Demand에 동시에 두 후보를 제안하지 않는다.
- 제안만으로 참여자 수를 증가시키지 않는다.
- 수락할 때만 확정 편입하고 원 수량을 승계한다.
- 거절하면 Board 연결을 지우고 `UNASSIGNED`로 복귀시킨다.
- 후보가 없거나 판단 근거가 부족하면 질문·운영 `REVIEW` 없이 미제안 처리한다.
- AI 계획 적용 전 Backend가 최신 상태를 다시 검증한다.

## 10. 후속 결정 상태

- 상품 기능 보존은 identity 또는 승인된 방향성 coverage relation으로 정의했다.
- CPU 검색은 E5-small 기능문구 Top-10, 생존 0일 때 Top-20 확장으로 평가했다.
- 현재 배치 CLI는 활성 보드 catalog의 claim 포함관계 인덱스를 사용한다.
  E5는 PASSTHROUGH 선호 점수에 사용하며, 위 Top-K/관계 검색 평가와 별개다.
- 자연어 조건은 MUST/EXCLUDE hard gate, PREFER/PASSTHROUGH 순위,
  CONFLICT/NONE 비차단으로 정했다.
- relation 310개는 도메인 승인 전이며 운영 loader가 차단한다.

남은 연동·협의 사항은 다음과 같다.

- Part A 상품도감 기준 profile·taxonomy 공급과 DB 입력 catalog ID 일치 확인
- CPU E5 모델 파일 공급과 버전 관리
- 합의한 두 Backend 내부 API의 실제 연동과 Parameter Store 키 주입
- 재제안은 허용하되, 이미 거절한 동일 보드·상품을 제외할지와 거절 이력 조회 방식
- Seller Offer 매칭과 낙찰 방식

현재 배치에 필요한 외부 입력은 Part A 상품도감 기준 artifact와 PostgreSQL 수요·보드
snapshot이다. relation 도메인 승인과 오프라인 embedding artifact 발행은 별도 평가
경로의 후속 과제이며 현재 배치 실행의 선행 조건은 아니다.

## 11. 현재 구현과의 차이

- Part B에는 공유 PostgreSQL 조회, 원상품 계획 API, DB 재조회, 활성 보드
  profile join, 대체 제안 API까지 연결하는 CLI가 있다.
- 실패한 요청을 저장·재전송하지 않고 다음 정기 배치에서 DB 최신 상태로
  다시 계산한다. 상태 재검증과 DML은 Backend가 수행한다.
- 합의한 Backend 양쪽 API의 실제 구현, 상품도감 ID 일치, 인증 키 주입과
  시간별 스케줄 배포는 별도 실연동 검증이 필요하다.

따라서 현 상태를 대체상품 후보 제안 기능이 완성됐다고 표현하지 않는다.
