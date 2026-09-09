from __future__ import annotations

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.function_relation_pilot_analysis import (
    analyze_function_relation_pilot,
)


def test_reports_directional_ceiling_and_disagreement_types() -> None:
    independent = pd.DataFrame([
        {
            "direction_id": "d1",
            "reviewer_a_label": "COVERS",
            "reviewer_a_reason_code": "SAME_ENDPOINT_EQUIVALENT_WORDING",
            "reviewer_b_label": "COVERS",
            "reviewer_b_reason_code": "SAME_ENDPOINT_MECHANISM_DETAIL",
            "agreement_status": "ADJUDICATION_REQUIRED",
        },
        {
            "direction_id": "d2",
            "reviewer_a_label": "COVERS",
            "reviewer_a_reason_code": "CANDIDATE_INCLUDES_SOURCE_ENDPOINT",
            "reviewer_b_label": "DOES_NOT_COVER",
            "reviewer_b_reason_code": "CANDIDATE_SCOPE_NARROWER",
            "agreement_status": "ADJUDICATION_REQUIRED",
        },
        {
            "direction_id": "d3",
            "reviewer_a_label": "DOES_NOT_COVER",
            "reviewer_a_reason_code": "DIFFERENT_ENDPOINT",
            "reviewer_b_label": "DOES_NOT_COVER",
            "reviewer_b_reason_code": "DIFFERENT_ENDPOINT",
            "agreement_status": "AGREEMENT",
        },
        {
            "direction_id": "d4",
            "reviewer_a_label": "DOES_NOT_COVER",
            "reviewer_a_reason_code": "DIFFERENT_ENDPOINT",
            "reviewer_b_label": "DOES_NOT_COVER",
            "reviewer_b_reason_code": "DIFFERENT_ENDPOINT",
            "agreement_status": "AGREEMENT",
        },
    ])
    adjudicated = pd.DataFrame([
        {
            "direction_id": direction_id,
            "agreement_status": status,
            "final_coverage_label": label,
            "final_reason_code": reason,
        }
        for direction_id, status, label, reason in (
            ("d1", "ADJUDICATED", "COVERS", "SAME_ENDPOINT_EQUIVALENT_WORDING"),
            ("d2", "ADJUDICATED", "DOES_NOT_COVER", "CANDIDATE_SCOPE_NARROWER"),
            ("d3", "AGREEMENT", "DOES_NOT_COVER", "DIFFERENT_ENDPOINT"),
            ("d4", "AGREEMENT", "DOES_NOT_COVER", "DIFFERENT_ENDPOINT"),
        )
    ])
    audit = pd.DataFrame([
        {
            "direction_id": direction_id,
            "pair_id": pair_id,
            "sampling_stratum": stratum,
            "character_bigram_similarity": score,
            "focus_bigram_similarity": score,
        }
        for direction_id, pair_id, stratum, score in (
            ("d1", "p1", "LEXICAL_NEAR", "0.9"),
            ("d2", "p1", "LEXICAL_NEAR", "0.9"),
            ("d3", "p2", "LOW_SIMILARITY_CONTROL", "0.1"),
            ("d4", "p2", "LOW_SIMILARITY_CONTROL", "0.1"),
        )
    ])

    result = analyze_function_relation_pilot(independent, adjudicated, audit)

    assert result["disagreements"] == {"label": 1, "reasonOnly": 1}
    assert result["pairDirectionPatterns"] == {
        "ASYMMETRIC_COVERAGE": 1,
        "BIDIRECTIONAL_DOES_NOT_COVER": 1,
    }
    assert result["directionInvariantScoreAccuracyCeiling"] == 0.75
    assert result["bestObservedThresholdBaselines"]["characterBigram"][
        "accuracy"
    ] == 0.75
