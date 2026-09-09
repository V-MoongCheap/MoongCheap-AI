import pandas as pd

from moongcheap_ai.data_foundation.facet_evidence import aggregate_evidence, build_review_queue, _extract_text_evidence


def test_text_evidence_drops_medical_claims_and_keeps_only_attributes() -> None:
    frame = pd.DataFrame([
        {"id": "1", "title": "무설탕 캡슐", "category": "vitamin"},
        {"id": "2", "title": "당뇨 치료에 효과", "category": "vitamin"},
    ])
    result = _extract_text_evidence("test", "CONSUMER_QA", frame, ["title"], "category", "id", "id")
    assert set(result["normalized_value"]) == {"sugar_free", "capsule"}
    assert "price" not in set(result["normalized_attribute"])


def test_cross_source_aggregation_preserves_review_status() -> None:
    frame = pd.DataFrame([
        {"category": "vitamin", "normalized_attribute": "odor", "normalized_value": "fishy", "source": "mfds", "source_type": "PRODUCT_FACT", "document_id": "p1", "medical_risk": "SAFE_ATTRIBUTE"},
        {"category": "vitamin", "normalized_attribute": "odor", "normalized_value": "fishy", "source": "seller", "source_type": "SELLER_LISTING", "document_id": "s1", "medical_risk": "SAFE_ATTRIBUTE"},
    ])
    aggregate = aggregate_evidence(frame)
    queue = build_review_queue(aggregate, frame)
    assert len(aggregate) == 1
    assert aggregate.iloc[0]["source_count"] == 2
    assert aggregate.iloc[0]["review_status"] == "REVIEW"
    assert queue.iloc[0]["review_decision"] == ""
