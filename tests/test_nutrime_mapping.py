import json
from pathlib import Path

from scripts.reviews.analyze_nutrime_mapping import analyze


def test_mapping_failure_queue_classifies_missing_product_id(tmp_path: Path) -> None:
    input_path = tmp_path / "reviews.jsonl"
    input_path.write_text(
        json.dumps({"source_review_id": "1", "source_product_id": "", "product_name": "", "review_text": "좋아요"}, ensure_ascii=False) + "\n"
        + json.dumps({"source_review_id": "2", "source_product_id": "p1", "product_name": "상품", "review_text": "좋아요"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report = analyze(input_path, tmp_path / "out", fetch_product_pages=False)
    assert report["total_reviews"] == 2
    assert report["mapped_reviews"] == 1
    assert report["unresolved_count"] == 1
    assert report["failure_types"] == {"PRODUCT_ID_NOT_FOUND": 1}
