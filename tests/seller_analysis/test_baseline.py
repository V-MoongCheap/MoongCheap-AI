import pandas as pd

from moongcheap_ai.seller_analysis.baseline import summarize_seller_demand


def test_seller_summary_counts_candidate_offers() -> None:
    clusters = pd.DataFrame([{"cluster_id": "c1", "participant_count": 2, "total_quantity": 4, "catalog_count": 1, "substitutable": False}])
    matches = pd.DataFrame([{"cluster_id": "c1", "item_id": "i1", "match_status": "CANDIDATE", "score": 75}])
    result = summarize_seller_demand(clusters, matches)
    assert result.loc[0, "candidate_offer_count"] == 1
