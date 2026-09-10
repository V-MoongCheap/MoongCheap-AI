import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "model1" / "run_multisource_facet_discovery.py"
SPEC = importlib.util.spec_from_file_location("model1_multisource", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _input_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "category_key": "health-functional-food:probiotics",
                "category_name": "유산균·프로바이오틱스",
                "source_product_id": "mfds:p1",
                "product_name": "유산균 캡슐",
                "source_category": "프로바이오틱스",
                "product_form": "캡슐",
                "functional_ingredients": "프로바이오틱스",
                "regulated_function": "",
                "intake_method": "",
                "sampling_reason": "test",
                "source_type": "MFDS_PRODUCT",
                "price_text": "",
                "quantity_text": "",
                "seller_condition": "",
                "evidence_text": "유산균 캡슐",
            },
            {
                "category_key": "health-functional-food:probiotics",
                "category_name": "유산균·프로바이오틱스",
                "source_product_id": "seller:s1",
                "product_name": "유산균 캡슐 판매 공고",
                "source_category": "건강식품",
                "product_form": "캡슐",
                "functional_ingredients": "프로바이오틱스",
                "regulated_function": "",
                "intake_method": "",
                "sampling_reason": "test",
                "source_type": "SELLER_LISTING",
                "price_text": "12000",
                "quantity_text": "2",
                "seller_condition": "",
                "evidence_text": "유산균 캡슐 판매 공고",
            },
        ]
    )


def test_reasoned_output_keeps_reason_and_source_type():
    payload = {
        "category_key": "health-functional-food:probiotics",
        "category_name": "유산균·프로바이오틱스",
        "facets": [
            {
                "facet_id_candidate": "product_form",
                "name": "Product Form",
                "definition": "제형",
                "selection_reason": "제형이 달라지면 섭취 편의성과 상품 비교 기준이 달라집니다.",
                "values": [{"value": "캡슐", "aliases": [], "value_reason": "캡슐 형태의 제품을 뜻합니다."}],
                "evidence": [{"source_product_id": "mfds:p1", "source_field": "product_form", "source_text": "캡슐"}],
            }
        ],
    }

    parsed, failures = MODULE.parse_reasoned_output(payload, _input_frame())

    assert not failures
    assert parsed.iloc[0]["reason_status"] == "PRESENT"
    assert parsed.iloc[0]["selection_reason"].startswith("제형이")
    assert parsed.iloc[0]["value_reason"].startswith("캡슐")
    assert parsed.iloc[0]["evidence_source_type"] == "MFDS_PRODUCT"


def test_selection_requires_model_and_source_consensus():
    base = MODULE.parse_reasoned_output(
        {
            "category_key": "health-functional-food:probiotics",
            "category_name": "유산균·프로바이오틱스",
            "facets": [
                {
                    "name": "Product Form",
                    "definition": "제형",
                    "selection_reason": "제형이 달라지면 섭취 편의성과 상품 비교 기준이 달라집니다.",
                    "values": [{"value": "캡슐", "aliases": [], "value_reason": "캡슐 형태"}],
                    "evidence": [{"source_product_id": "mfds:p1", "source_field": "product_form", "source_text": "캡슐"}],
                }
            ],
        },
        _input_frame(),
    )[0]
    candidate = pd.concat([base.assign(model="qwen3:4b"), base.assign(model="gemma3:4b", source_product_id="seller:s1", evidence_source_type="SELLER_LISTING")], ignore_index=True)

    selected = MODULE.select_candidates(candidate)

    assert selected.iloc[0]["selection_status"] == "SELECTED_CANDIDATE"
    assert selected.iloc[0]["model_support"] == 2
    assert selected.iloc[0]["source_type_count"] == 2


def test_malformed_facet_item_is_recorded_as_schema_failure():
    parsed, failures = MODULE.parse_reasoned_output(
        {"category_key": "health-functional-food:probiotics", "facets": ["malformed"]},
        _input_frame(),
    )

    assert parsed.empty
    assert failures[0]["failure_type"] == "SCHEMA_VALIDATION_FAILED"


def test_data_selection_reason_reports_observed_rows_and_sources():
    payload = {
        "category_key": "health-functional-food:probiotics",
        "category_name": "유산균·프로바이오틱스",
        "facets": [
            {
                "name": "Product Form",
                "selection_reason": "입력 상품과 판매 공고에서 관찰됨",
                "values": [{"value": "캡슐", "aliases": [], "value_reason": "캡슐 제품"}],
                "evidence": [{"source_product_id": "mfds:p1", "source_field": "product_form", "source_text": "캡슐"}],
            }
        ],
    }
    parsed, _ = MODULE.parse_reasoned_output(payload, _input_frame())
    parsed["model"] = "qwen3:4b"

    result = MODULE.add_data_selection_reason(parsed, _input_frame())

    assert result.iloc[0]["observed_row_count"] == 2
    assert result.iloc[0]["observed_source_type_count"] == 2
    assert "MFDS_PRODUCT" in result.iloc[0]["data_selection_reason"]


def test_facet_input_excludes_synthetic_demand_sources(monkeypatch):
    base = _input_frame().iloc[[0]].copy()
    synthetic = base.copy()
    synthetic["source_product_id"] = "demand:d1"
    synthetic["source_type"] = "GROUNDED_DEMAND_SYNTHETIC"

    monkeypatch.setattr(MODULE, "load_products", lambda path: base)
    monkeypatch.setattr(MODULE, "load_seller_offers", lambda path: base.iloc[0:0])
    monkeypatch.setattr(MODULE, "load_demands", lambda path: synthetic)
    monkeypatch.setattr(MODULE, "load_boards", lambda path: synthetic)
    monkeypatch.setattr(MODULE, "load_translated_queries", lambda path: base.iloc[0:0])

    result = MODULE.build_multisource_input({
        "products": Path("products.csv"),
        "sellers": Path("sellers.csv"),
        "demands": Path("demands.csv"),
        "boards": Path("boards.json"),
        "queries": Path("queries.parquet"),
    })

    assert set(result["source_type"]) == {"MFDS_PRODUCT"}
