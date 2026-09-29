import pandas as pd

from scripts.evaluation.prepare_model1_facet_review_queue import prepare_queue


def test_splits_obvious_composites_and_keeps_source() -> None:
    result = prepare_queue(
        pd.DataFrame(
            [
                {"category_id": "a", "facet_candidate": "ingredient", "value_candidate": "A, B"},
                {"category_id": "a", "facet_candidate": "ingredient", "value_candidate": "A"},
            ]
        )
    )
    assert set(result.atomic_value) == {"A", "B"}
    assert len(result) == 2
    assert result.loc[result.atomic_value.eq("A"), "composite_source_value"].iloc[0] == "A, B"


def test_does_not_split_conjunction_without_strong_evidence() -> None:
    result = prepare_queue(
        pd.DataFrame(
            [{"category_id": "a", "facet_candidate": "ingredient", "value_candidate": "EPA 및 DHA 함유 유지"}]
        )
    )
    assert list(result.atomic_value) == ["EPA 및 DHA 함유 유지"]
