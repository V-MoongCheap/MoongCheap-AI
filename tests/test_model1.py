import pandas as pd

from moongcheap_ai.model1 import MockModelAdapter, parse_model_output, sample_products


def _frame():
    return pd.DataFrame([{"source_product_id": "1", "name": "비타민", "product_type": "비타민 C", "product_form": "정제", "functional_ingredients": "비타민 C", "main_functionality": "항산화", "intake_method": "1일 1회"}])


def test_sampling_is_category_scoped_and_reproducible():
    frame = pd.concat([_frame(), _frame().assign(source_product_id="2")], ignore_index=True)
    left = sample_products(frame, max_per_category=4)
    right = sample_products(frame, max_per_category=4)
    assert left.equals(right)
    assert set(left.columns) >= {"category_key", "source_product_id", "sampling_reason"}


def test_mock_output_parser_accepts_input_evidence():
    frame = _frame()
    output = MockModelAdapter().generate_facet_candidates("health-functional-food:vitamin_mineral", [{"category_name": "비타민·미네랄", "source_product_id": "1", "product_form": "정제"}], "v0")
    parsed, failures = parse_model_output(output, frame)
    assert len(parsed) == 1
    assert not failures
    assert parsed.iloc[0]["status"] == "PROVISIONAL_MODEL_OUTPUT"


def test_hallucinated_evidence_is_rejected():
    payload = {"category_key": "C", "category_name": "C", "facets": [{"name": "f", "values": [{"value": "x", "aliases": []}], "evidence": [{"source_product_id": "999", "source_field": "product_form", "source_text": "정제"}]}]}
    parsed, failures = parse_model_output(payload, _frame())
    assert parsed.empty
    assert failures[0]["failure_type"] == "HALLUCINATED_EVIDENCE"
