from __future__ import annotations

import pytest

from moongcheap_ai.demand_clustering import (
    RetrievedProductCandidate,
    SubstituteProductProfile,
    assess_substitute_product_pair,
    rank_bounded_substitute_product_candidates,
    rank_substitute_product_candidates,
)


def profile(catalog_id: int, **overrides: object) -> SubstituteProductProfile:
    values: dict[str, object] = {
        "catalogId": catalog_id,
        "productName": f"건강기능식품 {catalog_id}",
        "serviceCategoryId": "health-functional-food:eye-health",
        "taxonomyVersion": "v1",
        "recordType": "FINISHED_PRODUCT",
        "productForm": "캡슐",
        "functionalIngredients": ["루테인"],
        "mainFunctionalityCodes": ["EYE_HEALTH"],
        "mainFunctionalityText": "눈 건강에 도움을 줄 수 있음",
        "intakeMethodText": "하루 한 번 섭취",
        "profileStatus": "APPROVED",
    }
    values.update(overrides)
    return SubstituteProductProfile.from_mapping(values)


def test_function_coverage_is_directional() -> None:
    eye_only = profile(1)
    eye_and_antioxidant = profile(
        2,
        mainFunctionalityCodes=["EYE_HEALTH", "ANTIOXIDANT"],
    )

    forward = assess_substitute_product_pair(eye_only, eye_and_antioxidant)
    reverse = assess_substitute_product_pair(eye_and_antioxidant, eye_only)

    assert forward.eligible_for_semantic_ranking
    assert reverse.decision == "NOT_SUBSTITUTABLE"
    assert "SOURCE_FUNCTION_NOT_COVERED:ANTIOXIDANT" in reverse.reason_codes


def test_approved_directional_relation_can_cover_a_different_claim_code() -> None:
    relation_edges = {("SOURCE_CLAIM", "BROADER_CANDIDATE_CLAIM")}
    source = profile(1, mainFunctionalityCodes=["SOURCE_CLAIM"])
    candidate = profile(
        2,
        mainFunctionalityCodes=["BROADER_CANDIDATE_CLAIM"],
    )

    forward = assess_substitute_product_pair(
        source,
        candidate,
        function_coverage_resolver=lambda left, right: (
            left,
            right,
        ) in relation_edges,
    )
    reverse = assess_substitute_product_pair(
        candidate,
        source,
        function_coverage_resolver=lambda left, right: (
            left,
            right,
        ) in relation_edges,
    )

    assert forward.eligible_for_semantic_ranking
    assert forward.features.directional_function_coverage == 1.0
    assert reverse.decision == "NOT_SUBSTITUTABLE"


def test_unknown_relation_defaults_to_no_offer() -> None:
    result = assess_substitute_product_pair(
        profile(1, mainFunctionalityCodes=["SOURCE_CLAIM"]),
        profile(2, mainFunctionalityCodes=["UNKNOWN_CANDIDATE_CLAIM"]),
        function_coverage_resolver=lambda _left, _right: False,
    )

    assert result.decision == "NOT_SUBSTITUTABLE"
    assert result.reason_codes == (
        "SOURCE_FUNCTION_NOT_COVERED:SOURCE_CLAIM",
    )


def test_missing_evidence_means_no_offer_not_runtime_review() -> None:
    result = assess_substitute_product_pair(
        profile(1),
        profile(
            2,
            functionalIngredients=[],
            profileStatus="PROVISIONAL",
        ),
    )

    assert result.decision == "INSUFFICIENT_EVIDENCE"
    assert "CANDIDATE_PROFILE_NOT_APPROVED" in result.reason_codes
    assert "CANDIDATE_INGREDIENT_EVIDENCE_MISSING" in result.reason_codes


def test_category_mismatch_is_not_substitutable() -> None:
    result = assess_substitute_product_pair(
        profile(1),
        profile(
            2,
            serviceCategoryId="health-functional-food:liver-health",
        ),
    )

    assert result.decision == "NOT_SUBSTITUTABLE"
    assert result.reason_codes == ("SERVICE_CATEGORY_MISMATCH",)


def test_form_difference_is_a_feature_not_a_product_gate() -> None:
    result = assess_substitute_product_pair(
        profile(1, productForm="캡슐"),
        profile(2, productForm="분말"),
    )

    assert result.eligible_for_semantic_ranking
    assert result.features.product_form_match is False


def test_ingredient_overlap_is_exposed_as_structured_baseline() -> None:
    source = profile(
        1,
        functionalIngredients=["루테인", "지아잔틴"],
    )
    partial = profile(
        2,
        functionalIngredients=["루테인", "아스타잔틴"],
    )

    result = assess_substitute_product_pair(source, partial)

    assert result.features.directional_function_coverage == 1.0
    assert result.features.ingredient_jaccard == 0.333333
    assert result.features.structured_baseline_score == 0.666667


def test_semantic_scorer_only_receives_objective_gate_survivors() -> None:
    calls: list[tuple[str, str]] = []

    def scorer(source_card: str, candidate_card: str) -> float:
        calls.append((source_card, candidate_card))
        return 0.8 if "건강기능식품 3" in candidate_card else 0.7

    ranking = rank_substitute_product_candidates(
        profile(1),
        (
            profile(
                2,
                serviceCategoryId="health-functional-food:liver-health",
            ),
            profile(3),
            profile(4),
        ),
        semantic_scorer=scorer,
    )

    assert len(calls) == 2
    assert [item.catalog_id for item in ranking.ranked_candidates] == [3, 4]
    assert [
        item.candidate_catalog_id for item in ranking.rejected_pairs
    ] == [2]


def test_rejects_invalid_semantic_scores() -> None:
    with pytest.raises(ValueError, match="between -1 and 1"):
        rank_substitute_product_candidates(
            profile(1),
            (profile(2),),
            semantic_scorer=lambda _left, _right: 1.1,
        )


def test_bounded_runtime_path_stops_when_primary_window_has_survivor() -> None:
    source = profile(1, mainFunctionalityCodes=["SOURCE"])
    candidates = (
        RetrievedProductCandidate(
            profile(2, mainFunctionalityCodes=["UNKNOWN"]),
            0.9,
        ),
        RetrievedProductCandidate(
            profile(3, mainFunctionalityCodes=["COVERING"]),
            0.8,
        ),
        RetrievedProductCandidate(
            profile(4, mainFunctionalityCodes=["COVERING"]),
            0.7,
        ),
    )

    result = rank_bounded_substitute_product_candidates(
        source,
        candidates,
        function_coverage_resolver=lambda left, right: (
            left,
            right,
        ) == ("SOURCE", "COVERING"),
        primary_limit=2,
        fallback_limit=3,
    )

    assert [item.catalog_id for item in result.ranked_candidates] == [3]
    assert result.retrieval_limit_used == 2
    assert not result.fallback_used
    assert not result.runtime_review_required


def test_bounded_runtime_path_expands_only_after_zero_primary_survivors() -> None:
    source = profile(1, mainFunctionalityCodes=["SOURCE"])
    candidates = (
        RetrievedProductCandidate(
            profile(2, mainFunctionalityCodes=["UNKNOWN_A"]),
            0.9,
        ),
        RetrievedProductCandidate(
            profile(3, mainFunctionalityCodes=["UNKNOWN_B"]),
            0.8,
        ),
        RetrievedProductCandidate(
            profile(4, mainFunctionalityCodes=["COVERING"]),
            0.7,
        ),
    )

    result = rank_bounded_substitute_product_candidates(
        source,
        candidates,
        function_coverage_resolver=lambda left, right: (
            left,
            right,
        ) == ("SOURCE", "COVERING"),
        primary_limit=2,
        fallback_limit=3,
    )

    assert [item.catalog_id for item in result.ranked_candidates] == [4]
    assert result.retrieval_limit_used == 3
    assert result.fallback_used
    assert not result.runtime_review_required
