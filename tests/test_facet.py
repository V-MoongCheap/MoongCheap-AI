import json

import pandas as pd

from moongcheap_ai.facet import preprocess_i0030


def test_preprocess_i0030_uses_mfds_category_fields(tmp_path):
    raw_dir = tmp_path / "I0030"
    raw_dir.mkdir()
    (raw_dir / "page_0001.json").write_text(
        json.dumps({"I0030": {"row": [{
            "PRDLST_REPORT_NO": "1234567890123",
            "PRDLST_NM": "테스트 제품",
            "PRDLST_CDNM": "비타민",
            "PRDT_SHAP_CD_NM": "정제",
            "IFTKN_ATNT_MATR_CN": "주의사항",
        }]}}, ensure_ascii=False),
        encoding="utf-8",
    )

    output = tmp_path / "clean.csv"
    result = preprocess_i0030(raw_dir, output)
    frame = pd.read_csv(output, dtype=str).fillna("")

    assert result == {"raw_rows": 1, "processed_rows": 1}
    assert frame.loc[0, "product_type"] == "비타민"
    assert frame.loc[0, "raw_category_name"] == "비타민"
    assert frame.loc[0, "product_form"] == "정제"
    assert frame.loc[0, "caution"] == "주의사항"
