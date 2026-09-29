import pandas as pd

from scripts.evaluation.build_model1_facet_gold import build_gold


def test_build_gold_accepts_taxonomy_review_schema_and_keeps_pending() -> None:
    review = pd.DataFrame(
        [
            {
                "category_id": "cat-a",
                "category_name": "테스트",
                "facet_candidate": "form",
                "value_candidate": "캡슐",
                "aliases": "[\"캅셀\"]",
                "human_decision": "APPROVE",
                "support_count": "4",
            },
            {
                "category_id": "cat-a",
                "facet_candidate": "form",
                "value_candidate": "정제",
                "human_decision": "UNCERTAIN",
            },
        ]
    )
    gold, audit = build_gold(review)
    assert len(gold) == 1
    assert gold.iloc[0].canonical_value == "캡슐"
    assert gold.iloc[0].gold_status == "GOLD_READY"
    assert len(audit) == 1


def test_edit_uses_corrected_values_and_is_deterministic() -> None:
    review = pd.DataFrame(
        [
            {
                "category_key": "cat-b",
                "category_name": "테스트",
                "facet_name": "form",
                "facet_value": "잘못된 값",
                "human_review_decision": "EDIT",
                "human_corrected_values_json": "[\"분말\", \"가루\"]",
            }
        ]
    )
    first, _ = build_gold(review)
    second, _ = build_gold(review)
    assert list(first.canonical_value) == ["가루", "분말"]
    assert first[["category_key", "facet_name", "canonical_value", "split"]].equals(
        second[["category_key", "facet_name", "canonical_value", "split"]]
    )
