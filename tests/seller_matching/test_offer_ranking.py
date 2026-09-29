"""낙찰 판정 엔진 회귀.

기준
- 「백로그 · 우선순위 P0–P3 · 스프린트 계획」 FSYS-04 — *"낙찰 판정 — 총액 최저 + 최소 성사 수량"*
- 「평가 / Gold Set 세부 정의」 v0.3 6-2절 — *"총비용 오름차순 순위화, 동률은 공고 ID로 확정"*
- 요구사항 Product-01 — 판매자 입력(단가 · 배송비 · 총 판매 수량 · 최소 성사 인원 · 최소 성사 수량 ·
  1인 최대 구매 수량). *"둘 중 하나라도 미달이면 무산"*, *"1인 최대 구매 수량 … 미설정 시 총 판매 수량을 상한"*
- 요구사항 Product-08 — *"응찰 0건, 또는 전 건이 조건 미달로 판정된 경우"* 무산. 판정 보류는 없다
- 「AI-Backend 낙찰 판정 연동 API 기능 요구 명세서」 — `score` 0.0000~1.0000, 낙찰 최대 1건
"""

from decimal import Decimal

import pytest

from moongcheap_ai.seller_matching.offer_ranking import (
    AWARD,
    NO_AWARD,
    PASS,
    RULE_VERSION,
    SKIPPED,
    BoardInput,
    OfferInput,
    RankingPolicy,
    rank_offers,
)

UNIT_PER_BOARD = RankingPolicy(shipping_fee_unit="PER_BOARD", price_cap_basis="UNIT_PRICE")


def _board(**overrides) -> BoardInput:
    values = {
        "board_id": 1,
        "total_quantity": 20,
        "participant_count": 4,
        "price_max": 2000,
        "max_demand_quantity_per_member": 5,
    }
    values.update(overrides)
    return BoardInput(**values)


def _offer(**overrides) -> OfferInput:
    """모든 검사를 통과하는 공고. 단가 1,000원 × 20개 + 배송비 3,000원 = 23,000원."""
    values = {
        "product_id": 501,
        "unit_price": 1000,
        "shipping_fee": 3000,
        "total_quantity": 50,
        "min_quantity": 10,
        "min_participant_count": 2,
        "max_quantity_per_member": 5,
    }
    values.update(overrides)
    return OfferInput(**values)


def _only(decision):
    assert len(decision.evaluations) == 1
    return decision.evaluations[0]


def _check(evaluation, name):
    return dict(evaluation.checks)[name]


# ── 적격 검사 ─────────────────────────────────────────────


def test_offer_meeting_every_condition_is_awarded():
    decision = rank_offers(_board(), [_offer()], UNIT_PER_BOARD)

    assert decision.outcome == AWARD
    assert decision.awarded_product_id == 501
    evaluation = _only(decision)
    assert evaluation.eligible
    assert evaluation.exclusion_reasons == ()
    assert evaluation.is_awarded


def test_demand_below_seller_minimum_quantity_is_excluded():
    evaluation = _only(rank_offers(_board(total_quantity=20), [_offer(min_quantity=21)], UNIT_PER_BOARD))

    assert not evaluation.eligible
    assert evaluation.exclusion_reasons == ("MIN_QUANTITY_NOT_MET",)


def test_demand_equal_to_seller_minimum_quantity_passes():
    evaluation = _only(rank_offers(_board(total_quantity=20), [_offer(min_quantity=20)], UNIT_PER_BOARD))

    assert _check(evaluation, "min_quantity") == PASS


def test_participants_below_seller_minimum_are_excluded():
    evaluation = _only(rank_offers(_board(participant_count=4), [_offer(min_participant_count=5)], UNIT_PER_BOARD))

    assert evaluation.exclusion_reasons == ("MIN_PARTICIPANTS_NOT_MET",)


def test_supply_smaller_than_demand_is_excluded():
    evaluation = _only(rank_offers(_board(total_quantity=20), [_offer(total_quantity=19)], UNIT_PER_BOARD))

    assert evaluation.exclusion_reasons == ("SUPPLY_INSUFFICIENT",)


def test_supply_equal_to_demand_passes():
    evaluation = _only(rank_offers(_board(total_quantity=20), [_offer(total_quantity=20)], UNIT_PER_BOARD))

    assert _check(evaluation, "supply") == PASS


def test_per_member_limit_below_largest_buyer_request_is_excluded():
    evaluation = _only(rank_offers(_board(max_demand_quantity_per_member=6), [_offer(max_quantity_per_member=5)], UNIT_PER_BOARD))

    assert evaluation.exclusion_reasons == ("MAX_PER_MEMBER_EXCEEDED",)


def test_unset_per_member_limit_falls_back_to_total_supply():
    """Product-01 — *"미설정 시 총 판매 수량을 상한으로 본다"*."""
    within = _only(rank_offers(_board(max_demand_quantity_per_member=30), [_offer(max_quantity_per_member=None, total_quantity=50)], UNIT_PER_BOARD))
    beyond = _only(rank_offers(_board(max_demand_quantity_per_member=51, total_quantity=20), [_offer(max_quantity_per_member=None, total_quantity=50)], UNIT_PER_BOARD))

    assert _check(within, "max_per_member") == PASS
    assert beyond.exclusion_reasons == ("MAX_PER_MEMBER_EXCEEDED",)


def test_unit_price_above_board_cap_is_excluded():
    evaluation = _only(rank_offers(_board(price_max=999), [_offer(unit_price=1000)], UNIT_PER_BOARD))

    assert evaluation.exclusion_reasons == ("PRICE_CAP_EXCEEDED",)


def test_unit_price_equal_to_board_cap_passes():
    evaluation = _only(rank_offers(_board(price_max=1000), [_offer(unit_price=1000)], UNIT_PER_BOARD))

    assert _check(evaluation, "price_cap") == PASS


def test_total_with_shipping_cap_compares_per_unit_total():
    """23,000원 ÷ 20개 = 1,150원. 상한 1,150원이면 통과, 1,149원이면 탈락."""
    policy = RankingPolicy(shipping_fee_unit="PER_BOARD", price_cap_basis="TOTAL_WITH_SHIPPING")

    at_cap = _only(rank_offers(_board(price_max=1150), [_offer()], policy))
    below = _only(rank_offers(_board(price_max=1149), [_offer()], policy))

    assert _check(at_cap, "price_cap") == PASS
    assert below.exclusion_reasons == ("PRICE_CAP_EXCEEDED",)


def test_all_failed_conditions_are_reported_in_order():
    evaluation = _only(
        rank_offers(
            _board(total_quantity=20, participant_count=1, price_max=500),
            [_offer(min_quantity=30, total_quantity=10)],
            UNIT_PER_BOARD,
        )
    )

    assert evaluation.exclusion_reasons == (
        "MIN_QUANTITY_NOT_MET",
        "MIN_PARTICIPANTS_NOT_MET",
        "SUPPLY_INSUFFICIENT",
        "PRICE_CAP_EXCEEDED",
    )


# ── 입력이 오지 않은 조건 ─────────────────────────────────
# 조회 API 가 아직 보내지 않는 값은 검사하지 않고 기록한다. 탈락시키지도, 통과로 치지도 않는다.


def test_판정_조건은_모두_필수다():
    """명세 10-1.4절 — 누락은 `awarding_batch` 가 계약 오류로 거른다. 엔진은 값을 요구한다."""
    with pytest.raises(TypeError):
        OfferInput(product_id=1, unit_price=1, shipping_fee=0, total_quantity=1)  # 조건 4개 누락


def test_board_without_price_cap_skips_cap_check():
    evaluation = _only(rank_offers(_board(price_max=None), [_offer()], UNIT_PER_BOARD))

    assert evaluation.eligible
    assert _check(evaluation, "price_cap") == SKIPPED


def test_skipped_checks_are_listed_on_the_decision():
    decision = rank_offers(_board(price_max=None), [_offer()], UNIT_PER_BOARD)

    assert decision.skipped_checks == ("price_cap",)


# ── 총액 ─────────────────────────────────────────────────


def test_total_cost_is_unit_price_times_demand_plus_board_shipping():
    evaluation = _only(rank_offers(_board(total_quantity=20), [_offer(unit_price=1000, shipping_fee=3000)], UNIT_PER_BOARD))

    assert evaluation.total_cost == 23000


def test_per_participant_shipping_multiplies_by_participants():
    policy = RankingPolicy(shipping_fee_unit="PER_PARTICIPANT", price_cap_basis="UNIT_PRICE")

    evaluation = _only(rank_offers(_board(total_quantity=20, participant_count=4), [_offer(shipping_fee=3000)], policy))

    assert evaluation.total_cost == 20000 + 12000


def test_zero_shipping_fee_adds_nothing():
    evaluation = _only(rank_offers(_board(), [_offer(shipping_fee=0)], UNIT_PER_BOARD))

    assert evaluation.total_cost == 20000


def test_ineligible_offer_still_reports_its_total_cost():
    evaluation = _only(rank_offers(_board(), [_offer(total_quantity=1)], UNIT_PER_BOARD))

    assert evaluation.total_cost == 23000


# ── 순위 · 낙찰 ──────────────────────────────────────────


def test_lowest_total_cost_wins_not_lowest_unit_price():
    cheap_unit = _offer(product_id=501, unit_price=900, shipping_fee=5000)  # 23,000
    cheap_total = _offer(product_id=502, unit_price=1000, shipping_fee=1000)  # 21,000

    decision = rank_offers(_board(), [cheap_unit, cheap_total], UNIT_PER_BOARD)

    assert decision.awarded_product_id == 502
    assert [(e.product_id, e.rank) for e in decision.evaluations] == [(501, 2), (502, 1)]


def test_tie_goes_to_smaller_product_id():
    decision = rank_offers(_board(), [_offer(product_id=503), _offer(product_id=502)], UNIT_PER_BOARD)

    assert decision.awarded_product_id == 502
    runner_up = next(e for e in decision.evaluations if e.product_id == 503)
    assert runner_up.rank == 2
    assert "공고 번호가 작은" in runner_up.reason


def test_ineligible_offers_are_not_ranked_even_if_cheaper():
    cheaper_but_short = _offer(product_id=501, unit_price=1, total_quantity=5)
    eligible = _offer(product_id=502)

    decision = rank_offers(_board(), [cheaper_but_short, eligible], UNIT_PER_BOARD)

    assert decision.awarded_product_id == 502
    assert decision.evaluations[0].rank is None


def test_all_ineligible_is_no_award():
    decision = rank_offers(_board(), [_offer(product_id=501, total_quantity=1), _offer(product_id=502, min_quantity=99)], UNIT_PER_BOARD)

    assert decision.outcome == NO_AWARD
    assert decision.awarded_product_id is None
    assert not any(e.is_awarded for e in decision.evaluations)


def test_no_offers_is_no_award_with_no_evaluations():
    decision = rank_offers(_board(), [], UNIT_PER_BOARD)

    assert decision.outcome == NO_AWARD
    assert decision.evaluations == ()


def test_at_most_one_offer_is_awarded():
    offers = [_offer(product_id=500 + i) for i in range(5)]

    decision = rank_offers(_board(), offers, UNIT_PER_BOARD)

    assert sum(e.is_awarded for e in decision.evaluations) == 1


def test_evaluations_cover_every_offer_sorted_by_product_id():
    decision = rank_offers(_board(), [_offer(product_id=9), _offer(product_id=3, total_quantity=1), _offer(product_id=5)], UNIT_PER_BOARD)

    assert [e.product_id for e in decision.evaluations] == [3, 5, 9]


def test_duplicate_product_id_is_rejected():
    with pytest.raises(ValueError, match="duplicate product_id"):
        rank_offers(_board(), [_offer(product_id=1), _offer(product_id=1)], UNIT_PER_BOARD)


def test_decision_carries_rule_version():
    assert rank_offers(_board(), [_offer()], UNIT_PER_BOARD).rule_version == RULE_VERSION


# ── score ────────────────────────────────────────────────


def test_winner_scores_one():
    assert _only(rank_offers(_board(), [_offer()], UNIT_PER_BOARD)).score == Decimal("1.0000")


def test_ineligible_scores_zero():
    assert _only(rank_offers(_board(), [_offer(total_quantity=1)], UNIT_PER_BOARD)).score == Decimal("0.0000")


def test_eligible_loser_scores_best_total_over_own_total_rounded_down():
    """21,000 ÷ 23,000 = 0.913043… → 0.9130. 올림하면 순위와 점수가 어긋날 수 있어 내림한다."""
    decision = rank_offers(
        _board(),
        [_offer(product_id=501), _offer(product_id=502, shipping_fee=1000)],
        UNIT_PER_BOARD,
    )

    scores = {e.product_id: e.score for e in decision.evaluations}
    assert scores == {501: Decimal("0.9130"), 502: Decimal("1.0000")}


def test_runner_up_just_above_winner_never_scores_one():
    """99,999 ÷ 100,000 = 0.99999. 반올림하면 1.0000 이 되어 낙찰 공고와 구분되지 않는다."""
    board = _board(total_quantity=1, participant_count=1, price_max=None, max_demand_quantity_per_member=1)
    decision = rank_offers(
        board,
        [
            _offer(product_id=501, unit_price=99999, shipping_fee=0, total_quantity=1, min_quantity=1, min_participant_count=1),
            _offer(product_id=502, unit_price=100000, shipping_fee=0, total_quantity=1, min_quantity=1, min_participant_count=1),
        ],
        UNIT_PER_BOARD,
    )

    scores = {e.product_id: e.score for e in decision.evaluations}
    assert scores == {501: Decimal("1.0000"), 502: Decimal("0.9999")}


def test_score_never_exceeds_one_for_zero_cost_winner():
    decision = rank_offers(
        _board(price_max=None),
        [_offer(product_id=501, unit_price=0, shipping_fee=0), _offer(product_id=502)],
        UNIT_PER_BOARD,
    )

    scores = {e.product_id: e.score for e in decision.evaluations}
    assert scores == {501: Decimal("1.0000"), 502: Decimal("0.0000")}


def test_scores_have_four_decimal_places():
    decision = rank_offers(_board(), [_offer(product_id=501), _offer(product_id=502, unit_price=1337)], UNIT_PER_BOARD)

    assert all(e.score.as_tuple().exponent == -4 for e in decision.evaluations)


# ── reason ───────────────────────────────────────────────
# 구매자 「낙찰 결과」 화면의 낙찰 사유로 쓰일 수 있다. 사람이 읽는 문장이며 다른 판매자의 금액을 담지 않는다.


def test_winner_reason_explains_lowest_total():
    reason = _only(rank_offers(_board(), [_offer()], UNIT_PER_BOARD)).reason

    assert "총액이 가장 낮" in reason
    assert "23,000원" in reason


def test_ineligible_reason_names_each_unmet_condition_with_numbers():
    reason = _only(rank_offers(_board(total_quantity=20), [_offer(min_quantity=30, total_quantity=10)], UNIT_PER_BOARD)).reason

    assert "최소 성사 수량 30개" in reason
    assert "공급 가능 수량 10개" in reason
    assert "MIN_QUANTITY_NOT_MET" not in reason


def test_loser_reason_does_not_reveal_winner_amount():
    decision = rank_offers(
        _board(),
        [_offer(product_id=501), _offer(product_id=502, shipping_fee=1000)],
        UNIT_PER_BOARD,
    )

    loser = next(e for e in decision.evaluations if e.product_id == 501)
    assert "21,000" not in loser.reason
    assert "2위" in loser.reason


def test_reasons_fit_backend_limit():
    decision = rank_offers(
        _board(total_quantity=10**9, participant_count=1, price_max=1, max_demand_quantity_per_member=10**9),
        [_offer(unit_price=10**9, shipping_fee=10**9, total_quantity=1, min_quantity=10**9, min_participant_count=10**9, max_quantity_per_member=1)],
        UNIT_PER_BOARD,
    )

    assert len(_only(decision).reason) <= 500


# ── 입력 계약 ────────────────────────────────────────────


@pytest.mark.parametrize(
    "board, offer",
    [
        ({"total_quantity": 0}, {}),
        ({"participant_count": -1}, {}),
        ({}, {"unit_price": -1}),
        ({}, {"shipping_fee": -1}),
        ({}, {"total_quantity": 0}),
        ({"max_demand_quantity_per_member": 0}, {}),
        ({}, {"min_quantity": 0}),
        ({}, {"min_participant_count": 0}),
        ({}, {"max_quantity_per_member": 0}),
    ],
)
def test_impossible_values_raise_instead_of_deciding(board, offer):
    with pytest.raises(ValueError):
        rank_offers(_board(**board), [_offer(**offer)], UNIT_PER_BOARD)


def test_policy_must_be_decided():
    with pytest.raises(ValueError, match="shipping_fee_unit"):
        RankingPolicy(shipping_fee_unit="UNKNOWN", price_cap_basis="UNIT_PRICE")
    with pytest.raises(ValueError, match="price_cap_basis"):
        RankingPolicy(shipping_fee_unit="PER_BOARD", price_cap_basis=None)
