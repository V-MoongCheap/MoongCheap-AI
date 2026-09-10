import json
from pathlib import Path

from moongcheap_ai.data_foundation.facet_evidence import build_review_evidence


def test_review_evidence_excludes_medical_sentence_and_keeps_consumer_expression(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    path.write_text(
        json.dumps({
            "source_review_id": "r1",
            "source_product_id": "p1",
            "review_title": "",
            "review_text": "목넘김이 편해요. 혈압이 내려갔어요.",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    evidence, stats = build_review_evidence(path, "nutrime")
    assert stats["medical_outcome_sentence_count"] == 1
    assert set(evidence["normalized_attribute"]) == {"swallowability"}
    assert set(evidence["source"]) == {"nutrime"}


def test_review_evidence_can_cap_reviews_per_product_without_changing_raw_count(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    rows = [
        {"source_review_id": f"r{i}", "source_product_id": "p1", "review_text": "목넘김이 편해요."}
        for i in range(3)
    ]
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    evidence, stats = build_review_evidence(path, "nutrime", max_reviews_per_product=2)
    assert stats["review_count"] == 3
    assert stats["sampled_review_count"] == 2
    assert len(evidence) == 2
