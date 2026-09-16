"""판매자 수요 분석(bid-guide) 계약 로직.

전송 계층과 분리한다. 이 모듈은 표준 라이브러리만 쓰므로 FastAPI 없이도
검증할 수 있고, `api.py` 는 이 함수를 부르기만 한다.

계약 근거 — 「AI–Backend 판매자 수요 분석 연동 API 기능 요구 명세서(협의안)」
5절 「API: 판매자 수요 지표 산출」 (노션 게시본, 2026-09-08).
그 문서가 인용하는 정본은 「AI API Contract」 5절 「Seller Analysis API」·
7절 「Error Response」, 「AI 시스템 디자인」 4.4절 「판매자용 소비자 수요 지표 산출」이다.

원칙 셋:
  - 수치는 결정적 계산으로만 만든다. 생성 모델이 고치거나 다시 추정하지 않는다.
  - 개별 소비자 식별정보는 입력으로 받지도, 출력으로 내지도 않는다.
  - 계산할 수 없으면 추정하지 않고 거절한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 이 구현이 지원하는 계산 정책 버전. 요청이 다른 버전을 요구하면 계산하지 않고 거절한다
# (명세서 4.2절 「버전」 · 「AI API Contract」 7절 「Error Response」 의 `VERSION_MISMATCH`).
METRICS_VERSION = "seller-metrics-v1"
SUPPORTED_POLICY_VERSIONS = frozenset({METRICS_VERSION})

# 2026-09-09 Backend 회신으로 셋이 바뀌었다.
#   ⛔ `round_ref` 제거 — *"어떤 기능인지 확인이 어렵지만, 아마 현재 구현하지 않을 기능"*.
#      Backend 에 대응 개념이 없는 필드를 Required 로 두면 호출 자체가 불가능하다.
#   ⛔ `cluster_ref`·`product_ref` 는 **정수** — *"id인 만큼 정수로 표기 부탁드립니다"*.
#   ⛔ `product_ref` 는 `product_catalog.id` 가 아니라 **`product.id`** 다 —
#      *"판매자가 생성한 product라면 product.id를 말씀하시는 것 같습니다"*.
#      카탈로그 상품이 아니라 **판매자의 응찰 건**이다.
REQUEST_FIELDS = {
    "request_id",
    "input_context_version",
    "cluster_ref",
    "product_ref",
    "participant_count",
    "total_demand_quantity",
    "minimum_success_quantity",
    "maximum_supply_quantity",
    "calculation_policy_version",
}

# 요청에 실려서는 안 되는 개인 단위 값. 오면 조용히 버리지 않고 거절한다.
FORBIDDEN_REQUEST_FIELDS = {
    "member_ids", "participant_ids", "individual_budget", "budgets",
    "requested_quantities", "user_id", "buyer_id", "contact",
}


class ContractViolation(ValueError):
    """계약 위반. 명세서 5.6절 「오류 응답」 의 `INVALID_INPUT` 로 나간다."""


class VersionMismatch(ValueError):
    """지원하지 않는 정책·문맥 버전. 명세서 5.6절의 `VERSION_MISMATCH` 로 나간다.

    ⛔ `ContractViolation` 과 형제다. 하위형으로 두면 전송 계층에서 먼저
    걸리는 쪽에 따라 코드가 뒤바뀐다.
    """


def _required_string(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation(f"{field} must be a non-empty string")
    return value.strip()


def _positive_int(data: dict[str, Any], field: str) -> int:
    value = data.get(field)
    # bool 은 int 의 하위형이므로 먼저 막는다. 소수·문자열 수량도 보정하지 않는다.
    if type(value) is not int or value <= 0:
        raise ContractViolation(f"{field} must be a positive integer")
    return value


@dataclass(frozen=True)
class BidGuideRequest:
    request_id: str
    # Backend 가 제공하는 마지막 변경 시각(`UPDATED_AT`)이다 — 2026-09-09 회신.
    # 컬럼 단위 변경 통지는 구현이 어렵고 이 값으로 갈음한다.
    input_context_version: str
    cluster_ref: int
    product_ref: int
    participant_count: int
    total_demand_quantity: int
    minimum_success_quantity: int
    maximum_supply_quantity: int
    calculation_policy_version: str

    @classmethod
    def from_dict(cls, data: Any) -> "BidGuideRequest":
        if not isinstance(data, dict):
            raise ContractViolation("request must be a JSON object")
        leaked = FORBIDDEN_REQUEST_FIELDS & set(data)
        if leaked:
            raise ContractViolation(
                "request must not carry individual consumer data: "
                + ", ".join(sorted(leaked))
            )
        if set(data) != REQUEST_FIELDS:
            raise ContractViolation("request must contain exactly the contract fields")
        policy_version = _required_string(data, "calculation_policy_version")
        # 버전 검증은 형식 검사를 통과한 뒤에 한다. AI 는 버전을 발급하지 않고 검증만 한다.
        if policy_version not in SUPPORTED_POLICY_VERSIONS:
            raise VersionMismatch(
                f"calculation_policy_version {policy_version!r} is not supported; "
                "supported: " + ", ".join(sorted(SUPPORTED_POLICY_VERSIONS))
            )
        return cls(
            request_id=_required_string(data, "request_id"),
            input_context_version=_required_string(data, "input_context_version"),
            cluster_ref=_positive_int(data, "cluster_ref"),
            product_ref=_positive_int(data, "product_ref"),
            participant_count=_positive_int(data, "participant_count"),
            total_demand_quantity=_positive_int(data, "total_demand_quantity"),
            minimum_success_quantity=_positive_int(data, "minimum_success_quantity"),
            maximum_supply_quantity=_positive_int(data, "maximum_supply_quantity"),
            calculation_policy_version=policy_version,
        )


# 자리수는 문서가 정해 두었다.
#   4자리 — 「AI 파트 → 백엔드 스키마 명세(초안)」 2절 매칭 결과 테이블이 점수 컬럼을
#           `numeric(5,4)` 로 둔다. ⚠️ 그 문서는 v0.1 초안이고 상태가
#           *"파트 내부 검토 전. 백엔드 미전달"* 이므로 확정으로 쓰지 않는다.
#   2자리 — 문서 예시가 전부 소수 둘째 자리다. 「AI API Contract」 5절의 근거 문장
#           *"…1.30입니다"* · *"약 1.15이며"*, 「AI 평가 데이터셋 및 평가 지표 정의서」
#           16절 `150 / 120 = 1.25`, 18.1절 `= 1.20`.
# 공급 충족률의 상한. 「AI API Contract」 5절 「Seller Analysis API」 의 예시가
# `supply_coverage_ratio: 1.0` 을 내고 근거 문장에 *"약 1.15이며, 계산 정책의 상한 1.0을
# 적용했습니다"* 라고 적는다. 게시된 계약이 상한을 전제하므로 그대로 따른다.
#
# ⚠️ 「AI 평가 데이터셋 및 평가 지표 정의서」 16절(`150 / 120 = 1.25`)과
#    「AI 통합 영역 최종 선정 및 BE/FE 통합 인터페이스 명세」 3.5절(`1.15`)의 예시는
#    상한을 적용하지 않는다. 이 둘과는 값이 어긋난다 — 파트 확정이 필요하다.
#
# ⛔ MOQ 달성률에는 상한을 두지 않는다. 계약이 상한을 말한 것은 공급 충족률뿐이다.
SUPPLY_COVERAGE_CAP = 1.0

RATIO_PRECISION = 4
DISPLAY_PRECISION = 2


def _ratio(numerator: int, denominator: int, *, met: bool) -> float:
    """비율을 반환하되 반올림이 1.0 경계를 넘지 못하게 한다.

    999/1000을 소수 둘째 자리에서 반올림하면 1.00이 되어, 미달 판정과
    같은 응답 안에서 서로 어긋난 숫자가 나갔다. 판정은 정수 비교로
    이미 끝났으므로 여기서는 그 판정을 뒤집지 않는 값만 낸다.
    """
    value = round(numerator / denominator, RATIO_PRECISION)
    if met:
        return max(value, 1.0)
    return min(value, 1.0 - 10 ** -RATIO_PRECISION)


def _display(value: float, *, met: bool) -> str:
    """사람이 읽는 자리수로 줄이되 같은 경계 규칙을 다시 적용한다."""
    text = f"{value:.{DISPLAY_PRECISION}f}"
    if met and float(text) < 1.0:
        return f"{1.0:.{DISPLAY_PRECISION}f}"
    if not met and float(text) >= 1.0:
        return f"{1.0 - 10 ** -DISPLAY_PRECISION:.{DISPLAY_PRECISION}f}"
    return text


def build_bid_guide(request: BidGuideRequest) -> dict[str, Any]:
    """수요 지표를 결정적으로 계산한다. 같은 입력이면 항상 같은 결과다."""
    demand = request.total_demand_quantity
    moq = request.minimum_success_quantity
    supply = request.maximum_supply_quantity

    # 판정은 반올림하지 않은 정수 비교로 먼저 내린다 (명세서 5.4절 「AI 처리 규칙」).
    moq_met = demand >= moq
    supply_met = supply >= demand
    moq_status = "MOQ_MET" if moq_met else "MOQ_NOT_MET"
    supply_status = "SUPPLY_SUFFICIENT" if supply_met else "SUPPLY_INSUFFICIENT"

    # 총수요 / 최소 성사수량. 1.0 이상이면 성사 조건을 채운다.
    moq_attainment_ratio = _ratio(demand, moq, met=moq_met)
    # 판매자가 댈 수 있는 최대 수량 / 총수요. 1.0 이상이면 전량 공급 가능.
    # 상한 1.0 을 적용한다. 근거는 위 SUPPLY_COVERAGE_CAP 주석에 적었다.
    raw_supply_coverage = _ratio(supply, demand, met=supply_met)
    supply_coverage_ratio = min(raw_supply_coverage, SUPPLY_COVERAGE_CAP)
    supply_capped = raw_supply_coverage > SUPPLY_COVERAGE_CAP

    # 판단 사유 문장. 2026-09-09 Backend 회신 —
    # *"판단 사유를 AI측에서 잡아주는 것이 좋아 보입니다. (그대로 REASON FIELD에 저장 및 제공)"*
    #
    # 「AI 통합 영역 최종 선정 및 BE/FE 통합 인터페이스 명세」 3.6절 「FE 화면 반영」 의
    # 「수요 분석」 항목에 해당한다. 그 절의 예시 문장을 상태 조합에 맞춰 만든다.
    #
    # ⛔ 입력에 없는 사실을 넣지 않는다. 「AI 아키텍처 및 안전성 정책 초안」 24절
    #    「Unsupported Claim 제한」 이 연령·성별 추정과 *"이 가격이면 반드시 판매에
    #    성공합니다"* 같은 확정적 예측을 금지한다. **관측된 두 상태만 서술한다.**
    # ⛔ 생성 모델을 쓰지 않는다. 템플릿이므로 같은 입력이면 같은 문장이 나온다.
    if moq_met and supply_met:
        analysis_reason = (
            "현재 총수요는 판매자의 최소 성사 수량을 충족하고 있으며, "
            "공급 가능 수량이 총수요를 충당합니다."
        )
    elif moq_met and not supply_met:
        analysis_reason = (
            "현재 총수요는 판매자의 최소 성사 수량을 충족하고 있으나, "
            "공급 가능 수량이 총수요에 미치지 못합니다."
        )
    elif not moq_met and supply_met:
        analysis_reason = (
            "현재 총수요는 판매자의 최소 성사 수량에 미치지 못합니다. "
            "공급 가능 수량은 현재 총수요를 충당합니다."
        )
    else:
        analysis_reason = (
            "현재 총수요는 판매자의 최소 성사 수량에 미치지 못하며, "
            "공급 가능 수량도 총수요에 미치지 못합니다."
        )

    # 근거 문장은 계산된 수치만 다시 읽는다. 새 사실을 만들지 않는다.
    calculation_evidence = [
        f"총수요 {demand}개를 최소 성사 수량 {moq}개로 나눈 결과는 "
        f"{_display(moq_attainment_ratio, met=moq_met)}입니다.",
        (
            f"판매자 최대 공급 가능 수량 {supply}개를 총수요 {demand}개로 나눈 결과는 "
            f"약 {_display(raw_supply_coverage, met=supply_met)}이며, "
            f"계산 정책의 상한 {SUPPLY_COVERAGE_CAP:.1f}을 적용했습니다."
            if supply_capped
            else
            f"판매자 최대 공급 가능 수량 {supply}개를 총수요 {demand}개로 나눈 결과는 "
            f"{_display(supply_coverage_ratio, met=supply_met)}입니다."
        ),
        f"상태 판정은 표시용 반올림 값이 아니라 원본 정수 비교로 했습니다: "
        f"{demand} vs {moq} → {moq_status}, {supply} vs {demand} → {supply_status}.",
    ]

    return {
        "request_id": request.request_id,
        "input_context_version": request.input_context_version,
        # ⛔ `metrics` 는 **정확히 이 네 키다.** 「AI API Contract」 5절 「Seller Analysis API」
        # 의 Response 표가 `metrics.participant_count`·`metrics.total_demand_quantity`·
        # `metrics.moq_attainment_ratio`·`metrics.supply_coverage_ratio` 를 나열한다.
        #
        # ⛔ 상태(`moq_status`·`supply_status`)를 여기 넣지 않는다. 2026-09-08 에 「예시에
        # 없지만 가산」이라고 넣었던 것은 **오독이었다** — 예시가 아니라 필드 정의표였다.
        # 「AI 평가 데이터셋 및 평가 지표 정의서」 18.2·18.3절이 상태를 평가 대상으로
        # 요구하지만, 같은 문서 16절이 *"실제 API Response의 최종 Field명은 Backend / AI
        # API Contract와 동일하게 맞춘다"* 고 하므로 계약이 우선한다.
        #
        # 상태는 비율에서 도출된다 — `ratio >= 1.0` 이면 충족이다. 이 동치가 성립하는 것은
        # `_ratio` 가 반올림으로 1.0 경계를 넘지 못하게 막기 때문이다. 그 가드를 없애면
        # 상태를 되살릴 수 없게 된다.
        "metrics": {
            "participant_count": request.participant_count,
            "total_demand_quantity": demand,
            "moq_attainment_ratio": moq_attainment_ratio,
            "supply_coverage_ratio": supply_coverage_ratio,
        },
        # Backend 가 REASON 필드에 그대로 저장·제공한다 (2026-09-09 회신).
        "analysis_reason": analysis_reason,
        "calculation_evidence": calculation_evidence,
        # 정보 부족으로 계산하지 못한 항목. 지금 요청 계약은 필요한 값을 모두
        # 필수로 받으므로 비어 있다. 채움 규칙의 형식은 확정 대기다(명세서 8-2).
        "unresolved_items": [],
        "calculation_policy_version": request.calculation_policy_version,
    }


def handle_bid_guide(payload: Any) -> dict[str, Any]:
    """전송 계층에서 부르는 단일 진입점."""
    return build_bid_guide(BidGuideRequest.from_dict(payload))
