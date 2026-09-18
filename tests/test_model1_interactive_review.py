from __future__ import annotations

import pandas as pd

from scripts.model1.review_queue_interactive import apply_decision


def test_apply_decision_adds_review_columns_and_preserves_source_data() -> None:
    source = pd.DataFrame(
        [{"review_id": "r1", "facet_name": "product_form", "facet_value": "분말"}]
    )
    reviewed = apply_decision(
        source,
        0,
        "EDIT",
        facet="product_form",
        value="캡슐",
        note="근거 문장과 후보 값이 불일치",
        reviewed_at="2026-09-18T00:00:00+00:00",
    )

    assert reviewed.loc[0, "review_id"] == "r1"
    assert reviewed.loc[0, "facet_value"] == "분말"
    assert reviewed.loc[0, "human_decision"] == "EDIT"
    assert reviewed.loc[0, "human_corrected_facet"] == "product_form"
    assert reviewed.loc[0, "human_value"] == "캡슐"
    assert reviewed.loc[0, "human_note"] == "근거 문장과 후보 값이 불일치"


def test_apply_decision_rejects_unknown_decision() -> None:
    source = pd.DataFrame([{"review_id": "r1"}])
    try:
        apply_decision(source, 0, "MAYBE")
    except ValueError as exc:
        assert "unsupported decision" in str(exc)
    else:
        raise AssertionError("unknown decisions must be rejected")
