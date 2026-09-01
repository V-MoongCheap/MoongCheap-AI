import pandas as pd

from moongcheap_ai.category_detail import build_category_detail_analysis


def test_detail_analysis_only_writes_review_artifacts(tmp_path):
    frame = pd.DataFrame([
        {"source_product_id": "1", "name": "비타민C", "product_type": "비타민 C", "functional_ingredients": "비타민 C", "main_functionality": "항산화에 도움", "product_form": "정제"},
        {"source_product_id": "2", "name": "칼슘", "product_type": "칼슘", "functional_ingredients": "칼슘", "main_functionality": "뼈 건강", "product_form": "정제"},
        {"source_product_id": "3", "name": "단백질", "product_type": "단백질", "functional_ingredients": "단백질", "main_functionality": "근육", "product_form": "분말"},
    ])
    result = build_category_detail_analysis(frame, tmp_path)
    assert result["categories"]["VITAMIN_MINERAL"] == 2
    assert (tmp_path / "category_detail_analysis_v2.csv").exists()
    assert (tmp_path / "category_detail_analysis_v2.md").exists()
    csv = pd.read_csv(tmp_path / "category_detail_analysis_v2.csv", dtype=str)
    assert set(csv["analysis_type"]) == {"SOURCE_CATEGORY_TOP30", "NORMALIZED_FUNCTIONAL_INGREDIENT_TOP30", "REGULATED_FUNCTION_GROUP", "CANDIDATE_SUBGROUP"}
