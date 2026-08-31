import pandas as pd
import pytest

from moongcheap_ai.labeling import TaxonomyLoader, TaxonomyValidationError, label_demands


TAXONOMY = {"categories": [{"category_id": "C1", "facets": [{"name": "sugar_type", "order": 1, "values": [
    {"code": 0, "value": "ALL", "aliases": []}, {"code": 2, "value": "sugar_free", "aliases": ["무설탕"]}
]}]}]}


def test_loader_matches_alias_and_defaults_all() -> None:
    loader = TaxonomyLoader(TAXONOMY)
    matched, warnings = loader.resolve("C1", "무설탕으로")
    assert matched["sugar_type"]["code"] == 2
    assert not warnings
    all_values, _ = loader.resolve("C1", "")
    assert all_values["sugar_type"]["code"] == 0


def test_batch_keeps_required_output_columns() -> None:
    loader = TaxonomyLoader(TAXONOMY)
    result = label_demands(pd.DataFrame([{"demand_id": "D1", "catalog_id": "P1", "category_id": "C1", "extra_requirement": "무설탕으로", "desired_quantity": "2"}]), loader)
    assert result.iloc[0]["label"] == "2"
    assert result.iloc[0]["label_status"] == "LABELED"
    assert result.iloc[0]["quantity"] == "2"


def test_duplicate_value_codes_are_rejected() -> None:
    invalid = {"categories": [{"category_id": "C1", "facets": [{"name": "f", "values": [{"code": 0}, {"code": 0}]}]}]}
    with pytest.raises(TaxonomyValidationError):
        TaxonomyLoader(invalid)
