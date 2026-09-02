import pandas as pd

from moongcheap_ai.data_foundation.category_v2_1 import build_category_v2_1, classify_v2_1


def test_v21_promotes_only_approved_other_candidates():
    row = pd.Series({"product_type": "콜라겐", "functional_ingredients": "콜라겐", "main_functionality": "피부 건강", "name": "콜라겐"})
    key, name, _, _ = classify_v2_1(row)
    assert key == "SKIN_COLLAGEN"
    assert name == "피부·콜라겐"


def test_v21_keeps_ids_blank_and_preserves_unmapped(tmp_path):
    frame = pd.DataFrame([
        {"source_product_id": "1", "name": "콜라겐", "product_type": "콜라겐", "functional_ingredients": "콜라겐", "main_functionality": "피부", "product_form": "정제"},
        {"source_product_id": "2", "name": "미분류", "product_type": "", "functional_ingredients": "", "main_functionality": "", "product_form": "분말"},
    ])
    result = build_category_v2_1(frame, tmp_path)
    assert result["unmapped"] == 1
    tree = pd.read_csv(tmp_path / "service_category_tree_v2_1.csv", dtype=str).fillna("")
    assert tree["category_candidate_key"].str.startswith("health-functional-food").all()
    assert tree["category_candidate_key"].str.contains("skin_collagen").any()
    validation = pd.read_csv(tmp_path / "category_validation_report_v2_1.csv", dtype=str).fillna("")
    assert validation.loc[validation["category_name"] == "피부·콜라겐", "representative_product_names"].iloc[0] == "콜라겐"
