import pandas as pd

from moongcheap_ai.data_foundation.postgres_reader import resolve_taxonomy_category_keys


def test_resolve_category_key_from_full_facet_text() -> None:
    frame = pd.DataFrame([{
        "category_db_id": 8,
        "category_id": 8,
        "category_facet": '{"category_id":"health-functional-food:probiotics","facets":[]}',
    }])

    resolved = resolve_taxonomy_category_keys(frame)

    assert resolved.loc[0, "category_id"] == "health-functional-food:probiotics"


def test_resolve_category_key_keeps_db_id_when_facet_is_not_mapped() -> None:
    frame = pd.DataFrame([{
        "category_db_id": 8,
        "category_id": 8,
        "category_facet": "[]",
    }])

    resolved = resolve_taxonomy_category_keys(frame)

    assert resolved.loc[0, "category_id"] == 8
