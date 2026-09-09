"""Compile reviewed function coverage into an auditable runtime candidate."""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..function_relation_contract import (
    ARTIFACT_COLUMNS,
    function_direction_id,
    function_relation_artifact_fingerprint,
)


REQUIRED_STATUS_COLUMNS = {
    "direction_id",
    "source_claim_id",
    "source_claim_text",
    "candidate_claim_id",
    "candidate_claim_text",
    "final_coverage_label",
    "final_reason_code",
}


def build_function_relation_runtime_payload(
    artifact: pd.DataFrame,
    summary: dict[str, Any],
) -> dict[str, Any]:
    """Convert the tabular artifact to the versioned Backend JSON contract."""

    if missing := sorted(set(ARTIFACT_COLUMNS) - set(artifact.columns)):
        raise ValueError(
            "relation artifact missing runtime columns: " + ", ".join(missing)
        )
    expected_fingerprint = function_relation_artifact_fingerprint(artifact)
    if summary.get("artifactFingerprintSha256") != expected_fingerprint:
        raise ValueError("summary fingerprint does not match relation artifact")
    if artifact["artifact_version"].nunique() != 1:
        raise ValueError("relation artifact must contain one artifact version")
    if artifact["rule_version"].nunique() != 1:
        raise ValueError("relation artifact must contain one rule version")

    relations = []
    for row in artifact.loc[:, ARTIFACT_COLUMNS].itertuples(
        index=False,
        name=None,
    ):
        values = dict(zip(ARTIFACT_COLUMNS, row, strict=True))
        relations.append({
            "relationId": str(values["relation_id"]),
            "sourceClaimId": str(values["source_claim_id"]),
            "sourceClaimText": str(values["source_claim_text"]),
            "candidateClaimId": str(values["candidate_claim_id"]),
            "candidateClaimText": str(values["candidate_claim_text"]),
            "coverageLabel": str(values["coverage_label"]),
            "ruleVersion": str(values["rule_version"]),
            "artifactVersion": str(values["artifact_version"]),
            "decisionReasonCode": str(values["decision_reason_code"]),
            "decisionProvenance": str(values["decision_provenance"]),
        })
    relations.sort(key=lambda item: item["relationId"])
    return {
        "schemaVersion": summary["schemaVersion"],
        "artifactVersion": summary["artifactVersion"],
        "ruleVersion": summary["ruleVersion"],
        "artifactFingerprintSha256": expected_fingerprint,
        "deploymentStatus": summary["deploymentStatus"],
        "goldStatus": summary["goldStatus"],
        "identityPolicy": summary["identityPolicy"],
        "transitivityPolicy": summary["transitivityPolicy"],
        "runtimePolicy": summary["runtimePolicy"],
        "relations": relations,
    }


def compile_function_relation_artifact(
    named_statuses: dict[str, pd.DataFrame],
    *,
    candidate_directions: pd.DataFrame | None = None,
    artifact_version: str = "mfds-function-coverage-relations-v1",
    rule_version: str = "v3",
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Return complete audit status and a COVERS-only runtime candidate."""

    if not named_statuses:
        raise ValueError("at least one named status is required")
    if not artifact_version.strip():
        raise ValueError("artifact_version must not be blank")
    normalized_frames: list[pd.DataFrame] = []
    source_counts: dict[str, dict[str, int]] = {}
    for provenance, frame in sorted(named_statuses.items()):
        if not provenance.strip():
            raise ValueError("status provenance must not be blank")
        if missing := sorted(REQUIRED_STATUS_COLUMNS - set(frame.columns)):
            raise ValueError(
                f"{provenance} status missing columns: {', '.join(missing)}"
            )
        normalized = frame.fillna("").copy()
        if normalized["direction_id"].duplicated().any():
            raise ValueError(f"{provenance} direction IDs must be unique")
        if normalized["final_coverage_label"].eq("").any():
            raise ValueError(f"{provenance} contains unfinished final labels")
        labels = set(normalized["final_coverage_label"])
        if invalid := sorted(labels - {"COVERS", "DOES_NOT_COVER"}):
            raise ValueError(
                f"{provenance} contains invalid final labels: {', '.join(invalid)}"
            )
        expected_ids = [
            function_direction_id(source_id, candidate_id)
            for source_id, candidate_id in normalized[[
                "source_claim_id",
                "candidate_claim_id",
            ]].astype(str).itertuples(index=False, name=None)
        ]
        if not normalized["direction_id"].astype(str).eq(expected_ids).all():
            raise ValueError(f"{provenance} direction IDs do not match claim pairs")
        if normalized["source_claim_id"].eq(normalized["candidate_claim_id"]).any():
            raise ValueError(f"{provenance} must not contain identity directions")
        eligible = normalized["final_coverage_label"].eq("COVERS")
        if "relation_artifact_eligible" in normalized:
            recorded = normalized["relation_artifact_eligible"].astype(
                str
            ).str.casefold().map({"true": True, "false": False})
            if recorded.isna().any() or not recorded.eq(eligible).all():
                raise ValueError(
                    f"{provenance} artifact eligibility disagrees with final label"
                )
        normalized["relation_artifact_eligible"] = eligible
        normalized["decision_provenance"] = provenance
        normalized_frames.append(normalized)
        source_counts[provenance] = {
            "directions": len(normalized),
            "covers": int(eligible.sum()),
            "doesNotCover": int((~eligible).sum()),
        }

    audit = pd.concat(normalized_frames, ignore_index=True, sort=False).fillna("")
    if audit["direction_id"].duplicated().any():
        duplicates = sorted(audit.loc[
            audit["direction_id"].duplicated(keep=False),
            "direction_id",
        ].unique())
        raise ValueError(
            "status sources overlap direction IDs: " + ", ".join(duplicates)
        )
    claim_text_mappings = pd.concat([
        audit[["source_claim_id", "source_claim_text"]].rename(columns={
            "source_claim_id": "claim_id",
            "source_claim_text": "claim_text",
        }),
        audit[["candidate_claim_id", "candidate_claim_text"]].rename(columns={
            "candidate_claim_id": "claim_id",
            "candidate_claim_text": "claim_text",
        }),
    ], ignore_index=True)
    if claim_text_mappings.groupby("claim_id")["claim_text"].nunique().gt(1).any():
        raise ValueError("claim IDs map to inconsistent claim text")
    audit = audit.sort_values("direction_id", kind="stable").reset_index(drop=True)

    candidate_summary: dict[str, Any] = {}
    if candidate_directions is not None:
        if "direction_id" not in candidate_directions:
            raise ValueError("candidate directions missing column: direction_id")
        if candidate_directions["direction_id"].duplicated().any():
            raise ValueError("candidate direction IDs must be unique")
        candidate_ids = set(candidate_directions["direction_id"].astype(str))
        audit_ids = set(audit["direction_id"].astype(str))
        if missing_ids := sorted(candidate_ids - audit_ids):
            raise ValueError(
                "candidate directions missing final decisions: "
                + ", ".join(missing_ids)
            )
        candidate_audit = audit.loc[audit["direction_id"].isin(candidate_ids)]
        candidate_summary = {
            "candidateSetDirections": len(candidate_ids),
            "candidateSetDecisionsComplete": True,
            "candidateSetCovers": int(candidate_audit[
                "final_coverage_label"
            ].eq("COVERS").sum()),
            "candidateSetDoesNotCover": int(candidate_audit[
                "final_coverage_label"
            ].eq("DOES_NOT_COVER").sum()),
        }

    approved = audit.loc[
        audit["relation_artifact_eligible"],
        [
            "direction_id",
            "source_claim_id",
            "source_claim_text",
            "candidate_claim_id",
            "candidate_claim_text",
            "final_reason_code",
            "decision_provenance",
        ],
    ].copy()
    approved = approved.rename(columns={
        "direction_id": "relation_id",
        "final_reason_code": "decision_reason_code",
    })
    approved.insert(5, "coverage_label", "COVERS")
    approved.insert(6, "rule_version", rule_version)
    approved.insert(7, "artifact_version", artifact_version)
    approved = approved.sort_values("relation_id", kind="stable").reset_index(drop=True)
    summary = {
        "schemaVersion": "mfds-function-coverage-relation-artifact.v1",
        "artifactVersion": artifact_version,
        "ruleVersion": rule_version,
        "statusSourceCounts": source_counts,
        "auditedDirections": len(audit),
        "coversRelations": len(approved),
        "doesNotCoverDirections": int(audit["final_coverage_label"].eq(
            "DOES_NOT_COVER"
        ).sum()),
        **candidate_summary,
        "artifactFingerprintSha256": function_relation_artifact_fingerprint(
            approved
        ),
        "identityPolicy": (
            "An exact source/candidate claim ID match covers by identity and "
            "is not duplicated as a relation row."
        ),
        "transitivityPolicy": (
            "No transitive coverage edges are inferred; only explicitly "
            "reviewed COVERS directions are present."
        ),
        "runtimePolicy": (
            "CPU retrieval may rank candidates, but production passes the hard "
            "gate only for identity or an approved relation artifact edge. "
            "Missing directions abstain without runtime REVIEW."
        ),
        "deploymentStatus": "REQUIRES_DOMAIN_OWNER_SIGNOFF",
        "goldStatus": (
            "LLM_CONSENSUS_CANDIDATE_ONLY: not human or regulatory-domain gold."
        ),
    }
    return audit, approved, summary
