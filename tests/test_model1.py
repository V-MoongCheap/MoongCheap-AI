import pandas as pd

from moongcheap_ai.data_foundation.model1 import (
    MockModelAdapter,
    OllamaAdapter,
    OpenAICompatibleAdapter,
    TransformersAdapter,
    create_model_adapter,
    parse_model_output,
    sample_products,
)
from moongcheap_ai.data_foundation.model1 import _build_compact_prompt
from moongcheap_ai.data_foundation.model1_postprocess import (
    atomic_values,
    map_products,
    normalize_candidates,
)


def test_composite_values_are_split_before_deduplication():
    assert atomic_values("functional_ingredients", "vitamin C, zinc, vitamin C") == [
        "vitamin C",
        "zinc",
    ]
    assert atomic_values(
        "regulated_function", "skin moisturizing (생리활성기능 2등급)"
    ) == ["skin moisturizing"]


def test_atomic_values_handles_pandas_missing_scalar():
    assert atomic_values("product_form", pd.NA) == []


def test_compact_prompt_bounds_evidence_and_requires_contract_shape():
    prompt = _build_compact_prompt(
        "health-functional-food:probiotics",
        [
            {
                "source_product_id": "p1",
                "source_type": "MFDS_PRODUCT",
                "evidence_text": "long" * 100,
            }
        ],
        "test",
    )
    assert "at most 1 facet and 1 value" in prompt
    assert "source_text" in prompt
    assert "long" not in prompt


def _frame():
    return pd.DataFrame(
        [
            {
                "source_product_id": "1",
                "name": "비타민",
                "product_type": "비타민 C",
                "product_form": "정제",
                "functional_ingredients": "비타민 C",
                "main_functionality": "항산화",
                "intake_method": "1일 1회",
            }
        ]
    )


def test_sampling_is_category_scoped_and_reproducible():
    frame = pd.concat(
        [_frame(), _frame().assign(source_product_id="2")], ignore_index=True
    )
    left = sample_products(frame, max_per_category=4)
    right = sample_products(frame, max_per_category=4)
    assert left.equals(right)
    assert set(left.columns) >= {"category_key", "source_product_id", "sampling_reason"}


def test_sampling_keeps_small_limits_non_empty():
    result = sample_products(_frame(), max_per_category=2)
    assert len(result) == 1


def test_sampling_handles_empty_or_partially_schematized_input():
    empty = sample_products(pd.DataFrame())
    partial = sample_products(
        pd.DataFrame([{"source_product_id": "1", "product_type": "비타민"}])
    )
    assert list(empty.columns) == [
        "category_key",
        "category_name",
        "source_product_id",
        "product_name",
        "source_category",
        "product_form",
        "functional_ingredients",
        "regulated_function",
        "intake_method",
        "sampling_reason",
    ]
    assert len(partial) == 1


def test_mock_output_parser_accepts_input_evidence():
    frame = _frame()
    output = MockModelAdapter().generate_facet_candidates(
        "health-functional-food:vitamin_mineral",
        [
            {
                "category_name": "비타민·미네랄",
                "source_product_id": "1",
                "product_form": "정제",
            }
        ],
        "v0",
    )
    parsed, failures = parse_model_output(output, frame)
    assert len(parsed) == 1
    assert not failures
    assert parsed.iloc[0]["status"] == "PROVISIONAL_MODEL_OUTPUT"


def test_hallucinated_evidence_is_rejected():
    payload = {
        "category_key": "C",
        "category_name": "C",
        "facets": [
            {
                "name": "f",
                "values": [{"value": "x", "aliases": []}],
                "evidence": [
                    {
                        "source_product_id": "999",
                        "source_field": "product_form",
                        "source_text": "정제",
                    }
                ],
            }
        ],
    }
    parsed, failures = parse_model_output(payload, _frame())
    assert parsed.empty
    assert failures[0]["failure_type"] == "HALLUCINATED_EVIDENCE"


def test_numeric_product_id_is_not_accepted_as_unknown_facet_id():
    payload = {
        "category_key": "C",
        "category_name": "C",
        "facets": [
            {
                "facet_id_candidate": "2019001407111",
                "name": "Invented ingredient facet",
                "values": [{"value": "x", "aliases": []}],
                "evidence": [
                    {
                        "source_product_id": "1",
                        "source_field": "product_form",
                        "source_text": "정제",
                    }
                ],
            }
        ],
    }
    parsed, failures = parse_model_output(payload, _frame())
    assert parsed.empty
    assert failures[0]["failure_type"] == "INVALID_FACET_ID"


def test_parser_normalizes_alternate_grounded_model_shape():
    frame = _frame().assign(evidence_text="정제 | 비타민 C")
    payload = {
        "category_key": "C",
        "facets": [
            {
                "facet_key": "product_form",
                "values": [
                    {
                        "value": "정제",
                        "evidence": [
                            {
                                "source_product_id": "1",
                                "evidence_text": "정제 | 비타민 C",
                            }
                        ],
                    }
                ],
            }
        ],
    }
    parsed, failures = parse_model_output(payload, frame)
    assert len(parsed) == 1
    assert parsed.iloc[0]["name"] == "product_form"
    assert parsed.iloc[0]["source_field"] == "evidence_text"
    assert not failures


def test_parser_keeps_ungrounded_flat_model_shape_in_review():
    payload = {
        "category_key": "C",
        "facets": [{"facet_name": "Ingredient", "value": "비타민 C"}],
    }
    parsed, failures = parse_model_output(payload, _frame())
    assert parsed.empty
    assert failures[0]["failure_type"] == "EVIDENCE_MISSING"


def test_parser_rejects_malformed_nested_values_without_crashing():
    payload = {
        "category_key": "C",
        "facets": [
            "not-a-facet",
            {
                "name": "product_form",
                "values": [None, {"value": "정제", "aliases": "tablet"}],
                "evidence": [
                    {
                        "source_product_id": "1",
                        "source_field": "product_form",
                        "source_text": "정제",
                    }
                ],
            },
        ],
    }
    parsed, failures = parse_model_output(payload, _frame())
    assert len(parsed) == 1
    assert parsed.iloc[0]["alias"] == "tablet"
    assert {failure["failure_type"] for failure in failures} == {
        "INVALID_FACET",
        "INVALID_VALUE",
    }


def test_parser_rejects_unknown_field_and_empty_evidence_text():
    payload = {
        "category_key": "C",
        "facets": [
            {
                "name": "product_form",
                "value": "정제",
                "evidence": [
                    {
                        "source_product_id": "1",
                        "source_field": "made_up_field",
                        "source_text": "",
                    },
                    {
                        "source_product_id": "1",
                        "source_field": "made_up_field",
                        "source_text": "정제",
                    },
                ],
            }
        ],
    }
    parsed, failures = parse_model_output(payload, _frame())
    assert len(parsed) == 1
    assert parsed.iloc[0]["source_field"] == "product_form"
    assert {failure["failure_type"] for failure in failures} == {
        "EVIDENCE_TEXT_MISSING"
    }


def test_parser_rejects_empty_values_but_keeps_valid_value():
    payload = {
        "category_key": "C",
        "facets": [
            {
                "name": "product_form",
                "values": [{"value": ""}, {"value": "정제"}],
                "evidence": [
                    {
                        "source_product_id": "1",
                        "source_field": "product_form",
                        "source_text": "정제",
                    }
                ],
            }
        ],
    }
    parsed, failures = parse_model_output(payload, _frame())
    assert len(parsed) == 1
    assert parsed.iloc[0]["value"] == "정제"
    assert failures[0]["failure_type"] == "EMPTY_VALUE"


def test_parser_reports_missing_input_identity_column():
    payload = {"category_key": "C", "facets": []}
    parsed, failures = parse_model_output(payload, pd.DataFrame([{"name": "상품"}]))
    assert parsed.empty
    assert failures[0]["failure_type"] == "SCHEMA_VALIDATION_FAILED"


def test_ollama_adapter_keeps_provider_swappable():
    adapter = OllamaAdapter("actual-model-name")
    assert adapter.provider == "ollama"
    assert adapter.model == "actual-model-name"
    assert adapter.endpoint.endswith("11434")


def test_model_factory_supports_non_ollama_runtimes():
    assert isinstance(
        create_model_adapter(
            "openai_compatible", "model", endpoint="http://localhost:8000/v1"
        ),
        OpenAICompatibleAdapter,
    )
    assert isinstance(
        create_model_adapter("transformers", "local-model"), TransformersAdapter
    )


def test_postprocess_normalizes_form_names_and_values():
    review = pd.DataFrame(
        [
            {
                "category_key": "C",
                "facet_id_candidate": "form",
                "name": "Product Form",
                "definition": "",
                "value": " powder ",
                "alias": "",
                "source_product_id": "1",
                "source_field": "product_form",
            },
            {
                "category_key": "C",
                "facet_id_candidate": "form",
                "name": "제품 형태",
                "definition": "",
                "value": "분말",
                "alias": "",
                "source_product_id": "2",
                "source_field": "product_form",
            },
        ]
    )
    result = normalize_candidates(review)
    assert len(result) == 1 and result.iloc[0]["value"] == "분말"


def test_postprocess_mapping_is_evidence_backed():
    products = pd.DataFrame(
        [
            {
                "source_product_id": "1",
                "name": "상품",
                "product_type": "프로바이오틱스",
                "product_form": "분말",
                "functional_ingredients": "",
                "main_functionality": "",
            }
        ]
    )
    candidates = pd.DataFrame(
        [
            {
                "category_key": "health-functional-food:probiotics",
                "facet_id": "product_form",
                "facet_name": "제품 형태",
                "value": "분말",
            }
        ]
    )
    assert map_products(products, candidates).iloc[0]["mapping_status"] == "MAPPED"


def test_postprocess_mapping_handles_empty_or_missing_columns():
    candidates = pd.DataFrame(
        [
            {
                "category_key": "C",
                "facet_id": "product_form",
                "facet_name": "제품 형태",
                "value": "분말",
            }
        ]
    )
    assert map_products(pd.DataFrame(), candidates).empty
    assert map_products(
        pd.DataFrame([{"source_product_id": "1", "name": "상품"}]), candidates
    ).empty
    assert map_products(
        pd.DataFrame(
            [{"source_product_id": "1", "name": "상품", "product_type": "비타민"}]
        ),
        pd.DataFrame([{"category_key": "C"}]),
    ).empty


def test_metadata_parentheses_do_not_split_semantic_values():
    assert atomic_values("functional_ingredients", "selenium(또는 셀렌), biotin") == [
        "selenium",
        "biotin",
    ]
    assert atomic_values(
        "regulated_function", "피부상태 개선에 도움을 줄 수 있음 (생리활성기능 2등급)"
    ) == ["피부상태 개선에 도움을 줄 수 있음"]


def test_regulated_functions_are_grouped_by_meaning():
    assert atomic_values("regulated_function", "장건강에 도움을 줄 수 있음") == [
        "장 건강"
    ]
    assert atomic_values(
        "regulated_function", "자외선에 의한 피부손상으로부터 피부 건강 유지에 도움"
    ) == ["자외선에 의한 피부 손상으로부터 피부 건강 유지"]


def test_one_product_can_have_multiple_ingredient_values():
    assert atomic_values("functional_ingredients", "비타민 C, 아연") == [
        "비타민 C",
        "아연",
    ]
