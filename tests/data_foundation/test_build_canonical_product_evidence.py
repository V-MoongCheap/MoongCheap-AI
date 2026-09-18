import pandas as pd

from scripts.data.build_canonical_product_evidence import build


def test_build_canonical_product_evidence_aggregates_observed_rows(tmp_path):
    evidence = tmp_path / "evidence.csv"
    output = tmp_path / "canonical.csv"
    pd.DataFrame([
        {
            "evidence_id": "e1", "category": "PROBIOTICS", "service_category": "PROBIOTICS",
            "source": "mfds", "document_id": "doc-1", "product_ref": "p1",
            "text_raw": "상품명 | 분말", "normalized_attribute": "product_form",
            "normalized_value": "분말", "license_status": "LOCAL_ONLY",
        },
        {
            "evidence_id": "e2", "category": "PROBIOTICS", "service_category": "PROBIOTICS",
            "source": "mfds", "document_id": "doc-1", "product_ref": "p1",
            "text_raw": "상품명 | 유산균", "normalized_attribute": "functional_ingredient",
            "normalized_value": "유산균", "license_status": "LOCAL_ONLY",
        },
    ]).to_csv(evidence, index=False)

    result = build(evidence, output)

    assert len(result) == 1
    assert result.loc[0, "source_product_id"] == "p1"
    assert result.loc[0, "product_form"] == "분말"
    assert result.loc[0, "source_document_id"] == "doc-1"
    assert result.loc[0, "name"] == "상품명"
