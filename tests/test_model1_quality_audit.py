from __future__ import annotations

import pandas as pd

from scripts.model1.audit_multisource_quality import audit


def test_model1_audit_passes_grounded_candidate() -> None:
    inputs = pd.DataFrame(
        [{"category_key": "cat", "source_product_id": "product-1"}]
    )
    candidates = pd.DataFrame(
        [
            {
                "model": "kanana",
                "category_key": "cat",
                "name": "form",
                "value": "capsule",
                "source_product_id": "product-1",
                "selection_reason": "observed form",
                "value_reason": "observed value",
                "observed_row_count": "1",
            }
        ]
    )
    result = audit(inputs, candidates)
    assert result["status"] == "PASS"
    assert result["blocking_issues"] == {}


def test_model1_audit_blocks_unobserved_or_foreign_evidence() -> None:
    inputs = pd.DataFrame(
        [{"category_key": "cat", "source_product_id": "product-1"}]
    )
    candidates = pd.DataFrame(
        [
            {
                "model": "kanana",
                "category_key": "cat",
                "name": "form",
                "value": "invented",
                "source_product_id": "foreign-product",
                "selection_reason": "",
                "value_reason": "",
                "observed_row_count": "0",
            }
        ]
    )
    result = audit(inputs, candidates)
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["blocking_issues"]["missing_source_product"] == 1
    assert result["blocking_issues"]["unobserved_value"] == 1
