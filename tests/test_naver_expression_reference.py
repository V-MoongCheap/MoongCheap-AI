from __future__ import annotations

import pandas as pd

from scripts.reviews.build_naver_expression_reference import build_candidates


def test_expression_reference_keeps_candidates_pending_and_not_hff_evidence() -> None:
    corpus = pd.DataFrame(
        {
            "rating": ["5", "5", "5"],
            "review_text": [
                "목넘김이 편하고 냄새가 없어서 좋아요",
                "혈압 개선에 효과가 있다고 느꼈어요",
                "배송은 빠르지만 의자 사이즈가 작아요",
            ],
        }
    )

    candidates, summary = build_candidates(corpus, [("swallowability", "easy"), ("odor", "fishy")])

    assert len(candidates) == 2
    assert candidates["reviewer_decision"].eq("PENDING_REVIEW").all()
    assert candidates["proposed_alias"].eq("").all()
    assert summary["swallowability:easy"]["related_sentence_count"] == 1
    assert summary["odor:fishy"]["related_sentence_count"] == 1
