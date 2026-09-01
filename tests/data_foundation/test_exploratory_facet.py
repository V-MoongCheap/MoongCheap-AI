import pandas as pd

from moongcheap_ai.parts.aihub.exploratory_facet import build_exploratory_facets


def test_exploratory_facet_keeps_health_taxonomy_separate(tmp_path):
    frame = pd.DataFrame([
        {"kan_code": "K1", "source_category_name": "식품", "product_name_normalized": "분말 비타민", "fragile": "False", "refrigerate": "False", "length": "10", "width": "2", "height": "3", "weight": "1"},
        {"kan_code": "K1", "source_category_name": "식품", "product_name_normalized": "분말 홍삼", "fragile": "False", "refrigerate": "True", "length": "11", "width": "2", "height": "3", "weight": "1"},
        {"kan_code": "K1", "source_category_name": "식품", "product_name_normalized": "분말 유산균", "fragile": "True", "refrigerate": "False", "length": "12", "width": "2", "height": "3", "weight": "2"},
    ])

    result = build_exploratory_facets(
        frame,
        tmp_path / "terms.csv",
        tmp_path / "structured.csv",
        tmp_path / "queue.csv",
        tmp_path / "taxonomy.json",
        min_documents=2,
        min_ratio=0,
    )

    assert result["status"] == "COMPLETED"
    assert result["category_count"] == 1
    assert "EXPLORATORY_PENDING_REVIEW" in (tmp_path / "taxonomy.json").read_text(encoding="utf-8")
    assert "functional_ingredients" not in (tmp_path / "taxonomy.json").read_text(encoding="utf-8")
