import json
import re
import unicodedata
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
    assert {
        "corrected_expected_preference_groups",
        "proposed_expected_effective_requirement_mode",
        "corrected_expected_effective_requirement_mode",
        "proposed_expected_passthrough_text",
        "corrected_expected_passthrough_text",
    }.issubset(frame.columns)
    normalized = frame["extra_requirement"].map(
        lambda value: re.sub(
            r"[^0-9A-Za-z가-힣]+",
            "",
            unicodedata.normalize("NFKC", value).strip(),
        )
    )
    assert not normalized[normalized.ne("")].duplicated().any()


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
    multi = challenge.loc[challenge["scenario_type"].eq("MULTI_CONSTRAINT_CANDIDATE")]
    assert set(multi["proposed_expected_mode"]) == {"MIXED"}


def test_holdout_contains_only_unseen_candidates() -> None:
    frame = build_candidate_set(
        ROOT / "config/facet_taxonomy_v2_2.json",
        ROOT / "tests/demand_constraints/fixtures/v042_approved_eval.csv",
    )
    holdout = frame.loc[frame["evaluation_partition_candidate"].eq("HOLDOUT")]
    assert len(holdout) == 50
    assert set(holdout["parser_exposure"]) == {"NEW_UNSEEN_CANDIDATE"}
    assert frame.loc[frame["evaluation_partition_candidate"].eq("DEV"), "parser_exposure"].eq(
        "KNOWN_TO_EXISTING_TESTS"
    ).all()


def test_taxonomy_cleanup_removes_invalid_daily_frequency_and_duplicate_value() -> None:
    frame = build_candidate_set(
        ROOT / "config/facet_taxonomy_v2_2.json",
        ROOT / "tests/demand_constraints/fixtures/v042_approved_eval.csv",
    ).set_index("case_id")
    assert not frame["proposed_expected_constraints"].str.contains("11일 1회").any()
    assert not frame["proposed_expected_constraints"].str.contains("비오틴, 판토텐산").any()
    assert set(frame["reviewer_status"]) == {"PENDING_REVIEW"}


def test_finalize_blocks_pending_review(tmp_path: Path) -> None:
    source = tmp_path / "candidates.csv"
    frame = build_candidate_set(
        ROOT / "config/facet_taxonomy_v2_2.json",
        ROOT / "tests/demand_constraints/fixtures/v042_approved_eval.csv",
    )
    frame.to_csv(source, index=False, encoding="utf-8-sig")
    with pytest.raises(ValueError, match="not APPROVED"):
        finalize(source, tmp_path / "gold")
