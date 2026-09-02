import pandas as pd

from moongcheap_ai.data_foundation.demand_synthetic import generate_synthetic_demands, prepare_demand_input


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
