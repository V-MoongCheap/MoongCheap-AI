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


def test_assistant_qa_corrections_are_applied_without_auto_approval() -> None:
    frame = build_candidate_set(
        ROOT / "config/facet_taxonomy_v2_2.json",
        ROOT / "tests/demand_constraints/fixtures/v042_approved_eval.csv",
    ).set_index("case_id")

    row = frame.loc["part-a-v2-2-121"]
    assert row["proposed_expected_mode"] == "MUST"
    assert '"constraint_type":"MUST"' in row["proposed_expected_constraints"]

    row = frame.loc["part-a-v2-2-129"]
    assert row["extra_requirement"] == "캡슐 제형이 포함된 제품을 찾아주세요."
    assert '"value_code":1' in row["proposed_expected_constraints"]

    assert frame.loc["part-a-v2-2-149", "extra_requirement"] == (
        "오메가-3지방산함유유지가 포함된 제품을 찾습니다."
    )
    assert frame.loc["part-a-v2-2-180", "extra_requirement"] == (
        "겔은 반드시 포함하고, 겔은 제외해주세요."
    )
    assert frame.loc["part-a-v2-2-191", "extra_requirement"] == (
        "반드시 캡슐 제품이면 좋겠어요."
    )

    # QA corrections prepare the candidate set; human approval is still required.
    assert set(frame["reviewer_status"]) == {"PENDING_REVIEW"}
    assert "11일 1회" not in frame.loc["part-a-v2-2-118", "reviewer_note"]
    assert "TAXONOMY_CHECK_REQUIRED" not in frame.loc["part-a-v2-2-162", "reviewer_note"]


def test_finalize_blocks_pending_review(tmp_path: Path) -> None:
    source = tmp_path / "candidates.csv"
    frame = build_candidate_set(
        ROOT / "config/facet_taxonomy_v2_2.json",
        ROOT / "tests/demand_constraints/fixtures/v042_approved_eval.csv",
    )
    frame.to_csv(source, index=False, encoding="utf-8-sig")
    with pytest.raises(ValueError, match="not APPROVED"):
        finalize(source, tmp_path / "gold")
