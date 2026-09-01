import pandas as pd

from moongcheap_ai.health_v1 import parse_intake, split_ingredient_text, split_recognition_number


def test_recognition_number_is_separated_without_losing_source_text():
    normalized, number = split_recognition_number("홍삼제품 (제2025-46호)")
    assert normalized == "홍삼제품"
    assert number == "제2025-46호"


def test_ingredient_parser_respects_parentheses():
    values, status = split_ingredient_text("비오틴, 나이아신(혼합물, 10%), 홍삼")
    assert values == ["비오틴", "나이아신(혼합물, 10%)", "홍삼"]
    assert status == "PARSED"


def test_intake_parser_extracts_frequency_and_dose():
    result = parse_intake("1일 2회, 1회 2캡슐을 섭취하십시오.")
    assert result["daily_frequency_candidate"] == "1일 2회"
    assert result["amount_per_intake_candidate"] == "2"
    assert result["dose_unit_candidate"] == "캡슐"


def test_v1_artifacts_keep_missing_category_products(tmp_path):
    from moongcheap_ai.health_v1 import build_v1_artifacts

    frame = pd.DataFrame([{
        "source_product_id": "1", "name": "A", "product_type": "홍삼 (제2025-1호)",
        "product_form": "정제", "intake_method": "1일 1회 1정 섭취", "functional_ingredients": "홍삼",
        "standard_spec": "규격", "main_functionality": "기능", "manufacturer": "M",
    }, {
        "source_product_id": "2", "name": "B", "product_type": "", "product_form": "분말",
        "intake_method": "", "functional_ingredients": "비타민C", "standard_spec": "", "main_functionality": "", "manufacturer": "N",
    }])
    result = build_v1_artifacts(frame, tmp_path)
    assert result["product_rows"] == 2
    catalog = pd.read_csv(tmp_path / "product_catalog_candidate_v1.csv", dtype=str).fillna("")
    assert len(catalog) == 2
    assert catalog.loc[1, "service_category_key"] == "UNMAPPED"
    assert catalog["catalog_id"].eq("").all()
