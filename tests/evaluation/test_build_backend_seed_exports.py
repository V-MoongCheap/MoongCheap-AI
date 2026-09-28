import pandas as pd

from scripts.evaluation.build_backend_seed_exports import build_exports


def test_build_exports_replaces_seed_ids_with_backend_ids() -> None:
    categories = pd.DataFrame([{
        "id": "16", "parent_id": "7", "name": "비타민", "depth": "4",
        "facet": "{}", "created_at": "", "updated_at": "",
    }])
    backend_mapping = pd.DataFrame([{
        "product_catalog.id": "1990", "product_catalog.name": "상품 A",
        "product_catalog.category_id": "16",
    }])
    old_products = pd.DataFrame([{
        "catalog_seed_id": "seed-a", "name": "상품 A", "category_id": "seed-cat",
        "spec_summary": "", "list_price": "", "thumbnail_url": "",
        "description": "", "status": "ACTIVE", "source": "TEST",
        "source_category_path": "식품", "source_category_id": "health:vitamin",
        "source_status": "판매중",
    }])
    old_mapping = pd.DataFrame([{
        "catalog_id": "1990", "catalog_seed_id": "seed-a", "source_product_id": "s1",
    }])

    _, products, summary = build_exports(categories, backend_mapping, old_products, old_mapping)

    assert products.loc[0, "id"] == "1990"
    assert products.loc[0, "category_id"] == "16"
    assert products.loc[0, "source_product_id"] == "s1"
    assert summary["product_rows"] == 1
