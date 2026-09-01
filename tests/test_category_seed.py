import pandas as pd
import pytest

from moongcheap_ai.category_seed import CategorySeedError, build_health_category_seed


def test_health_seed_uses_observed_mfds_product_types() -> None:
    result = build_health_category_seed(pd.DataFrame({"product_type": ["비타민", "비타민", "프로바이오틱스"]}))
    assert list(result["name"]) == ["건강기능식품", "비타민", "프로바이오틱스"]
    assert result.iloc[1]["parent_key"] == "health-functional-food"
    assert result.iloc[1]["source"] == "MFDS_OBSERVED"


def test_empty_mfds_is_blocked() -> None:
    with pytest.raises(CategorySeedError):
        build_health_category_seed(pd.DataFrame(columns=["product_type"]))
