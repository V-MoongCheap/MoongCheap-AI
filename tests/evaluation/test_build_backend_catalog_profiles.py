import pandas as pd
import pytest

from scripts.evaluation.build_backend_catalog_profiles import build_profiles


def _taxonomy():
    return {
        "version": "taxonomy-v1",
        "categories": [
            {
                "category_id": "health:vitamin",
                "facets": [],
            }
        ],
    }


def test_build_profiles_keeps_backend_ids_and_excludes_unmapped_categories():
    mapping = pd.DataFrame(
        [
            {"catalog_id": "1990", "catalog_seed_id": "seed-a", "source_category_id": "health:vitamin"},
            {"catalog_id": "1991", "catalog_seed_id": "seed-b", "source_category_id": ""},
        ]
    )
    facets = pd.DataFrame(
        [
            {
                "catalog_id": "seed-a",
                "facet_name": "product_form",
                "value": "정제",
                "mapping_status": "MAPPED",
            },
            {
                "catalog_id": "seed-a",
                "facet_name": "functional_ingredients",
                "value": "비타민C",
                "mapping_status": "MAPPED",
            },
        ]
    )
    catalog = pd.DataFrame([{"id": "1990", "name": "상품 A"}, {"id": "1991", "name": "상품 B"}])

    profiles, summary = build_profiles(mapping, facets, catalog, _taxonomy())

    assert profiles["catalog_id"].tolist() == ["1990"]
    assert profiles.loc[0, "product_form"] == "정제"
    assert profiles.loc[0, "functional_ingredients_json"] == '["비타민C"]'
    assert summary["excluded_without_service_category"] == 1


def test_build_profiles_rejects_mapping_id_absent_from_backend_export():
    mapping = pd.DataFrame(
        [{"catalog_id": "3901", "catalog_seed_id": "seed-a", "source_category_id": "health:vitamin"}]
    )
    facets = pd.DataFrame(columns=["catalog_id", "facet_name", "value", "mapping_status"])
    catalog = pd.DataFrame([{"id": "1990", "name": "상품 A"}])

    with pytest.raises(ValueError, match="absent from Backend export"):
        build_profiles(mapping, facets, catalog, _taxonomy())
