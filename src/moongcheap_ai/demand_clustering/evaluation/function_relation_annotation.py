"""Validate and combine independent MFDS function-coverage reviews."""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from .function_relation_pilot import ADJUDICATION_COLUMNS, PILOT_REVIEW_COLUMNS
from .function_relation_review import REVIEW_LABELS


REASON_CODES_BY_LABEL = {
    "COVERS": (
        "SAME_ENDPOINT_EQUIVALENT_WORDING",
        "SAME_ENDPOINT_MECHANISM_DETAIL",
        "CANDIDATE_INCLUDES_SOURCE_ENDPOINT",
    ),
    "DOES_NOT_COVER": (
        "DIFFERENT_BODY_TARGET",
        "DIFFERENT_ENDPOINT",
        "CANDIDATE_SCOPE_NARROWER",
        "CANDIDATE_TOO_BROAD_OR_VAGUE",
        "SHARED_WORDING_ONLY",
    ),
    "INSUFFICIENT_EVIDENCE": (
        "SOURCE_CLAIM_UNCLEAR",
        "CANDIDATE_CLAIM_UNCLEAR",
        "TEMPORAL_OR_REFERENCE_CONFLICT",
    ),
}

REASON_CODES_BY_LABEL_V2 = {
    "COVERS": (
        "SAME_ENDPOINT_EQUIVALENT_WORDING",
        "SAME_ENDPOINT_BROADER_POPULATION_OR_CONTEXT",
        "SAME_ENDPOINT_MECHANISM_DETAIL",
        "CANDIDATE_INCLUDES_SOURCE_ENDPOINT",
    ),
    "DOES_NOT_COVER": (
        "DIFFERENT_BODY_TARGET",
        "DIFFERENT_ENDPOINT",
        "CANDIDATE_SCOPE_NARROWER",
        "SOURCE_ENDPOINT_NOT_FULLY_COVERED",
        "CANDIDATE_TOO_BROAD_OR_VAGUE",
    ),
    "INSUFFICIENT_EVIDENCE": (
        "SOURCE_CLAIM_UNCLEAR",
        "CANDIDATE_CLAIM_UNCLEAR",
        "TEMPORAL_OR_REFERENCE_CONFLICT",
    ),
}


def reason_codes_for_version(version: str) -> dict[str, tuple[str, ...]]:
    if version == "v1":
        return REASON_CODES_BY_LABEL
    if version in {"v2", "v2.1", "v2.2", "v3"}:
        return REASON_CODES_BY_LABEL_V2
    raise ValueError(f"unknown function relation rubric version: {version}")

EVIDENCE_COLUMNS = PILOT_REVIEW_COLUMNS[:5]


def apply_positive_relation_safety_audit(
    base_status: pd.DataFrame,
    safety_status: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Apply conservative re-audit results to initial directional labels."""

    required = {
        "direction_id",
        "source_claim_id",
        "source_claim_text",
        "candidate_claim_id",
        "candidate_claim_text",
        "final_coverage_label",
        "final_reason_code",
    }
    for name, frame in (("base status", base_status), ("safety status", safety_status)):
        if missing := sorted(required - set(frame.columns)):
            raise ValueError(f"{name} missing columns: {', '.join(missing)}")
        if frame["direction_id"].duplicated().any():
            raise ValueError(f"{name} direction_id must be unique")
    base = base_status.fillna("").copy()
    safety = safety_status.fillna("").copy()
    if base["final_coverage_label"].eq("").any():
        raise ValueError("base status must have complete final labels")
    if safety["final_coverage_label"].eq("").any():
        raise ValueError("safety status must have complete final labels")
    positive_ids = set(base.loc[
        base["final_coverage_label"].eq("COVERS"),
        "direction_id",
    ].astype(str))
    safety_ids = set(safety["direction_id"].astype(str))
    if missing_ids := sorted(positive_ids - safety_ids):
        raise ValueError(
            "safety status missing initial COVERS directions: "
            + ", ".join(missing_ids)
        )

    evidence_columns = [
        "source_claim_id",
        "source_claim_text",
        "candidate_claim_id",
        "candidate_claim_text",
    ]
    base_positive = base.loc[
        base["direction_id"].isin(positive_ids),
        ["direction_id", *evidence_columns],
    ].set_index("direction_id")
    safety_subset = safety.loc[
        safety["direction_id"].isin(positive_ids),
        ["direction_id", *evidence_columns, "final_coverage_label", "final_reason_code"],
    ].set_index("direction_id").loc[base_positive.index]
    if not base_positive[evidence_columns].equals(safety_subset[evidence_columns]):
        raise ValueError("safety status claim evidence does not match base status")

    output = base.copy()
    output.insert(
        output.columns.get_loc("final_coverage_label"),
        "pre_safety_coverage_label",
        output["final_coverage_label"],
    )
    output.insert(
        output.columns.get_loc("final_reason_code"),
        "pre_safety_reason_code",
        output["final_reason_code"],
    )
    audit_label = safety_subset["final_coverage_label"].to_dict()
    audit_reason = safety_subset["final_reason_code"].to_dict()
    output["safety_audit_status"] = "NOT_REQUIRED_INITIAL_NEGATIVE"
    for index, direction_id in output["direction_id"].astype(str).items():
        if direction_id not in positive_ids:
            continue
        output.at[index, "final_coverage_label"] = audit_label[direction_id]
        output.at[index, "final_reason_code"] = audit_reason[direction_id]
        output.at[index, "safety_audit_status"] = (
            "CONFIRMED_COVERS"
            if audit_label[direction_id] == "COVERS"
            else "REJECTED_FALSE_POSITIVE"
        )
    output["relation_artifact_eligible"] = output[
        "final_coverage_label"
    ].eq("COVERS")
    rejected = int(output["safety_audit_status"].eq(
        "REJECTED_FALSE_POSITIVE"
    ).sum())
    summary = {
        "schemaVersion": "mfds-function-relation-safety-merge.v1",
        "baseDirections": len(output),
        "initialCovers": len(positive_ids),
        "confirmedCovers": int(output["relation_artifact_eligible"].sum()),
        "rejectedFalsePositives": rejected,
        "finalDoesNotCover": int(output["final_coverage_label"].eq(
            "DOES_NOT_COVER"
        ).sum()),
        "runtimePolicy": (
            "Only confirmed COVERS rows are eligible for the approved relation "
            "artifact; all other rows abstain without runtime REVIEW."
        ),
    }
    return output, summary


def _normalized_review(
    frame: pd.DataFrame,
    slot_name: str,
    reason_codes_by_label: dict[str, tuple[str, ...]],
    *,
    allow_missing_reason: bool = False,
) -> pd.DataFrame:
    if missing := sorted(set(PILOT_REVIEW_COLUMNS) - set(frame.columns)):
        raise ValueError(
            f"{slot_name} frame missing columns: {', '.join(missing)}"
        )
    normalized = frame.loc[:, PILOT_REVIEW_COLUMNS].fillna("").astype(str)
    for column in PILOT_REVIEW_COLUMNS:
        normalized[column] = normalized[column].str.strip()
    if normalized.empty:
        raise ValueError(f"{slot_name} frame must not be empty")
    if normalized["direction_id"].eq("").any():
        raise ValueError(f"{slot_name} direction_id must not be empty")
    if not normalized["direction_id"].is_unique:
        raise ValueError(f"{slot_name} direction_id must be unique")
    if normalized[list(EVIDENCE_COLUMNS[1:])].eq("").any().any():
        raise ValueError(f"{slot_name} claim evidence must not be empty")

    reviewer_ids = sorted(set(normalized["reviewer_id"]))
    if len(reviewer_ids) != 1 or not reviewer_ids[0]:
        raise ValueError(
            f"{slot_name} must contain exactly one non-empty reviewer_id"
        )

    for row in normalized.itertuples(index=False):
        direction_id = row.direction_id
        label = row.coverage_label
        reason = row.reason_code
        if not label and not reason:
            continue
        if not label or (not reason and not allow_missing_reason):
            raise ValueError(
                f"{slot_name} {direction_id} must provide both label and reason"
            )
        if label not in REVIEW_LABELS:
            raise ValueError(
                f"{slot_name} {direction_id} has invalid label: {label}"
            )
        if reason and reason not in reason_codes_by_label[label]:
            raise ValueError(
                f"{slot_name} {direction_id} reason {reason} is invalid "
                f"for {label}"
            )
    return normalized.sort_values("direction_id", kind="stable").reset_index(drop=True)


def _ensure_same_questions(
    reviewer_a: pd.DataFrame,
    reviewer_b: pd.DataFrame,
) -> None:
    if set(reviewer_a["direction_id"]) != set(reviewer_b["direction_id"]):
        raise ValueError("reviewer direction_id sets must match")
    evidence_a = reviewer_a.loc[:, EVIDENCE_COLUMNS].set_index("direction_id")
    evidence_b = reviewer_b.loc[:, EVIDENCE_COLUMNS].set_index("direction_id")
    evidence_b = evidence_b.loc[evidence_a.index]
    if not evidence_a.equals(evidence_b):
        raise ValueError("reviewer claim evidence must match for every direction_id")
    if reviewer_a.at[0, "reviewer_id"] == reviewer_b.at[0, "reviewer_id"]:
        raise ValueError("reviewer A and B identifiers must be different")


def compile_function_relation_reviews(
    reviewer_a: pd.DataFrame,
    reviewer_b: pd.DataFrame,
    *,
    rubric_version: str = "v1",
    adjudication_scope: str = "label-and-reason",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Combine independent reviews without inventing missing or disputed gold."""

    if adjudication_scope not in {"label-and-reason", "label-only"}:
        raise ValueError(f"unknown adjudication scope: {adjudication_scope}")
    reason_codes_by_label = reason_codes_for_version(rubric_version)
    normalized_a = _normalized_review(
        reviewer_a,
        "reviewer A",
        reason_codes_by_label,
        allow_missing_reason=adjudication_scope == "label-only",
    )
    normalized_b = _normalized_review(
        reviewer_b,
        "reviewer B",
        reason_codes_by_label,
        allow_missing_reason=adjudication_scope == "label-only",
    )
    _ensure_same_questions(normalized_a, normalized_b)

    indexed_a = normalized_a.set_index("direction_id")
    indexed_b = normalized_b.set_index("direction_id")
    rows: list[dict[str, str]] = []
    statuses: Counter[str] = Counter()
    for direction_id in indexed_a.index:
        row_a = indexed_a.loc[direction_id]
        row_b = indexed_b.loc[direction_id]
        label_a = row_a["coverage_label"]
        label_b = row_b["coverage_label"]
        reason_a = row_a["reason_code"]
        reason_b = row_b["reason_code"]
        if not label_a and not label_b:
            status = "PENDING_BOTH"
        elif not label_a:
            status = "PENDING_REVIEWER_A"
        elif not label_b:
            status = "PENDING_REVIEWER_B"
        elif label_a == label_b and (
            reason_a == reason_b or adjudication_scope == "label-only"
        ):
            status = "AGREEMENT"
        else:
            status = "ADJUDICATION_REQUIRED"
        statuses[status] += 1

        rows.append({
            "direction_id": direction_id,
            **{column: row_a[column] for column in EVIDENCE_COLUMNS[1:]},
            "reviewer_a_label": label_a,
            "reviewer_a_reason_code": reason_a,
            "reviewer_a_note": row_a["review_note"],
            "reviewer_b_label": label_b,
            "reviewer_b_reason_code": reason_b,
            "reviewer_b_note": row_b["review_note"],
            "agreement_status": status,
            "final_coverage_label": label_a if status == "AGREEMENT" else "",
            "final_reason_code": (
                reason_a
                if status == "AGREEMENT" and reason_a == reason_b
                else ""
            ),
            "adjudicator_id": "",
            "adjudication_note": "",
        })

    combined = pd.DataFrame(rows).loc[:, ADJUDICATION_COLUMNS]
    total = len(combined)
    reviewed_by_a = int(indexed_a["coverage_label"].ne("").sum())
    reviewed_by_b = int(indexed_b["coverage_label"].ne("").sum())
    independent_complete = reviewed_by_a == total and reviewed_by_b == total
    label_agreements = int(
        indexed_a["coverage_label"].eq(indexed_b["coverage_label"]).sum()
    )
    label_and_reason_agreements = int((
        indexed_a["coverage_label"].eq(indexed_b["coverage_label"])
        & indexed_a["reason_code"].eq(indexed_b["reason_code"])
        & indexed_a["reason_code"].ne("")
    ).sum())
    summary = {
        "schemaVersion": "mfds-function-relation-review-status.v1",
        "rubricVersion": rubric_version,
        "totalQuestions": total,
        "reviewerAId": indexed_a.iloc[0]["reviewer_id"],
        "reviewerBId": indexed_b.iloc[0]["reviewer_id"],
        "reviewedByA": reviewed_by_a,
        "reviewedByB": reviewed_by_b,
        "pendingBoth": int(statuses["PENDING_BOTH"]),
        "pendingReviewerA": int(statuses["PENDING_REVIEWER_A"]),
        "pendingReviewerB": int(statuses["PENDING_REVIEWER_B"]),
        "agreements": int(statuses["AGREEMENT"]),
        "adjudicationRequired": int(statuses["ADJUDICATION_REQUIRED"]),
        "independentReviewsComplete": independent_complete,
        "goldStatus": (
            "NOT_READY: independent reviews or adjudication are incomplete."
        ),
    }
    if adjudication_scope == "label-only":
        summary.update({
            "adjudicationScope": adjudication_scope,
            "labelAgreements": label_agreements,
            "labelAndReasonAgreements": label_and_reason_agreements,
            "acceptedReasonDisagreements": (
                label_agreements - label_and_reason_agreements
            ),
        })
    return combined, summary
