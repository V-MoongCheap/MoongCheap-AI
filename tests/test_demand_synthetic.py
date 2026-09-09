import pandas as pd

from moongcheap_ai.data_foundation.demand_synthetic import PRICE_OPTIONS, generate_synthetic_demands, prepare_demand_input
from moongcheap_ai.data_foundation.grounded_demand import generate_grounded_demands


def test_synthetic_demands_are_marked_and_catalog_bound() -> None:
    catalog = pd.DataFrame({"catalog_seed_id": ["catalog-1"], "kan_code": ["01150101"]})
    result = generate_synthetic_demands(catalog, count=3, seed=7)
    assert len(result) == 3
    assert result["synthetic"].eq(True).all()
    assert result["catalog_id"].eq("catalog-1").all()
    assert result["source_note"].str.contains("not a user Demand").all()


def test_prepare_demand_input_normalizes_ranges_and_defaults() -> None:
    result = prepare_demand_input(pd.DataFrame([{
        "demand_id": " d1 ", "catalog_id": "c1", "desired_price_min": "50000",
        "desired_price_max": "10000", "quantity": "bad", "is_substitutable": "false",
    }]))
    assert result.loc[0, "demand_id"] == "d1"
    assert result.loc[0, "desired_price_min"] == 50000
    assert result.loc[0, "desired_price_max"] == 50000
    assert result.loc[0, "quantity"] == 1
    assert bool(result.loc[0, "is_substitutable"]) is False
    assert bool(result.loc[0, "synthetic"]) is True


def test_synthetic_price_comes_from_options_and_keeps_open_ended_upper_bound() -> None:
    catalog = pd.DataFrame({"catalog_seed_id": ["catalog-1"]})
    result = generate_synthetic_demands(catalog, count=100, seed=11)
    options = {code: (minimum, maximum) for code, minimum, maximum in PRICE_OPTIONS}
    for row in result.itertuples():
        minimum, maximum = options[row.price_option]
        assert row.desired_price_min == minimum
        if maximum is None:
            assert pd.isna(row.desired_price_max)
        else:
            assert row.desired_price_max == maximum


def test_grounded_demands_use_catalog_taxonomy_and_reference_style(tmp_path) -> None:
    products = tmp_path / "products.csv"
    mapping = tmp_path / "mapping.csv"
    taxonomy = tmp_path / "taxonomy.csv"
    xpqa = tmp_path / "xpqa"
    xpqa.mkdir()
    pd.DataFrame({"source_product_id": ["p1"], "name": ["상품"]}).to_csv(products, index=False)
    pd.DataFrame({"source_product_id": ["p1"], "product_name": ["상품"], "service_category_candidate_key": ["C1"], "service_category_name": ["카테고리"]}).to_csv(mapping, index=False)
    pd.DataFrame({"service_category_key": ["C1"], "service_category_name": ["카테고리"], "facet_name_candidate": ["형태"], "source_field": ["product_form"], "normalized_value": ["정제"], "review_status": ["NEEDS_REVIEW"]}).to_csv(taxonomy, index=False)
    pd.DataFrame({"lang": ["ko"], "question": ["어떤 상품이 있나요?"]}).to_csv(xpqa / "train.csv", index=False)
    result = generate_grounded_demands(products, mapping, taxonomy, xpqa, None, count=2)
    assert result["catalog_id"].eq("catalog-seed-p1").all()
    assert result["extra_requirement"].str.contains("정제").all()
    assert result["reference_source"].eq("xPQA").all()
