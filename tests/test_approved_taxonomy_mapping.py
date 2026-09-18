from __future__ import annotations

import pandas as pd

from scripts.model1.build_approved_taxonomy_and_mapping import (
    build_product_mapping,
    build_taxonomy,
)
from scripts.model1.build_human_reviewed_taxonomy_and_mapping import human_approved_candidates


def _approved() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"category_key": "health-functional-food:a", "facet_name": "product_form", "value": "정"},
            {"category_key": "health-functional-food:a", "facet_name": "product_form", "value": "분말"},
            {"category_key": "health-functional-food:a", "facet_name": "functional_ingredients", "value": "비타민 C"},
            {"category_key": "health-functional-food:a", "facet_name": "product_form", "value": "정"},
        ]
    )


def test_taxonomy_is_deterministic_and_all_is_zero() -> None:
    first = build_taxonomy(_approved(), {"health-functional-food:a": "테스트"})
    second = build_taxonomy(_approved().sample(frac=1, random_state=11), {"health-functional-food:a": "테스트"})
    assert first == second
    assert first["status"] == "DRAFT_PENDING_HUMAN_REVIEW"
    assert first["human_approved"] is False
    for facet in first["categories"][0]["facets"]:
        assert facet["values"][0]["value"] == "ALL"
        assert facet["values"][0]["code"] == 0
        assert [value["code"] for value in facet["values"]] == list(range(len(facet["values"])))


def test_product_missing_value_is_unmapped_not_all(monkeypatch) -> None:
    taxonomy = build_taxonomy(_approved(), {"health-functional-food:a": "테스트"})
    products = pd.DataFrame(
        [
            {
                "source_product_id": "p1",
                "name": "비타민 정제",
                "product_type": "비타민",
                "product_form": "",
                "functional_ingredients": "",
                "main_functionality": "",
            },
        ]
    )
    import scripts.model1.build_approved_taxonomy_and_mapping as module

    monkeypatch.setattr(module, "classify_v2_1", lambda _: ("A", "테스트", 1.0, "fixture"))
    mapped = module.build_product_mapping(products, taxonomy)
    assert set(mapped["mapping_status"]) == {"UNMAPPED"}
    assert set(mapped["value"]) == {""}
    assert set(mapped["value_code"]) == {""}


def test_product_observed_values_get_taxonomy_codes(monkeypatch) -> None:
    taxonomy = build_taxonomy(_approved(), {"health-functional-food:a": "테스트"})
    products = pd.DataFrame(
        [
            {
                "source_product_id": "p1",
                "name": "비타민 정제",
                "product_type": "비타민",
                "product_form": "정",
                "functional_ingredients": "비타민 C",
                "main_functionality": "",
            },
        ]
    )
    import scripts.model1.build_approved_taxonomy_and_mapping as module

    monkeypatch.setattr(module, "classify_v2_1", lambda _: ("A", "테스트", 1.0, "fixture"))
    mapped = module.build_product_mapping(products, taxonomy)
    assert set(mapped["mapping_status"]) == {"MAPPED"}
    assert set(mapped["value_code"]) == {1, 2}


def test_human_queue_only_promotes_approve_and_edit() -> None:
    review = pd.DataFrame(
        [
            {
                "category_id": "cat:a",
                "facet_candidate": "product_form",
                "value_candidate": "정",
                "human_review_decision": "APPROVE",
                "human_corrected_values_json": "",
            },
            {
                "category_id": "cat:a",
                "facet_candidate": "functional_ingredients",
                "value_candidate": "복합값",
                "human_review_decision": "EDIT",
                "human_corrected_values_json": '["A", "B"]',
            },
            {
                "category_id": "cat:a",
                "facet_candidate": "product_form",
                "value_candidate": "잘못된값",
                "human_review_decision": "REJECT",
                "human_corrected_values_json": "",
            },
        ]
    )
    candidates = human_approved_candidates(review)
    assert candidates[["facet_name", "value"]].to_dict("records") == [
        {"facet_name": "functional_ingredients", "value": "A"},
        {"facet_name": "functional_ingredients", "value": "B"},
        {"facet_name": "product_form", "value": "정"},
    ]
