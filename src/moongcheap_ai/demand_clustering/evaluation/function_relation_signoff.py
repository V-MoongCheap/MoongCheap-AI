"""Build a risk-prioritized, offline sign-off queue for relation artifacts."""

from __future__ import annotations

from typing import Any

import pandas as pd


REQUIRED_RELATION_COLUMNS = {
    "relation_id",
    "source_claim_id",
    "source_claim_text",
    "candidate_claim_id",
    "candidate_claim_text",
    "coverage_label",
    "decision_reason_code",
    "decision_provenance",
}
REQUIRED_AUDIT_COLUMNS = {
    "direction_id",
    "agreement_status",
    "final_coverage_label",
    "final_reason_code",
}

SCOPE_EXPANSION_REASONS = {
    "CANDIDATE_INCLUDES_SOURCE_ENDPOINT",
    "SAME_ENDPOINT_BROADER_POPULATION_OR_CONTEXT",
}
MECHANISM_REASONS = {"SAME_ENDPOINT_MECHANISM_DETAIL"}


def build_function_relation_signoff_bundle(
    relations: pd.DataFrame,
    audit: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return the offline approval queue and its deterministic risk summary.

    This queue is a release-time data-governance artifact.  It must never be
    mapped to a user-facing runtime REVIEW state.
    """

    if missing := sorted(REQUIRED_RELATION_COLUMNS - set(relations.columns)):
        raise ValueError("relations missing columns: " + ", ".join(missing))
    if missing := sorted(REQUIRED_AUDIT_COLUMNS - set(audit.columns)):
        raise ValueError("audit missing columns: " + ", ".join(missing))
    if relations["relation_id"].duplicated().any():
        raise ValueError("relation IDs must be unique")
    if audit["direction_id"].duplicated().any():
        raise ValueError("audit direction IDs must be unique")
    if set(relations["coverage_label"].astype(str)) != {"COVERS"}:
        raise ValueError("sign-off relations must contain only COVERS rows")

    normalized_relations = relations.fillna("").copy()
    normalized_audit = audit.fillna("").copy()
    audit_by_id = normalized_audit.set_index("direction_id", drop=False)
    relation_ids = set(normalized_relations["relation_id"].astype(str))
    if missing_ids := sorted(relation_ids - set(audit_by_id.index.astype(str))):
        raise ValueError(
            "relations missing from audit: " + ", ".join(missing_ids)
        )
    selected_audit = audit_by_id.loc[
        normalized_relations["relation_id"].astype(str)
    ]
    if not selected_audit["final_coverage_label"].eq("COVERS").all():
        raise ValueError("relation and audit coverage labels disagree")
    if not selected_audit["final_reason_code"].astype(str).reset_index(
        drop=True
    ).eq(
        normalized_relations["decision_reason_code"].astype(str).reset_index(
            drop=True
        )
    ).all():
        raise ValueError("relation and audit reason codes disagree")

    edges = set(zip(
        normalized_relations["source_claim_id"].astype(str),
        normalized_relations["candidate_claim_id"].astype(str),
        strict=True,
    ))
    output_rows = []
    for relation, audit_row in zip(
        normalized_relations.to_dict("records"),
        selected_audit.to_dict("records"),
        strict=True,
    ):
        source_id = str(relation["source_claim_id"])
        candidate_id = str(relation["candidate_claim_id"])
        reason = str(relation["decision_reason_code"])
        reverse_present = (candidate_id, source_id) in edges

        signals = []
        if str(audit_row["agreement_status"]) == "ADJUDICATED":
            signals.append("ADJUDICATED_LABEL_CONFLICT")
        if not reason:
            signals.append("MISSING_DECISION_REASON")
        if not reverse_present:
            signals.append("ASYMMETRIC_COVERAGE")
        if reason in SCOPE_EXPANSION_REASONS:
            signals.append("SCOPE_EXPANSION_OR_INCLUDED_ENDPOINT")
        if reason in MECHANISM_REASONS:
            signals.append("MECHANISM_DETAIL_VARIATION")

        if {
            "ADJUDICATED_LABEL_CONFLICT",
            "MISSING_DECISION_REASON",
        } & set(signals):
            risk_tier = "HIGH"
            recommendation = "INDIVIDUAL_DOMAIN_REVIEW_REQUIRED"
        elif signals:
            risk_tier = "MEDIUM"
            recommendation = "BATCH_DOMAIN_REVIEW_REQUIRED"
        else:
            risk_tier = "LOW"
            recommendation = "BATCH_DOMAIN_APPROVAL_ELIGIBLE"

        output_rows.append({
            **relation,
            "agreement_status": str(audit_row["agreement_status"]),
            "reverse_relation_present": reverse_present,
            "risk_tier": risk_tier,
            "risk_signals": "|".join(signals),
            "review_recommendation": recommendation,
            "approval_status": "PENDING",
            "reviewer_id": "",
            "reviewed_at": "",
            "review_note": "",
        })

    output = pd.DataFrame(output_rows).sort_values(
        ["risk_tier", "relation_id"],
        key=lambda column: (
            column.map({"HIGH": 0, "MEDIUM": 1, "LOW": 2})
            if column.name == "risk_tier"
            else column
        ),
        kind="stable",
    ).reset_index(drop=True)
    risk_counts = {
        tier: int(output["risk_tier"].eq(tier).sum())
        for tier in ("HIGH", "MEDIUM", "LOW")
    }
    signal_counts = {
        signal: int(output["risk_signals"].str.split("|").map(
            lambda values: signal in values
        ).sum())
        for signal in (
            "ADJUDICATED_LABEL_CONFLICT",
            "MISSING_DECISION_REASON",
            "ASYMMETRIC_COVERAGE",
            "SCOPE_EXPANSION_OR_INCLUDED_ENDPOINT",
            "MECHANISM_DETAIL_VARIATION",
        )
    }
    summary = {
        "schemaVersion": "mfds-function-relation-signoff-bundle.v1",
        "relations": len(output),
        "riskTierCounts": risk_counts,
        "riskSignalCounts": signal_counts,
        "pendingApproval": int(output["approval_status"].eq("PENDING").sum()),
        "runtimeReviewRows": 0,
        "policy": (
            "Sign-off is an offline release gate. Unapproved or missing "
            "relations produce no runtime substitute proposal."
        ),
    }
    return output, summary
