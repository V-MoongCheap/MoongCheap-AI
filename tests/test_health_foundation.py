import pandas as pd

from moongcheap_ai.data_foundation.health_foundation import build_health_artifacts


def test_health_artifacts_keep_categories_and_ids_reviewable(tmp_path):
    frame = pd.DataFrame([
        {"source_product_id": "1", "name": "A", "product_type": "비타민", "product_form": "정제", "functional_ingredients": "비타민C", "intake_method": "1일 1회", "manufacturer": "M"},
        {"source_product_id": "2", "name": "B", "product_type": "홍삼", "product_form": "액상", "functional_ingredients": "홍삼", "intake_method": "1일 1회", "manufacturer": "N"},
    ])

    result = build_health_artifacts(frame, tmp_path)

    assert result["source_category_count"] == 2
    categories = pd.read_csv(tmp_path / "category_v0.csv", dtype=str).fillna("")
    assert categories["category_id"].eq("").all()
    mapping = pd.read_csv(tmp_path / "product_category_mapping_review.csv", dtype=str).fillna("")
    assert mapping["review_status"].eq("NEEDS_REVIEW").all()
    assert (tmp_path / "taxonomy_review_v0.csv").exists()


def test_health_taxonomy_uses_stable_codes_and_all_zero(tmp_path):
    frame = pd.DataFrame([
        {"source_product_id": "1", "name": "A", "product_type": "비타민", "product_form": "분말", "functional_ingredients": "비타민C", "intake_method": "1일 1회", "manufacturer": "M"},
        {"source_product_id": "2", "name": "B", "product_type": "비타민", "product_form": "정제", "functional_ingredients": "비타민C", "intake_method": "1일 1회", "manufacturer": "N"},
        {"source_product_id": "3", "name": "C", "product_type": "비타민", "product_form": "분말", "functional_ingredients": "비타민D", "intake_method": "1일 2회", "manufacturer": "O"},
    ])

    build_health_artifacts(frame, tmp_path)
    import json

    taxonomy = json.loads((tmp_path / "facet_taxonomy_v0.json").read_text(encoding="utf-8"))
    form = taxonomy["categories"][0]["facets"][0]
    assert form["values"][0]["code"] == 0
    assert form["values"][1]["value"] == "분말"
    assert form["values"][1]["code"] == 1
    assert (tmp_path / "facet_review_queue.csv").exists()
