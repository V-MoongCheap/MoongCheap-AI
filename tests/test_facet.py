import json

import pandas as pd

from moongcheap_ai.data_foundation.facet import preprocess_i0030, validate_i0030


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


def test_preprocess_i2710_maps_actual_mfds_i2710_keys(tmp_path):
    raw_dir = tmp_path / "I2710"
    raw_dir.mkdir()
    (raw_dir / "page_001.json").write_text(
        json.dumps({"I2710": {"row": [{
            "PRDCT_NM": "홍삼", "PRIMARY_FNCLTY": "면역력 증진",
            "SKLL_IX_IRDNT_RAWMTRL": "진세노사이드", "DAY_INTK_LOWLIMIT": "3",
            "DAY_INTK_HIGHLIMIT": "80", "INTK_UNIT": "mg",
            "IFTKN_ATNT_MATR_CN": "주의",
        }]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    output = tmp_path / "i2710.csv"
    from moongcheap_ai.data_foundation.facet import preprocess_i2710
    result = preprocess_i2710(raw_dir, output)
    frame = pd.read_csv(output, dtype=str).fillna("")
    assert result == {"raw_rows": 1, "processed_rows": 1}
    assert frame.loc[0, "category_reference_name"] == "홍삼"
    assert frame.loc[0, "ingredient_name"] == "진세노사이드"
    assert frame.loc[0, "daily_intake_min"] == "3"
    assert frame.loc[0, "daily_intake_max"] == "80"
    assert frame.loc[0, "unit"] == "mg"
    assert frame.loc[0, "caution"] == "주의"


def test_validate_i0030_removes_only_duplicate_report_numbers():
    frame = pd.DataFrame([
        {"source_product_id": "1", "name": "같은 신고번호", "product_type": "비타민"},
        {"source_product_id": "1", "name": "같은 신고번호", "product_type": "비타민"},
        {"source_product_id": "2", "name": "같은 상품명", "product_type": "홍삼"},
    ])

    clean, duplicates, stats = validate_i0030(frame)

    assert clean["source_product_id"].tolist() == ["1", "2"]
    assert len(duplicates) == 1
    assert stats["duplicate_rows_removed"] == 1
    assert stats["missing_product_type"] == 0
