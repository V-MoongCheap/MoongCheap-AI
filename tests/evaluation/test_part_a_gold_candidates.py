import json
from pathlib import Path

import pytest

from scripts.evaluation.build_part_a_gold_candidates import build_candidate_set
from scripts.evaluation.finalize_part_a_gold_v2_2 import finalize


ROOT = Path(__file__).resolve().parents[2]


def test_candidate_set_has_fixed_review_splits_and_pending_status() -> None:
    frame = build_candidate_set(
        ROOT / "config/facet_taxonomy_v2_2.json",
        ROOT / "tests/demand_constraints/fixtures/v042_approved_eval.csv",
    )
    assert len(frame) == 200
    assert frame["split_candidate"].value_counts().to_dict() == {"STANDARD": 150, "CHALLENGE": 50}
    assert set(frame["reviewer_status"]) == {"PENDING_REVIEW"}
    assert frame["case_id"].is_unique


def test_candidate_constraints_are_serializable_and_category_local() -> None:
    frame = build_candidate_set(
        ROOT / "config/facet_taxonomy_v2_2.json",
        ROOT / "tests/demand_constraints/fixtures/v042_approved_eval.csv",
    )
    for raw in frame["proposed_expected_constraints"]:
        assert isinstance(json.loads(raw), list)
    assert frame["category_id"].str.startswith("health-functional-food:").all()


def test_challenge_split_covers_runtime_edge_states() -> None:
    frame = build_candidate_set(
        ROOT / "config/facet_taxonomy_v2_2.json",
        ROOT / "tests/demand_constraints/fixtures/v042_approved_eval.csv",
    )
    challenge = frame.loc[frame["split_candidate"].eq("CHALLENGE")]
    assert set(challenge["proposed_expected_status"]) == {
        "PARSED", "PASSTHROUGH", "CONFLICT", "REVIEW", "NOT_APPLICABLE", "NONE",
    }
    assert "ANY_OF" in set(challenge["proposed_expected_mode"])


def test_finalize_blocks_pending_review(tmp_path: Path) -> None:
    source = tmp_path / "candidates.csv"
    frame = build_candidate_set(
        ROOT / "config/facet_taxonomy_v2_2.json",
        ROOT / "tests/demand_constraints/fixtures/v042_approved_eval.csv",
    )
    frame.to_csv(source, index=False, encoding="utf-8-sig")
    with pytest.raises(ValueError, match="not APPROVED"):
        finalize(source, tmp_path / "gold")
