from __future__ import annotations

import pandas as pd

from scripts.reviews.discover_nutrime_consumer_facets import _extract_review_rows, _strength


def test_unmapped_review_cannot_be_strong_new_facet() -> None:
    assert _strength(10, 0, 3) == "WEAK_CANDIDATE"


def test_medical_expression_is_separated_from_consumer_facet() -> None:
    frame = pd.DataFrame(
        {
            "source_review_id": ["r1"],
            "source_product_id": ["p1"],
            "product_name": ["상품"],
            "review_title": [""],
            "review_text": ["혈압 개선에 도움이 된 것 같아요"],
        }
    )

    rows = pd.DataFrame(_extract_review_rows(frame))

    assert rows["discovery_type"].tolist() == ["SUBJECTIVE_MEDICAL_OUTCOME"]
    assert rows["medical_outcome_flag"].tolist() == [True]
