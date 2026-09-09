from __future__ import annotations

import pandas as pd
import pytest

from moongcheap_ai.demand_clustering.evaluation.function_relation_annotation import (
    apply_positive_relation_safety_audit,
    compile_function_relation_reviews,
)


def _reviewer_frame(reviewer_id: str) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "review_order": index + 1,
            "direction_id": f"direction-{index}",
            "source_claim_id": f"source-{index}",
            "source_claim_text": f"source text {index}",
            "source_reference_names": "source ref",
            "candidate_claim_id": f"candidate-{index}",
            "candidate_claim_text": f"candidate text {index}",
            "candidate_reference_names": "candidate ref",
            "coverage_label": "",
            "reason_code": "",
            "reviewer_id": reviewer_id,
            "review_note": "",
        }
        for index in range(4)
    ])


def test_compiles_pending_agreement_and_disagreement_statuses() -> None:
    reviewer_a = _reviewer_frame("alice")
    reviewer_b = _reviewer_frame("bob").iloc[::-1].reset_index(drop=True)
    reviewer_a.loc[0, ["coverage_label", "reason_code"]] = [
        "COVERS",
        "SAME_ENDPOINT_EQUIVALENT_WORDING",
    ]
    reviewer_b.loc[
        reviewer_b["direction_id"].eq("direction-0"),
        ["coverage_label", "reason_code"],
    ] = ["COVERS", "SAME_ENDPOINT_EQUIVALENT_WORDING"]
    reviewer_a.loc[1, ["coverage_label", "reason_code"]] = [
        "COVERS",
        "SAME_ENDPOINT_MECHANISM_DETAIL",
    ]
    reviewer_b.loc[
        reviewer_b["direction_id"].eq("direction-1"),
        ["coverage_label", "reason_code"],
    ] = ["DOES_NOT_COVER", "CANDIDATE_SCOPE_NARROWER"]
    reviewer_a.loc[2, ["coverage_label", "reason_code"]] = [
        "DOES_NOT_COVER",
        "DIFFERENT_ENDPOINT",
    ]

    combined, summary = compile_function_relation_reviews(reviewer_a, reviewer_b)

    statuses = combined.set_index("direction_id")["agreement_status"].to_dict()
    assert statuses == {
        "direction-0": "AGREEMENT",
        "direction-1": "ADJUDICATION_REQUIRED",
        "direction-2": "PENDING_REVIEWER_B",
        "direction-3": "PENDING_BOTH",
    }
    agreed = combined.set_index("direction_id").loc["direction-0"]
    assert agreed["final_coverage_label"] == "COVERS"
    assert agreed["final_reason_code"] == "SAME_ENDPOINT_EQUIVALENT_WORDING"
    assert summary == {
        "schemaVersion": "mfds-function-relation-review-status.v1",
        "rubricVersion": "v1",
        "totalQuestions": 4,
        "reviewerAId": "alice",
        "reviewerBId": "bob",
        "reviewedByA": 3,
        "reviewedByB": 2,
        "pendingBoth": 1,
        "pendingReviewerA": 0,
        "pendingReviewerB": 1,
        "agreements": 1,
        "adjudicationRequired": 1,
        "independentReviewsComplete": False,
        "goldStatus": (
            "NOT_READY: independent reviews or adjudication are incomplete."
        ),
    }


def test_rejects_reason_that_does_not_belong_to_label() -> None:
    reviewer_a = _reviewer_frame("alice")
    reviewer_b = _reviewer_frame("bob")
    reviewer_a.loc[0, ["coverage_label", "reason_code"]] = [
        "COVERS",
        "DIFFERENT_ENDPOINT",
    ]

    with pytest.raises(ValueError, match="invalid for COVERS"):
        compile_function_relation_reviews(reviewer_a, reviewer_b)


def test_rejects_changed_question_or_same_reviewer() -> None:
    reviewer_a = _reviewer_frame("alice")
    reviewer_b = _reviewer_frame("bob")
    reviewer_b.loc[0, "candidate_claim_text"] = "changed evidence"
    with pytest.raises(ValueError, match="claim evidence must match"):
        compile_function_relation_reviews(reviewer_a, reviewer_b)

    reviewer_b = _reviewer_frame("alice")
    with pytest.raises(ValueError, match="identifiers must be different"):
        compile_function_relation_reviews(reviewer_a, reviewer_b)


def test_rejects_partial_decision() -> None:
    reviewer_a = _reviewer_frame("alice")
    reviewer_b = _reviewer_frame("bob")
    reviewer_a.loc[0, "coverage_label"] = "COVERS"

    with pytest.raises(ValueError, match="provide both label and reason"):
        compile_function_relation_reviews(reviewer_a, reviewer_b)


def test_v2_accepts_distinct_broader_scope_and_missing_endpoint_reasons() -> None:
    reviewer_a = _reviewer_frame("alice").iloc[:2].copy()
    reviewer_b = _reviewer_frame("bob").iloc[:2].copy()
    decisions = [
        ["COVERS", "SAME_ENDPOINT_BROADER_POPULATION_OR_CONTEXT"],
        ["DOES_NOT_COVER", "SOURCE_ENDPOINT_NOT_FULLY_COVERED"],
    ]
    for index, decision in enumerate(decisions):
        reviewer_a.loc[index, ["coverage_label", "reason_code"]] = decision
        reviewer_b.loc[index, ["coverage_label", "reason_code"]] = decision

    _, summary = compile_function_relation_reviews(
        reviewer_a,
        reviewer_b,
        rubric_version="v2",
    )

    assert summary["rubricVersion"] == "v2"
    assert summary["agreements"] == 2


def test_v22_uses_the_v2_reason_code_family() -> None:
    reviewer_a = _reviewer_frame("alice").iloc[:1].copy()
    reviewer_b = _reviewer_frame("bob").iloc[:1].copy()
    for reviewer in (reviewer_a, reviewer_b):
        reviewer.loc[0, ["coverage_label", "reason_code"]] = [
            "COVERS",
            "SAME_ENDPOINT_BROADER_POPULATION_OR_CONTEXT",
        ]

    _, summary = compile_function_relation_reviews(
        reviewer_a,
        reviewer_b,
        rubric_version="v2.2",
    )

    assert summary["rubricVersion"] == "v2.2"
    assert summary["agreements"] == 1


def test_label_only_scope_accepts_reason_disagreement_without_inventing_reason() -> None:
    reviewer_a = _reviewer_frame("alice").iloc[:1].copy()
    reviewer_b = _reviewer_frame("bob").iloc[:1].copy()
    reviewer_a.loc[0, ["coverage_label", "reason_code"]] = [
        "DOES_NOT_COVER",
        "DIFFERENT_BODY_TARGET",
    ]
    reviewer_b.loc[0, ["coverage_label", "reason_code"]] = [
        "DOES_NOT_COVER",
        "DIFFERENT_ENDPOINT",
    ]

    combined, summary = compile_function_relation_reviews(
        reviewer_a,
        reviewer_b,
        rubric_version="v2.2",
        adjudication_scope="label-only",
    )

    assert combined.at[0, "agreement_status"] == "AGREEMENT"
    assert combined.at[0, "final_coverage_label"] == "DOES_NOT_COVER"
    assert combined.at[0, "final_reason_code"] == ""
    assert summary["labelAgreements"] == 1
    assert summary["labelAndReasonAgreements"] == 0
    assert summary["acceptedReasonDisagreements"] == 1


def test_label_only_scope_accepts_a_quarantined_invalid_reason() -> None:
    reviewer_a = _reviewer_frame("alice").iloc[:1].copy()
    reviewer_b = _reviewer_frame("bob").iloc[:1].copy()
    reviewer_a.loc[0, ["coverage_label", "reason_code"]] = ["COVERS", ""]
    reviewer_b.loc[0, ["coverage_label", "reason_code"]] = [
        "COVERS",
        "SAME_ENDPOINT_EQUIVALENT_WORDING",
    ]

    combined, summary = compile_function_relation_reviews(
        reviewer_a,
        reviewer_b,
        rubric_version="v3",
        adjudication_scope="label-only",
    )

    assert combined.at[0, "agreement_status"] == "AGREEMENT"
    assert combined.at[0, "final_coverage_label"] == "COVERS"
    assert combined.at[0, "final_reason_code"] == ""
    assert summary["labelAgreements"] == 1
    assert summary["labelAndReasonAgreements"] == 0


def test_rejects_unknown_adjudication_scope() -> None:
    with pytest.raises(ValueError, match="unknown adjudication scope"):
        compile_function_relation_reviews(
            _reviewer_frame("alice"),
            _reviewer_frame("bob"),
            adjudication_scope="anything",
        )


def test_applies_positive_safety_audit_without_changing_initial_negatives() -> None:
    base = pd.DataFrame([
        {
            "direction_id": "positive",
            "source_claim_id": "a",
            "source_claim_text": "구체 효익",
            "candidate_claim_id": "b",
            "candidate_claim_text": "일반 건강",
            "final_coverage_label": "COVERS",
            "final_reason_code": "SAME_ENDPOINT_EQUIVALENT_WORDING",
        },
        {
            "direction_id": "negative",
            "source_claim_id": "c",
            "source_claim_text": "기능 C",
            "candidate_claim_id": "d",
            "candidate_claim_text": "기능 D",
            "final_coverage_label": "DOES_NOT_COVER",
            "final_reason_code": "DIFFERENT_ENDPOINT",
        },
    ])
    safety = base.iloc[:1].copy()
    safety["final_coverage_label"] = "DOES_NOT_COVER"
    safety["final_reason_code"] = "CANDIDATE_TOO_BROAD_OR_VAGUE"

    output, summary = apply_positive_relation_safety_audit(base, safety)

    by_id = output.set_index("direction_id")
    assert by_id.at["positive", "safety_audit_status"] == (
        "REJECTED_FALSE_POSITIVE"
    )
    assert not bool(by_id.at["positive", "relation_artifact_eligible"])
    assert by_id.at["negative", "final_reason_code"] == "DIFFERENT_ENDPOINT"
    assert summary["initialCovers"] == 1
    assert summary["confirmedCovers"] == 0
    assert summary["rejectedFalsePositives"] == 1
