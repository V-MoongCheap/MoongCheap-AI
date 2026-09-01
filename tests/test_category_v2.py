import pandas as pd

from moongcheap_ai.category_v2 import build_category_v2, classify_service_group


def test_category_group_uses_product_facts_not_recognition_number():
    row = pd.Series({"product_type": "홍삼 (제2025-46호)", "functional_ingredients": "홍삼", "main_functionality": "면역력", "name": "홍삼 제품"})
    key, name, confidence = classify_service_group(row)
    assert key == "RED_GINSENG"
    assert name == "홍삼·인삼"
    assert confidence > 0


def test_category_v2_keeps_unmapped_products_and_fake_ids_blank(tmp_path):
    frame = pd.DataFrame([
        {"source_product_id": "1", "name": "홍삼", "product_type": "홍삼", "functional_ingredients": "홍삼", "main_functionality": "면역", "product_form": "액상"},
        {"source_product_id": "2", "name": "미분류", "product_type": "", "functional_ingredients": "", "main_functionality": "", "product_form": "분말"},
    ])
    result = build_category_v2(frame, tmp_path)
    assert result["unmapped_products"] == 1
    mapping = pd.read_csv(tmp_path / "product_service_category_mapping_v2.csv", dtype=str).fillna("")
    assert mapping.loc[1, "service_category_candidate_key"] == "UNMAPPED"
    tree = pd.read_csv(tmp_path / "service_category_tree_v2.csv", dtype=str).fillna("")
    assert tree["category_candidate_key"].str.startswith("health-functional-food").all()
