from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from moongcheap_ai.demand_clustering.evaluation.substitute_annotation import (
    AnnotationValidationError,
    SubstituteAnnotationStore,
    dataset_fingerprint,
    load_pair_frame,
)


def pair_frame(count: int = 6) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "pair_id": f"pair-{index}",
                "source_product_id": f"source-{index}",
                "candidate_product_id": f"candidate-{index}",
                "source_product_name": f"원상품 {index}",
                "candidate_product_name": f"후보상품 {index}",
                "gold_label": "",
                "label_reason_codes": "",
                "critical_negative": "",
                "reviewer_1": "",
                "reviewer_2": "",
                "adjudicator": "",
                "reviewed_at": "",
            }
            for index in range(count)
        ]
    )


def initialized_store(tmp_path: Path) -> tuple[SubstituteAnnotationStore, pd.DataFrame]:
    pairs = pair_frame()
    store = SubstituteAnnotationStore(tmp_path / "annotations.sqlite3")
    store.initialize_assignments(
        pairs["pair_id"].tolist(),
        ("reviewer-a", "reviewer-b", "reviewer-c"),
        "dataset-v1",
    )
    return store, pairs


def test_pair_loader_and_fingerprint_are_stable(tmp_path: Path) -> None:
    path = tmp_path / "pairs.csv"
    pair_frame().to_csv(path, index=False)

    loaded = load_pair_frame(path)

    assert len(loaded) == 6
    assert dataset_fingerprint(path) == dataset_fingerprint(path)


def test_balances_two_independent_assignments_across_three_reviewers(
    tmp_path: Path,
) -> None:
    store, _pairs = initialized_store(tmp_path)

    assert store.assignment_counts() == {
        "reviewer-a": 4,
        "reviewer-b": 4,
        "reviewer-c": 4,
    }
    assert all(
        len(store.reviewers_for_pair(f"pair-{index}")) == 2
        for index in range(6)
    )
    assert store.progress_summary() == {
        "total_pairs": 6,
        "assigned_judgments": 12,
        "completed_judgments": 0,
        "pending_judgments": 12,
        "fully_reviewed_pairs": 0,
        "agreement_pairs": 0,
        "conflict_pairs": 0,
        "adjudicated_pairs": 0,
        "gold_complete_pairs": 0,
    }


def test_agreement_is_exported_without_adjudication(tmp_path: Path) -> None:
    store, pairs = initialized_store(tmp_path)
    pair_id = "pair-0"
    reviewer_1, reviewer_2 = store.reviewers_for_pair(pair_id)
    store.save_annotation(
        pair_id,
        reviewer_1,
        "SUBSTITUTABLE",
        ("SOURCE_FUNCTION_COVERED",),
        False,
    )
    store.save_annotation(
        pair_id,
        reviewer_2,
        "SUBSTITUTABLE",
        ("SAME_PRIMARY_FUNCTION",),
        False,
    )

    output_path = tmp_path / "gold.csv"
    result = store.export_gold(pairs, output_path)
    exported = pd.read_csv(output_path, dtype=str, keep_default_na=False)
    row = exported.loc[exported["pair_id"] == pair_id].iloc[0]

    assert result["gold_rows"] == 1
    assert row["gold_label"] == "SUBSTITUTABLE"
    assert row["annotation_status"] == "AGREEMENT"
    assert row["adjudicator"] == ""
    assert set(row["label_reason_codes"].split(" | ")) == {
        "SOURCE_FUNCTION_COVERED",
        "SAME_PRIMARY_FUNCTION",
    }


def test_conflict_requires_unassigned_third_reviewer_and_note(
    tmp_path: Path,
) -> None:
    store, pairs = initialized_store(tmp_path)
    pair_id = "pair-1"
    reviewer_1, reviewer_2 = store.reviewers_for_pair(pair_id)
    adjudicator = next(
        reviewer
        for reviewer in store.reviewer_ids()
        if reviewer not in {reviewer_1, reviewer_2}
    )
    store.save_annotation(
        pair_id,
        reviewer_1,
        "SUBSTITUTABLE",
        ("SOURCE_FUNCTION_COVERED",),
        False,
    )
    store.save_annotation(
        pair_id,
        reviewer_2,
        "NOT_SUBSTITUTABLE",
        ("SOURCE_FUNCTION_NOT_COVERED",),
        True,
    )

    assert store.conflict_pair_ids() == (pair_id,)
    with pytest.raises(AnnotationValidationError, match="must not be"):
        store.save_adjudication(
            pair_id,
            reviewer_1,
            "NOT_SUBSTITUTABLE",
            ("SOURCE_FUNCTION_NOT_COVERED",),
            True,
            "합의 근거",
        )
    with pytest.raises(AnnotationValidationError, match="note is required"):
        store.save_adjudication(
            pair_id,
            adjudicator,
            "NOT_SUBSTITUTABLE",
            ("SOURCE_FUNCTION_NOT_COVERED",),
            True,
            "",
        )

    store.save_adjudication(
        pair_id,
        adjudicator,
        "NOT_SUBSTITUTABLE",
        ("SOURCE_FUNCTION_NOT_COVERED",),
        True,
        "후보가 원상품의 핵심 기능을 보존하지 못함",
    )
    assert store.conflict_pair_ids() == ()
    result = store.export_gold(pairs, tmp_path / "gold.csv")
    assert result["gold_rows"] == 1
    assert result["status_counts"]["ADJUDICATED"] == 1


def test_rejects_invalid_or_unassigned_decisions(tmp_path: Path) -> None:
    store, _pairs = initialized_store(tmp_path)
    pair_id = "pair-0"
    assigned = store.reviewers_for_pair(pair_id)[0]
    unassigned = next(
        reviewer for reviewer in store.reviewer_ids() if reviewer not in store.reviewers_for_pair(pair_id)
    )

    with pytest.raises(AnnotationValidationError, match="reason code is required"):
        store.save_annotation(pair_id, assigned, "SUBSTITUTABLE", (), False)
    with pytest.raises(AnnotationValidationError, match="only for NOT_SUBSTITUTABLE"):
        store.save_annotation(
            pair_id,
            assigned,
            "SUBSTITUTABLE",
            ("SOURCE_FUNCTION_COVERED",),
            True,
        )
    with pytest.raises(AnnotationValidationError, match="not assigned"):
        store.save_annotation(
            pair_id,
            unassigned,
            "NOT_SUBSTITUTABLE",
            ("CATEGORY_MISMATCH",),
            False,
        )


def test_database_is_bound_to_exact_pair_file(tmp_path: Path) -> None:
    store, pairs = initialized_store(tmp_path)

    store.verify_dataset(pairs["pair_id"].tolist(), "dataset-v1")
    with pytest.raises(AnnotationValidationError, match="differs"):
        store.verify_dataset(pairs["pair_id"].tolist(), "different")
