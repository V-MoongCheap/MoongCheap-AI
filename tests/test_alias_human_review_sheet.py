from __future__ import annotations

import pandas as pd

from scripts.reviews.build_alias_human_review_sheet import build_sheet


def test_human_review_sheet_keeps_examples_and_pending_status() -> None:
    candidates = pd.DataFrame(
        {
            "facet_id": ["taste", "swallowability"],
            "value_candidate": ["bitter", "easy"],
            "seed_expression": ["맛", "목넘김"],
            "candidate_expression": ["쓴맛", "목넘김"],
            "occurrence_count": [2, 1],
            "semantic_similarity": [1.0, 1.0],
            "reviewer_decision": ["PENDING_REVIEW", "PENDING_REVIEW"],
        }
    )
    raw = pd.DataFrame(
        {
            "rating": ["5", "2", "4", "5"],
            "review_text": ["쓴맛은 없어요", "쓴맛이 조금 있어요", "목넘김이 편해요", "목넘김도 편합니다"],
        }
    )

    sheet, stats = build_sheet(candidates, raw)

    assert len(sheet) == 2
    assert sheet["reviewer_decision"].eq("PENDING_REVIEW").all()
    assert sheet["example_sentence_1"].str.len().gt(0).all()
    assert sheet["example_sentence_2"].str.len().gt(0).all()
    assert stats["category_facet_combination_count"] == 0
