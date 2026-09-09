# 기존보드 대체 편입 v0.1

> 업무 범위와 상태 계약의 정본은
> `SUBSTITUTE_CANDIDATE_PROBLEM_DEFINITION.md`다. 이 문서는 다른 상품의 기존
> 활성 Board 한 건을 제안하는 구현 메모다. 대체상품 요청끼리 신규 Board를
> 만드는 경로는 기능 범위가 아니다.

## 범위

동일 catalog의 일반 기존보드 편입이 실패한 `UNASSIGNED` 수요 중
`is_substitutable=true`인 요청에 대해 다른 catalog의 기존 수요보드 한 건을
고른다. 이 단계는 판매자 매칭이 아니며 DB를 변경하지 않는다.

## 서비스 입력 조건 적용

| `effective_requirement_mode` | 동작 |
|---|---|
| `STRUCTURED` | MUST/EXCLUDE hard gate, PREFER 및 ANY_OF/MAX 순위 반영 |
| `SEMANTIC_TEXT` | 주입된 text scorer로 순위 반영 |
| `NONE` | 자연어 조건 비차단·무가점 |

`CONFLICT`는 서비스 입력 계약에서 `NONE`이므로 진단값만 남기고 편입을 막지 않는다.
대체상품 미동의는 자연어 내용과 무관하게 이 단계에 들어오지 않는다.

## 상품 대체가능성 AI 경계

기존보드 조건을 보기 전에 원 상품과 후보 상품이 실제로 대체 가능한지 먼저
판정한다. 운영 요청 경로에서 외부 LLM은 호출하지 않는다.

현재 `demand-clustering-batch`는 재조회된 활성 보드 catalog에 대해 동일 서비스
카테고리와 claim ID 포함관계를 인덱스로 확인한다. 모든 원상품 claim이 후보에
있는 identity-only 경로이며 승인 relation 확장은 연결하지 않았다. 이후 보드
가격·MUST·EXCLUDE를 검사하고 PREFER/PASSTHROUGH와 참가자 수로 순위를 정한다.
CPU E5는 PASSTHROUGH 자연어 선호 점수에만 사용하며 이때 지연 로드한다.

아래 E5 Top-K 방식은 **별도 오프라인 검색 평가·시뮬레이션 경로**다.

1. Backend/catalog가 허용해 전달한 상품의 기능근거 문구 embedding으로 동일
   서비스 카테고리 E5 Top-10을 검색한다.
2. 원 상품의 모든 주기능을 identity 또는 승인된 방향 relation이 덮는지 hard
   gate로 확인한다.
3. 생존 상품이 0이면 같은 E5 순위를 Top-20까지 확장하고 gate를 한 번 더 적용한다.
4. 생존 상품의 활성 Board만 조회한 뒤 가격·MUST·EXCLUDE를 적용하고,
   PREFER/PASSTHROUGH와 참가자 수로 최종 순위를 정한다.

원료 겹침과 제품 형태는 비교 feature로 남기되 현재 단계에서는 형태 차이만으로
탈락시키지 않는다. 정적 catalog embedding은 batch에서 사전 계산한다.

주기능 coverage는 방향성이 있다. 예를 들어 `눈 건강` 상품을 `눈 건강 +
항산화` 상품으로 대체하는 후보는 통과할 수 있지만 그 역방향은 항산화 기능을
잃으므로 탈락한다. 근거 필드가 없거나 profile이 승인되지 않은 경우 결과는
`INSUFFICIENT_EVIDENCE` 등 미제안 진단으로 처리하며, 실서비스에서는 REVIEW를 생성하지 않고 제안하지
않는다.

706개 MFDS profile의 전수 hard-gate graph를 기준으로 CPU 검색을 평가했다.
기능문구 E5 Top-10은 통과 후보가 있는 원상품 639/641을 회수했고, 생존 0일 때
Top-20으로 확장하면 641/641을 회수했다. 이는 hard-gate 후보 회수율이며 대체상품
정밀도나 사용자 만족도는 아니다. 외부 LLM API는 실서비스에서 호출하지 않는다.

고정 Top-1 641건의 독립 오프라인 품질평가에서는 614건이 두 평가자 모두
`PROPOSABLE`, 27건이 보수적 `ABSTAIN`이었다. relation 보조 29건 중 14건이
미제안이므로 승인 전 relation은 계속 hard fail한다. 상세 결과는
프로젝트 저장소 밖에서 관리하는 `PRODUCT_PROPOSAL_QUALITY_V1_RESULT.md`에 있다.

## 기존보드 후보 조건

- 원 catalog와 다른 catalog
- 동일 category와 taxonomy version
- 활성 `GB_GATHERING` 보드
- 후보 보드의 가격 상한이 원 수요의 희망 가격 상한 이하
- MUST 일치, EXCLUDE 불일치

PREFER 불일치는 후보 제거 사유가 아니다. 통과 후보는 구조화 선호, 텍스트
점수, 현재 확정 참여자 수, 보드 ID 순으로 결정론적으로 정렬한다.

## 상태 계약

선택기는 후보만 반환한다. 계획 생성 결과도 DML이 아닌 Backend handoff다.

```text
UNASSIGNED -> SUBSTITUTE_OFFERED: demand_board_id 선반영, 참가자 수 변화 없음
SUBSTITUTE_OFFERED -> ASSIGNED: 사용자 수락, 참가자 수 +1
SUBSTITUTE_OFFERED -> UNASSIGNED: 사용자 거절, demand_board_id 제거
SUBSTITUTE_OFFERED -> EXPIRED: 유효기간 만료까지 미응답
```

원 수요의 quantity는 수락 시 그대로 승계한다. 사용자에게는 후보 한 건만
노출하며 별도 REVIEW 질문이나 운영자 큐를 만들지 않는다.

## 입력 경계

기존 ERD 입력에는 catalog의 category, taxonomy version, facet profile이 없으므로
`SubstituteDemandInput.from_demand`와 `SubstituteBoardCandidateInput.from_board`가
Backend 행과 catalog profile의 명시적 join 지점이다.

최소 catalog profile은 다음 필드가 필요하다.

```json
{
  "catalogId": 201,
  "productName": "단백질 건강기능식품",
  "serviceCategoryId": "health-functional-food:protein",
  "taxonomyVersion": "v2.1",
  "recordType": "FINISHED_PRODUCT",
  "productForm": "분말",
  "functionalIngredients": ["유청단백"],
  "mainFunctionalityCodes": ["PROTEIN_SUPPLY"],
  "mainFunctionalityText": "단백질 공급",
  "intakeMethodText": "1일 1회",
  "profileStatus": "APPROVED",
  "facetValues": {
    "product_form": 1,
    "functional_ingredients": 3,
    "daily_frequency": 2
  },
  "semanticText": "딸기맛 단백질 분말"
}
```

문자 bigram cosine 구현은 scorer 주입 경계를 시험하는 lexical baseline이다.
운영 선호 점수기는 CPU E5이며, 기능 coverage는 현재 claim ID 포함관계로
판정한다. 오프라인 방향성 관계표를 CLI에 자동 적용하지 않는다.

## 남은 연동

- Part A 상품도감 기준 profile·taxonomy 공급과 DB 입력 catalog ID 일치 확인
- CPU E5 모델 파일 공급 및 버전 관리
- 합의한 두 Backend 내부 API의 실제 연동·상태 재검증 확인
- Backend `reject_history` 테이블 배포·거절 저장과 AI DB 계정의 SELECT 권한 확인
- Parameter Store 키 주입 및 시간별 배치 배포

relation 310개 승인과 오프라인 catalog embedding artifact 발행은 별도 평가 경로의
후속 과제이며 현재 claim 인덱스·CPU E5 배치 실행의 선행 조건은 아니다.

활성 보드 snapshot/profile join과 두 API 순차 호출은 구현되어 있다.
실패한 요청은 재전송하지 않고 다음 정기 배치에서 DB를 새로 조회한다. 사용 설정은
`../src/moongcheap_ai/demand_clustering/README.md`를 참고한다.

Backend와 합의한 거절 처리는 미만료 수요의 `UNASSIGNED` 복귀와 보드 연결 해제다.
참가자 수와 기존 보드는 유지한다. 신규 보드는 원상품 수요 최소 5건으로 생성하고,
대체상품 수요는 생성된 보드에 제안한 뒤 수락 시에만 참가자로 확정한다.

## 거절 이력에 따른 재제안 제외

2026-09-09 Backend 협의와 갱신된 ERD 이미지 기준으로 MVP부터
`reject_history`를 조회한다. 기존 ERD SQL에는 아직 이 테이블이 반영되지 않았다.

| 컬럼 | 타입 | AI 사용 |
| --- | --- | --- |
| `demand_id` | BIGINT | 거절한 수요 ID |
| `demand_board_id` | BIGINT | 그 수요가 거절한 보드 ID |
| `created_at` | TIMESTAMPTZ | 기록 시각; AI 후보 제외에 시간 제한을 두지 않음 |

AI는 현재 처리할 수요·활성 보드에 해당하는 이력을 한 번에 읽고, API 1 이후
DB 재조회에서도 이력을 다시 읽는다. 실행 시작 이후 생긴 거절도 반영하기 위해
`created_at <= plannedAt` 같은 과거 시각 제한을 적용하지 않는다.

`(demand_id, demand_board_id)`가 이력에 있으면 해당 수요의 대체 후보에서
임베딩 준비·순위 계산 전에 제외한다. 같은 상품의 다른 보드와 다른 수요의 추천은
이 이력으로 제외하지 않는다. 모든 후보가 제외되면 대체 제안을 생성하지 않으며,
해당 수요는 기존 유효기간 안에서 다음 배치의 원상품 경로부터 다시 검토한다.
Backend API 2 전송 직전 검증에서도 이미 거절한 조합을 차단한다.
운영 `ruleVersion`은 `substitute-admission-v2`다.

테이블 생성·이력 저장·수요 상태 변경은 Backend 책임이다. 사용자 거절 시
이력 저장과 `UNASSIGNED` 복귀·보드 연결 해제는 같은 트랜잭션에 반영해야 한다.
AI 조회 이후의 동시 상태 변경까지 처리하려면 Backend API 2에서도 거절 이력을
재검증해야 하며, 실제 연동에서 확인한다. AI는 이력을 쓰거나 삭제하지 않는다.
이력 조회 오류는 실행 실패로 처리하며, 빈 이력으로 대체해 재추천하지 않는다.

## 5,000건 시간 배치 검증

상품 적격성은 상위 입력으로 간주하고 MFDS 기능근거와 고정 CPU E5 검색 결과만
사용하는 최종 시뮬레이션에서는 1시간 배치로 보드 8개, 직접 편입 40건,
identity-only 대체 제안 112건이
생성됐다. 미승인 relation 보조 제안과 런타임 REVIEW는 모두 0건이다. Part C용
snapshot은 제안 대기 112건을 확정 참가자 수에 포함하지 않으며 상품명이나
운영 적격성 판정을 전달하지 않는다. 상세 실행 결과와 전달 산출물은 프로젝트
저장소 밖에서 관리한다.
