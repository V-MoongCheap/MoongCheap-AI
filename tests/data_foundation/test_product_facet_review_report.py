import json

import pandas as pd

from scripts.data.build_product_facet_review_report import build


def test_review_report_prioritizes_unresolved_mapping_and_keeps_decisions_blank(tmp_path):
    mapping = tmp_path / "mapping.csv"
    queue = tmp_path / "review.csv"
    summary = tmp_path / "summary.json"
    pd.DataFrame(
        [
            {
                "catalog_id": "c1",
                "source_product_id": "p1",
                "category_id": "cat1",
                "facet_name": "product_form",
                "value": "",
                "mapping_status": "UNKNOWN",
                "mapping_reason": "NO_OBSERVED_VALUE",
                "matched_text": "",
                "source_fields": "[]",
                "source_document_id": "p1",
                "source": "DOMEGGOOK",
            },
            {
                "catalog_id": "c2",
                "source_product_id": "p2",
                "category_id": "cat1",
                "facet_name": "product_form",
                "value": "",
                "mapping_status": "AMBIGUOUS",
                "mapping_reason": "MULTIPLE_OBSERVED_VALUES",
                "matched_text": "분말;캡슐",
                "source_fields": "[\"name\"]",
                "source_document_id": "p2",
                "source": "DOMEGGOOK",
            },
            {
                "catalog_id": "c3",
                "source_product_id": "p3",
                "category_id": "cat1",
                "facet_name": "product_form",
                "value": "capsule",
                "mapping_status": "MAPPED",
                "mapping_reason": "OBSERVED_CATALOG_TEXT",
                "matched_text": "캡슐",
                "source_fields": "[\"name\"]",
                "source_document_id": "p3",
                "source": "DOMEGGOOK",
            },
        ]
    ).to_csv(mapping, index=False, encoding="utf-8-sig")

    result, report = build(mapping, queue, summary)

    assert list(result["review_priority"]) == ["HIGH", "MEDIUM"]
    assert result["reviewed_value"].eq("").all()
    assert result["reviewed_code"].eq("").all()
    assert result["review_decision"].eq("").all()
    assert report["status_counts"] == {"UNKNOWN": 1, "AMBIGUOUS": 1, "MAPPED": 1}
    assert json.loads(summary.read_text(encoding="utf-8"))["review_rows"] == 2
