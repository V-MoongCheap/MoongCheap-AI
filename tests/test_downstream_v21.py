import pandas as pd

from moongcheap_ai.downstream_v21 import build_provisional_taxonomy, run_downstream_v21


def _frame():
    return pd.DataFrame([
        {"source_product_id": "1", "name": "비타민C", "product_type": "비타민 C", "functional_ingredients": "비타민 C", "main_functionality": "항산화", "product_form": "정제", "intake_method": "1일 1회 1정", "standard_spec": "", "manufacturer": "M"},
        {"source_product_id": "2", "name": "콜라겐", "product_type": "콜라겐", "functional_ingredients": "콜라겐", "main_functionality": "피부", "product_form": "분말", "intake_method": "1일 2회 1포", "standard_spec": "", "manufacturer": "M"},
        {"source_product_id": "3", "name": "미분류", "product_type": "", "functional_ingredients": "", "main_functionality": "", "product_form": "", "intake_method": "", "standard_spec": "", "manufacturer": "M"},
    ])


def test_v21_taxonomy_is_provisional_and_uses_category_groups(tmp_path):
    from moongcheap_ai.downstream_v21 import _catalog_and_types
    catalog, _ = _catalog_and_types(_frame())
    taxonomy, review, summary = build_provisional_taxonomy(_frame(), catalog)
    assert taxonomy["status"] == "PROVISIONAL"
    assert len(taxonomy["categories"]) >= 1
    assert not review.empty
    assert "category_name" in summary.columns


def test_downstream_keeps_unmapped_and_exports_clustering_input(tmp_path):
    result = run_downstream_v21(_frame(), tmp_path, count=8)
    assert result["unmapped"] == 1
    assert (tmp_path / "product_catalog_v2_1_provisional.csv").exists()
    assert (tmp_path / "clustering_input_v2_1.csv").exists()
    cluster = pd.read_csv(tmp_path / "clustering_input_v2_1.csv", dtype=str).fillna("")
    assert cluster["taxonomy_status"].eq("PROVISIONAL").all()
    assert cluster["data_origin"].eq("MOCK").all()
