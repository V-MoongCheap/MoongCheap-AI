import pandas as pd

from moongcheap_ai.model1 import MockModelAdapter, OllamaAdapter, parse_model_output, sample_products
from moongcheap_ai.model1_postprocess import atomic_values, map_products, normalize_candidates

def test_composite_values_are_split_before_deduplication():
    assert atomic_values("functional_ingredients", "vitamin C, zinc, vitamin C") == ["vitamin C", "zinc"]
    assert atomic_values("regulated_function", "skin moisturizing (생리활성기능 2등급)") == ["skin moisturizing"]


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


def test_ollama_adapter_keeps_provider_swappable():
    adapter = OllamaAdapter("actual-model-name")
    assert adapter.provider == "ollama"
    assert adapter.model == "actual-model-name"
    assert adapter.endpoint.endswith("11434")

def test_postprocess_normalizes_form_names_and_values():
    review = pd.DataFrame([{"category_key": "C", "facet_id_candidate": "form", "name": "Product Form", "definition": "", "value": " powder ", "alias": "", "source_product_id": "1", "source_field": "product_form"}, {"category_key": "C", "facet_id_candidate": "form", "name": "제품 형태", "definition": "", "value": "분말", "alias": "", "source_product_id": "2", "source_field": "product_form"}])
    result = normalize_candidates(review)
    assert len(result) == 1 and result.iloc[0]["value"] == "분말"

def test_postprocess_mapping_is_evidence_backed():
    products = pd.DataFrame([{"source_product_id": "1", "name": "상품", "product_type": "프로바이오틱스", "product_form": "분말", "functional_ingredients": "", "main_functionality": ""}])
    candidates = pd.DataFrame([{"category_key": "health-functional-food:probiotics", "facet_id": "product_form", "facet_name": "제품 형태", "value": "분말"}])
    assert map_products(products, candidates).iloc[0]["mapping_status"] == "MAPPED"
def test_metadata_parentheses_do_not_split_semantic_values():
    assert atomic_values("functional_ingredients", "selenium(또는 셀렌), biotin") == ["selenium", "biotin"]
    assert atomic_values("regulated_function", "피부상태 개선에 도움을 줄 수 있음 (생리활성기능 2등급)") == ["피부상태 개선에 도움을 줄 수 있음"]
