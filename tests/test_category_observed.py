import pandas as pd

from moongcheap_ai.data_foundation.category import (
    build_aihub_category_hierarchy,
    build_observed_kan,
)


def test_observed_category_builders_tolerate_missing_optional_columns(tmp_path):
    frame = pd.DataFrame([{"source_product_id": "p1"}])
    assert build_observed_kan(frame, tmp_path / "kan.csv")["observed_kan_codes"] == 0
    assert build_aihub_category_hierarchy(frame, tmp_path / "hierarchy.csv")["category_count"] == 0
