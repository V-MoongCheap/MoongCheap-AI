from __future__ import annotations

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.function_relation_candidate_review import (
    analyze_candidate_relation_review,
    build_candidate_relation_review_sample,
    build_candidate_relation_review_workset,
)


def test_samples_each_channel_rank_cell_and_blinds_retrieval_metadata() -> None:
    rows = []
    for channel in ("E5", "TFIDF", "E5 | TFIDF"):
        for rank in (1, 2):
            for index in range(3):
                rows.append({
                    "direction_id": f"{channel}-{rank}-{index}",
                    "source_claim_id": f"s-{index}",
                    "source_claim_text": f"source {index}",
                    "candidate_claim_id": f"c-{index}",
                    "candidate_claim_text": f"candidate {index}",
                    "retrieval_channels": channel,
                    "best_rank": rank,
                    "review_status": "NEEDS_V3_OFFLINE_REVIEW",
                    "e5_rank": rank,
                    "e5_score": 0.9,
                    "tfidf_rank": rank,
                    "tfidf_score": 0.8,
                })
    rows.append({
        **rows[0],
        "direction_id": "known",
        "review_status": "KNOWN_APPROVED_COVERS",
    })

    reviewer_a, reviewer_b, audit, manifest = build_candidate_relation_review_sample(
        pd.DataFrame(rows),
        directions_per_stratum=2,
        seed="test-seed",
    )

    assert len(reviewer_a) == 12
    assert set(reviewer_a["direction_id"]) == set(reviewer_b["direction_id"])
    assert reviewer_a["direction_id"].tolist() != reviewer_b["direction_id"].tolist()
    assert "retrieval_channels" not in reviewer_a
    assert "retrieval_channels" in audit
    assert "known" not in set(audit["direction_id"])
    assert set(manifest["selectedStratumCounts"].values()) == {2}


def test_analyzes_imbalanced_candidate_review_without_calling_it_prevalence() -> None:
    independent = pd.DataFrame([
        {
            "direction_id": "d1",
            "reviewer_a_label": "COVERS",
            "reviewer_a_reason_code": "SAME",
            "reviewer_b_label": "COVERS",
            "reviewer_b_reason_code": "SAME",
            "agreement_status": "AGREEMENT",
        },
        {
            "direction_id": "d2",
            "reviewer_a_label": "COVERS",
            "reviewer_a_reason_code": "SAME",
            "reviewer_b_label": "DOES_NOT_COVER",
            "reviewer_b_reason_code": "DIFFERENT",
            "agreement_status": "ADJUDICATION_REQUIRED",
        },
    ])
    final = pd.DataFrame([
        {"direction_id": "d1", "final_coverage_label": "COVERS"},
        {"direction_id": "d2", "final_coverage_label": "DOES_NOT_COVER"},
    ])
    audit = pd.DataFrame([
        {
            "direction_id": "d1",
            "sampling_stratum": "BOTH_1",
            "retrieval_channels": "E5 | TFIDF",
            "best_rank": "1",
        },
        {
            "direction_id": "d2",
            "sampling_stratum": "E5_2",
            "retrieval_channels": "E5",
            "best_rank": "2",
        },
    ])

    result = analyze_candidate_relation_review(independent, final, audit)

    assert result["labelAgreement"]["rate"] == 0.5
    assert result["labelConflictsAdjudicated"] == 1
    assert result["finalLabelCounts"] == {"COVERS": 1, "DOES_NOT_COVER": 1}
    assert result["byRetrievalChannel"]["E5"]["labelConflicts"] == 1
    assert "must not be treated as corpus prevalence" in result["interpretation"]


def test_workset_excludes_completed_pilot_and_keeps_blinding() -> None:
    candidates = pd.DataFrame([
        {
            "direction_id": f"d{index}",
            "source_claim_id": f"s{index}",
            "source_claim_text": f"source {index}",
            "candidate_claim_id": f"c{index}",
            "candidate_claim_text": f"candidate {index}",
            "retrieval_channels": "E5 | TFIDF",
            "best_rank": "1",
            "review_status": "NEEDS_V3_OFFLINE_REVIEW",
            "e5_rank": "1",
            "e5_score": "0.9",
            "tfidf_rank": "1",
            "tfidf_score": "0.8",
        }
        for index in range(3)
    ])

    reviewer_a, reviewer_b, audit, manifest = (
        build_candidate_relation_review_workset(
            candidates,
            excluded_direction_ids=["d1"],
            seed="workset-test",
        )
    )

    assert set(reviewer_a["direction_id"]) == {"d0", "d2"}
    assert set(reviewer_b["direction_id"]) == {"d0", "d2"}
    assert "retrieval_channels" not in reviewer_a
    assert "retrieval_channels" in audit
    assert manifest["excludedPreviouslyReviewedDirections"] == 1
    assert manifest["selectedDirections"] == 2
