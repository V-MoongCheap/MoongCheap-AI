from __future__ import annotations

import pandas as pd
import pytest

from moongcheap_ai.demand_clustering.evaluation.function_relation_retrieval_evaluation import (
    build_function_relation_candidate_set,
    evaluate_function_relation_retrieval,
    evaluate_known_positive_rank_union,
)


def _gold() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "direction_id": "a-b",
            "source_claim_id": "a",
            "candidate_claim_id": "b",
            "final_coverage_label": "COVERS",
        },
        {
            "direction_id": "a-c",
            "source_claim_id": "a",
            "candidate_claim_id": "c",
            "final_coverage_label": "DOES_NOT_COVER",
        },
        {
            "direction_id": "d-b",
            "source_claim_id": "d",
            "candidate_claim_id": "b",
            "final_coverage_label": "COVERS",
        },
    ])


def _scores() -> pd.DataFrame:
    return pd.DataFrame([
        {"source_claim_id": "a", "candidate_claim_id": "b", "score": 0.8},
        {"source_claim_id": "a", "candidate_claim_id": "c", "score": 0.9},
        {"source_claim_id": "a", "candidate_claim_id": "d", "score": 0.7},
        {"source_claim_id": "d", "candidate_claim_id": "a", "score": 0.9},
        {"source_claim_id": "d", "candidate_claim_id": "b", "score": 0.8},
        {"source_claim_id": "d", "candidate_claim_id": "c", "score": 0.7},
    ])


def test_reports_sparse_known_positive_ranks_and_auc() -> None:
    metrics, ranks = evaluate_function_relation_retrieval(
        _gold(),
        _scores(),
        top_ks=(1, 2),
    )

    assert metrics["judgedDirectionRocAuc"] == 0.0
    assert metrics["knownPositiveRecallAtK"] == {"1": 0.0, "2": 1.0}
    assert metrics["sourceHitAtK"] == {"1": 0.0, "2": 1.0}
    assert metrics["meanKnownPositiveRank"] == 2.0
    assert metrics["meanReciprocalRankToFirstKnownPositive"] == 0.5
    assert set(ranks["rank"]) == {2}


def test_rejects_incomplete_scores_and_nonbinary_gold() -> None:
    with pytest.raises(ValueError, match="missing gold directions"):
        evaluate_function_relation_retrieval(_gold(), _scores().iloc[1:])

    gold = _gold()
    gold.loc[0, "final_coverage_label"] = "INSUFFICIENT_EVIDENCE"
    with pytest.raises(ValueError, match="binary labels"):
        evaluate_function_relation_retrieval(gold, _scores())


def test_evaluates_equal_k_rank_union() -> None:
    lexical = pd.DataFrame([
        {"direction_id": "a-b", "source_claim_id": "a", "candidate_claim_id": "b", "rank": 1},
        {"direction_id": "a-c", "source_claim_id": "a", "candidate_claim_id": "c", "rank": 4},
        {"direction_id": "d-b", "source_claim_id": "d", "candidate_claim_id": "b", "rank": 3},
    ])
    semantic = lexical.copy()
    semantic["rank"] = [5, 2, 4]

    result = evaluate_known_positive_rank_union(
        {"tfidf": lexical, "e5": semantic},
        top_ks=(1, 3),
    )

    assert result["unionAtK"]["1"] == {
        "knownPositiveRecall": 0.333333,
        "knownPositiveCount": 1,
        "sourceHit": 0.5,
        "sourceCount": 1,
        "maxCandidateBudget": 2,
    }
    assert result["unionAtK"]["3"]["knownPositiveRecall"] == 1.0
    assert result["unionAtK"]["3"]["maxCandidateBudget"] == 6


def test_rank_union_rejects_mismatched_positive_sets() -> None:
    lexical = pd.DataFrame([
        {"direction_id": "a-b", "source_claim_id": "a", "candidate_claim_id": "b", "rank": 1},
    ])
    semantic = lexical.copy()
    semantic["direction_id"] = "different"

    with pytest.raises(ValueError, match="sets must match"):
        evaluate_known_positive_rank_union({"tfidf": lexical, "e5": semantic})


def _complete_scores(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=["source_claim_id", "candidate_claim_id", "score"],
    )


def test_builds_bounded_union_and_reuses_only_known_approvals() -> None:
    claims = pd.DataFrame([
        {"claim_id": "a", "claim_text": "기능 A"},
        {"claim_id": "b", "claim_text": "기능 B"},
        {"claim_id": "c", "claim_text": "기능 C"},
    ])
    tfidf = _complete_scores([
        ("a", "b", 0.9), ("a", "c", 0.8),
        ("b", "a", 0.9), ("b", "c", 0.8),
        ("c", "a", 0.9), ("c", "b", 0.8),
    ])
    e5 = _complete_scores([
        ("a", "b", 0.8), ("a", "c", 0.95),
        ("b", "a", 0.8), ("b", "c", 0.95),
        ("c", "a", 0.8), ("c", "b", 0.95),
    ])
    known = pd.DataFrame([
        {
            "source_claim_id": "a",
            "candidate_claim_id": "b",
            "final_coverage_label": "COVERS",
            "relation_artifact_eligible": "True",
            "final_reason_code": "SAME_ENDPOINT_EQUIVALENT_SCOPE",
        },
        {
            "source_claim_id": "a",
            "candidate_claim_id": "c",
            "final_coverage_label": "DOES_NOT_COVER",
            "relation_artifact_eligible": "False",
            "final_reason_code": "DIFFERENT_ENDPOINT",
        },
    ])

    candidates, recovery, summary = build_function_relation_candidate_set(
        claims,
        {"tfidf": tfidf, "e5": e5},
        known,
        top_k=1,
    )

    assert len(candidates) == 6
    statuses = candidates.set_index(
        ["source_claim_id", "candidate_claim_id"]
    )["review_status"]
    assert statuses.loc[("a", "b")] == "KNOWN_APPROVED_COVERS"
    assert statuses.loc[("a", "c")] == "KNOWN_DOES_NOT_COVER"
    assert statuses.loc[("b", "c")] == "NEEDS_V3_OFFLINE_REVIEW"
    assert set(candidates["retrieval_channels"]) == {"E5", "TFIDF"}
    assert recovery.loc[0, "retrieved"]
    assert summary["maxCandidateBudgetPerSource"] == 2
    assert summary["knownApprovedPositiveRecall"] == 1.0
    assert summary["offlineV3ReviewDirections"] == 4


def test_candidate_builder_rejects_incomplete_pair_scores() -> None:
    claims = pd.DataFrame([
        {"claim_id": "a", "claim_text": "기능 A"},
        {"claim_id": "b", "claim_text": "기능 B"},
        {"claim_id": "c", "claim_text": "기능 C"},
    ])
    complete = _complete_scores([
        ("a", "b", 0.9), ("a", "c", 0.8),
        ("b", "a", 0.9), ("b", "c", 0.8),
        ("c", "a", 0.9), ("c", "b", 0.8),
    ])
    known = pd.DataFrame(columns=[
        "source_claim_id",
        "candidate_claim_id",
        "final_coverage_label",
        "relation_artifact_eligible",
    ])

    with pytest.raises(ValueError, match="cover every directed non-self pair"):
        build_function_relation_candidate_set(
            claims,
            {"tfidf": complete.iloc[1:], "e5": complete},
            known,
            top_k=1,
        )
