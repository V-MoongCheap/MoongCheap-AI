import pandas as pd

from scripts.evaluation.export_backend_health_category_mapping import export_mapping


def test_exports_health_rows_and_ancestors(tmp_path) -> None:
    mapping = tmp_path / "mapping.csv"
    categories = tmp_path / "categories.csv"
    pd.DataFrame(
        [
            {"catalog_id": "2001", "backend_name": "건기식", "source_product_id": "p1", "category_key": "cat-v5-식품/건강식품/leaf", "source_category_id": "health:x", "status_backend": "ACTIVE", "match_method": "EXACT"},
            {"catalog_id": "2002", "backend_name": "일반품", "source_product_id": "p2", "category_key": "other", "source_category_id": "", "status_backend": "ACTIVE", "match_method": "EXACT"},
        ]
    ).to_csv(mapping, index=False, encoding="utf-8-sig")
    pd.DataFrame(
        [
            {"category_key": "root", "parent_key": "", "name": "식품", "depth": 1, "facet": "", "source_category_path": "식품", "health_taxonomy_category_id": "", "source": "seed"},
            {"category_key": "cat-v5-식품/건강식품/leaf", "parent_key": "root", "name": "건기식", "depth": 2, "facet": "{}", "source_category_path": "식품 > 건강식품 > leaf", "health_taxonomy_category_id": "health:x", "source": "seed"},
        ]
    ).to_csv(categories, index=False, encoding="utf-8-sig")
    result = export_mapping(mapping, categories, tmp_path / "out")
    assert result["health_products"] == 1
    assert result["non_health_products_excluded"] == 1
    assert len(pd.read_csv(tmp_path / "out/backend_health_category_seed_v1.csv")) == 2
    exported = pd.read_csv(tmp_path / "out/backend_health_catalog_category_mapping_v1.csv", dtype=str)
    assert list(exported.product_catalog_id) == ["2001"]
    assert exported.backend_category_id.iloc[0] != exported.backend_category_id.iloc[0] or pd.isna(exported.backend_category_id.iloc[0])
