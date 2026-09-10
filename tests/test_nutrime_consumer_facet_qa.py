from __future__ import annotations

import json

import pandas as pd

from scripts.reviews.qa_nutrime_consumer_facets import _discovery_counts, _mixability_details, _product_field_qa


def test_product_field_qa_detects_daily_frequency(tmp_path) -> None:
    path = tmp_path / "intake.csv"
    pd.DataFrame(
        {
            "source_product_id": ["p1", "p2"],
            "daily_frequency_candidate": ["1일 1회", ""],
        }
    ).to_csv(path, index=False)
    result = _product_field_qa(path)
    assert result["available"] is True
    assert result["daily_frequency_rows"] == 1
    assert result["unique_products"] == 1


def test_mixability_details_preserve_unmapped_reason() -> None:
    raw = pd.DataFrame(
        [{"source_review_id": "r1", "source_product_id": "", "product_name": "", "review_text": "물에 잘 녹아요"}]
    )
    discovery = pd.DataFrame([{"review_id": "r1", "proposed_facet": "mixability"}])
    result = _mixability_details(raw, discovery)
    assert result.loc[0, "mapping_status"] == "UNMAPPED"
    assert "SOURCE_PRODUCT_ID_EMPTY" in result.loc[0, "mapping_failure_reason"]


def test_discovery_counts_separate_rows_and_unique_reviews() -> None:
    discovery = pd.DataFrame(
        [
            {"discovery_type": "NEW_VALUE", "review_id": "r1"},
            {"discovery_type": "NEW_VALUE", "review_id": "r1"},
            {"discovery_type": "NEW_FACET_CANDIDATE", "review_id": "r1"},
        ]
    )
    result = _discovery_counts(discovery).set_index("discovery_type")
    assert result.loc["NEW_VALUE", "analysis_row_count"] == 2
    assert result.loc["NEW_VALUE", "unique_review_count"] == 1
