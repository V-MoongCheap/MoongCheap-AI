import pandas as pd

from scripts.demand.apply_model2_review_resolution import build


def test_review_resolution_does_not_auto_approve_edits(tmp_path):
    review = tmp_path / "review.csv"
    runtime = tmp_path / "runtime.csv"
    output = tmp_path / "resolved.csv"
    gold = tmp_path / "gold.csv"
    pd.DataFrame([{"demand_id": "d1", "review_decision": "EDIT", "review_note": "수정 필요"}, {"demand_id": "d2", "review_decision": "REJECT", "review_note": "무관"}]).to_csv(review, index=False, encoding="utf-8-sig")
    pd.DataFrame([{"demand_id": "d1", "status": "PARSED", "effectiveRequirementMode": "STRUCTURED", "constraints": "[]", "label": "0", "facet_values": "{}"}, {"demand_id": "d2", "status": "REVIEW", "effectiveRequirementMode": "NONE", "constraints": "[]", "label": "", "facet_values": "{}"}]).to_csv(runtime, index=False, encoding="utf-8-sig")
    summary = build(review, runtime, output, gold)
    assert summary["gold_candidate_rows"] == 0
    result = pd.read_csv(output, dtype=str)
    assert result.loc[0, "gold_eligibility"] == "PENDING_EDIT_AND_REVIEW"
    assert result.loc[1, "gold_eligibility"] == "EXCLUDED"
