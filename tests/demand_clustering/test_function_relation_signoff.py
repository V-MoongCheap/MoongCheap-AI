from __future__ import annotations

import pandas as pd
import pytest

from moongcheap_ai.demand_clustering.evaluation.function_relation_signoff import (
    build_function_relation_signoff_bundle,
)


def _relation(
    relation_id: str,
    source: str,
    candidate: str,
    reason: str,
) -> dict[str, object]:
    return {
        "relation_id": relation_id,
        "source_claim_id": source,
        "source_claim_text": f"text {source}",
        "candidate_claim_id": candidate,
        "candidate_claim_text": f"text {candidate}",
        "coverage_label": "COVERS",
        "rule_version": "v3",
        "artifact_version": "artifact-v1",
        "decision_reason_code": reason,
        "decision_provenance": "TEST",
    }


def _audit(
    relation: dict[str, object],
    agreement: str = "AGREEMENT",
) -> dict[str, object]:
    return {
        "direction_id": relation["relation_id"],
        "agreement_status": agreement,
        "final_coverage_label": "COVERS",
        "final_reason_code": relation["decision_reason_code"],
    }


def test_builds_offline_risk_tiers_without_runtime_review() -> None:
    low_forward = _relation(
        "r1", "a", "b", "SAME_ENDPOINT_EQUIVALENT_WORDING"
    )
    low_reverse = _relation(
        "r2", "b", "a", "SAME_ENDPOINT_EQUIVALENT_WORDING"
    )
    medium = _relation(
        "r3", "a", "c", "CANDIDATE_INCLUDES_SOURCE_ENDPOINT"
    )
    high = _relation("r4", "d", "e", "")
    relations = pd.DataFrame([low_forward, low_reverse, medium, high])
    audit = pd.DataFrame([
        _audit(low_forward),
        _audit(low_reverse),
        _audit(medium),
        _audit(high, "ADJUDICATED"),
    ])

    bundle, summary = build_function_relation_signoff_bundle(relations, audit)

    assert summary["riskTierCounts"] == {"HIGH": 1, "MEDIUM": 1, "LOW": 2}
    assert summary["runtimeReviewRows"] == 0
    assert set(bundle["approval_status"]) == {"PENDING"}
    assert bundle.set_index("relation_id").at["r1", "risk_tier"] == "LOW"
    assert bundle.set_index("relation_id").at["r3", "risk_tier"] == "MEDIUM"
    assert bundle.set_index("relation_id").at["r4", "risk_tier"] == "HIGH"


def test_rejects_audit_relation_label_disagreement() -> None:
    relation = _relation(
        "r1", "a", "b", "SAME_ENDPOINT_EQUIVALENT_WORDING"
    )
    audit = _audit(relation)
    audit["final_coverage_label"] = "DOES_NOT_COVER"

    with pytest.raises(ValueError, match="labels disagree"):
        build_function_relation_signoff_bundle(
            pd.DataFrame([relation]),
            pd.DataFrame([audit]),
        )
