from __future__ import annotations

import pandas as pd
import pytest

from moongcheap_ai.demand_clustering.evaluation.function_relation_pilot import (
    build_function_relation_pilot,
    build_positive_relation_reaudit,
)
from moongcheap_ai.demand_clustering.evaluation.function_relation_review import SAMPLING_STRATA


def _source_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    review_rows: list[dict[str, str]] = []
    audit_rows: list[dict[str, str]] = []
    for stratum_index, stratum in enumerate(SAMPLING_STRATA):
        for pair_index in range(3):
            pair_id = f"pair-{stratum_index}-{pair_index}"
            for direction_index in range(2):
                direction_id = f"direction-{stratum_index}-{pair_index}-{direction_index}"
                review_rows.append({
                    "direction_id": direction_id,
                    "source_claim_id": f"source-{direction_id}",
                    "source_claim_text": f"source text {direction_id}",
                    "source_reference_names": "source ref",
                    "candidate_claim_id": f"candidate-{direction_id}",
                    "candidate_claim_text": f"candidate text {direction_id}",
                    "candidate_reference_names": "candidate ref",
                    "coverage_label": "",
                    "reason_code": "",
                    "reviewer_id": "",
                    "review_note": "",
                })
                audit_rows.append({
                    "direction_id": direction_id,
                    "pair_id": pair_id,
                    "sampling_stratum": stratum,
                    "character_bigram_similarity": "0.9",
                })
    return pd.DataFrame(review_rows), pd.DataFrame(audit_rows)


def test_builds_balanced_blinded_two_reviewer_pilot() -> None:
    review, audit = _source_frames()
    reviewer_a, reviewer_b, adjudication, manifest = (
        build_function_relation_pilot(
            review,
            audit,
            pairs_per_stratum=2,
            seed="test-pilot",
        )
    )

    assert len(reviewer_a) == 16
    assert len(reviewer_b) == 16
    assert len(adjudication) == 16
    assert set(reviewer_a["direction_id"]) == set(reviewer_b["direction_id"])
    assert reviewer_a["direction_id"].tolist() != reviewer_b["direction_id"].tolist()
    assert set(reviewer_a["reviewer_id"]) == {"REVIEWER_A"}
    assert set(reviewer_b["reviewer_id"]) == {"REVIEWER_B"}
    for frame in (reviewer_a, reviewer_b, adjudication):
        assert "sampling_stratum" not in frame.columns
        assert "character_bigram_similarity" not in frame.columns
    assert manifest["selectedPairCounts"] == {
        stratum: 2 for stratum in SAMPLING_STRATA
    }
    assert manifest["undirectedPairs"] == 8
    assert manifest["directedQuestionsPerReviewer"] == 16
    assert manifest["excludedUndirectedPairs"] == 0
    assert manifest["excludedClaimIdsProvided"] == 0
    assert manifest["excludedTextPairsProvided"] == 0
    assert manifest["goldStatus"].startswith("EMPTY")


def test_is_deterministic_when_source_rows_are_shuffled() -> None:
    review, audit = _source_frames()
    result = build_function_relation_pilot(review, audit, seed="stable")
    shuffled_result = build_function_relation_pilot(
        review.sample(frac=1, random_state=4),
        audit.sample(frac=1, random_state=8),
        seed="stable",
    )

    for left, right in zip(result[:3], shuffled_result[:3], strict=True):
        pd.testing.assert_frame_equal(left, right)
    assert result[3] == shuffled_result[3]


def test_rejects_labels_or_misaligned_audit() -> None:
    review, audit = _source_frames()
    review.loc[0, "coverage_label"] = "COVERS"
    with pytest.raises(ValueError, match="must not contain annotations"):
        build_function_relation_pilot(review, audit)

    review.loc[0, "coverage_label"] = ""
    with pytest.raises(ValueError, match="sets must match"):
        build_function_relation_pilot(review, audit.iloc[1:])


def test_rejects_nonpositive_sample_size() -> None:
    review, audit = _source_frames()
    with pytest.raises(ValueError, match="must be positive"):
        build_function_relation_pilot(review, audit, pairs_per_stratum=0)


def test_excludes_both_directions_of_prior_pairs() -> None:
    review, audit = _source_frames()
    excluded = [
        f"direction-{stratum_index}-0-0"
        for stratum_index, _ in enumerate(SAMPLING_STRATA)
    ]

    reviewer_a, _, _, manifest = build_function_relation_pilot(
        review,
        audit,
        pairs_per_stratum=2,
        excluded_direction_ids=excluded,
    )

    selected = set(reviewer_a["direction_id"])
    assert not any(
        direction_id.split("-")[2] == "0"
        for direction_id in selected
    )
    assert manifest["excludedUndirectedPairs"] == 4
    assert manifest["excludedDirectionIdsProvided"] == 4


def test_excludes_every_pair_containing_prior_claims() -> None:
    review, audit = _source_frames()
    excluded_claim = "source-direction-0-0-0"

    reviewer_a, _, _, manifest = build_function_relation_pilot(
        review,
        audit,
        pairs_per_stratum=2,
        excluded_claim_ids=[excluded_claim],
    )

    assert excluded_claim not in set(reviewer_a["source_claim_id"])
    assert excluded_claim not in set(reviewer_a["candidate_claim_id"])
    assert manifest["excludedClaimIdsProvided"] == 1


def test_excludes_prior_undirected_text_pair() -> None:
    review, audit = _source_frames()
    prior_pair = review.loc[
        review["direction_id"].str.startswith("direction-0-0-"),
        ["source_claim_text", "candidate_claim_text"],
    ].iloc[0]

    reviewer_a, _, _, manifest = build_function_relation_pilot(
        review,
        audit,
        pairs_per_stratum=2,
        excluded_text_pairs=[tuple(prior_pair)],
    )

    assert not any(
        direction_id.startswith("direction-0-0-")
        for direction_id in reviewer_a["direction_id"]
    )
    assert manifest["excludedUndirectedPairs"] == 1
    assert manifest["excludedTextPairsProvided"] == 1


def test_builds_blinded_positive_relation_reaudit() -> None:
    review, _ = _source_frames()
    source = review.loc[:2, [
        "direction_id",
        "source_claim_id",
        "source_claim_text",
        "candidate_claim_id",
        "candidate_claim_text",
    ]].copy()
    source["final_coverage_label"] = [
        "COVERS",
        "DOES_NOT_COVER",
        "COVERS",
    ]

    reviewer_a, reviewer_b, adjudication, manifest = (
        build_positive_relation_reaudit(source, seed="safety")
    )

    assert len(reviewer_a) == len(reviewer_b) == len(adjudication) == 2
    assert set(reviewer_a["direction_id"]) == {
        source.at[0, "direction_id"],
        source.at[2, "direction_id"],
    }
    assert reviewer_a["direction_id"].tolist() != reviewer_b["direction_id"].tolist()
    assert set(reviewer_a["reviewer_id"]) == {"REVIEWER_A"}
    assert manifest["positiveQuestions"] == 2
    assert manifest["sourceRows"] == 3
