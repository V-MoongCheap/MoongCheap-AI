#!/usr/bin/env python3
"""영역 2(판매자 수요 분석) 고정 평가셋 100건을 결정적으로 생성한다.

근거 문서 — 「AI 평가 데이터셋 및 평가 지표 정의서」 v0.3
  · 16절 「Seller Analysis 평가 Dataset」 — 총 100건, 입력 Schema, Ground Truth Field, 산식
  · 17절 「Seller Analysis Scenario 구성」 — Scenario별 건수, primary_scenario / scenario_tags,
    Boundary / Invalid Input 유형
  · 22절 「평가 Dataset 파일 구성」 — `data/evaluation/seller_analysis/` 아래 파일 구성
  · 25절 「Seller Analysis 파일 분리」 — 입력/정답 파일명과 Field
  · 2절 「평가 데이터 관리 원칙」 — 모델 입력과 정답을 분리한다

⛔ **정답을 구현으로 계산하지 않는다.**
   `moongcheap_ai.seller_analysis.bid_guide` 를 부르지 않고, 16절이 적은 산식을 이 파일에서 다시 세운다.
   구현으로 정답을 만들면 구현이 틀려도 평가가 100%로 나오는 순환 논증이 된다.

⛔ **반올림 정책에 의존하지 않게 만든다.**
   문서는 비율의 자리수·반올림 방식을 정하지 않았고, 18.1절은 "사전에 정한 허용 오차"라고만 적는다.
   그래서 모든 정상 Case 를 **소수 4자리에서 정확히 떨어지는 입력**으로만 구성하고, 그 사실을
   생성 시점에 검사한다. 반올림 방식이 무엇으로 정해지든 정답이 흔들리지 않는다.

실행:
    python -m scripts.evaluation.build_seller_analysis_eval_set
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

# src/moongcheap_ai/seller_analysis/evaluation/eval_set.py → 저장소 루트
REPO_ROOT = Path(__file__).resolve().parents[4]
OUTPUT_DIR = REPO_ROOT / "data" / "evaluation" / "seller_analysis"
EVAL_CSV = OUTPUT_DIR / "seller_analysis_eval_v1.csv"
GROUND_TRUTH_CSV = OUTPUT_DIR / "seller_analysis_ground_truth_v1.csv"
README = OUTPUT_DIR / "README.md"

DATASET_VERSION = "seller_analysis_eval_v1"

# 25절 「Seller Analysis 파일 분리」 의 Field. 순서까지 문서를 따른다.
EVAL_FIELDS = [
    "eval_id",
    "participant_count",
    "total_demand_quantity",
    "minimum_success_quantity",
    "maximum_supply_quantity",
    # 25절이 허용한 예외 — "Invalid Input Scenario에서 추가하는 비정상 Field는 별도의
    # Fixture 또는 JSON Column으로 관리할 수 있다". 정상 Case 에서는 빈 값이다.
    "invalid_input_overrides",
]
GROUND_TRUTH_FIELDS = [
    "eval_id",
    "expected_moq_attainment_ratio",
    "expected_supply_coverage_ratio",
    "expected_moq_status",
    "expected_supply_status",
    "expected_request_result",
    "primary_scenario",
    "scenario_tags",
]

# 17절의 Scenario 구성표. 합계 100.
SCENARIO_QUOTA = {
    "MOQ_MET": 20,
    "MOQ_NOT_MET": 15,
    "MOQ_EXACT": 10,
    "SUPPLY_SUFFICIENT": 10,
    "SUPPLY_INSUFFICIENT": 15,
    "LOW_DEMAND": 10,
    "HIGH_DEMAND": 10,
    "BOUNDARY_OR_INVALID": 10,
}

# 최소 참가자 5명 — 「수요 클러스터링 작업 설명서」 Part I 「신규 원상품 보드 생성」 ·
# 「AI–Backend 수요보드 생성·편입 계획 연동 API 기능 요구 명세서」 5.3절.
MIN_PARTICIPANTS = 5

# ⚠️ 아래 둘은 **이 생성기가 정한 경계다.** 문서는 "수요량 매우 적음 / 매우 큼"이라고만 적고
# 수치 기준을 주지 않았다. README 에 확인 요청으로 남긴다.
LOW_DEMAND_MAX = 10
HIGH_DEMAND_MIN = 10_000

RATIO_PLACES = 4


class GeneratorError(RuntimeError):
    """생성 시점 불변조건 위반. 조용히 통과시키지 않는다."""


# 공급 충족률 상한. 「AI API Contract」 5절 「Seller Analysis API」 의 예시가
# `supply_coverage_ratio: 1.0` 과 근거 문장 *"약 1.15이며, 계산 정책의 상한 1.0을
# 적용했습니다"* 를 함께 적는다.
#
# ⛔ 이 값을 `bid_guide` 에서 import 하지 않는다. 정답을 구현에서 가져오면 채점이
#    순환한다. 계약 문장을 읽고 여기서 따로 세운다.
#
# ⚠️ 16절의 예시(`150 / 120 = 1.25`)는 상한을 적용하지 않는다. 그 예시와는 값이
#    어긋나며, 게시된 계약(5절) 쪽을 따랐다.
SUPPLY_COVERAGE_CAP = 1.0


def _exact_ratio(numerator: int, denominator: int) -> float:
    """소수 4자리에서 **정확히** 떨어지는 비율만 만든다.

    떨어지지 않으면 반올림 방식에 따라 정답이 달라지므로 거절한다.
    이 검사가 "정답이 반올림 정책에 의존하지 않는다"는 성질을 강제한다.
    """
    scaled = numerator * 10**RATIO_PLACES
    if scaled % denominator != 0:
        raise GeneratorError(
            f"{numerator}/{denominator} 는 소수 {RATIO_PLACES}자리에서 떨어지지 않는다"
        )
    return scaled // denominator / 10**RATIO_PLACES


def _valid_case(
    *,
    participant_count: int,
    total_demand_quantity: int,
    minimum_success_quantity: int,
    maximum_supply_quantity: int,
    primary_scenario: str,
    extra_tags: tuple[str, ...] = (),
) -> dict[str, Any]:
    """정상 처리 Case 하나. 정답은 16절 산식으로 여기서 직접 계산한다."""
    if participant_count < MIN_PARTICIPANTS:
        raise GeneratorError(f"참가자 {participant_count}명 — 최소 참가 {MIN_PARTICIPANTS}명 미만")
    if participant_count > total_demand_quantity:
        # 한 참가자는 최소 1개를 요청하므로 인원이 수량을 넘을 수 없다.
        raise GeneratorError(
            f"참가자 {participant_count}명 > 총수요 {total_demand_quantity}개"
        )

    # 판정은 정수 비교로만 한다 (18.3절 — 표시용 Ratio 반올림 값이 아니라 원본 정수값 기준).
    moq_met = total_demand_quantity >= minimum_success_quantity
    supply_met = maximum_supply_quantity >= total_demand_quantity

    tags = {primary_scenario, *extra_tags}
    tags.add("MOQ_MET" if moq_met else "MOQ_NOT_MET")
    tags.add("SUPPLY_SUFFICIENT" if supply_met else "SUPPLY_INSUFFICIENT")
    if total_demand_quantity == minimum_success_quantity:
        tags.add("MOQ_EXACT")
    if total_demand_quantity <= LOW_DEMAND_MAX:
        tags.add("LOW_DEMAND")
    if total_demand_quantity >= HIGH_DEMAND_MIN:
        tags.add("HIGH_DEMAND")
    if participant_count == MIN_PARTICIPANTS:
        tags.add("MIN_PARTICIPANTS")

    return {
        "participant_count": participant_count,
        "total_demand_quantity": total_demand_quantity,
        "minimum_success_quantity": minimum_success_quantity,
        "maximum_supply_quantity": maximum_supply_quantity,
        "invalid_input_overrides": "",
        "expected_moq_attainment_ratio": _exact_ratio(
            total_demand_quantity, minimum_success_quantity
        ),
        "expected_supply_coverage_ratio": min(
            _exact_ratio(maximum_supply_quantity, total_demand_quantity),
            SUPPLY_COVERAGE_CAP,
        ),
        "expected_moq_status": "MOQ_MET" if moq_met else "MOQ_NOT_MET",
        "expected_supply_status": "SUPPLY_SUFFICIENT" if supply_met else "SUPPLY_INSUFFICIENT",
        "expected_request_result": "SUCCESS",
        "primary_scenario": primary_scenario,
        "scenario_tags": sorted(tags),
    }


def _invalid_case(*, overrides: dict[str, Any], invalid_kind: str) -> dict[str, Any]:
    """거절되어야 하는 Case. 기준 입력은 정상값이고 overrides 가 계약을 깬다.

    비율·상태는 **비워 둔다.** 계산하지 않는 것이 정답이므로 값을 적으면 안 된다
    (18.1절 — Invalid Input Case 는 Numeric Accuracy 분모에서 제외한다).
    """
    return {
        "participant_count": 13,
        "total_demand_quantity": 130,
        "minimum_success_quantity": 100,
        "maximum_supply_quantity": 150,
        "invalid_input_overrides": json.dumps(overrides, ensure_ascii=False, sort_keys=True),
        "expected_moq_attainment_ratio": "",
        "expected_supply_coverage_ratio": "",
        "expected_moq_status": "",
        "expected_supply_status": "",
        "expected_request_result": "REJECTED",
        "primary_scenario": "BOUNDARY_OR_INVALID",
        "scenario_tags": sorted({"BOUNDARY_OR_INVALID", "INVALID_INPUT", invalid_kind}),
    }


def _supply_for(total: int, k: int) -> int:
    """공급량을 세 갈래로 돌린다 — 전량 공급 / 초과 공급 / 부족(0.8)."""
    if k % 3 == 0:
        return total
    if k % 3 == 1:
        return total * 2
    return total * 4 // 5  # 총수요가 5의 배수일 때만 정확하다. _exact_ratio 가 확인한다.


def build_cases() -> list[dict[str, Any]]:
    """17절 구성표대로 100건을 만든다. 난수를 쓰지 않으므로 항상 같은 결과다."""
    cases: list[dict[str, Any]] = []

    # ① 정상 MOQ 충족 20건 — 최소 성사 수량 100 고정, 총수요를 105~200 으로 올린다.
    for k in range(1, 21):
        total = 100 + 5 * k
        cases.append(
            _valid_case(
                participant_count=MIN_PARTICIPANTS + k,
                total_demand_quantity=total,
                minimum_success_quantity=100,
                maximum_supply_quantity=_supply_for(total, k),
                primary_scenario="MOQ_MET",
            )
        )

    # ② MOQ 미달 15건 — 최소 성사 수량 200 고정, 총수요를 195~125 로 낮춘다.
    for k in range(1, 16):
        total = 200 - 5 * k
        cases.append(
            _valid_case(
                participant_count=MIN_PARTICIPANTS + k,
                total_demand_quantity=total,
                minimum_success_quantity=200,
                maximum_supply_quantity=_supply_for(total, k),
                primary_scenario="MOQ_NOT_MET",
            )
        )

    # ③ MOQ 정확히 충족 10건 — 총수요 == 최소 성사 수량. 비율이 정확히 1.0 인 경계다.
    for k in range(1, 11):
        total = 50 * k
        cases.append(
            _valid_case(
                participant_count=MIN_PARTICIPANTS + k,
                total_demand_quantity=total,
                minimum_success_quantity=total,
                maximum_supply_quantity=total if k % 2 == 0 else total * 4 // 5,
                primary_scenario="MOQ_EXACT",
            )
        )

    # ④ 공급량 충분 10건 — 공급이 총수요의 1.5 배. MOQ 는 충족/미달을 번갈아 둔다.
    for k in range(1, 11):
        total = 100 + 10 * k
        cases.append(
            _valid_case(
                participant_count=MIN_PARTICIPANTS + k,
                total_demand_quantity=total,
                minimum_success_quantity=100 if k % 2 else total * 2,
                maximum_supply_quantity=total * 3 // 2,
                primary_scenario="SUPPLY_SUFFICIENT",
            )
        )

    # ⑤ 공급량 부족 15건 — 공급이 총수요의 0.7 배.
    for k in range(1, 16):
        total = 200 + 10 * k
        cases.append(
            _valid_case(
                participant_count=MIN_PARTICIPANTS + k,
                total_demand_quantity=total,
                minimum_success_quantity=100 if k % 2 else total * 2,
                maximum_supply_quantity=total * 7 // 10,
                primary_scenario="SUPPLY_INSUFFICIENT",
            )
        )

    # ⑥ 수요량 매우 적음 10건 — 최소 참가 5명을 채운 가장 작은 보드들.
    #    ⛔ 참가자 수는 5명 이상이면서 총수요를 넘지 않아야 한다.
    low_demand = [
        (5, 5, 10, 5), (5, 6, 10, 6), (5, 7, 10, 14), (5, 8, 10, 4), (5, 9, 10, 9),
        (5, 10, 10, 5), (6, 6, 25, 12), (7, 8, 50, 8), (8, 10, 20, 4), (10, 10, 25, 20),
    ]
    for participants, total, moq, supply in low_demand:
        cases.append(
            _valid_case(
                participant_count=participants,
                total_demand_quantity=total,
                minimum_success_quantity=moq,
                maximum_supply_quantity=supply,
                primary_scenario="LOW_DEMAND",
            )
        )

    # ⑦ 수요량 매우 큼 10건 — 만 단위. 큰 수에서 자리수가 깨지지 않는지 본다.
    for k in range(1, 11):
        total = 10_000 * k
        cases.append(
            _valid_case(
                participant_count=total // 10,
                total_demand_quantity=total,
                minimum_success_quantity=10_000,
                maximum_supply_quantity=_supply_for(total, k),
                primary_scenario="HIGH_DEMAND",
            )
        )

    # ⑧ Boundary / Invalid Input 10건 — 17절이 열거한 유형을 하나씩 덮는다.
    #    경계값 5건(정상 처리) + 계약 위반 5건(거절).
    boundaries = [
        # 모든 값이 최소인 보드. 참가 5명·수요 5개.
        (5, 5, 5, 5),
        # 총수요와 최소 성사 수량이 같은데 공급이 1개 모자란다.
        (100, 1000, 1000, 999),
        # 총수요가 최소 성사 수량보다 1개 모자란다. 반올림하면 1.00 으로 보이는 자리다.
        (99, 999, 1000, 999),
        # 최소 성사 수량이 1. 비율이 극단으로 커진다.
        (5, 10_000, 1, 10_000),
        # 가장 작은 보드에서 미달과 부족이 함께 난다.
        (5, 5, 10, 4),
    ]
    for participants, total, moq, supply in boundaries:
        cases.append(
            _valid_case(
                participant_count=participants,
                total_demand_quantity=total,
                minimum_success_quantity=moq,
                maximum_supply_quantity=supply,
                primary_scenario="BOUNDARY_OR_INVALID",
                extra_tags=("BOUNDARY",),
            )
        )

    # 17절 「Boundary / Invalid Input에는 다음과 같은 Case를 포함한다」 의 다섯 유형.
    cases.append(_invalid_case(
        overrides={"set": {"total_demand_quantity": 0}},
        invalid_kind="NON_POSITIVE_QUANTITY",
    ))
    cases.append(_invalid_case(
        overrides={"set": {"total_demand_quantity": "130"}},
        invalid_kind="WRONG_DATA_TYPE",
    ))
    cases.append(_invalid_case(
        overrides={"remove": ["minimum_success_quantity"]},
        invalid_kind="MISSING_REQUIRED_FIELD",
    ))
    cases.append(_invalid_case(
        overrides={"set": {"undeclared_field": "x"}},
        invalid_kind="UNDECLARED_EXTRA_FIELD",
    ))
    cases.append(_invalid_case(
        overrides={"set": {"member_ids": ["MEMBER_0001", "MEMBER_0002"]}},
        invalid_kind="PII_FIELD",
    ))

    for index, case in enumerate(cases, start=1):
        case["eval_id"] = f"SELLER_EVAL_{index:03d}"

    _check_quota(cases)
    return cases


def _check_quota(cases: list[dict[str, Any]]) -> None:
    """17절 구성표와 실제 생성 결과를 대조한다. 어긋나면 파일을 쓰지 않는다."""
    if len(cases) != sum(SCENARIO_QUOTA.values()):
        raise GeneratorError(f"총 {len(cases)}건 — 100건이 아니다")
    counted: dict[str, int] = {}
    for case in cases:
        counted[case["primary_scenario"]] = counted.get(case["primary_scenario"], 0) + 1
    if counted != SCENARIO_QUOTA:
        raise GeneratorError(f"Scenario 구성이 17절과 다르다: {counted}")
    ids = [case["eval_id"] for case in cases]
    if len(set(ids)) != len(ids):
        raise GeneratorError("eval_id 가 중복됐다")


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row[field] for field in fields})


README_TEXT = """# 영역 2 — 판매자 수요 분석 고정 평가셋 v1

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
"""


def main() -> None:
    cases = build_cases()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    eval_rows = [
        {**case, "scenario_tags": "|".join(case["scenario_tags"])} for case in cases
    ]
    _write_csv(EVAL_CSV, EVAL_FIELDS, eval_rows)
    _write_csv(GROUND_TRUTH_CSV, GROUND_TRUTH_FIELDS, eval_rows)
    README.write_text(README_TEXT, encoding="utf-8")

    valid = sum(1 for case in cases if case["expected_request_result"] == "SUCCESS")
    print(f"{DATASET_VERSION}: {len(cases)}건 (정상 {valid} / 거절 {len(cases) - valid})")
    print(f"  입력  {EVAL_CSV.relative_to(REPO_ROOT)}")
    print(f"  정답  {GROUND_TRUTH_CSV.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
