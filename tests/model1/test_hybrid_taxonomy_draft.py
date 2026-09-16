import json

import pandas as pd

from scripts.model1.build_hybrid_taxonomy_draft import build_draft


def test_hybrid_taxonomy_is_evidence_gated_and_deterministic():
    hybrid = pd.DataFrame(
        [
            {"category_key": "cat", "facet_id": "product_form", "value": "powder", "rule_support": 2, "rule_support_ratio": 0.5, "hybrid_status": "HYBRID_BACKED", "source_fields": "product_form"},
            {"category_key": "cat", "facet_id": "product_form", "value": "capsule", "rule_support": 1, "rule_support_ratio": 0.25, "hybrid_status": "RULE_ONLY", "source_fields": "product_form"},
            {"category_key": "cat", "facet_id": "functional_ingredients", "value": "invented", "rule_support": 0, "rule_support_ratio": 0, "hybrid_status": "MODEL_ONLY_REVIEW", "source_fields": "functional_ingredients"},
        ]
    )
    inputs = pd.DataFrame([{"category_key": "cat", "category_name": "Category"}])
    taxonomy, queue = build_draft(hybrid, inputs)
    assert taxonomy["status"] == "DRAFT_PENDING_HUMAN_REVIEW"
    assert taxonomy["categories"][0]["facets"][0]["values"][0]["code"] == 0
    assert taxonomy["categories"][0]["facets"][0]["values"][0]["value"] == "ALL"
    assert "capsule" not in json.dumps(taxonomy, ensure_ascii=False)
    assert "invented" in queue.loc[queue["hybrid_status"] == "MODEL_ONLY_REVIEW", "value_candidate"].tolist()


def test_empty_hybrid_input_has_stable_empty_review_schema():
    columns = [
        "category_key", "facet_id", "value", "rule_support", "rule_support_ratio",
        "hybrid_status", "source_fields",
    ]
    taxonomy, queue = build_draft(pd.DataFrame(columns=columns), pd.DataFrame())
    assert taxonomy["categories"] == []
    assert queue.empty
    assert queue.columns.tolist() == [
        "category_id", "category_name", "facet_candidate", "value_candidate", "aliases",
        "support_count", "document_ratio", "source_fields", "evidence_terms",
        "hybrid_status", "review_decision", "review_note",
    ]


def test_missing_hybrid_columns_fail_with_actionable_error():
    try:
        build_draft(pd.DataFrame(), pd.DataFrame())
    except ValueError as error:
        assert "missing required columns" in str(error)
    else:
        raise AssertionError("expected missing-column validation error")


def test_malformed_numeric_evidence_is_reviewable_not_fatal():
    columns = [
        "category_key", "facet_id", "value", "rule_support", "rule_support_ratio",
        "hybrid_status", "source_fields",
    ]
    hybrid = pd.DataFrame([["cat", "product_form", "powder", "bad", "bad", "RULE_ONLY", "product_form"]], columns=columns)
    _, queue = build_draft(hybrid, pd.DataFrame())
    assert queue.iloc[0]["review_decision"] == "REVIEW_REQUIRED"


def test_non_finite_numbers_and_duplicate_values_are_safe():
    columns = [
        "category_key", "facet_id", "value", "rule_support", "rule_support_ratio",
        "hybrid_status", "source_fields",
    ]
    hybrid = pd.DataFrame(
        [
            ["cat", "product_form", "powder", float("inf"), float("nan"), "RULE_ONLY", "product_form"],
            ["cat", "product_form", "powder", 2, 0.5, "RULE_ONLY", "product_form"],
        ],
        columns=columns,
    )
    taxonomy, _ = build_draft(hybrid, pd.DataFrame())
    values = taxonomy["categories"][0]["facets"][0]["values"]
    assert [item["value"] for item in values] == ["ALL", "powder"]
