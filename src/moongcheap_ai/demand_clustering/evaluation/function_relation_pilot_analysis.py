"""Metrics for an independently reviewed directional function pilot."""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from .function_relation_review import REVIEW_LABELS, SAMPLING_STRATA


def _best_threshold_accuracy(
    scores: pd.Series,
    labels: pd.Series,
) -> dict[str, float]:
    numeric_scores = scores.astype(float)
    unique_scores = sorted(set(numeric_scores))
    thresholds = [unique_scores[0] - 1.0]
    thresholds.extend(
        (left + right) / 2
        for left, right in zip(unique_scores, unique_scores[1:])
    )
    thresholds.append(unique_scores[-1] + 1.0)
    results = [
        (
            float(numeric_scores.ge(threshold).eq(labels).mean()),
            float(threshold),
        )
        for threshold in thresholds
    ]
    accuracy, threshold = max(results)
    return {
        "accuracy": round(accuracy, 6),
        "threshold": round(threshold, 6),
    }


def analyze_function_relation_pilot(
    independent_status: pd.DataFrame,
    adjudicated_status: pd.DataFrame,
    sampling_audit: pd.DataFrame,
) -> dict[str, Any]:
    """Return agreement, directionality, stratum, and baseline metrics."""

    status_required = {
        "direction_id",
        "reviewer_a_label",
        "reviewer_a_reason_code",
        "reviewer_b_label",
        "reviewer_b_reason_code",
        "agreement_status",
    }
    final_required = {
        "direction_id",
        "agreement_status",
        "final_coverage_label",
        "final_reason_code",
    }
    audit_required = {
        "direction_id",
        "pair_id",
        "sampling_stratum",
        "character_bigram_similarity",
        "focus_bigram_similarity",
    }
    for frame, required, name in (
        (independent_status, status_required, "independent status"),
        (adjudicated_status, final_required, "adjudicated status"),
        (sampling_audit, audit_required, "sampling audit"),
    ):
        if missing := sorted(required - set(frame.columns)):
            raise ValueError(f"{name} missing columns: {', '.join(missing)}")
        if frame["direction_id"].duplicated().any():
            raise ValueError(f"{name} direction_id must be unique")

    direction_ids = set(independent_status["direction_id"].astype(str))
    if direction_ids != set(adjudicated_status["direction_id"].astype(str)):
        raise ValueError("independent and adjudicated direction IDs must match")
    audit_subset = sampling_audit.loc[
        sampling_audit["direction_id"].astype(str).isin(direction_ids),
        list(audit_required),
    ].copy()
    if set(audit_subset["direction_id"].astype(str)) != direction_ids:
        raise ValueError("sampling audit does not cover every pilot direction")

    independent = independent_status.fillna("").copy()
    final = adjudicated_status.fillna("").copy()
    if final["final_coverage_label"].eq("").any():
        raise ValueError("every adjudicated row must have a final label")
    invalid_labels = sorted(
        set(final["final_coverage_label"]) - set(REVIEW_LABELS)
    )
    if invalid_labels:
        raise ValueError(f"invalid final labels: {', '.join(invalid_labels)}")

    merged = final.merge(
        audit_subset,
        on="direction_id",
        how="inner",
        validate="one_to_one",
    )
    pair_counts = merged.groupby("pair_id")["direction_id"].nunique()
    if not pair_counts.eq(2).all():
        raise ValueError("each pilot pair must contain exactly two directions")

    label_equal = independent["reviewer_a_label"].eq(
        independent["reviewer_b_label"]
    )
    reason_equal = independent["reviewer_a_reason_code"].eq(
        independent["reviewer_b_reason_code"]
    )
    total = len(independent)
    observed_agreement = float(label_equal.mean())
    labels = sorted(
        set(independent["reviewer_a_label"])
        | set(independent["reviewer_b_label"])
    )
    expected_agreement = sum(
        float(independent["reviewer_a_label"].eq(label).mean())
        * float(independent["reviewer_b_label"].eq(label).mean())
        for label in labels
    )
    kappa = (
        None
        if expected_agreement == 1.0
        else (observed_agreement - expected_agreement)
        / (1.0 - expected_agreement)
    )

    pair_patterns: Counter[str] = Counter()
    for _, group in merged.groupby("pair_id"):
        pair_labels = list(group["final_coverage_label"])
        covers = pair_labels.count("COVERS")
        if covers == 2:
            pair_patterns["BIDIRECTIONAL_COVERS"] += 1
        elif covers == 1:
            pair_patterns["ASYMMETRIC_COVERAGE"] += 1
        else:
            pair_patterns["BIDIRECTIONAL_DOES_NOT_COVER"] += 1
    asymmetric_pairs = int(pair_patterns["ASYMMETRIC_COVERAGE"])
    symmetric_ceiling = (len(merged) - asymmetric_pairs) / len(merged)

    by_stratum: dict[str, dict[str, Any]] = {}
    independent_with_stratum = independent.merge(
        audit_subset.loc[:, ["direction_id", "sampling_stratum"]],
        on="direction_id",
        how="inner",
        validate="one_to_one",
    )
    for stratum in SAMPLING_STRATA:
        final_group = merged.loc[merged["sampling_stratum"].eq(stratum)]
        independent_group = independent_with_stratum.loc[
            independent_with_stratum["sampling_stratum"].eq(stratum)
        ]
        by_stratum[stratum] = {
            "questions": len(final_group),
            "labelDisagreements": int(
                independent_group["reviewer_a_label"].ne(
                    independent_group["reviewer_b_label"]
                ).sum()
            ),
            "labelOrReasonDisagreements": int(
                independent_group["agreement_status"].eq(
                    "ADJUDICATION_REQUIRED"
                ).sum()
            ),
            "finalLabelCounts": dict(sorted(Counter(
                final_group["final_coverage_label"]
            ).items())),
        }

    final_binary = merged["final_coverage_label"].eq("COVERS")
    return {
        "schemaVersion": "mfds-function-relation-llm-pilot-analysis.v1",
        "questions": total,
        "undirectedPairs": int(merged["pair_id"].nunique()),
        "reviewerLabelCounts": {
            "reviewerA": dict(sorted(Counter(
                independent["reviewer_a_label"]
            ).items())),
            "reviewerB": dict(sorted(Counter(
                independent["reviewer_b_label"]
            ).items())),
        },
        "labelAgreement": {
            "count": int(label_equal.sum()),
            "rate": round(observed_agreement, 6),
            "cohenKappa": None if kappa is None else round(kappa, 6),
        },
        "labelAndReasonAgreement": {
            "count": int((label_equal & reason_equal).sum()),
            "rate": round(float((label_equal & reason_equal).mean()), 6),
        },
        "disagreements": {
            "label": int((~label_equal).sum()),
            "reasonOnly": int((label_equal & ~reason_equal).sum()),
        },
        "finalLabelCounts": dict(sorted(Counter(
            merged["final_coverage_label"]
        ).items())),
        "finalReasonCounts": dict(sorted(Counter(
            reason
            for reason in merged["final_reason_code"]
            if reason
        ).items())),
        "pairDirectionPatterns": dict(sorted(pair_patterns.items())),
        "directionInvariantScoreAccuracyCeiling": round(
            symmetric_ceiling,
            6,
        ),
        "bestObservedThresholdBaselines": {
            "characterBigram": _best_threshold_accuracy(
                merged["character_bigram_similarity"],
                final_binary,
            ),
            "focusBigram": _best_threshold_accuracy(
                merged["focus_bigram_similarity"],
                final_binary,
            ),
        },
        "bySamplingStratum": by_stratum,
        "goldStatus": (
            "LLM_CONSENSUS_CANDIDATE_ONLY: stratified pilot, not human or "
            "regulatory-domain gold and not a production prevalence estimate."
        ),
    }
