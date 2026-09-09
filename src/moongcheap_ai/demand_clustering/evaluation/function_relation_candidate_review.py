"""Build a blinded sample from newly retrieved function-relation candidates."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any

import pandas as pd


REQUIRED_COLUMNS = {
    "direction_id",
    "source_claim_id",
    "source_claim_text",
    "candidate_claim_id",
    "candidate_claim_text",
    "retrieval_channels",
    "best_rank",
    "review_status",
}
REVIEW_COLUMNS = (
    "direction_id",
    "source_claim_id",
    "source_claim_text",
    "candidate_claim_id",
    "candidate_claim_text",
    "coverage_label",
    "reason_code",
    "reviewer_id",
    "review_note",
)


def _stable_rank(seed: str, purpose: str, identifier: str) -> str:
    return hashlib.sha256(
        f"{seed}|{purpose}|{identifier}".encode("utf-8")
    ).hexdigest()


def _reviewer_copy(
    selected: pd.DataFrame,
    *,
    reviewer_slot: str,
    seed: str,
) -> pd.DataFrame:
    output = selected.loc[:, REVIEW_COLUMNS].copy()
    output["reviewer_id"] = reviewer_slot
    output["_rank"] = output["direction_id"].map(
        lambda direction_id: _stable_rank(seed, reviewer_slot, direction_id)
    )
    output = output.sort_values("_rank", kind="stable").drop(columns="_rank")
    output.insert(0, "review_order", range(1, len(output) + 1))
    return output.reset_index(drop=True)


def build_candidate_relation_review_sample(
    candidates: pd.DataFrame,
    *,
    directions_per_stratum: int = 8,
    seed: str = "mfds-function-relation-candidate-pilot-v1",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Sample unseen directions across retrieval channel and best-rank cells."""

    if missing := sorted(REQUIRED_COLUMNS - set(candidates.columns)):
        raise ValueError(f"candidate frame missing columns: {', '.join(missing)}")
    if directions_per_stratum <= 0:
        raise ValueError("directions_per_stratum must be positive")
    if candidates["direction_id"].duplicated().any():
        raise ValueError("candidate direction IDs must be unique")
    unseen = candidates.loc[
        candidates["review_status"].eq("NEEDS_V3_OFFLINE_REVIEW")
    ].fillna("").copy()
    if unseen.empty:
        raise ValueError("candidate frame has no directions needing offline review")
    unseen["best_rank"] = pd.to_numeric(unseen["best_rank"], errors="raise").astype(int)
    unseen["sampling_stratum"] = (
        unseen["retrieval_channels"].str.replace(" ", "", regex=False)
        + "_BEST_RANK_"
        + unseen["best_rank"].astype(str)
    )
    unseen["_selection_rank"] = unseen["direction_id"].map(
        lambda direction_id: _stable_rank(seed, "selection", direction_id)
    )

    available_counts = unseen["sampling_stratum"].value_counts().sort_index()
    if shortfalls := {
        stratum: directions_per_stratum - int(count)
        for stratum, count in available_counts.items()
        if int(count) < directions_per_stratum
    }:
        raise ValueError(f"sampling stratum shortfalls: {shortfalls}")
    selected = (
        unseen.sort_values(
            ["sampling_stratum", "_selection_rank"],
            kind="stable",
        )
        .groupby("sampling_stratum", sort=True)
        .head(directions_per_stratum)
        .copy()
    )
    for column in REVIEW_COLUMNS[5:]:
        selected[column] = ""

    reviewer_a = _reviewer_copy(selected, reviewer_slot="reviewer_a", seed=seed)
    reviewer_b = _reviewer_copy(selected, reviewer_slot="reviewer_b", seed=seed)
    private_columns = [
        column
        for column in (
            "direction_id",
            "sampling_stratum",
            "retrieval_channels",
            "best_rank",
            "e5_rank",
            "e5_score",
            "tfidf_rank",
            "tfidf_score",
        )
        if column in selected
    ]
    audit = selected.loc[:, private_columns].sort_values(
        "direction_id",
        kind="stable",
    ).reset_index(drop=True)
    evidence = selected.loc[:, REVIEW_COLUMNS[:5]].sort_values(
        "direction_id",
        kind="stable",
    )
    evidence_payload = "\n".join(
        "\x1f".join(row)
        for row in evidence.astype(str).itertuples(index=False, name=None)
    )
    manifest = {
        "schemaVersion": "mfds-function-relation-candidate-review-sample.v1",
        "seed": seed,
        "sourceUnseenDirections": len(unseen),
        "directionsPerStratum": directions_per_stratum,
        "availableStratumCounts": {
            stratum: int(count) for stratum, count in available_counts.items()
        },
        "selectedStratumCounts": {
            stratum: int(count)
            for stratum, count in selected["sampling_stratum"].value_counts().sort_index().items()
        },
        "selectedDirections": len(selected),
        "evidenceFingerprintSha256": hashlib.sha256(
            evidence_payload.encode("utf-8")
        ).hexdigest(),
        "blinding": (
            "Reviewers receive only claim IDs and official texts. Retrieval "
            "channels, ranks, and scores remain in the private audit file."
        ),
        "reusePolicy": (
            "Adjudicated sample directions may be merged into the approved "
            "relation artifact; this is not a disposable benchmark sample."
        ),
    }
    return reviewer_a, reviewer_b, audit, manifest


def build_candidate_relation_review_workset(
    candidates: pd.DataFrame,
    *,
    excluded_direction_ids: Iterable[str] = (),
    seed: str = "mfds-function-relation-candidate-workset-v1",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Build blinded reviewer inputs for all unseen, not-yet-reviewed rows."""

    if missing := sorted(REQUIRED_COLUMNS - set(candidates.columns)):
        raise ValueError(f"candidate frame missing columns: {', '.join(missing)}")
    if candidates["direction_id"].duplicated().any():
        raise ValueError("candidate direction IDs must be unique")
    unseen = candidates.loc[
        candidates["review_status"].eq("NEEDS_V3_OFFLINE_REVIEW")
    ].fillna("").copy()
    if unseen.empty:
        raise ValueError("candidate frame has no directions needing offline review")
    excluded = {str(direction_id).strip() for direction_id in excluded_direction_ids}
    excluded.discard("")
    unseen_ids = set(unseen["direction_id"].astype(str))
    if unknown_exclusions := sorted(excluded - unseen_ids):
        raise ValueError(
            "excluded directions are not unseen candidates: "
            + ", ".join(unknown_exclusions)
        )
    selected = unseen.loc[~unseen["direction_id"].isin(excluded)].copy()
    if selected.empty:
        raise ValueError("all unseen candidates were excluded")
    selected["best_rank"] = pd.to_numeric(
        selected["best_rank"], errors="raise"
    ).astype(int)
    selected["sampling_stratum"] = (
        selected["retrieval_channels"].str.replace(" ", "", regex=False)
        + "_BEST_RANK_"
        + selected["best_rank"].astype(str)
    )
    for column in REVIEW_COLUMNS[5:]:
        selected[column] = ""

    reviewer_a = _reviewer_copy(selected, reviewer_slot="reviewer_a", seed=seed)
    reviewer_b = _reviewer_copy(selected, reviewer_slot="reviewer_b", seed=seed)
    private_columns = [
        column
        for column in (
            "direction_id",
            "sampling_stratum",
            "retrieval_channels",
            "best_rank",
            "e5_rank",
            "e5_score",
            "tfidf_rank",
            "tfidf_score",
        )
        if column in selected
    ]
    audit = selected.loc[:, private_columns].sort_values(
        "direction_id",
        kind="stable",
    ).reset_index(drop=True)
    evidence = selected.loc[:, REVIEW_COLUMNS[:5]].sort_values(
        "direction_id",
        kind="stable",
    )
    evidence_payload = "\n".join(
        "\x1f".join(row)
        for row in evidence.astype(str).itertuples(index=False, name=None)
    )
    manifest = {
        "schemaVersion": "mfds-function-relation-candidate-workset.v1",
        "seed": seed,
        "sourceUnseenDirections": len(unseen),
        "excludedPreviouslyReviewedDirections": len(excluded),
        "selectedDirections": len(selected),
        "selectedSourceClaims": int(selected["source_claim_id"].nunique()),
        "selectedStratumCounts": {
            stratum: int(count)
            for stratum, count in selected[
                "sampling_stratum"
            ].value_counts().sort_index().items()
        },
        "evidenceFingerprintSha256": hashlib.sha256(
            evidence_payload.encode("utf-8")
        ).hexdigest(),
        "blinding": (
            "Reviewers receive only claim IDs and official texts. Retrieval "
            "channels, ranks, and scores remain in the private audit file."
        ),
    }
    return reviewer_a, reviewer_b, audit, manifest


def analyze_candidate_relation_review(
    independent_status: pd.DataFrame,
    adjudicated_status: pd.DataFrame,
    sampling_audit: pd.DataFrame,
) -> dict[str, Any]:
    """Summarize a retrieval-stratified candidate review pilot."""

    independent_required = {
        "direction_id",
        "reviewer_a_label",
        "reviewer_a_reason_code",
        "reviewer_b_label",
        "reviewer_b_reason_code",
        "agreement_status",
    }
    final_required = {"direction_id", "final_coverage_label"}
    audit_required = {
        "direction_id",
        "sampling_stratum",
        "retrieval_channels",
        "best_rank",
    }
    for frame, required, name in (
        (independent_status, independent_required, "independent status"),
        (adjudicated_status, final_required, "adjudicated status"),
        (sampling_audit, audit_required, "sampling audit"),
    ):
        if missing := sorted(required - set(frame.columns)):
            raise ValueError(f"{name} missing columns: {', '.join(missing)}")
        if frame["direction_id"].duplicated().any():
            raise ValueError(f"{name} direction IDs must be unique")
    direction_ids = set(independent_status["direction_id"].astype(str))
    if direction_ids != set(adjudicated_status["direction_id"].astype(str)):
        raise ValueError("independent and adjudicated direction ID sets must match")
    if direction_ids != set(sampling_audit["direction_id"].astype(str)):
        raise ValueError("sampling audit direction ID set must match reviews")

    independent = independent_status.loc[
        :, sorted(independent_required)
    ].fillna("").copy()
    merged = independent.merge(
        adjudicated_status.loc[:, ["direction_id", "final_coverage_label"]],
        on="direction_id",
        how="inner",
        validate="one_to_one",
    ).merge(
        sampling_audit.loc[:, list(audit_required)],
        on="direction_id",
        how="inner",
        validate="one_to_one",
    )
    if merged["final_coverage_label"].eq("").any():
        raise ValueError("adjudicated status must contain complete final labels")
    label_equal = merged["reviewer_a_label"].eq(merged["reviewer_b_label"])
    reason_equal = (
        merged["reviewer_a_reason_code"].ne("")
        & merged["reviewer_a_reason_code"].eq(
            merged["reviewer_b_reason_code"]
        )
    )
    observed = float(label_equal.mean())
    labels = sorted(
        set(merged["reviewer_a_label"]) | set(merged["reviewer_b_label"])
    )
    expected = sum(
        float(merged["reviewer_a_label"].eq(label).mean())
        * float(merged["reviewer_b_label"].eq(label).mean())
        for label in labels
    )
    kappa = None if expected == 1.0 else (observed - expected) / (1.0 - expected)

    def grouped_counts(column: str) -> dict[str, dict[str, Any]]:
        output: dict[str, dict[str, Any]] = {}
        for value, group in merged.groupby(column, sort=True):
            counts = group["final_coverage_label"].value_counts()
            output[str(value)] = {
                "questions": len(group),
                "finalCovers": int(counts.get("COVERS", 0)),
                "finalDoesNotCover": int(counts.get("DOES_NOT_COVER", 0)),
                "labelConflicts": int(group["agreement_status"].eq(
                    "ADJUDICATION_REQUIRED"
                ).sum()),
            }
        return output

    final_counts = merged["final_coverage_label"].value_counts()
    return {
        "schemaVersion": "mfds-function-relation-candidate-review-analysis.v1",
        "questions": len(merged),
        "reviewerLabelCounts": {
            "reviewerA": {
                str(label): int(count)
                for label, count in merged["reviewer_a_label"].value_counts().sort_index().items()
            },
            "reviewerB": {
                str(label): int(count)
                for label, count in merged["reviewer_b_label"].value_counts().sort_index().items()
            },
        },
        "labelAgreement": {
            "count": int(label_equal.sum()),
            "rate": round(observed, 6),
            "cohenKappa": None if kappa is None else round(kappa, 6),
            "expectedAgreement": round(expected, 6),
        },
        "labelAndReasonAgreement": {
            "count": int((label_equal & reason_equal).sum()),
            "rate": round(float((label_equal & reason_equal).mean()), 6),
        },
        "reasonOnlyDisagreements": int((label_equal & ~reason_equal).sum()),
        "labelConflictsAdjudicated": int((~label_equal).sum()),
        "finalLabelCounts": {
            "COVERS": int(final_counts.get("COVERS", 0)),
            "DOES_NOT_COVER": int(final_counts.get("DOES_NOT_COVER", 0)),
        },
        "byRetrievalChannel": grouped_counts("retrieval_channels"),
        "byBestRank": grouped_counts("best_rank"),
        "bySamplingStratum": grouped_counts("sampling_stratum"),
        "interpretation": (
            "The overall positive rate describes the supplied review set; an "
            "intentionally balanced sample must not be treated as corpus "
            "prevalence. Low kappa must be read with the high expected "
            "agreement caused by a negative-heavy label distribution."
        ),
        "goldStatus": (
            "LLM_CONSENSUS_CANDIDATE_ONLY: not human or regulatory-domain gold."
        ),
    }
