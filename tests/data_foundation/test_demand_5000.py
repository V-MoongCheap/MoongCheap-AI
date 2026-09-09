import json

import pandas as pd

from moongcheap_ai.data_foundation.demand_5000 import SCENARIOS, generate_demand_5000


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
