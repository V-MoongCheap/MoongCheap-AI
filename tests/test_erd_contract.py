import pandas as pd

from moongcheap_ai.erd_contract import validate_catalog_export, validate_category_seed, validate_labeled_demands


def test_category_seed_checks_parent_and_facet_json() -> None:
    frame = pd.DataFrame([{"category_key": "root", "parent_key": "", "name": "건강기능식품", "depth": 1, "facet": ""}, {"category_key": "leaf", "parent_key": "root", "name": "관측분류", "depth": 2, "facet": "{}"}])
    assert validate_category_seed(frame)["status"] == "VALID"


def test_catalog_requires_backend_category_id() -> None:
    result = validate_catalog_export(pd.DataFrame({"id": [1], "name": ["x"]}))
    assert result["status"] == "INVALID"


def test_labeled_demands_require_valid_facet_json() -> None:
    frame = pd.DataFrame({"demand_id": ["D1"], "catalog_id": ["P1"], "label": ["0"], "facet_values": ['{"f":{"code":0}}']})
    assert validate_labeled_demands(frame)["status"] == "VALID"
