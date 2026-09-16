# 영역 2 — 판매자 수요 분석 고정 평가셋 v1

`moongcheap_ai.seller_analysis.evaluation.eval_set` 가 생성한다.
난수를 쓰지 않으므로 다시 돌리면 같은 파일이 나온다. **손으로 고치지 않고 생성기를 고친다.**

## 근거

「AI 평가 데이터셋 및 평가 지표 정의서」 v0.3 의
16절 「Seller Analysis 평가 Dataset」 · 17절 「Seller Analysis Scenario 구성」 ·
22절 「평가 Dataset 파일 구성」 · 25절 「Seller Analysis 파일 분리」.

## 파일

| 파일 | 무엇 |
|---|---|
| `seller_analysis_eval_v1.csv` | 모델 입력. 정답이 들어 있지 않다 |
| `seller_analysis_ground_truth_v1.csv` | 정답. 평가 단계에서만 쓴다 |

2절 「평가 데이터 관리 원칙」 에 따라 입력과 정답을 나눴다. 평가 대상에게는 입력 파일만 전달한다.

`invalid_input_overrides` 는 25절이 허용한 JSON Column 이다
(*"Invalid Input Scenario에서 추가하는 비정상 Field는 별도의 Fixture 또는 JSON Column으로
관리할 수 있다"*). `{"set": {...}}` 는 값을 덮어쓰고 `{"remove": [...]}` 는 필드를 지운다.
정상 Case 에서는 빈 값이다.

## 구성 (17절)

| Primary Scenario | 건수 |
|---|---|
| 정상 MOQ 충족 `MOQ_MET` | 20 |
| MOQ 미달 `MOQ_NOT_MET` | 15 |
| MOQ 정확히 충족 `MOQ_EXACT` | 10 |
| 공급량 충분 `SUPPLY_SUFFICIENT` | 10 |
| 공급량 부족 `SUPPLY_INSUFFICIENT` | 15 |
| 수요량 매우 적음 `LOW_DEMAND` | 10 |
| 수요량 매우 큼 `HIGH_DEMAND` | 10 |
| Boundary / Invalid Input `BOUNDARY_OR_INVALID` | 10 |
| 합계 | **100** |

하나의 Case 가 여러 조건에 해당하므로 `primary_scenario` 외에 `scenario_tags` 를 복수로 적는다.

Boundary / Invalid 10건은 경계값 5건(정상 처리)과 계약 위반 5건(거절)이다.
위반 5건은 17절이 열거한 유형을 하나씩 덮는다 — 0 이하의 수량 · 잘못된 Data Type ·
필수 Field 누락 · 허용되지 않은 추가 Field · 개인 단위 식별 Field 포함.

## 이 평가셋이 지키는 것

- **정답을 구현으로 만들지 않았다.** 생성기는 `moongcheap_ai.seller_analysis.bid_guide` 를 부르지 않고
  16절의 산식을 다시 세운다. 구현으로 정답을 만들면 구현이 틀려도 100% 가 나온다.
- **정답이 반올림 정책에 기대지 않는다.** 모든 정상 Case 는 비율이 소수 4자리에서 정확히
  떨어지는 입력으로만 구성했고, 생성 시점에 검사한다.
- **상태 판정은 정수 비교로 계산했다** (18.3절).
- **참가자 수는 5명 이상이고 총수요를 넘지 않는다.** 최소 참가 5명은
  「수요 클러스터링 작업 설명서」 Part I 과 「AI–Backend 수요보드 생성·편입 계획 연동 API
  기능 요구 명세서」 5.3절 이 정한 값이다.

## ⚠️ 확인이 필요한 것

| # | 항목 | 지금 어떻게 했나 |
|---|---|---|
| 1 | **`supply_coverage_ratio` 의 상한 1.0** | **상한을 적용한다.** 게시된 「AI API Contract」 5절이 `1.0` 과 근거 문장 *"계산 정책의 상한 1.0을 적용했습니다"* 를 함께 적기 때문이다. ⚠️ 16절의 예시(`150 / 120 = 1.25`)와 「AI 통합 영역 최종 선정 및 BE/FE 통합 인터페이스 명세」 3.5절(`1.15`)은 상한이 없어 **값이 어긋난다.** 파트 확정이 필요하다 |
| 2 | **거절 Case 의 `expected_request_result` 값** | `REJECTED` 로 적었다. 16절의 예시는 정상 Case 의 `SUCCESS` 만 보여 준다. 거절 쪽 값의 표기를 확인해야 한다 |
| 3 | **「수요량 매우 적음 / 매우 큼」 의 수치 기준** | 각각 총수요 10 이하 · 10,000 이상으로 잡았다. 문서에 기준이 없다 |
| 4 | **비율의 자리수와 반올림 방식** | 정답이 자리수에 의존하지 않도록 구성했으므로 이 평가셋은 영향받지 않는다. 다만 **응답 필드의 자리수 자체는 계약에 없다** |
| 5 | **Field 명** | 16절은 *"실제 API Response의 최종 Field명은 Backend / AI API Contract와 동일하게 맞춘다"* 고 한다. 현재 응답은 `metrics` 중첩이고 이 평가셋은 25절의 평면 Field 명을 쓴다. 평가 실행기가 대응시킨다 |
