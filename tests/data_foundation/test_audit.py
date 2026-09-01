import pandas as pd

from moongcheap_ai.audit import audit_aihub, build_category_source_mapping


def test_aihub_audit_reports_barcode_conflicts_without_deduplicating_rows():
    frame = pd.DataFrame([
        {"product_name_normalized": "상품 A", "barcode": "001", "kan_code": "K1", "source_category_path": "식품"},
        {"product_name_normalized": "상품 B", "barcode": "001", "kan_code": "K2", "source_category_path": "식품"},
    ])

    summary, conflicts = audit_aihub(frame)

    assert summary["raw_row_count"] == 2
    assert summary["unique_barcode_count"] == 1
    assert summary["same_barcode_different_product_name_groups"] == 1
    assert summary["same_barcode_different_kan_code_groups"] == 1
    assert len(conflicts) == 1


def test_category_source_mapping_uses_observed_kan_code_only():
    frame = pd.DataFrame([{
        "source": "AI_HUB",
        "source_category_id": "1",
        "source_category_name": "식품",
        "source_category_path": "식품",
        "kan_code": "01010101",
    }])

    result = build_category_source_mapping(frame)

    assert result.loc[0, "category_key"] == "KAN:01010101"
    assert result.loc[0, "mapping_method"] == "EXACT_CODE"
    assert result.loc[0, "review_status"] == "OBSERVED"
