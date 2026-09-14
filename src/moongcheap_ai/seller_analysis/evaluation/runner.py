#!/usr/bin/env python3
"""영역 2 고정 평가셋으로 구현을 채점하고 리포트를 남긴다.

「AI 평가 데이터셋 및 평가 지표 정의서」 v0.3
  · 18절 「Seller Analysis 평가 지표」 — Numeric / MOQ Status / Supply Status /
    Evidence Consistency / Invalid Input Rejection
  · 20절 「개인정보 안전성 평가」 — PII Input Rejection Accuracy · PII Leakage Rate
  · 21절 「Seller Analysis 목표 지표」 — 목표치
  · 26절 「평가 실행 방식」 — *"동일한 Evaluation Dataset으로 반복 평가한다"*
  · 27절 「평가 결과 기록」 — Experiment 마다 기록을 남긴다

⛔ 정답은 `build_seller_analysis_eval_set.py` 가 16절 산식으로 **따로** 세운 값이다.
   이 실행기는 그 정답과 구현 결과를 대조만 한다. 정답을 구현으로 만들지 않는다.

⛔ 상태(`moq_status`·`supply_status`)는 응답에 없다. 「AI API Contract」 5절이 `metrics` 를
   네 필드로 정하기 때문이다. **비율에서 도출**해 채점한다 — `ratio >= 1.0` 이면 충족.

실행:
    python -m scripts.evaluation.run_seller_analysis_eval
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# src/moongcheap_ai/seller_analysis/evaluation/runner.py → 저장소 루트
REPO_ROOT = Path(__file__).resolve().parents[4]

from ..bid_guide import (
    METRICS_VERSION,
    ContractViolation,
    VersionMismatch,
    handle_bid_guide,
)

DATASET_DIR = REPO_ROOT / "data" / "evaluation" / "seller_analysis"
EVAL_CSV = DATASET_DIR / "seller_analysis_eval_v1.csv"
GROUND_TRUTH_CSV = DATASET_DIR / "seller_analysis_ground_truth_v1.csv"
RESPONSE_SCHEMA = REPO_ROOT / "docs" / "contracts" / "seller_bid_guide_response_v01.schema.json"
# 실행 결과는 재생성 가능하므로 저장소에 담지 않는다. `data/reports/*` 는 gitignore 대상이다.
OUTPUT_ROOT = REPO_ROOT / "data" / "reports" / "seller_analysis_eval"

DATASET_VERSION = "seller_analysis_eval_v1"
# 계산에 쓰이지 않는 참조값. 기대값을 만들 때도 이 상수를 쓴다.
EVAL_CONTEXT_VERSION = "eval-context-v1"

# 21절 「Seller Analysis 목표 지표」.
TARGETS = {
    "numeric_accuracy": 1.0,
    "moq_status_accuracy": 1.0,
    "supply_status_accuracy": 1.0,
    "evidence_consistency": 1.0,
    "invalid_input_rejection_accuracy": 1.0,
    "pii_input_rejection_accuracy": 1.0,
    "response_schema_validation_success": 0.99,
}
# 0% 가 목표인 지표. 위와 방향이 반대라 따로 둔다.
ZERO_TARGETS = {"pii_leakage_rate": 0.0}

# 「AI 평가 데이터셋 및 평가 지표 정의서」 18.1절 「Numeric Accuracy」 —
# *"부동소수점 값은 **사전에 정한 허용 오차** 내에서 비교한다"*.
# 그 문서는 정하라고만 하고 값을 주지 않았다. **이 값이 그 「사전에 정한」 값이다.**
#
# ⛔ 자리수(1e-4)를 허용 오차로 쓰지 않는다. 계약이 비율을 소수 4자리로 두는데
#    (「AI 파트 → 백엔드 스키마 명세(초안)」 2절의 `numeric(5,4)`) 마지막 자리를
#    통째로 덮으면 그 자리수 명세가 무의미해진다. 허용 오차는 **부동소수점 표현 오차만**
#    흡수하면 된다 — 양쪽이 같은 자리수로 반올림하므로 그 이상은 실제 계산 오류다.
NUMERIC_TOLERANCE = 1e-9

# 근거 문장을 만들 때 쓰는 자리수·상한. ⛔ `bid_guide` 에서 import 하지 않는다.
# 계약(「AI API Contract」 5절 「Seller Analysis API」)과 「AI 파트 → 백엔드 스키마
# 명세(초안)」 2절의 `numeric(5,4)` 에서 **다시 적은** 값이다. 구현이 이 값을 바꾸면
# 기대 문장과 어긋나 평가가 실패해야 한다 — 같이 따라 움직이면 검사가 아니다.
RATIO_PRECISION = 4
DISPLAY_PRECISION = 2
SUPPLY_COVERAGE_CAP = 1.0

# 판단 사유 문장. (moq_met, supply_met) → 문장.
#
# ⛔ 여기서 「독립」의 의미를 분명히 해 둔다. 「AI 통합 영역 최종 선정 및 BE/FE 통합
#    인터페이스 명세」 3.6절 「FE 화면 반영」 이 준 것은 예시 **한 문장**
#    (*"현재 총수요는 판매자의 최소 성사 수량을 충족하고 있습니다"*)뿐이고, 네 조합으로
#    펼친 것은 **우리 파트가 만든 템플릿**이다. 따라서 이 표는 비율·상태처럼 문서에서
#    유도한 정답이 아니라, **고정된 템플릿을 그대로 지키는지 보는 기준**이다.
#    그래도 필요하다 — 이 필드는 계약상 AI 가 채워 Backend 의 REASON 에 그대로 저장되고,
#    「AI 아키텍처 및 안전성 정책 초안」 24절 「Unsupported Claim 제한」 이 금지한
#    *"이 가격이면 반드시 판매에 성공합니다"* 류가 들어가도 2026-09-11 이전에는
#    95/95 가 나왔다. 아무도 보지 않는 필드였다.
REASON_TEMPLATES = {
    (True, True): (
        "현재 총수요는 판매자의 최소 성사 수량을 충족하고 있으며, "
        "공급 가능 수량이 총수요를 충당합니다."
    ),
    (True, False): (
        "현재 총수요는 판매자의 최소 성사 수량을 충족하고 있으나, "
        "공급 가능 수량이 총수요에 미치지 못합니다."
    ),
    (False, True): (
        "현재 총수요는 판매자의 최소 성사 수량에 미치지 못합니다. "
        "공급 가능 수량은 현재 총수요를 충당합니다."
    ),
    (False, False): (
        "현재 총수요는 판매자의 최소 성사 수량에 미치지 못하며, "
        "공급 가능 수량도 총수요에 미치지 못합니다."
    ),
}

# 성공 Case 하나가 채워야 할 지표들. 어느 한 곳에서 빠지면 그 지표만 분모가 줄어
# 정확도가 부풀려지므로, 실패 경로에서도 이 목록을 그대로 쓴다.
SCORED_ON_SUCCESS = (
    "numeric_accuracy",
    "moq_status_accuracy",
    "supply_status_accuracy",
    "evidence_consistency",
    "response_schema_validation_success",
)

OPPOSITE_STATUS = {
    "MOQ_MET": "MOQ_NOT_MET",
    "MOQ_NOT_MET": "MOQ_MET",
    "SUPPLY_SUFFICIENT": "SUPPLY_INSUFFICIENT",
    "SUPPLY_INSUFFICIENT": "SUPPLY_SUFFICIENT",
}

# 응답에 절대 실려서는 안 되는 개인 단위 흔적.
PII_MARKERS = ("member_id", "user_id", "buyer_id", "participant_id", "MEMBER_", "contact")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def as_request(row: dict[str, str]) -> Any:
    """평가 행을 계약 요청으로 바꾼다.

    16절의 입력 Schema 는 계산에 쓰이는 다섯 값만 정의한다. 나머지 계약 필드는 계산에
    영향을 주지 않는 참조·버전 값이므로 고정값으로 채운다.
    """
    payload: dict[str, Any] = {
        "request_id": row["eval_id"],
        "input_context_version": EVAL_CONTEXT_VERSION,
        # 계산에 쓰이지 않는 참조값이다. 정수 계약이므로 eval_id 의 일련번호를 쓴다.
        "cluster_ref": int(row["eval_id"].rsplit("_", 1)[-1]),
        "product_ref": int(row["eval_id"].rsplit("_", 1)[-1]),
        "calculation_policy_version": METRICS_VERSION,
    }
    for field in (
        "participant_count",
        "total_demand_quantity",
        "minimum_success_quantity",
        "maximum_supply_quantity",
    ):
        payload[field] = int(row[field])

    overrides = json.loads(row["invalid_input_overrides"] or "{}")
    for field in overrides.get("remove", []):
        payload.pop(field, None)
    payload.update(overrides.get("set", {}))
    return payload


def derive_status(metrics: dict[str, Any]) -> tuple[str, str]:
    """상태를 비율에서 되살린다. `_ratio` 의 1.0 경계 가드가 이 동치를 지킨다."""
    moq = "MOQ_MET" if metrics["moq_attainment_ratio"] >= 1.0 else "MOQ_NOT_MET"
    supply = (
        "SUPPLY_SUFFICIENT"
        if metrics["supply_coverage_ratio"] >= 1.0
        else "SUPPLY_INSUFFICIENT"
    )
    return moq, supply


def _display(ratio: float, *, met: bool) -> str:
    """비율을 사람이 읽는 자리수로 줄인다. 표시값이 판정을 뒤집지 못하게 막는다.

    명세서 5.4절 「AI 처리 규칙」 — 판정은 반올림 전 정수 비교로 끝난다. 999/1000 을
    소수 둘째 자리에서 반올림하면 `1.00` 이 되어 미달 판정과 같은 문장 안에서 숫자가
    어긋난다. 경계를 넘길 값은 경계 바로 앞으로 되돌린다.
    """
    text = f"{ratio:.{DISPLAY_PRECISION}f}"
    if met and float(text) < 1.0:
        return f"{1.0:.{DISPLAY_PRECISION}f}"
    if not met and float(text) >= 1.0:
        return f"{1.0 - 10 ** -DISPLAY_PRECISION:.{DISPLAY_PRECISION}f}"
    return text


def expected_evidence(row: dict[str, str], truth: dict[str, str]) -> list[str]:
    r"""평가셋과 정답만으로 근거 세 문장을 **글자 그대로** 만든다.

    ⛔ 예전에는 `\d+` 정규식으로 「형태」만 봤다. **그것으로는 부족했다** — 문장 속
       수량을 `999999` 로 바꿔도 형태는 그대로라 `evidence_consistency` 가 100% 로
       나왔다. 계약이 `calculation_evidence` 를 *"템플릿으로만 만들며 생성 모델이
       문장을 새로 쓰지 않는다"* 고 정하므로, 기대 문장을 여기서 완성해 **동일성**으로
       대조한다. 숫자 한 자리만 달라도 실패한다.

    ⛔ 수량은 **평가 입력 CSV**, 비율은 **정답 CSV** 에서 온다. 구현이나 그 응답에서
       가져오지 않는다 — 채점 기준을 채점 대상이 만들면 검사가 아니다.
    """
    demand = int(row["total_demand_quantity"])
    moq = int(row["minimum_success_quantity"])
    supply = int(row["maximum_supply_quantity"])
    moq_met = truth["expected_moq_status"] == "MOQ_MET"
    supply_met = truth["expected_supply_status"] == "SUPPLY_SUFFICIENT"

    # ⛔ 상한 분기를 `supply > demand` 로 두면 **올바른 구현을 실패로 찍는다.**
    #    총수요 100000·공급 100001 에서 정수로는 초과지만 비율은 `round(1.00001, 4)`
    #    = `1.0` 이라 상한이 걸리지 않는다. 2026-09-11 재현에서 구현은 상한 문장을
    #    쓰지 않았는데 평가기만 상한 문장을 기대했다. 판정은 **비율 자리수로** 한다.
    raw = round(supply / demand, RATIO_PRECISION)
    if raw > SUPPLY_COVERAGE_CAP:
        # 상한을 적용한 경우. 정답 CSV 는 상한을 **건 뒤**의 1.0 만 갖고 있어
        # 상한 전 값은 여기서 16절 산식으로 다시 낸다. 입력만 쓰므로 순환은 아니다.
        supply_line = (
            f"판매자 최대 공급 가능 수량 {supply}개를 총수요 {demand}개로 나눈 결과는 "
            f"약 {_display(raw, met=True)}이며, "
            f"계산 정책의 상한 {SUPPLY_COVERAGE_CAP:.1f}을 적용했습니다."
        )
    else:
        supply_line = (
            f"판매자 최대 공급 가능 수량 {supply}개를 총수요 {demand}개로 나눈 결과는 "
            f"{_display(float(truth['expected_supply_coverage_ratio']), met=supply_met)}입니다."
        )

    return [
        f"총수요 {demand}개를 최소 성사 수량 {moq}개로 나눈 결과는 "
        f"{_display(float(truth['expected_moq_attainment_ratio']), met=moq_met)}입니다.",
        supply_line,
        f"상태 판정은 표시용 반올림 값이 아니라 원본 정수 비교로 했습니다: "
        f"{demand} vs {moq} → {truth['expected_moq_status']}, "
        f"{supply} vs {demand} → {truth['expected_supply_status']}.",
    ]


# 계약이 실제로 쓰는 키워드만 구현한다. 이 목록에 없는 키워드가 계약에 새로 생기면
# `validate_against_schema` 가 예외를 던진다 — 검증기가 조용히 뒤처지지 않게 하는 장치다.
SUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {
        "$schema", "$id", "title", "description",
        "type", "properties", "required", "additionalProperties",
        "items", "minItems", "minLength", "minimum", "const",
    }
)

_JSON_TYPES: dict[str, Any] = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
}


def check_schema(schema: Any, path: str = "$") -> None:
    """검증 **전에 스키마 전체**를 훑어 모르는 키워드가 있으면 멈춘다.

    ⛔ 2026-09-11 이전에는 이 검사를 `validate_against_schema` 안에서 **값이 닿은
       노드에서만** 했다. 그래서 장치가 절반만 작동했다 — `unresolved_items` 가 빈
       배열이면 그 `items` 가지는 한 번도 걸어 보지 않으므로, 계약이 거기에 새 키워드를
       들여도 조용히 지나갔다(재현 확인). 값과 무관하게 스키마부터 전부 본다.
    """
    if not isinstance(schema, dict):
        raise NotImplementedError(f"{path}: 스키마 노드는 객체여야 한다 — {type(schema).__name__}")

    unknown = set(schema) - SUPPORTED_SCHEMA_KEYWORDS
    if unknown:
        raise NotImplementedError(
            f"{path}: 이 검증기가 모르는 스키마 키워드 {sorted(unknown)} — "
            f"계약이 늘었으면 검증기도 늘려야 한다"
        )
    declared = schema.get("type")
    if declared is not None and declared not in _JSON_TYPES:
        raise NotImplementedError(f"{path}: 모르는 type {declared!r}")

    for name, sub in schema.get("properties", {}).items():
        check_schema(sub, f"{path}.{name}")
    if "items" in schema:
        check_schema(schema["items"], f"{path}[]")
    # ⛔ 계약은 지금 `false` 만 쓴다. 스키마를 값으로 두는 형태는 `_validate` 가
    #    **구현하지 않았으므로** 걸어 보지 않고 거절한다. 2026-09-11 재현에서
    #    `additionalProperties: {"type": "string"}` 에 숫자를 넣어도 오류가 없었다.
    #    선순회가 「이 스키마는 다 안다」고 말해 놓고 검사하지 않으면 그게 더 나쁘다.
    extra = schema.get("additionalProperties", False)
    if extra is not False:
        raise NotImplementedError(
            f"{path}: additionalProperties 는 `false` 만 구현했다 — {extra!r}"
        )


def validate_against_schema(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """계약 스키마의 **타입·범위까지** 검사한다.

    ⛔ 2026-09-09 이전에는 키 집합만 비교하고 *"additionalProperties: false 이므로
       키 집합 일치가 곧 구조 일치"* 라고 적어 두었다. **그것은 틀렸다.** 키 집합은
       키의 유무만 말한다. `analysis_reason` 에 정수 123 을 넣어도 그 검사는 통과했고
       `response_schema_validation_success` 가 95/95 로 나왔다. 계약이 정한 `type`·
       `minimum`·`minLength`·`const` 는 아무도 보지 않고 있었다.

    외부 검증기를 새로 의존하지 않는 방침은 유지하되, 계약이 쓰는 키워드는 전부 본다.
    """
    check_schema(schema, path)
    return _validate(value, schema, path)


def _validate(value: Any, schema: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    declared = schema.get("type")
    if declared:
        expected = _JSON_TYPES[declared]
        # JSON 의 boolean 은 number 가 아니다. Python 의 bool 이 int 인 것에 속지 않는다.
        if isinstance(value, bool) != (declared == "boolean") or not isinstance(value, expected):
            return [f"{path}: type={declared} 이어야 하는데 {type(value).__name__}"]

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: const={schema['const']!r} 이어야 하는데 {value!r}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: minLength={schema['minLength']} 미만")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # ⛔ `inf` 는 어떤 `minimum` 도 통과한다. JSON 에 없는 값이므로 여기서 막는다.
        if not math.isfinite(value):
            errors.append(f"{path}: JSON 에 없는 수 {value}")
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: minimum={schema['minimum']} 미만 ({value})")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: minItems={schema['minItems']} 미만")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(_validate(item, item_schema, f"{path}[{index}]"))
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path}.{name}: 필수인데 없다")
        if schema.get("additionalProperties") is False:
            for name in value:
                if name not in properties:
                    errors.append(f"{path}.{name}: 계약에 없는 키")
        for name, sub in properties.items():
            if name in value:
                errors.extend(_validate(value[name], sub, f"{path}.{name}"))
    return errors


def artifact_sha256() -> dict[str, str]:
    """결과를 좌우하는 파일들의 해시를 남긴다.

    「AI 평가 데이터셋 및 평가 지표 정의서」 26절이 *"동일한 Version 의 Evaluation
    Dataset 을 사용한다"* 고 정하는데, **버전 문자열만으로는 그것을 확인할 수 없다.**
    2026-09-11 재현에서 입력·정답을 양쪽 함께 줄여도 `dataset_version` 은 그대로
    `seller_analysis_eval_v1` 이었고 전 지표가 목표를 달성했다.

    ⚠️ 해시는 **「내용이 같은가」만** 말한다. 어느 내용이 승인된 것인지는 말하지 않는다.
       정책·데이터셋 버전을 어떻게 뗄지는 파트 확정 대기다. 두 리포트를 비교할 때
       해시가 다르면 **같은 버전 이름이어도 다른 것을 잰 것**이라는 뜻이다.
    """
    targets = {
        "eval_csv": EVAL_CSV,
        "ground_truth_csv": GROUND_TRUTH_CSV,
        "response_schema": RESPONSE_SCHEMA,
        # 채점 규칙과 계산 구현도 결과를 바꾼다. 데이터만 고정해서는 재현되지 않는다.
        "runner": Path(__file__).resolve(),
        "calculator": REPO_ROOT / "src" / "moongcheap_ai" / "seller_analysis" / "bid_guide.py",
    }
    return {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in targets.items()
    }


def dataset_integrity_errors(
    input_rows: list[dict[str, str]], truth_rows: list[dict[str, str]]
) -> list[str]:
    """채점 **전에** 평가셋과 정답이 서로 맞는 짝인지 본다.

    ⛔ 2026-09-11 이전에는 입력을 `{row["eval_id"]: row}` 로 바꾸기만 했다. 같은 ID 가
       두 번 있으면 **뒤엣것이 앞엣것을 조용히 덮고**, 정답은 행 그대로 돌므로 같은 건이
       두 번 채점됐다. 재현에서 양쪽에 첫 행을 하나씩 더 붙이자 **101건인데 전 지표
       목표 달성**이 나왔다. 빈 평가셋 방어(`unmeasured_metrics`)만으로는 부족하다.

    ⛔ 건수·시나리오 분포·ID 형식을 여기에 박지 않는다. 그렇게 하면 이 실행기가
       `seller_analysis_eval_v1` **한 벌 전용**이 되어, 골드셋을 버전별로 늘리는
       「AI 평가 데이터셋 및 평가 지표 정의서」 26절 방향과 어긋난다. 보는 것은
       **두 파일이 서로 맞는 짝인가**뿐이다.
    """
    errors: list[str] = []
    sets: dict[str, set[str]] = {}
    for label, rows in (("평가셋", input_rows), ("정답", truth_rows)):
        ids = [row["eval_id"] for row in rows]
        duplicated = sorted({value for value in ids if ids.count(value) > 1})
        if duplicated:
            errors.append(f"{label}에 중복된 eval_id {duplicated}")
        sets[label] = set(ids)

    # ⛔ 정답이 `NaN` 이면 `abs(got - want) > tol` 이 **항상 거짓**이라 무엇을 내놔도
    #    맞은 것이 된다. 2026-09-11 재현에서 정답 비율을 전부 `nan` 으로 바꿔도
    #    `numeric_accuracy` 가 95/95 였다. 숫자가 아닌 정답은 정답이 아니다.
    for row in truth_rows:
        if row.get("expected_request_result") == "REJECTED":
            continue
        for name in ("expected_moq_attainment_ratio", "expected_supply_coverage_ratio"):
            try:
                value = float(row[name])
            except (KeyError, TypeError, ValueError):
                errors.append(f"{row.get('eval_id')}: {name} 이 수가 아니다")
                continue
            if not math.isfinite(value) or value < 0:
                errors.append(f"{row.get('eval_id')}: {name} 이 {value}")

    only_input = sorted(sets["평가셋"] - sets["정답"])
    only_truth = sorted(sets["정답"] - sets["평가셋"])
    if only_input:
        errors.append(f"평가셋에만 있는 eval_id {only_input}")
    if only_truth:
        errors.append(f"정답에만 있는 eval_id {only_truth}")
    return errors


def evaluate() -> dict[str, Any]:
    input_rows = read_csv(EVAL_CSV)
    truths = read_csv(GROUND_TRUTH_CSV)
    # ⛔ 짝이 맞지 않는 데이터셋으로는 한 건도 채점하지 않는다. 부분 채점 결과를
    #    내놓으면 그 숫자가 어디서 나온 것인지 아무도 되짚을 수 없다.
    integrity_errors = dataset_integrity_errors(input_rows, truths)
    inputs = {} if integrity_errors else {row["eval_id"]: row for row in input_rows}
    if integrity_errors:
        truths = []
    schema = json.loads(RESPONSE_SCHEMA.read_text(encoding="utf-8"))
    # 한 건도 채점하기 전에 계약 스키마부터 전부 훑는다. 값이 닿지 않는 가지에 새
    # 키워드가 들어와 있으면 여기서 멈춘다 — 95건을 다 돌고 「전부 통과」를 내지 않는다.
    check_schema(schema)

    counts = {key: [0, 0] for key in TARGETS}  # [맞은 수, 분모]
    counts["pii_leakage_rate"] = [0, 0]
    failures: list[dict[str, Any]] = []

    def score(metric: str, ok: bool, eval_id: str, detail: str = "") -> None:
        counts[metric][1] += 1
        if ok:
            counts[metric][0] += 1
        else:
            failures.append({"eval_id": eval_id, "metric": metric, "detail": detail})

    for truth in truths:
        eval_id = truth["eval_id"]
        payload = as_request(inputs[eval_id])
        rejected_expected = truth["expected_request_result"] == "REJECTED"
        is_pii_case = "PII_FIELD" in truth["scenario_tags"].split("|")

        try:
            body = handle_bid_guide(payload)
        except (ContractViolation, VersionMismatch) as exc:
            # 18.5절 — 거절이 정답인 Case 만 이 지표의 분모다.
            if rejected_expected:
                score("invalid_input_rejection_accuracy", True, eval_id)
                if is_pii_case:
                    score("pii_input_rejection_accuracy", True, eval_id)
            else:
                # ⛔ `numeric_accuracy` 만 실패로 적으면 **나머지 지표의 분모가 줄어든다.**
                #    2026-09-11 재현에서 정상 1건을 잘못 거절하자 numeric 은 94/95 인데
                #    상태·근거·schema 는 94/94 로 나왔다. 채점하지 못한 것은 통과가 아니다.
                for metric in SCORED_ON_SUCCESS:
                    score(metric, False, eval_id, f"정상 Case 가 거절됐다: {exc}")
            continue

        if rejected_expected:
            # 거절했어야 하는데 계산해 버렸다.
            score("invalid_input_rejection_accuracy", False, eval_id, "거절하지 않고 계산했다")
            if is_pii_case:
                score("pii_input_rejection_accuracy", False, eval_id, "개인 단위 필드를 통과시켰다")
            continue

        # ⛔ **스키마 검증이 필드 접근보다 먼저다.** 2026-09-11 이전에는 `body["metrics"]`
        #    를 먼저 읽었다. `metrics` 가 빠지면 `KeyError`, 비율이 문자열이면
        #    `TypeError` 로 **평가 전체가 그 자리에서 멈췄다** — 한 건의 계약 위반이
        #    나머지 94건의 채점까지 못 하게 만든다. 계약을 벗어난 응답은 그 건만
        #    실패로 적고 다음 건으로 간다.
        schema_errors = validate_against_schema(body, schema)
        score(
            "response_schema_validation_success",
            not schema_errors,
            eval_id,
            "; ".join(schema_errors[:3]),
        )

        # 20절 출력 — 개별 Consumer 식별정보가 응답에 없어야 한다. 문자열만 보면 되므로
        # 스키마 위반 여부와 무관하게 센다. `default=str` 은 계약 밖 타입이 실려 와도
        # 직렬화가 여기서 죽지 않게 하려는 것이다.
        serialized = json.dumps(body, ensure_ascii=False, default=str)
        leaked = [marker for marker in PII_MARKERS if marker in serialized]
        counts["pii_leakage_rate"][1] += 1
        if leaked:
            counts["pii_leakage_rate"][0] += 1
            failures.append(
                {"eval_id": eval_id, "metric": "pii_leakage_rate", "detail": ",".join(leaked)}
            )

        if schema_errors:
            # ⛔ 분모에서 빼지 않는다. 빼면 채점하지 못한 건이 정확도를 **올려** 준다.
            for metric in SCORED_ON_SUCCESS:
                if metric == "response_schema_validation_success":
                    continue  # 바로 위에서 이미 매겼다
                score(metric, False, eval_id, "응답이 계약 스키마를 벗어나 채점하지 못했다")
            continue

        metrics = body["metrics"]

        # ⛔ 비율 두 개만 보지 않는다. `metrics` 는 **네 필드**이고(「AI API Contract」
        #    5절 「Seller Analysis API」 Response 표), 나머지 둘은 요청값을 그대로
        #    되돌려 주는 자리다. 정답 CSV 에 없다는 이유로 2026-09-11 이전에는 검사에서
        #    통째로 빠져 있었다 — `participant_count` 를 999 로 바꿔도 95/95 였다.
        #    `request_id`·`input_context_version` 도 같다. 이 둘이 어긋나면 그 응답은
        #    **다른 요청의 결과**이고, 그러면 맞은 숫자도 맞은 것이 아니다.
        wrong = [
            name
            for name, got, want in (
                (
                    "moq_attainment_ratio",
                    metrics["moq_attainment_ratio"],
                    float(truth["expected_moq_attainment_ratio"]),
                ),
                (
                    "supply_coverage_ratio",
                    metrics["supply_coverage_ratio"],
                    float(truth["expected_supply_coverage_ratio"]),
                ),
            )
            if not math.isfinite(got)
            or not math.isfinite(want)
            or abs(got - want) > NUMERIC_TOLERANCE
        ]
        # ⛔ 기준을 `payload` 로 두면 **구현이 payload 를 고쳐 놓고 맞췄다고 할 수 있다.**
        #    2026-09-11 재현에서 호출부가 입력과 응답의 참여자 수를 함께 999 로 바꾸자
        #    전 지표 95/95 에 `all_targets_met=True` 가 나왔다. `payload` 는 우리가
        #    넘겨 준 뒤 구현이 만질 수 있는 객체다. **평가셋 CSV 를 기준으로 삼는다.**
        row = inputs[eval_id]
        wrong += [
            name
            for name, got, want in (
                (
                    "metrics.participant_count",
                    metrics["participant_count"],
                    int(row["participant_count"]),
                ),
                (
                    "metrics.total_demand_quantity",
                    metrics["total_demand_quantity"],
                    int(row["total_demand_quantity"]),
                ),
                ("request_id", body["request_id"], eval_id),
                ("input_context_version", body["input_context_version"], EVAL_CONTEXT_VERSION),
            )
            if got != want
        ]
        score(
            "numeric_accuracy",
            not wrong,
            eval_id,
            ", ".join(wrong)
            or f"{metrics['moq_attainment_ratio']} / {metrics['supply_coverage_ratio']}",
        )

        moq_status, supply_status = derive_status(metrics)
        score("moq_status_accuracy", moq_status == truth["expected_moq_status"], eval_id, moq_status)
        score(
            "supply_status_accuracy",
            supply_status == truth["expected_supply_status"],
            eval_id,
            supply_status,
        )

        # 18.4절 — 설명과 구조화 결과가 서로 모순되지 않는지.
        #
        # ⛔ 「기대 상태 문자열이 들어 있다」만 보지 않는다. 그 검사는 **덧붙은 문장을
        #    보지 못한다** — 2026-09-09 재현에서 "모든 수량 계산은 잘못됐습니다" 를
        #    한 줄 더 넣어도 95/95 였다.
        # ⛔ **형태만 보지도 않는다.** 2026-09-11 재현에서 문장 속 수량을 `999999` 로
        #    바꿔도 정규식은 그대로 통과했다. 기대 문장을 평가셋·정답으로 완성해
        #    **한 글자씩** 대조한다. 줄 수·형태·상태 코드·숫자가 한꺼번에 걸린다.
        # 판단 사유도 같은 대조 대상이다. 근거 세 줄이 멀쩡해도 이 한 문장이
        # 딴소리를 하면 「설명과 구조화 결과가 모순되지 않는다」가 아니다.
        reason_ok = body["analysis_reason"] == REASON_TEMPLATES[
            truth["expected_moq_status"] == "MOQ_MET",
            truth["expected_supply_status"] == "SUPPLY_SUFFICIENT",
        ]

        # ⛔ `unresolved_items` 를 아무도 보지 않았다. 2026-09-11 재현에서 금지된
        #    확정 예측 문장을 넣어도 전 지표가 통과했다. 이 평가셋은 계산에 필요한 네
        #    수량을 **모두** 주므로 계산하지 못할 항목이 없다 — 기대값은 빈 목록이다.
        #    ⚠️ 「항상 비어 있어야 한다」는 운영 정책이 아니다. 채움 규칙의 형식은
        #    명세서 8-2 에서 확정 대기이고, 여기서는 **이 평가셋의 입력**에서 나온
        #    기대값일 뿐이다.
        unresolved_ok = body["unresolved_items"] == []

        evidence_lines = body["calculation_evidence"]
        wanted = expected_evidence(inputs[eval_id], truth)
        mismatched = [
            index
            for index in range(max(len(wanted), len(evidence_lines)))
            if index >= len(evidence_lines)
            or index >= len(wanted)
            or evidence_lines[index] != wanted[index]
        ]
        evidence = " ".join(evidence_lines)
        opposite = (
            OPPOSITE_STATUS[truth["expected_moq_status"]],
            OPPOSITE_STATUS[truth["expected_supply_status"]],
        )
        score(
            "evidence_consistency",
            not mismatched
            and reason_ok
            and unresolved_ok
            # 반대 상태가 같이 실려 있으면 설명이 스스로 모순이다. 동일성 대조로 이미
            # 걸리지만, 기대 문장 쪽이 잘못 만들어져도 이 조건은 남아 있게 둔다.
            and not any(token in evidence for token in opposite),
            eval_id,
            "; ".join(
                part
                for part in (
                    f"근거 {[i + 1 for i in mismatched]}번째 줄이 기대와 다르다" if mismatched else "",
                    "" if reason_ok else "판단 사유가 템플릿과 다르다",
                    "" if unresolved_ok else "계산 못 한 항목이 없는데 unresolved_items 가 비어 있지 않다",
                )
                if part
            ),
        )

    metrics_report: dict[str, Any] = {}
    for name, (hit, total) in counts.items():
        rate = (hit / total) if total else None
        target = TARGETS.get(name, ZERO_TARGETS.get(name))
        if name in ZERO_TARGETS:
            met = rate == 0.0 if rate is not None else None
        else:
            met = (rate >= target) if rate is not None else None
        metrics_report[name] = {
            "value": rate,
            "count": hit,
            "denominator": total,
            "target": target,
            "target_met": met,
        }

    # 목표가 걸린 지표는 전부 실제로 채점됐어야 한다. 분모 0 은 「측정 안 됨」이다.
    unmeasured = sorted(
        name
        for name in set(TARGETS) | set(ZERO_TARGETS)
        if not metrics_report[name]["denominator"]
    )
    measured = sorted(name for name in metrics_report if metrics_report[name]["denominator"])

    return {
        "dataset_version": DATASET_VERSION,
        "dataset_integrity_errors": integrity_errors,
        "artifact_sha256": artifact_sha256(),
        "numeric_tolerance": NUMERIC_TOLERANCE,
        "calculation_policy_version": METRICS_VERSION,
        "evaluated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "case_count": len(truths),
        "metrics": metrics_report,
        "failures": failures,
        # ⛔ 빈 평가셋을 합격으로 보고하지 않는다. 분모가 0 이면 `target_met` 이 None 이라
        #    걸러지고, 전부 걸러지면 `all([])` 이 공허하게 True 가 된다. 2026-09-09
        #    재현에서 입력·정답이 모두 0건인 채로 `all_targets_met: true` 가 나왔다.
        #    **채점하지 못한 것은 통과가 아니다.**
        "measured": measured,
        "unmeasured_metrics": unmeasured,
        "all_targets_met": bool(truths)
        and not integrity_errors
        and not unmeasured
        and all(
            entry["target_met"] for entry in metrics_report.values() if entry["target_met"] is not None
        ),
    }


def main() -> int:
    report = evaluate()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUT_ROOT / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ⛔ 판정 기호를 ASCII 로 둔다. Windows 기본 콘솔은 cp949 라 `✅` 에서
    #    UnicodeEncodeError 로 죽는다. 실행 결과가 CI 로그나 파일로 흘러갈 수도 있어
    #    표시 문자에 기대지 않는다. 한글 본문은 cp949 에 있으므로 그대로 둔다.
    print(f"{DATASET_VERSION} · {report['case_count']}건 · 정책 {report['calculation_policy_version']}")
    print(f"{'지표':<38}{'값':>9}{'목표':>9}   판정")
    print("-" * 72)
    for name, entry in report["metrics"].items():
        value = "-" if entry["value"] is None else f"{entry['value'] * 100:.1f}%"
        target = "-" if entry["target"] is None else f"{entry['target'] * 100:.0f}%"
        mark = "OK  " if entry["target_met"] else ("FAIL" if entry["target_met"] is False else "-   ")
        note = f"  ({entry['count']}/{entry['denominator']})"
        print(f"{name:<38}{value:>9}{target:>9}   {mark}{note}")
    print()
    if report["dataset_integrity_errors"]:
        errors = report["dataset_integrity_errors"]
        print(f"FAIL 데이터셋 무결성 {len(errors)}건")
        for line in errors[:10]:
            print(f"   {line}")
        if len(errors) > 10:
            print(f"   … 외 {len(errors) - 10}건")
        print()
    if report["failures"]:
        print(f"FAIL 실패 {len(report['failures'])}건")
        for item in report["failures"][:10]:
            print(f"   {item['eval_id']} · {item['metric']} · {item['detail']}")
    else:
        print("실패 없음")
    digests = report["artifact_sha256"]
    print("산출물 해시 (앞 12자리)")
    for name in ("eval_csv", "ground_truth_csv", "response_schema", "runner", "calculator"):
        print(f"   {name:<20}{digests[name][:12]}")
    print(f"\n리포트  {path.relative_to(REPO_ROOT)}")
    return 0 if report["all_targets_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
