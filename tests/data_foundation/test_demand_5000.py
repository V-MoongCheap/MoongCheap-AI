import json

import pandas as pd

from moongcheap_ai.data_foundation.demand_5000 import SCENARIOS, generate_demand_5000, load_catalog


def test_demand_5000_generator_keeps_profiles_and_provenance(tmp_path) -> None:
    products = tmp_path / "products.csv"
    mapping = tmp_path / "mapping.csv"
    taxonomy = tmp_path / "taxonomy.json"
    facets = tmp_path / "facets.csv"
    pd.DataFrame({"source_product_id": ["p1", "p2"], "name": ["상품1", "상품2"]}).to_csv(products, index=False)
    pd.DataFrame({
        "source_product_id": ["p1", "p2"],
        "product_name": ["상품1", "상품2"],
        "service_category_candidate_key": ["C1", "C1"],
        "service_category_name": ["카테고리", "카테고리"],
    }).to_csv(mapping, index=False)
    taxonomy.write_text(json.dumps({"categories": [{"category_id": "health-functional-food:c1", "facets": [{
        "name": "product_form", "order": 1, "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "캡슐", "aliases": ["캡슐형"]}],
    }]}]}, ensure_ascii=False), encoding="utf-8")
    pd.DataFrame({
        "source_product_id": ["p1"], "facet_name": ["product_form"], "value": ["캡슐"], "mapping_status": ["MAPPED"],
    }).to_csv(facets, index=False)

    result = generate_demand_5000(products, mapping, taxonomy, facets, count=48, seed=7)

    assert len(result) == 48
    assert result["demand_id"].is_unique
    assert result["profile_id"].duplicated().any()
    assert set(result["scenario_type"]) == set(SCENARIOS)
    assert result["data_origin"].eq("SYNTHETIC_GROUNDED").all()
    assert result["price_origin"].eq("MOCK_POLICY").all()


def test_demand_5000_uses_planned_scenario_distribution_and_source_columns(tmp_path) -> None:
    products = tmp_path / "products.csv"
    mapping = tmp_path / "mapping.csv"
    taxonomy = tmp_path / "taxonomy.json"
    facets = tmp_path / "facets.csv"
    pd.DataFrame({
        "source_product_id": ["p1"],
        "name": ["상품1"],
        "source_review_id": ["review-1"],
        "source_keyword": ["유산균 분말"],
        "source_document_id": ["doc-1"],
        "source_text": ["실제 상품 근거 문장"],
    }).to_csv(products, index=False)
    pd.DataFrame({
        "source_product_id": ["p1"],
        "product_name": ["상품1"],
        "service_category_candidate_key": ["C1"],
        "service_category_name": ["카테고리"],
    }).to_csv(mapping, index=False)
    taxonomy.write_text(json.dumps({"categories": [{"category_id": "health-functional-food:c1", "facets": [{
        "name": "product_form", "order": 1, "values": [
            {"code": 0, "value": "ALL"},
            {"code": 1, "value": "캡슐", "aliases": ["캡슐형"]},
        ],
    }]}]}, ensure_ascii=False), encoding="utf-8")
    pd.DataFrame({
        "source_product_id": ["p1"], "facet_name": ["product_form"],
        "value": ["캡슐"], "mapping_status": ["MAPPED"],
    }).to_csv(facets, index=False)

    result = generate_demand_5000(products, mapping, taxonomy, facets, count=100, seed=7)
    counts = result["scenario_type"].value_counts().to_dict()

    assert counts == {
        "NO_EXTRA_REQUIREMENT": 20,
        "SINGLE_FACET": 25,
        "MULTI_FACET": 20,
        "PREFERENCE": 10,
        "NEGATION": 10,
        "AMBIGUOUS": 5,
        "CONFLICT": 5,
        "OUT_OF_TAXONOMY": 5,
    }
    assert result["source_product_id"].eq("p1").all()
    assert result["source_review_id"].eq("review-1").all()
    assert result["source_keyword"].eq("유산균 분말").all()
    assert result["generation_method"].eq("TAXONOMY_VALUE_TEMPLATE_FROM_CANONICAL_PRODUCT").all()
    assert result.loc[result["scenario_type"] == "NO_EXTRA_REQUIREMENT", "extra_requirement"].eq("").all()


def test_load_catalog_accepts_current_catalog_seed_schema(tmp_path) -> None:
    products = tmp_path / "catalog_seed.csv"
    pd.DataFrame({
        "catalog_id": ["catalog-seed-domeggook-1"],
        "source_product_id": ["1"],
        "category_id": ["health-functional-food:probiotics"],
        "category_name": ["유산균"],
        "name": ["테스트 상품"],
    }).to_csv(products, index=False, encoding="utf-8-sig")
    result = load_catalog(products, tmp_path / "unused.csv")
    assert result.loc[0, "catalog_id"] == "catalog-seed-domeggook-1"
    assert result.loc[0, "service_category_candidate_key"] == "PROBIOTICS"
