"""로컬 MVP 데모의 후보 판정 회귀.

⚠️ pandas 가 돌려주는 것은 `np.bool_` 이라 `is True` 가 성립하지 않는다. `bool()` 로 감싼다.

⛔ 세 검사(카테고리·MOQ·가격)를 모두 통과해야 `CANDIDATE` 다.
   점수 합만 보면 카테고리가 전혀 맞지 않아도 MOQ·가격만으로 임계값(50)을 채운다.
"""

import pandas as pd

from moongcheap_ai.seller_matching.baseline import match_offers


def _cluster(**overrides) -> pd.DataFrame:
    """`summarize_clusters` 가 내보내는 모양 그대로 만든다."""
    row = {
        "cluster_id": "c1",
        "category_id": "health-functional-food:red_ginseng",
        "label": "홍삼",
        "participant_count": 2,
        "total_quantity": 2,
        "catalog_count": 1,
        "substitutable": False,
        "demand_ids": "1|2",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _offer(**overrides) -> pd.DataFrame:
    row = {"item_id": "i1", "category_leaf": "홍삼액", "title": "홍삼 스틱",
           "moq": "1", "min_unit_price": "10000"}
    row.update(overrides)
    return pd.DataFrame([row])


def test_matching_is_transparent_and_does_not_claim_exact_identity() -> None:
    result = match_offers(_cluster(), _offer())
    assert result.loc[0, "match_status"] == "CANDIDATE"
    assert "exact catalog identity unresolved" in result.loc[0, "reason"]


def test_korean_demand_label_is_used_not_only_the_english_slug() -> None:
    """`category_id` 는 영문 슬러그라 한글 공고와 맞지 않는다.

    `summarize_clusters` 가 `label` 을 함께 내보내므로 그 값으로 맞춘다.
    """
    result = match_offers(_cluster(), _offer())
    assert bool(result.loc[0, "category_match"]) is True


def test_unrelated_category_is_not_a_candidate() -> None:
    """⛔ 홍삼 수요에 스노우 타이어가 후보로 올라가면 안 된다.

    MOQ·가격만으로 점수 50 이 나와 임계값과 같아지던 경로다.
    """
    offers = _offer(item_id="x9", category_leaf="자동차 타이어",
                    title="겨울용 스노우 타이어", moq="1", min_unit_price="80000")
    result = match_offers(_cluster(), offers)
    assert bool(result.loc[0, "category_match"]) is False
    assert result.loc[0, "match_status"] == "REVIEW"
    assert "category" in result.loc[0, "reason"]


def test_unknown_moq_is_not_treated_as_satisfied() -> None:
    """⛔ 모르는 것은 통과가 아니다. 성사 불가능한 응찰이 후보에 남는다."""
    offers = _offer()
    offers = offers.drop(columns=["moq"])
    result = match_offers(_cluster(), offers)
    assert bool(result.loc[0, "moq_known"]) is False
    assert bool(result.loc[0, "moq_ok"]) is False
    assert result.loc[0, "match_status"] == "REVIEW"


def test_moq_above_demand_is_not_a_candidate() -> None:
    result = match_offers(_cluster(), _offer(moq="500"))
    assert bool(result.loc[0, "moq_ok"]) is False
    assert result.loc[0, "match_status"] == "REVIEW"


def test_offer_without_price_is_not_a_candidate() -> None:
    """가격을 모르면 비용 비교가 불가능하다."""
    offers = _offer().drop(columns=["min_unit_price"])
    result = match_offers(_cluster(), offers)
    assert bool(result.loc[0, "price_available"]) is False
    assert result.loc[0, "match_status"] == "REVIEW"


def test_reason_names_the_failed_checks() -> None:
    offers = _offer(category_leaf="자동차 타이어", title="타이어").drop(columns=["min_unit_price"])
    reason = match_offers(_cluster(), offers).loc[0, "reason"]
    assert "failed:" in reason and "category" in reason and "price" in reason


def test_missing_label_and_category_are_not_matching_tokens() -> None:
    for value in (float("nan"), pd.NA, None, "   "):
        result = match_offers(_cluster(label=value), _offer(category_leaf=value, title="자동차 타이어"))
        assert not bool(result.loc[0, "category_match"])
        assert result.loc[0, "match_status"] == "REVIEW"


def test_nonfinite_price_without_fallback_is_not_available() -> None:
    for value in (float("inf"), float("-inf"), float("nan")):
        result = match_offers(_cluster(), _offer(min_unit_price=value))
        assert not bool(result.loc[0, "price_available"])
        assert result.loc[0, "match_status"] == "REVIEW"


def test_missing_or_nonfinite_quantity_does_not_satisfy_moq() -> None:
    for value in (None, float("nan"), float("inf"), 0, -1):
        result = match_offers(_cluster(total_quantity=value), _offer())
        assert not bool(result.loc[0, "moq_ok"])
        assert result.loc[0, "match_status"] == "REVIEW"
