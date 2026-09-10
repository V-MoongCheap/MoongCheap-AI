import pandas as pd

from moongcheap_ai.data_foundation.model1_review import apply_human_decisions, build_review_queue, canonical_semantic_value, collapse_same_model_candidates, display_category_name, normalize_review_candidates, normalize_value, review_candidates


def _inputs() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "category_key": "health-functional-food:skin_collagen",
            "source_product_id": "p1",
            "product_form": "분말",
            "functional_ingredients": "콜라겐",
            "regulated_function": "피부 건강에 도움을 줄 수 있음",
            "intake_method": "1일 1회 1포",
            "price_text": "UNDER_10000",
            "evidence_text": "분말 콜라겐",
        },
        {
            "category_key": "health-functional-food:skin_collagen",
            "source_product_id": "p2",
            "product_form": "분말",
            "functional_ingredients": "콜라겐",
            "regulated_function": "피부 건강에 도움을 줄 수 있음",
            "intake_method": "1일 1회 1포",
            "price_text": "UNDER_10000",
            "evidence_text": "분말 콜라겐",
        },
    ])


def _candidate(name: str, value: str, source_text: str = "") -> pd.DataFrame:
    return pd.DataFrame([{
        "category_key": "health-functional-food:skin_collagen",
        "name": name,
        "value": value,
        "source_text": source_text,
        "source_product_id": "p1",
    }])


def test_product_form_with_repeated_input_evidence_passes():
    result = review_candidates(_candidate("Product Form", "분말", "분말"), _inputs())
    row = result.iloc[0]
    assert row.review_status == "ACCEPT_CANDIDATE"
    assert row.canonical_facet_id == "product_form"
    assert row.normalized_value == "powder"
    assert row.input_match_count == 2


def test_regulated_function_is_review_only():
    result = review_candidates(_candidate("Regulated Function", "피부 건강에 도움을 줄 수 있음", "피부 건강에 도움을 줄 수 있음"), _inputs())
    assert result.iloc[0].review_status == "REVIEW_REQUIRED"
    assert "regulated_function_is_evidence_only" in result.iloc[0].review_reasons


def test_out_of_scope_search_term_is_rejected():
    result = review_candidates(_candidate("Consumer Preference", "피부 알레르기 약", "피부 알레르기 약"), _inputs())
    assert result.iloc[0].review_status == "REJECT"
    assert "out_of_scope_product_or_treatment_term" in result.iloc[0].review_reasons


def test_price_is_demand_scope_and_not_product_facet():
    result = review_candidates(_candidate("Price Band", "UNDER_10000", "UNDER_10000"), _inputs())
    assert result.iloc[0].review_scope == "DEMAND"
    assert result.iloc[0].review_status == "REVIEW_REQUIRED"


def test_ingredient_recognition_number_is_separated():
    reviewed = review_candidates(
        _candidate("Functional Ingredients", "AP \ucf5c\ub77c\uac94 \ud6a8\uc18c\ubd84\ud574 \ud3a9\ud0c0\uc774\ub4dc(\uae30\ub2a5\uc131\uc6d0\ub8cc\uc778\uc815\uc81c2010-25\ud638)", "AP \ucf5c\ub77c\uac94"),
        _inputs(),
    )
    normalized = normalize_review_candidates(reviewed)
    assert normalized.iloc[0].recognition_number == "2010-25"
    assert "2010-25" not in normalized.iloc[0].normalized_atom


def test_ingredient_recognition_parenthesis_is_not_a_facet_value():
    value = "Collactive \ucf5c\ub77c\uac94\ud3a9\ud0c0\uc774\ub4dc(\uc81c2012-24\ud638)"
    reviewed = review_candidates(_candidate("Functional Ingredients", value, "Collactive"), _inputs())
    normalized = normalize_review_candidates(reviewed)
    assert "2012-24" not in normalized.iloc[0].normalized_atom
    assert normalized.iloc[0].recognition_number == "2012-24"


def test_intake_is_split_into_structured_fields():
    reviewed = review_candidates(_candidate("Intake Method", "1일 2회", "1일 2회"), _inputs())
    normalized = normalize_review_candidates(reviewed)
    assert normalized.iloc[0].intake_days == "1"
    assert normalized.iloc[0].intake_frequency == "2"


def test_same_model_value_collapses_and_keeps_product_ids():
    reviewed = review_candidates(_candidate("Product Form", "분말", "분말"), _inputs())
    reviewed["model"] = "qwen3:4b"
    reviewed = pd.concat([reviewed, reviewed.copy()], ignore_index=True)
    normalized = collapse_same_model_candidates(normalize_review_candidates(reviewed))
    assert len(normalized) == 1
    assert normalized.iloc[0].candidate_row_count == 2
    assert normalized.iloc[0].evidence_product_count == 1
    assert normalized.iloc[0].source_product_ids == "p1"


def test_category_display_name_comes_from_stable_key():
    expected = "".join(chr(int(value, 16)) for value in ("d53c", "bd80", "00b7", "cf5c", "b77c", "ac94"))
    assert display_category_name("health-functional-food:skin_collagen") == expected


def test_pill_form_is_normalized_without_auto_approval():
    reviewed = review_candidates(_candidate("Product Form", "환", "환"), _inputs())
    normalized = normalize_review_candidates(reviewed)
    assert normalized.iloc[0].normalized_atom == "pill"
    assert normalized.iloc[0].review_status == "REJECT"


def test_language_label_is_removed_from_regulated_function_text():
    korean_label = chr(0xad6d) + chr(0xbb38)
    assert normalize_value("regulated_function", f"skin moisture ({korean_label})") == "skin moisture"


def test_equivalent_regulated_functions_share_a_canonical_group():
    skin = chr(0xd53c) + chr(0xbd80) + " " + chr(0xbcf4) + chr(0xc2b5)
    assert canonical_semantic_value("regulated_function", skin + "에 도움") == skin
def test_review_queue_has_one_row_per_candidate_and_accepts_human_decision():
    reviewed = review_candidates(_candidate("Regulated Function", "skin moisture", "skin moisture"), _inputs())
    reviewed["model"] = "qwen3:4b"
    normalized = collapse_same_model_candidates(normalize_review_candidates(reviewed))
    queue = build_review_queue(normalized)
    assert len(queue) == 1
    queue.loc[0, "human_decision"] = "ACCEPT"
    resolved, accepted = apply_human_decisions(queue)
    assert resolved.iloc[0].resolution_status == "ACCEPTED_BY_HUMAN"
    assert len(accepted) == 1
