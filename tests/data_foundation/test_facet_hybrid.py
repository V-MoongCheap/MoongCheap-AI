import pandas as pd

from moongcheap_ai.data_foundation.facet_hybrid import (
    benchmark_candidate_sets,
    build_rule_candidates,
    merge_rule_model_candidates,
)


def _inputs() -> pd.DataFrame:
    return pd.DataFrame([
        {"category_key": "C", "category_name": "프로바이오틱스", "source_product_id": "p1", "source_type": "MFDS_PRODUCT", "product_form": "분말", "functional_ingredients": "유산균"},
        {"category_key": "C", "category_name": "프로바이오틱스", "source_product_id": "p2", "source_type": "SELLER_LISTING", "product_form": "분말", "functional_ingredients": "유산균"},
        {"category_key": "C", "category_name": "프로바이오틱스", "source_product_id": "p3", "source_type": "CONSUMER_SEARCH", "product_form": "캡슐", "functional_ingredients": ""},
    ])


def test_rule_candidates_exclude_consumer_search_and_count_sources() -> None:
    result = build_rule_candidates(_inputs())
    powder = result[(result.facet_id_candidate == "product_form") & (result.value == "분말")]
    assert len(powder) == 2
    assert set(powder.rule_support) == {2}


def test_hybrid_keeps_model_only_as_review() -> None:
    rule = build_rule_candidates(_inputs())
    model = pd.DataFrame([
        {"category_key": "C", "name": "제품 형태", "value": "분말", "source_product_id": "p1", "source_field": "product_form", "model": "gemma"},
        {"category_key": "C", "name": "새로운 형태", "value": "젤리", "source_product_id": "p1", "source_field": "product_form", "model": "gemma"},
    ])
    result = merge_rule_model_candidates(rule, model)
    assert set(result.hybrid_status) == {"HYBRID_BACKED", "RULE_ONLY", "MODEL_ONLY_REVIEW"}
    assert bool(result.loc[result.value == "젤리", "model_only_review_required"].iloc[0])


def test_benchmark_never_auto_accepts_unobserved_model_candidates() -> None:
    rule = build_rule_candidates(_inputs())
    model = pd.DataFrame([{"category_key": "C", "name": "새로운 형태", "value": "젤리", "source_product_id": "p1", "model": "gemma"}])
    hybrid = merge_rule_model_candidates(rule, model)
    metrics = benchmark_candidate_sets(rule, model, hybrid)
    assert metrics["unobserved_model_auto_accept_count"] == 0
    assert metrics["model_only_review_count"] == 1


def test_grounded_source_field_recovers_malformed_model_facet_name() -> None:
    rule = build_rule_candidates(_inputs())
    model = pd.DataFrame([
        {
            "category_key": "C",
            "name": "유산균",
            "value": "유산균",
            "source_product_id": "p1",
            "source_field": "functional_ingredients",
            "model": "kanana",
        }
    ])
    result = merge_rule_model_candidates(rule, model)
    matched = result[(result["facet_id"] == "functional_ingredients") & (result["value"] == "유산균")]
    assert len(matched) == 1
    assert matched.iloc[0]["hybrid_status"] == "HYBRID_BACKED"


def test_rule_candidates_drop_placeholders_and_package_sizes() -> None:
    inputs = pd.DataFrame([
        {
            "category_key": "C",
            "category_name": "C",
            "source_product_id": "p1",
            "source_type": "MFDS_PRODUCT",
            "product_form": "120g / 30포",
            "functional_ingredients": "상세설명참조",
        }
    ])
    result = build_rule_candidates(inputs)
    assert result.empty
