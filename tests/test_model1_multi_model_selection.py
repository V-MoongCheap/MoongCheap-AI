import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "model1" / "run_model1_multi_model_selection.py"
SPEC = importlib.util.spec_from_file_location("model1_multi_model_selection", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _candidate(model: str, value: str, source_id: str) -> dict:
    return {
        "category_key": "health-functional-food:probiotics",
        "category_name": "유산균·프로바이오틱스",
        "facet_id_candidate": "product_form",
        "name": "Product Form",
        "definition": "제형",
        "value": value,
        "alias": "",
        "source_product_id": source_id,
        "source_field": "product_form",
        "source_text": value,
        "status": "PROVISIONAL_MODEL_OUTPUT",
        "model": model,
    }


def test_selection_requires_two_models_for_auto_candidate():
    candidates = pd.DataFrame(
        [
            _candidate("qwen3:4b", "캡슐", "p1"),
            _candidate("gemma3:4b", "캡슐", "p2"),
            _candidate("qwen3:4b", "분말", "p3"),
        ]
    )

    selected = MODULE.select_candidates(candidates)

    consensus = selected[selected["value"] == "캡슐"].iloc[0]
    singleton = selected[selected["value"] == "분말"].iloc[0]
    assert consensus["model_support"] == 2
    assert consensus["selection_status"] == "SELECTED_CANDIDATE"
    assert singleton["model_support"] == 1
    assert singleton["selection_status"] == "MODEL_SINGLETON_REVIEW"


def test_query_evidence_is_marked_as_supplemental_source():
    sampled = pd.DataFrame(
        [{"category_key": "health-functional-food:probiotics", "category_name": "유산균"}]
    )
    translated = pd.DataFrame(
        [{"source_record_id": "q1", "query_translated": "유산균 캡슐"}]
    )

    result = MODULE.add_query_evidence(sampled, translated, limit=1)

    assert result.iloc[-1]["source_product_id"] == "kuaisearch:q1"
    assert result.iloc[-1]["sampling_reason"] == "translated consumer-query evidence"
