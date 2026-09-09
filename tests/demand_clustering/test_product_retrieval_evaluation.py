from __future__ import annotations

import json

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.product_retrieval_evaluation import (
    build_product_retrieval_texts,
    evaluate_product_retrieval,
)


def test_builds_function_focused_retrieval_text() -> None:
    profiles = pd.DataFrame([{
        "catalog_id": "a",
        "service_category_id": "cat",
        "profile_status": "CANDIDATE_READY",
        "functional_ingredients_json": json.dumps(["루테인"]),
        "main_functionality_claim_texts_json": json.dumps(["눈 건강"]),
        "product_form": "캡슐",
    }])

    function_only = build_product_retrieval_texts(
        profiles,
        text_mode="FUNCTION_ONLY",
    )
    evidence = build_product_retrieval_texts(
        profiles,
        text_mode="FUNCTION_INGREDIENT_FORM",
    )

    assert function_only.at[0, "retrieval_text"] == "주기능: 눈 건강"
    assert "기능성 원료: 루테인" in evidence.at[0, "retrieval_text"]
    assert "제품 형태: 캡슐" in evidence.at[0, "retrieval_text"]


def test_evaluates_source_hit_and_relation_rescue_at_k() -> None:
    profiles = pd.DataFrame([
        {"catalog_id": item, "service_category_id": "cat"}
        for item in ("a", "b", "c")
    ])
    pairs = pd.DataFrame([
        {
            "source_catalog_id": "a",
            "candidate_catalog_id": "b",
            "coverage_mode": "RELATION_ASSISTED",
        },
        {
            "source_catalog_id": "b",
            "candidate_catalog_id": "a",
            "coverage_mode": "IDENTITY_ONLY",
        },
    ])
    scores = pd.DataFrame([
        {"source_catalog_id": "a", "candidate_catalog_id": "b", "score": 0.8},
        {"source_catalog_id": "a", "candidate_catalog_id": "c", "score": 0.9},
        {"source_catalog_id": "b", "candidate_catalog_id": "a", "score": 0.7},
        {"source_catalog_id": "b", "candidate_catalog_id": "c", "score": 0.8},
        {"source_catalog_id": "c", "candidate_catalog_id": "a", "score": 0.9},
        {"source_catalog_id": "c", "candidate_catalog_id": "b", "score": 0.8},
    ])

    _, source_summary, metrics = evaluate_product_retrieval(
        profiles,
        pairs,
        scores,
        top_ks=(1, 2),
    )

    assert metrics["metricsByK"]["1"]["eligibleSourceHitRate"] == 0.0
    assert metrics["metricsByK"]["2"]["eligibleSourceHitRate"] == 1.0
    assert metrics["metricsByK"]["2"]["relationRescuedSourceHitRate"] == 1.0
    assert metrics["metricsByK"]["2"]["allReadySourceWithCandidateRate"] == (
        0.666667
    )
    assert source_summary.set_index("source_catalog_id").at[
        "a", "first_eligible_rank"
    ] == 2
