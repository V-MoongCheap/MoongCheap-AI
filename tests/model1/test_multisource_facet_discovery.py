from __future__ import annotations

import pandas as pd

from scripts.model1 import run_multisource_facet_discovery as runner


def _source(category: str, source_type: str, source_id: str, price: str = "") -> pd.DataFrame:
    return pd.DataFrame([{
        "category_key": category,
        "category_name": category,
        "source_product_id": source_id,
        "product_name": "상품",
        "source_category": "건강기능식품",
        "product_form": "정제",
        "functional_ingredients": "비타민",
        "regulated_function": "",
        "consumer_search_text": "",
        "intake_method": "1일 1회",
        "sampling_reason": "test",
        "source_type": source_type,
        "price_text": price,
        "quantity_text": "1",
        "seller_condition": "",
        "evidence_text": "상품 | 정제 | 비타민",
    }])


def test_build_input_keeps_all_observed_categories(monkeypatch) -> None:
    frames = {
        "products": _source("health-functional-food:vitamin_mineral", "MFDS_PRODUCT", "p1"),
        "sellers": _source("health-functional-food:propolis", "SELLER_LISTING", "s1"),
        "queries": _source("health-functional-food:eye_health", "CONSUMER_SEARCH", "q1"),
    }
    monkeypatch.setattr(runner, "load_products", lambda *args, **kwargs: frames["products"])
    monkeypatch.setattr(runner, "load_seller_offers", lambda *args, **kwargs: frames["sellers"])
    monkeypatch.setattr(runner, "load_translated_queries", lambda *args, **kwargs: frames["queries"])

    result = runner.build_multisource_input({"products": "p", "sellers": "s", "queries": "q"})

    assert set(result["category_key"]) == {
        "health-functional-food:vitamin_mineral",
        "health-functional-food:propolis",
        "health-functional-food:eye_health",
    }
    assert "GROUNDED_DEMAND_SYNTHETIC" not in set(result["source_type"])


def test_model_does_not_receive_price_as_facet_evidence(monkeypatch) -> None:
    captured: list[list[dict]] = []

    class Adapter:
        provider = "test"
        model = "test-model"

        def generate_facet_candidates(self, category, products, prompt_version):
            captured.append(products)
            return {
                "category_key": category,
                "category_name": category,
                "facets": [{
                    "facet_id_candidate": "product_form",
                    "name": "product_form",
                    "definition": "form",
                    "selection_reason": "observed",
                    "values": [{"value": "정제", "aliases": [], "value_reason": "observed"}],
                    "evidence": [{"source_product_id": "p1", "source_field": "product_form", "source_text": "정제"}],
                }],
            }

    monkeypatch.setattr(runner, "create_model_adapter", lambda *args, **kwargs: Adapter())
    data = _source("health-functional-food:vitamin_mineral", "MFDS_PRODUCT", "p1", price="9999")
    _raw, candidates, _report, failures = runner.run_model(
        "test-model", data, {"health-functional-food:vitamin_mineral"}, retries=0
    )

    assert not failures
    assert candidates
    assert captured[0][0]["price_text"] == ""

