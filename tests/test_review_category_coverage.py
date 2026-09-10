import json
from pathlib import Path

import pandas as pd

from scripts.reviews.build_hff_review_category_coverage import build_report


def test_category_coverage_keeps_unmapped_reviews_separate(tmp_path: Path) -> None:
    review_dir = tmp_path / "reviews" / "nutrime"
    review_dir.mkdir(parents=True)
    review_path = review_dir / "reviews.jsonl"
    review_path.write_text(json.dumps({"source_review_id": "r1", "source_product_id": "134", "product_name": "쇼핑몰 상품", "review_text": "좋아요"}, ensure_ascii=False) + "\n", encoding="utf-8")
    mapping = tmp_path / "mapping.csv"
    pd.DataFrame([{"source_product_id": "999", "product_name": "다른 상품", "service_category_name": "유산균·프로바이오틱스"}]).to_csv(mapping, index=False)
    categories = tmp_path / "categories.csv"
    pd.DataFrame([{"category_name": "유산균·프로바이오틱스"}]).to_csv(categories, index=False)
    output = tmp_path / "coverage.md"
    result = build_report([review_path], mapping, categories, None, output)
    assert result["mapped_review_count"] == 0
    assert "UNMAPPED_REVIEW_PRODUCT" in output.read_text(encoding="utf-8")
