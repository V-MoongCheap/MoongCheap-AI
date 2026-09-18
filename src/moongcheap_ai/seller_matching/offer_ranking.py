"""낙찰 판정 엔진.

한 수요보드에 입찰한 판매 공고(product)를 규칙으로 비교해 적격 여부 · 총액 · 순위 · 점수 · 사유를 정한다.
조회와 결과 전송은 이 모듈 밖에서 한다. 표준 라이브러리만 쓰는 순수 계산이다.

기준
- 「백로그 · 우선순위 P0–P3 · 스프린트 계획」 FSYS-04 — *"낙찰 판정 — 총액 최저 + 최소 성사 수량"*
- 「평가 / Gold Set 세부 정의」 v0.3 6-2절 — *"총비용 오름차순 순위화, 동률은 공고 ID로 확정"*
- 요구사항 Product-01 — 판매자가 입력하는 조건: 단가 · 배송비 · 총 판매 수량 · 최소 성사 인원 ·
  최소 성사 수량 · 1인 최대 구매 수량(*"미설정 시 총 판매 수량을 상한으로 본다"*)
- 요구사항 Product-08 — *"응찰 0건, 또는 전 건이 조건 미달로 판정된 경우"* 무산

⛔ 판정을 보류하지 않는다. 결과는 낙찰 1건 또는 유찰이다 (Product-08,
   「AI-Backend 낙찰 판정 연동 API 기능 요구 명세서 응답」 3절 — 보장하지 않는 조건은 AI가 판단해 유찰).

⛔ 판정 조건은 모두 필수다. 빠진 값이 있으면 이 엔진을 부르지 않는다 — 「AI 실행 및 Backend/Frontend
   통합 인터페이스 명세」 10-1.4절 *"필수 판정 필드가 누락된 요청은 해당 board의 정상 판정을 진행하지 않고
   계약 오류로 기록한다"*. 누락 판정은 `awarding_batch` 가 한다.

⛔ 미확정 정책 두 가지(배송비 부과 단위 · 가격 상한 비교 금액 — 「평가 / Gold Set 세부 정의」 11절)는
   `RankingPolicy` 로 **반드시** 받는다. 엔진이 기본값을 정하지 않는다.

제외 대상이 아닌 것
- 판매 가능 상태(회수 · 판매중지) — Backend 가 검증해 응답한다 (명세 응답 2절)
- 수량별 가격 구간 · 주문 단위 · 배송 가능 여부 — 서비스 상품 입력에 없다 (Product-01)
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

RULE_VERSION = "offer-ranking-v0.2"

AWARD = "AWARD"
NO_AWARD = "NO_AWARD"

PASS = "PASS"
FAIL = "FAIL"
SKIPPED = "SKIPPED"

SHIPPING_FEE_UNITS = ("PER_BOARD", "PER_PARTICIPANT")
PRICE_CAP_BASES = ("UNIT_PRICE", "TOTAL_WITH_SHIPPING")

REASON_MAX_LENGTH = 500  # Backend `AwardingResultRequestDto.Evaluation.reason` 제한
_SCORE_QUANTUM = Decimal("0.0001")  # Backend 는 소수 넷째 자리까지 받는다


@dataclass(frozen=True)
class BoardInput:
    """판정 대상 수요보드. 개별 구매자 값은 받지 않는다."""

    board_id: int
    total_quantity: int  # 판정 기준 총수요 수량
    participant_count: int
    price_max: int | None  # 구매자 희망 가격대 상한. `null` 이면 상한 검사를 하지 않는다
    # board 에 속한 개별 Demand 의 quantity 최댓값 (명세 10-1.5절 `maxDemandQuantityPerMember`)
    max_demand_quantity_per_member: int


@dataclass(frozen=True)
class OfferInput:
    """입찰한 판매 공고 한 건. 금액은 원 단위 정수다."""

    product_id: int
    unit_price: int
    shipping_fee: int
    total_quantity: int  # 총 판매 수량 = 공급 가능 수량
    min_quantity: int  # 최소 성사 수량
    min_participant_count: int  # 최소 성사 인원
    max_quantity_per_member: int | None  # 판매자가 설정하지 않으면 `null`, 총 판매 수량이 상한


@dataclass(frozen=True)
class RankingPolicy:
    """PM 결정이 필요한 정책. 정해지지 않은 값으로는 만들 수 없다."""

    shipping_fee_unit: str  # "PER_BOARD" | "PER_PARTICIPANT"
    price_cap_basis: str  # "UNIT_PRICE" | "TOTAL_WITH_SHIPPING" (총액 ÷ 수량과 비교)

    def __post_init__(self) -> None:
        if self.shipping_fee_unit not in SHIPPING_FEE_UNITS:
            raise ValueError(f"shipping_fee_unit must be one of {SHIPPING_FEE_UNITS}")
        if self.price_cap_basis not in PRICE_CAP_BASES:
            raise ValueError(f"price_cap_basis must be one of {PRICE_CAP_BASES}")


@dataclass(frozen=True)
class OfferEvaluation:
    product_id: int
    eligible: bool
    checks: tuple[tuple[str, str], ...]
    exclusion_reasons: tuple[str, ...]
    total_cost: int
    rank: int | None
    score: Decimal
    reason: str
    is_awarded: bool


@dataclass(frozen=True)
class BoardDecision:
    board_id: int
    outcome: str
    awarded_product_id: int | None
    evaluations: tuple[OfferEvaluation, ...]
    skipped_checks: tuple[str, ...]
    rule_version: str


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _validate(board: BoardInput, offers: list[OfferInput]) -> None:
    """계약상 나올 수 없는 값은 판정하지 않고 거절한다. 추정해서 이어가지 않는다."""
    _require(board.total_quantity >= 1, "board.total_quantity must be >= 1")
    _require(board.participant_count >= 0, "board.participant_count must be >= 0")
    _require(board.max_demand_quantity_per_member >= 1, "board.max_demand_quantity_per_member must be >= 1")
    ids = [offer.product_id for offer in offers]
    _require(len(ids) == len(set(ids)), "duplicate product_id")
    for offer in offers:
        _require(offer.unit_price >= 0, f"product {offer.product_id}: unit_price must be >= 0")
        _require(offer.shipping_fee >= 0, f"product {offer.product_id}: shipping_fee must be >= 0")
        _require(offer.total_quantity >= 1, f"product {offer.product_id}: total_quantity must be >= 1")
        _require(offer.min_quantity >= 1, f"product {offer.product_id}: min_quantity must be >= 1")
        _require(offer.min_participant_count >= 1, f"product {offer.product_id}: min_participant_count must be >= 1")
        _require(
            offer.max_quantity_per_member is None or offer.max_quantity_per_member >= 1,
            f"product {offer.product_id}: max_quantity_per_member must be >= 1 or null",
        )


def _total_cost(board: BoardInput, offer: OfferInput, policy: RankingPolicy) -> int:
    shipping = offer.shipping_fee
    if policy.shipping_fee_unit == "PER_PARTICIPANT":
        shipping *= board.participant_count
    return offer.unit_price * board.total_quantity + shipping


def _at_least(value: int, minimum: int) -> str:
    return PASS if value >= minimum else FAIL


# (검사 이름, 실패 코드). 이 순서로 검사하고 사유도 이 순서로 적는다.
_CHECKS = (
    ("min_quantity", "MIN_QUANTITY_NOT_MET"),
    ("min_participants", "MIN_PARTICIPANTS_NOT_MET"),
    ("supply", "SUPPLY_INSUFFICIENT"),
    ("max_per_member", "MAX_PER_MEMBER_EXCEEDED"),
    ("price_cap", "PRICE_CAP_EXCEEDED"),
)


def _run_checks(board: BoardInput, offer: OfferInput, policy: RankingPolicy, total: int) -> dict[str, str]:
    if board.price_max is None:
        price_cap = SKIPPED
    elif policy.price_cap_basis == "UNIT_PRICE":
        price_cap = PASS if offer.unit_price <= board.price_max else FAIL
    else:
        # 나눗셈 반올림을 피하려고 양변에 수량을 곱해 비교한다.
        price_cap = PASS if total <= board.price_max * board.total_quantity else FAIL

    per_member_limit = offer.total_quantity if offer.max_quantity_per_member is None else offer.max_quantity_per_member
    return {
        "min_quantity": _at_least(board.total_quantity, offer.min_quantity),
        "min_participants": _at_least(board.participant_count, offer.min_participant_count),
        "supply": _at_least(offer.total_quantity, board.total_quantity),
        "max_per_member": _at_least(per_member_limit, board.max_demand_quantity_per_member),
        "price_cap": price_cap,
    }


def _won(value: int) -> str:
    return f"{value:,}원"


def _failure_phrase(code: str, board: BoardInput, offer: OfferInput, policy: RankingPolicy, total: int) -> str:
    if code == "MIN_QUANTITY_NOT_MET":
        return f"최소 성사 수량 {offer.min_quantity:,}개에 현재 수요 {board.total_quantity:,}개로 미달"
    if code == "MIN_PARTICIPANTS_NOT_MET":
        return f"최소 성사 인원 {offer.min_participant_count:,}명에 현재 참여 {board.participant_count:,}명으로 미달"
    if code == "SUPPLY_INSUFFICIENT":
        return f"공급 가능 수량 {offer.total_quantity:,}개가 수요 {board.total_quantity:,}개보다 적음"
    if code == "MAX_PER_MEMBER_EXCEEDED":
        limit = offer.total_quantity if offer.max_quantity_per_member is None else offer.max_quantity_per_member
        return f"1인 최대 구매 수량 {limit:,}개가 한 구매자의 최대 요청 {board.max_demand_quantity_per_member:,}개보다 적음"
    if policy.price_cap_basis == "UNIT_PRICE":
        return f"단가 {_won(offer.unit_price)}이 희망 가격 상한 {_won(board.price_max)}을 넘음"
    return f"배송비 포함 총액 {_won(total)}이 희망 가격 상한 기준 {_won(board.price_max * board.total_quantity)}을 넘음"


def _cost_phrase(board: BoardInput, offer: OfferInput, policy: RankingPolicy, total: int) -> str:
    shipping = _won(offer.shipping_fee)
    if policy.shipping_fee_unit == "PER_PARTICIPANT":
        shipping = f"{shipping} × {board.participant_count:,}명"
    return f"총액 {_won(total)}(단가 {_won(offer.unit_price)} × {board.total_quantity:,}개 + 배송비 {shipping})"


def _fit(text: str) -> str:
    return text if len(text) <= REASON_MAX_LENGTH else text[: REASON_MAX_LENGTH - 1] + "…"


def _score(best_total: int, total: int) -> Decimal:
    """1위 총액 ÷ 자기 총액. 1위는 1이다. ⛔ 내림한다 — 반올림하면 2위가 1.0000 이 될 수 있다."""
    if total == best_total:
        return Decimal(1).quantize(_SCORE_QUANTUM)
    return (Decimal(best_total) / Decimal(total)).quantize(_SCORE_QUANTUM, rounding=ROUND_DOWN)


def rank_offers(board: BoardInput, offers: Iterable[OfferInput], policy: RankingPolicy) -> BoardDecision:
    """한 수요보드의 낙찰 판정. 결과는 `AWARD`(1위 한 건 낙찰) 또는 `NO_AWARD`(유찰)다."""
    offers = sorted(offers, key=lambda offer: offer.product_id)
    _validate(board, offers)

    drafts = []
    skipped: set[str] = set()
    for offer in offers:
        total = _total_cost(board, offer, policy)
        results = _run_checks(board, offer, policy, total)
        skipped.update(name for name, result in results.items() if result == SKIPPED)
        reasons = tuple(code for name, code in _CHECKS if results[name] == FAIL)
        drafts.append((offer, total, results, reasons))

    ranked = sorted(
        ((offer, total) for offer, total, _, reasons in drafts if not reasons),
        key=lambda item: (item[1], item[0].product_id),
    )
    ranks = {offer.product_id: position for position, (offer, _) in enumerate(ranked, start=1)}
    best_total = ranked[0][1] if ranked else None
    awarded = ranked[0][0].product_id if ranked else None

    evaluations = []
    for offer, total, results, reasons in drafts:
        rank = ranks.get(offer.product_id)
        if reasons:
            phrases = "; ".join(_failure_phrase(code, board, offer, policy, total) for code in reasons)
            reason, score = f"낙찰 조건 미충족: {phrases}.", Decimal(0).quantize(_SCORE_QUANTUM)
        elif rank == 1:
            reason = f"조건을 모두 충족한 응찰 중 총액이 가장 낮아 낙찰되었습니다. {_cost_phrase(board, offer, policy, total)}."
            score = _score(best_total, total)
        else:
            # ⛔ 낙찰 응찰의 금액을 적지 않는다. 사유는 다른 판매자에게도 보일 수 있다.
            tie = " 총액이 같으면 공고 번호가 작은 응찰이 앞섭니다." if total == best_total else ""
            reason = f"조건을 모두 충족했으나 총액 순위 {rank}위입니다. {_cost_phrase(board, offer, policy, total)}.{tie}"
            score = _score(best_total, total)
        evaluations.append(
            OfferEvaluation(
                product_id=offer.product_id,
                eligible=not reasons,
                checks=tuple((name, results[name]) for name, _ in _CHECKS),
                exclusion_reasons=reasons,
                total_cost=total,
                rank=rank,
                score=score,
                reason=_fit(reason),
                is_awarded=offer.product_id == awarded,
            )
        )

    return BoardDecision(
        board_id=board.board_id,
        outcome=AWARD if awarded is not None else NO_AWARD,
        awarded_product_id=awarded,
        evaluations=tuple(evaluations),
        skipped_checks=tuple(sorted(skipped)),
        rule_version=RULE_VERSION,
    )


__all__ = [
    "AWARD",
    "FAIL",
    "NO_AWARD",
    "PASS",
    "RULE_VERSION",
    "SKIPPED",
    "BoardDecision",
    "BoardInput",
    "OfferEvaluation",
    "OfferInput",
    "RankingPolicy",
    "rank_offers",
]
