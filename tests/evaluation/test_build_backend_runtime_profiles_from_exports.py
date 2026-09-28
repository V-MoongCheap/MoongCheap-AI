import json

import pandas as pd

from scripts.evaluation.build_backend_runtime_profiles_from_exports import build_profiles_from_exports


def test_build_profiles_keeps_all_backend_ids_and_marks_missing_facets() -> None:
    mapping = pd.DataFrame([
        {"product_catalog.id": "1990", "product_catalog.name": "상품 A", "product_catalog.category_id": "10", "source_product_id": "s1"},
        {"product_catalog.id": "1991", "product_catalog.name": "상품 B", "product_catalog.category_id": "11", "source_product_id": "s2"},
    ])
    categories = pd.DataFrame([
        {"id": "10", "name": "프로바이오틱스", "facet": json.dumps({"category_id": "health-functional-food:probiotics"}, ensure_ascii=False)},
        {"id": "11", "name": "철분", "facet": ""},
    ])
    facets = pd.DataFrame([
        {"source_product_id": "s1", "facet_name": "product_form", "value": "캡슐", "mapping_status": "MAPPED"},
    ])
    taxonomy = {"version": "v1", "categories": [
        {"category_id": "health-functional-food:probiotics", "facets": []},
        {"category_id": "health-functional-food:vitamin_mineral", "facets": []},
    ]}

    profiles, summary = build_profiles_from_exports(mapping, categories, facets, taxonomy)

    assert profiles["catalog_id"].tolist() == ["1990", "1991"]
    assert profiles.loc[0, "profile_status"] == "EVIDENCE_READY"
    assert profiles.loc[1, "service_category_id"] == "health-functional-food:vitamin_mineral"
    assert profiles.loc[1, "profile_status"] == "INSUFFICIENT_EVIDENCE"
    assert summary["profile_rows"] == 2


def test_build_profiles_rejects_missing_category_id() -> None:
    mapping = pd.DataFrame([{"product_catalog.id": "1990", "product_catalog.name": "상품", "product_catalog.category_id": "99"}])
    categories = pd.DataFrame(columns=["id", "name", "facet"])
    facets = pd.DataFrame(columns=["source_product_id", "facet_name", "value", "mapping_status"])
    with __import__("pytest").raises(ValueError, match="missing Backend category"):
        build_profiles_from_exports(mapping, categories, facets, {"version": "v1", "categories": []})
