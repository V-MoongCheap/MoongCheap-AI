"""Prepare a small, blinded pilot for directional function review."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable
from typing import Any

import pandas as pd

from .function_relation_review import SAMPLING_STRATA


SOURCE_REVIEW_REQUIRED_COLUMNS = (
    "direction_id",
    "source_claim_id",
    "source_claim_text",
    "source_reference_names",
    "candidate_claim_id",
    "candidate_claim_text",
    "candidate_reference_names",
    "coverage_label",
    "reason_code",
    "reviewer_id",
    "review_note",
)

PILOT_REVIEW_COLUMNS = (
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

AUDIT_REQUIRED_COLUMNS = (
    "direction_id",
    "pair_id",
    "sampling_stratum",
)

BLINDED_REVIEW_COLUMNS = (
    "review_order",
    *PILOT_REVIEW_COLUMNS,
)

ADJUDICATION_COLUMNS = (
    "direction_id",
    "source_claim_id",
    "source_claim_text",
    "candidate_claim_id",
    "candidate_claim_text",
    "reviewer_a_label",
    "reviewer_a_reason_code",
    "reviewer_a_note",
    "reviewer_b_label",
    "reviewer_b_reason_code",
    "reviewer_b_note",
    "agreement_status",
    "final_coverage_label",
    "final_reason_code",
    "adjudicator_id",
    "adjudication_note",
)

FINAL_RELATION_REQUIRED_COLUMNS = (
    "direction_id",
    "source_claim_id",
    "source_claim_text",
    "candidate_claim_id",
    "candidate_claim_text",
    "final_coverage_label",
)


def _require_columns(
    frame: pd.DataFrame,
    required: tuple[str, ...],
    frame_name: str,
) -> None:
    if missing := sorted(set(required) - set(frame.columns)):
        raise ValueError(
            f"{frame_name} frame missing columns: {', '.join(missing)}"
        )


def _frame_fingerprint(frame: pd.DataFrame, columns: tuple[str, ...]) -> str:
    canonical = frame.loc[:, columns].fillna("").astype(str).sort_values(
        list(columns),
        kind="stable",
    )
    payload = "\n".join(
        "\x1f".join(row)
        for row in canonical.itertuples(index=False, name=None)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _stable_rank(seed: str, purpose: str, identifier: str) -> str:
    return hashlib.sha256(
        f"{seed}|{purpose}|{identifier}".encode("utf-8")
    ).hexdigest()


def _pair_text_key(source_text: object, candidate_text: object) -> str:
    texts = sorted({" ".join(str(value).split()).casefold() for value in (
        source_text,
        candidate_text,
    )})
    return "\x1f".join(texts)


def _validate_source_frames(
    review: pd.DataFrame,
    audit: pd.DataFrame,
) -> pd.DataFrame:
    _require_columns(review, SOURCE_REVIEW_REQUIRED_COLUMNS, "review")
    _require_columns(audit, AUDIT_REQUIRED_COLUMNS, "audit")
    if review.empty:
        raise ValueError("review frame must not be empty")
    for name, frame in (("review", review), ("audit", audit)):
        if frame["direction_id"].eq("").any():
            raise ValueError(f"{name} direction_id must not be empty")
        if not frame["direction_id"].is_unique:
            raise ValueError(f"{name} direction_id must be unique")
    if set(review["direction_id"]) != set(audit["direction_id"]):
        raise ValueError("review and audit direction_id sets must match")
    if review[["coverage_label", "reason_code", "reviewer_id", "review_note"]].fillna("").ne("").any().any():
        raise ValueError("pilot source review must not contain annotations")

    pair_counts = audit.groupby("pair_id")["direction_id"].nunique()
    if not pair_counts.eq(2).all():
        raise ValueError("each audit pair_id must contain exactly two directions")
    stratum_counts = audit.groupby("pair_id")["sampling_stratum"].nunique()
    if not stratum_counts.eq(1).all():
        raise ValueError("each audit pair_id must belong to one sampling stratum")
    unknown_strata = sorted(set(audit["sampling_stratum"]) - set(SAMPLING_STRATA))
    if unknown_strata:
        raise ValueError(f"unknown sampling strata: {', '.join(unknown_strata)}")

    return review.merge(
        audit.loc[:, AUDIT_REQUIRED_COLUMNS],
        on="direction_id",
        how="inner",
        validate="one_to_one",
    )


def _reviewer_copy(
    selected_review: pd.DataFrame,
    *,
    reviewer_slot: str,
    seed: str,
) -> pd.DataFrame:
    output = selected_review.loc[:, PILOT_REVIEW_COLUMNS].copy()
    output["reviewer_id"] = reviewer_slot
    output["_review_rank"] = output["direction_id"].map(
        lambda direction_id: _stable_rank(seed, reviewer_slot, direction_id)
    )
    output = output.sort_values("_review_rank", kind="stable").drop(
        columns="_review_rank"
    )
    output.insert(0, "review_order", range(1, len(output) + 1))
    return output.loc[:, BLINDED_REVIEW_COLUMNS].reset_index(drop=True)


def _adjudication_template(selected_review: pd.DataFrame) -> pd.DataFrame:
    evidence_columns = PILOT_REVIEW_COLUMNS[:5]
    output = selected_review.loc[:, evidence_columns].sort_values(
        "direction_id",
        kind="stable",
    ).copy()
    for column in ADJUDICATION_COLUMNS[len(evidence_columns):]:
        output[column] = ""
    return output.loc[:, ADJUDICATION_COLUMNS].reset_index(drop=True)


def build_function_relation_pilot(
    review: pd.DataFrame,
    audit: pd.DataFrame,
    *,
    pairs_per_stratum: int = 3,
    seed: str = "mfds-function-relation-pilot-v1",
    excluded_direction_ids: Iterable[str] = (),
    excluded_claim_ids: Iterable[str] = (),
    excluded_text_pairs: Iterable[tuple[str, str]] = (),
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Return reviewer A/B copies, a blank adjudication template, and manifest.

    Sampling metadata stays outside every returned CSV. The same directional
    questions are assigned to both reviewer slots in different deterministic
    orders so their decisions can be collected independently.
    """

    if pairs_per_stratum <= 0:
        raise ValueError("pairs_per_stratum must be positive")
    merged = _validate_source_frames(review.fillna(""), audit.fillna(""))

    excluded_directions = {
        str(direction_id).strip()
        for direction_id in excluded_direction_ids
        if str(direction_id).strip()
    }
    unknown_exclusions = sorted(
        excluded_directions - set(merged["direction_id"].astype(str))
    )
    if unknown_exclusions:
        raise ValueError(
            "excluded direction IDs are not in the source review: "
            + ", ".join(unknown_exclusions)
        )
    excluded_pair_ids = set(merged.loc[
        merged["direction_id"].isin(excluded_directions),
        "pair_id",
    ])
    excluded_claims = {
        str(claim_id).strip()
        for claim_id in excluded_claim_ids
        if str(claim_id).strip()
    }
    known_claims = set(merged["source_claim_id"].astype(str)) | set(
        merged["candidate_claim_id"].astype(str)
    )
    unknown_claim_exclusions = sorted(excluded_claims - known_claims)
    if unknown_claim_exclusions:
        raise ValueError(
            "excluded claim IDs are not in the source review: "
            + ", ".join(unknown_claim_exclusions)
        )
    excluded_pair_ids.update(merged.loc[
        merged["source_claim_id"].isin(excluded_claims)
        | merged["candidate_claim_id"].isin(excluded_claims),
        "pair_id",
    ])
    excluded_text_pair_keys = {
        _pair_text_key(source_text, candidate_text)
        for source_text, candidate_text in excluded_text_pairs
    }
    merged_text_pair_keys = merged.apply(
        lambda row: _pair_text_key(
            row["source_claim_text"],
            row["candidate_claim_text"],
        ),
        axis=1,
    )
    excluded_pair_ids.update(merged.loc[
        merged_text_pair_keys.isin(excluded_text_pair_keys),
        "pair_id",
    ])

    pair_summary = merged.loc[:, ["pair_id", "sampling_stratum"]].drop_duplicates()
    pair_summary = pair_summary.loc[
        ~pair_summary["pair_id"].isin(excluded_pair_ids)
    ]
    selected_pair_ids: list[str] = []
    available_counts: dict[str, int] = {}
    selected_counts: Counter[str] = Counter()
    for stratum in SAMPLING_STRATA:
        candidates = pair_summary.loc[
            pair_summary["sampling_stratum"].eq(stratum),
            "pair_id",
        ].tolist()
        candidates.sort(key=lambda pair_id: _stable_rank(seed, stratum, pair_id))
        available_counts[stratum] = len(candidates)
        selected = candidates[:pairs_per_stratum]
        selected_pair_ids.extend(selected)
        selected_counts[stratum] = len(selected)

    selected_review = merged.loc[
        merged["pair_id"].isin(selected_pair_ids),
        SOURCE_REVIEW_REQUIRED_COLUMNS,
    ].copy()
    reviewer_a = _reviewer_copy(
        selected_review,
        reviewer_slot="REVIEWER_A",
        seed=seed,
    )
    reviewer_b = _reviewer_copy(
        selected_review,
        reviewer_slot="REVIEWER_B",
        seed=seed,
    )
    adjudication = _adjudication_template(selected_review)

    selected_counts_dict = {
        stratum: int(selected_counts[stratum]) for stratum in SAMPLING_STRATA
    }
    manifest = {
        "schemaVersion": "mfds-function-relation-pilot.v1",
        "question": (
            "Does candidate function B preserve the benefit and scope of "
            "source function A?"
        ),
        "seed": seed,
        "requestedPairsPerStratum": pairs_per_stratum,
        "availablePairCounts": available_counts,
        "selectedPairCounts": selected_counts_dict,
        "samplingStratumShortfalls": {
            stratum: max(0, pairs_per_stratum - selected_counts_dict[stratum])
            for stratum in SAMPLING_STRATA
        },
        "undirectedPairs": len(selected_pair_ids),
        "directedQuestionsPerReviewer": len(reviewer_a),
        "excludedUndirectedPairs": len(excluded_pair_ids),
        "excludedDirectionIdsProvided": len(excluded_directions),
        "excludedClaimIdsProvided": len(excluded_claims),
        "excludedTextPairsProvided": len(excluded_text_pair_keys),
        "reviewerSlots": ["REVIEWER_A", "REVIEWER_B"],
        "sourceReviewFingerprintSha256": _frame_fingerprint(
            review,
            SOURCE_REVIEW_REQUIRED_COLUMNS,
        ),
        "sourceAuditFingerprintSha256": _frame_fingerprint(
            audit,
            AUDIT_REQUIRED_COLUMNS,
        ),
        "blinding": (
            "Reviewer and adjudication CSV files omit reference ingredient "
            "names, sampling strata, and similarity scores. Reviewer copies "
            "contain the same questions in different deterministic orders."
        ),
        "goldStatus": (
            "EMPTY: two independent decisions and adjudication of "
            "disagreements are still required."
        ),
    }
    return reviewer_a, reviewer_b, adjudication, manifest


def build_positive_relation_reaudit(
    adjudicated: pd.DataFrame,
    *,
    seed: str = "mfds-function-positive-safety-audit-v1",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Build blinded reviewer copies for conservative re-audit of COVERS rows."""

    _require_columns(
        adjudicated,
        FINAL_RELATION_REQUIRED_COLUMNS,
        "adjudicated relation",
    )
    normalized = adjudicated.loc[:, FINAL_RELATION_REQUIRED_COLUMNS].fillna("").copy()
    if normalized["direction_id"].duplicated().any():
        raise ValueError("adjudicated relation direction_id must be unique")
    positives = normalized.loc[
        normalized["final_coverage_label"].eq("COVERS")
    ].copy()
    if positives.empty:
        raise ValueError("adjudicated relation has no COVERS rows to audit")
    evidence_columns = list(FINAL_RELATION_REQUIRED_COLUMNS[:-1])
    if positives[evidence_columns].eq("").any().any():
        raise ValueError("positive relation evidence must not be empty")

    review = positives.loc[:, evidence_columns].copy()
    for column in PILOT_REVIEW_COLUMNS[len(evidence_columns):]:
        review[column] = ""
    review = review.loc[:, PILOT_REVIEW_COLUMNS]
    reviewer_a = _reviewer_copy(
        review,
        reviewer_slot="REVIEWER_A",
        seed=seed,
    )
    reviewer_b = _reviewer_copy(
        review,
        reviewer_slot="REVIEWER_B",
        seed=seed,
    )
    adjudication = _adjudication_template(review)
    manifest = {
        "schemaVersion": "mfds-function-positive-safety-audit.v1",
        "seed": seed,
        "sourceRows": len(normalized),
        "positiveQuestions": len(review),
        "reviewerSlots": ["REVIEWER_A", "REVIEWER_B"],
        "sourceFingerprintSha256": _frame_fingerprint(
            normalized,
            FINAL_RELATION_REQUIRED_COLUMNS,
        ),
        "purpose": (
            "Conservative false-positive audit before a COVERS relation can "
            "be considered for an approved production artifact."
        ),
        "goldStatus": "EMPTY: independent safety re-audit is required.",
    }
    return reviewer_a, reviewer_b, adjudication, manifest
