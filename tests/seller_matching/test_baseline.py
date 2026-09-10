import pandas as pd

from moongcheap_ai.seller_matching.baseline import match_offers


def test_matching_is_transparent_and_does_not_claim_exact_identity() -> None:
    clusters = pd.DataFrame([{"cluster_id": "c1", "category_id": "health-functional-food:red_ginseng", "total_quantity": 2}])
    offers = pd.DataFrame([{"item_id": "i1", "category_leaf": "홍삼액", "title": "홍삼 스틱", "moq": "1", "min_unit_price": "10000"}])
    result = match_offers(clusters, offers)
    assert result.loc[0, "match_status"] == "CANDIDATE"
    assert "exact catalog identity unresolved" in result.loc[0, "reason"]
