from __future__ import annotations

import json

import pandas as pd

from scripts.data.build_facet_taxonomy_resolution_proposal import build_proposal


def _values(*items: tuple[int, str]) -> str:
    return json.dumps([{"code": code, "value": value} for code, value in items], ensure_ascii=False)


def test_normalised_duplicate_is_alias_candidate_with_lowest_code() -> None:
    overlap = pd.DataFrame([{
        "category_id": "vitamin",
        "facet_name": "functional_ingredients",
        "candidate_values": _values((2, "비타민 D"), (5, "비타민D")),
        "catalog_count": "45",
        "textual_overlap_pairs": json.dumps(["비타민 D = 비타민D (normalized duplicate)"], ensure_ascii=False),
    }])

    proposal, summary = build_proposal(overlap)

    assert summary["alias_merge_candidates"] == 1
    assert proposal.loc[0, "resolution_type"] == "MERGE_AS_ALIAS_CANDIDATE"
    assert proposal.loc[0, "proposed_canonical_code"] == 2
    assert json.loads(proposal.loc[0, "proposed_aliases"]) == ["비타민D"]
    assert proposal.loc[0, "review_decision"] == "PENDING_HUMAN_REVIEW"


def test_semantic_overlap_is_not_automatically_merged() -> None:
    overlap = pd.DataFrame([{
        "category_id": "red_ginseng",
        "facet_name": "functional_ingredients",
        "candidate_values": _values((1, "홍삼"), (2, "홍삼제품")),
        "catalog_count": "37",
        "textual_overlap_pairs": json.dumps(["홍삼 -> 홍삼제품"], ensure_ascii=False),
    }])

    proposal, summary = build_proposal(overlap)

    assert summary["semantic_review_required"] == 1
    assert proposal.loc[0, "resolution_type"] == "SEMANTIC_REVIEW_REQUIRED"
    assert proposal.loc[0, "proposed_canonical_code"] == ""
    assert proposal.loc[0, "proposed_aliases"] == "[]"
