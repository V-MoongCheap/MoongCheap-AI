import importlib.util
from pathlib import Path

import pandas as pd


def _load(relative: str, name: str):
    path = Path(__file__).parents[1] / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_manual_reviews_remove_pii_and_medical_outcomes():
    module = _load("scripts/reviews/process_manual_reviews.py", "manual_reviews")
    frame = pd.DataFrame([
        {"source_review_id": "r1", "source_product_id": "p1", "product_name": "건강기능식품", "product_type": "건강기능식품", "review_text": "캡슐이 커서 삼키기 힘들어요 test@example.com"},
        {"source_review_id": "r2", "source_product_id": "p1", "product_name": "건강기능식품", "product_type": "건강기능식품", "review_text": "혈압이 내려갔어요"},
    ])

    result, stats = module.process_reviews(frame)

    assert stats["collected_review_count"] == 2
    assert len(result) == 1
    assert "test@example.com" not in result.iloc[0]["evidence_text"]
    assert result.iloc[0]["evidence_type"] == "CONSUMER_EXPERIENCE"


def test_manual_aggregate_missing_file_is_waiting(tmp_path):
    module = _load("scripts/purchase/ingest_manual_aggregate.py", "manual_aggregate")
    result = module.normalize_aggregate(pd.DataFrame([{"제품명": "상품", "판매건수": "3"}]), "KOREAN_HFF_RETAIL_SALES")

    assert result.iloc[0]["product_name"] == "상품"
    assert result.iloc[0]["market_metric_type"] == "sales_count"
