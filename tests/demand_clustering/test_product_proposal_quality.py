from __future__ import annotations

import json

import pandas as pd
import pytest

from moongcheap_ai.demand_clustering.evaluation.product_proposal_quality import (
    CLUSTERING_SCOPE_REASON_CODES,
    build_operational_top1_proposals,
    build_clustering_scope_product_proposal_review_prompt,
    build_product_proposal_review_prompt,
    compile_product_proposal_reviews,
    decisions_to_product_proposal_review,
)


def profiles() -> pd.DataFrame:
    rows = []
    for catalog_id, name, ingredient in (
        ("source", "원상품", "원료A"),
        ("candidate-a", "후보A", "원료B"),
        ("candidate-b", "후보B", "원료A"),
        ("candidate-c", "후보C", "원료C"),
    ):
        rows.append({
            "catalog_id": catalog_id,
            "product_name": name,
            "service_category_id": "health-functional-food:test",
            "product_form": "정",
            "functional_ingredients_json": json.dumps([ingredient]),
            "main_functionality_claim_texts_json": json.dumps(["기능 A"]),
            "intake_method_text": "1일 1회",
            "profile_status": "CANDIDATE_READY",
        })
    return pd.DataFrame(rows)


def candidates(*, primary_eligible: bool = True) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "source_catalog_id": "source",
            "candidate_catalog_id": "candidate-a",
            "rank": 1,
            "score": 0.9,
            "hard_gate_eligible": primary_eligible,
            "coverage_mode": "IDENTITY_ONLY" if primary_eligible else "NOT_COVERED",
        },
        {
            "source_catalog_id": "source",
            "candidate_catalog_id": "candidate-b",
            "rank": 2,
            "score": 0.9,
            "hard_gate_eligible": primary_eligible,
            "coverage_mode": "IDENTITY_ONLY" if primary_eligible else "NOT_COVERED",
        },
        {
            "source_catalog_id": "source",
            "candidate_catalog_id": "candidate-c",
            "rank": 11,
            "score": 0.8,
            "hard_gate_eligible": True,
            "coverage_mode": "RELATION_ASSISTED",
        },
    ])


def test_top1_reproduces_structured_tie_break() -> None:
    result = build_operational_top1_proposals(profiles(), candidates())

    assert len(result) == 1
    assert result.iloc[0]["candidate_catalog_id"] == "candidate-b"
    assert result.iloc[0]["retrieval_rank"] == 2
    assert not result.iloc[0]["fallback_used"]


def test_fallback_is_used_only_without_primary_survivor() -> None:
    result = build_operational_top1_proposals(
        profiles(), candidates(primary_eligible=False)
    )

    assert result.iloc[0]["candidate_catalog_id"] == "candidate-c"
    assert result.iloc[0]["retrieval_rank"] == 11
    assert result.iloc[0]["fallback_used"]


def test_review_prompt_hides_model_decisions_and_scores() -> None:
    review = build_operational_top1_proposals(profiles(), candidates())
    prompt = build_product_proposal_review_prompt(review)

    assert "원상품" in prompt
    assert "후보B" in prompt
    assert "retrieval_score" not in prompt
    assert "coverage_mode" not in prompt


def test_clustering_scope_prompt_contains_only_official_function_evidence() -> None:
    review = build_operational_top1_proposals(profiles(), candidates())
    review.loc[:, "source_product_name"] = "수출용 원료 상품"
    prompt = build_clustering_scope_product_proposal_review_prompt(review)

    assert "기능 A" in prompt
    assert "수출용 원료 상품" not in prompt
    assert "후보B" not in prompt
    assert "원료A" not in prompt
    assert "1일 1회" not in prompt
    assert "retrieval_score" not in prompt
    assert "coverage_mode" not in prompt
    assert "상위 시스템에서 이미 서비스 사용이 승인" in prompt
    assert "오직 아래에 제공된 식품안전나라 공식 기능 문구만" in prompt
    assert "WRONG_PRODUCT_OR_CATEGORY" not in prompt
    assert "MATERIAL_SCOPE_NARROWING" not in prompt


def _review_frame(label: str, reviewer_id: str) -> pd.DataFrame:
    review = build_operational_top1_proposals(profiles(), candidates())
    reason = {
        "PROPOSABLE": "SOURCE_FUNCTIONS_PRESERVED",
        "NOT_PROPOSABLE": "SOURCE_FUNCTION_LOST",
        "INSUFFICIENT_EVIDENCE": "AMBIGUOUS_OFFICIAL_CLAIMS",
    }[label]
    response = json.dumps({
        "decisions": [{
            "proposal_id": review.iloc[0]["proposal_id"],
            "label": label,
            "reason_code": reason,
            "note": "판정 근거입니다.",
        }]
    })
    return decisions_to_product_proposal_review(
        review, response, reviewer_id=reviewer_id
    )


def test_review_response_is_strictly_validated() -> None:
    review = build_operational_top1_proposals(profiles(), candidates())

    with pytest.raises(ValueError, match="invalid reason code"):
        decisions_to_product_proposal_review(
            review,
            json.dumps({"decisions": [{
                "proposal_id": review.iloc[0]["proposal_id"],
                "label": "PROPOSABLE",
                "reason_code": "SOURCE_FUNCTION_LOST",
                "note": "잘못된 조합",
            }]}),
            reviewer_id="reviewer-a",
        )


def test_clustering_scope_rejects_out_of_scope_reason_code() -> None:
    review = build_operational_top1_proposals(profiles(), candidates())

    with pytest.raises(ValueError, match="invalid reason code"):
        decisions_to_product_proposal_review(
            review,
            json.dumps({"decisions": [{
                "proposal_id": review.iloc[0]["proposal_id"],
                "label": "NOT_PROPOSABLE",
                "reason_code": "WRONG_PRODUCT_OR_CATEGORY",
                "note": "클러스터링 책임 밖의 판정",
            }]}),
            reviewer_id="single-judge",
            reason_codes=CLUSTERING_SCOPE_REASON_CODES,
        )


def test_disagreement_becomes_offline_abstain_without_runtime_review() -> None:
    compiled, summary = compile_product_proposal_reviews(
        _review_frame("PROPOSABLE", "reviewer-a"),
        _review_frame("NOT_PROPOSABLE", "reviewer-b"),
    )

    assert compiled.iloc[0]["consensus_label"] == "DISAGREEMENT"
    assert compiled.iloc[0]["offline_disposition"] == "ABSTAIN"
    assert not compiled.iloc[0]["runtime_review_required"]
    assert summary["conservativeAbstainCount"] == 1
    assert summary["runtimeReviewRows"] == 0
