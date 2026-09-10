from __future__ import annotations

import json

import pandas as pd

from scripts.taxonomy.build_v2_2 import (
    build_alias_artifacts,
    build_taxonomy_v22,
    build_value_crosswalk,
    validate_taxonomy,
)


def _taxonomy() -> dict:
    return {
        "version": "v2.1",
        "status": "CANDIDATE",
        "categories": [
            {
                "category_id": "cat-a",
                "category_name": "A",
                "facets": [
                    {"facet_id": "cat-a:product_form", "name": "product_form", "order": 1, "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "정"}, {"code": 2, "value": "분말"}]},
                    {"facet_id": "cat-a:daily_frequency", "name": "daily_frequency", "order": 2, "values": [{"code": 0, "value": "ALL"}]},
                ],
            },
            {
                "category_id": "cat-b",
                "category_name": "B",
                "facets": [
                    {"facet_id": "cat-b:product_form", "name": "product_form", "order": 1, "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "분말"}, {"code": 2, "value": "정"}]},
                    {"facet_id": "cat-b:daily_frequency", "name": "daily_frequency", "order": 2, "values": [{"code": 0, "value": "ALL"}]},
                ],
            },
        ],
    }


def test_v22_preserves_codes_and_does_not_add_new_facets() -> None:
    before = _taxonomy()
    after = build_taxonomy_v22(before)
    assert after["version"] == "v2.2"
    assert after["status"] == "APPROVED"
    assert validate_taxonomy(before, after)["preserved_codes"] == 1
    assert sum(len(c["facets"]) for c in after["categories"]) == 4


def test_crosswalk_is_category_local() -> None:
    crosswalk = build_value_crosswalk(_taxonomy())
    local = crosswalk["mappings"]["product_form"]
    assert local["cat-a"]["powder"]["code"] == 2
    assert local["cat-b"]["powder"]["code"] == 1


def test_alias_apply_rejects_unknown_facet_and_keeps_rejected_rows_out() -> None:
    taxonomy = build_taxonomy_v22(_taxonomy())
    review = pd.DataFrame([
        {"review_order": "1", "facet_id": "product_form", "value_candidate": "powder", "corrected_value_candidate": "", "candidate_expression": "가루", "reviewer_decision": "APPROVE_ALIAS"},
        {"review_order": "2", "facet_id": "taste", "value_candidate": "bitter", "corrected_value_candidate": "taste", "candidate_expression": "쓴맛", "reviewer_decision": "NEEDS_REVIEW"},
        {"review_order": "3", "facet_id": "product_form", "value_candidate": "tablet", "corrected_value_candidate": "", "candidate_expression": "알약", "reviewer_decision": "REJECT_DIFFERENT_MEANING"},
    ])
    registry, audit = build_alias_artifacts(review, taxonomy, build_value_crosswalk(taxonomy))
    assert int((audit["apply_status"] == "APPLIED").sum()) == 1
    assert int((audit["apply_status"] == "DEFERRED_TAXONOMY_NOT_APPROVED").sum()) == 1
    assert int((audit["apply_status"] == "REJECTED_BY_HUMAN").sum()) == 1
    assert len(registry["aliases"]) == 1


def test_v22_artifact_is_json_round_trippable() -> None:
    payload = build_taxonomy_v22(_taxonomy())
    assert json.loads(json.dumps(payload, ensure_ascii=False))["version"] == "v2.2"
