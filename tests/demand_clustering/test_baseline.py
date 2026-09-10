import pandas as pd

from moongcheap_ai.demand_clustering.baseline import cluster_demands, summarize_clusters


def test_strict_and_substitutable_demands_have_expected_cluster_scope() -> None:
    frame = pd.DataFrame(
        [
            {"demand_id": "d1", "catalog_id": "p1", "category_id": "c", "label": "1", "quantity": "2", "is_substitutable": "False"},
            {"demand_id": "d2", "catalog_id": "p2", "category_id": "c", "label": "1", "quantity": "3", "is_substitutable": "True"},
            {"demand_id": "d3", "catalog_id": "p3", "category_id": "c", "label": "1", "quantity": "1", "is_substitutable": "True"},
        ]
    )
    result = cluster_demands(frame)
    assert result.loc[0, "cluster_id"] != result.loc[1, "cluster_id"]
    assert result.loc[1, "cluster_id"] == result.loc[2, "cluster_id"]
    assert summarize_clusters(result).loc[0, "participant_count"] >= 1
