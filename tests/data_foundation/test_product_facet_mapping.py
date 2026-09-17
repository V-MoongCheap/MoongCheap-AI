import json

import pandas as pd

from moongcheap_ai.data_foundation.product_facet_mapping import build_category_evidence, build_product_mapping, build_reference_evidence


def taxonomy():
    return {
        "health-functional-food:probiotics": {
            "category_id": "health-functional-food:probiotics",
            "category_name": "유산균·프로바이오틱스",
            "facets": [
                {"name": "product_form", "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "분말", "aliases": ["가루"]}]},
                {"name": "functional_ingredients", "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "프로바이오틱스"}]},
                {"name": "daily_frequency", "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "1일 1회"}]},
            ],
        }
    }


def test_product_mapping_preserves_unknown_and_observed_evidence():
    catalog = pd.DataFrame([{
        "catalog_id": "c1", "source_product_id": "p1", "category_id": "health-functional-food:probiotics",
        "name": "유산균 분말", "title": "", "category": "", "keywords_json": "프로바이오틱스",
        "source_document_id": "p1", "source": "DOMEGGOOK", "license_status": "LOCAL_ONLY",
    }])
    result = build_product_mapping(catalog, taxonomy())
    form = result[result.facet_name == "product_form"].iloc[0]
    assert form.mapping_status == "MAPPED"
    assert form.value == "분말"
    assert json.loads(form.source_fields) == ["name"]
    assert set(result[result.facet_name == "daily_frequency"].mapping_status) == {"UNKNOWN"}


def test_category_text_does_not_create_a_product_form_fact():
    catalog = pd.DataFrame([{
        "catalog_id": "c2", "source_product_id": "p2", "category_id": "health-functional-food:probiotics",
        "name": "유산균", "title": "", "category": "기타비타민", "keywords_json": "",
        "source_document_id": "p2", "source": "DOMEGGOOK", "license_status": "LOCAL_ONLY",
    }])
    result = build_product_mapping(catalog, taxonomy())
    form = result[result.facet_name == "product_form"].iloc[0]
    assert form.mapping_status == "UNKNOWN"


def test_ambiguous_mapping_keeps_per_value_source_fields_for_review():
    local_taxonomy = taxonomy()
    local_taxonomy["health-functional-food:probiotics"]["facets"][0]["values"].append(
        {"code": 2, "value": "캡슐"}
    )
    catalog = pd.DataFrame([{
        "catalog_id": "c3", "source_product_id": "p3", "category_id": "health-functional-food:probiotics",
        "name": "유산균 분말", "title": "", "package_spec": "캡슐 30정", "keywords_json": "",
        "source_document_id": "p3", "source": "DOMEGGOOK", "license_status": "LOCAL_ONLY",
    }])

    result = build_product_mapping(catalog, local_taxonomy)

    form = result[result.facet_name == "product_form"].iloc[0]
    evidence = json.loads(form.candidate_evidence)
    assert form.mapping_status == "AMBIGUOUS"
    assert evidence == [
        {"value_code": 1, "value": "분말", "matched_terms": ["분말"], "source_fields": ["name"]},
        {"value_code": 2, "value": "캡슐", "matched_terms": ["캡슐"], "source_fields": ["package_spec"]},
    ]


def test_mfds_evidence_uses_category_crosswalk_and_document_ratio():
    mfds = pd.DataFrame([
        {"source_product_id": "m1", "raw_category_name": "프로바이오틱스", "product_form": "분말", "product_type": "", "functional_ingredients": "프로바이오틱스"},
        {"source_product_id": "m2", "raw_category_name": "프로바이오틱스", "product_form": "분말", "product_type": "", "functional_ingredients": "프로바이오틱스"},
    ])
    result = build_category_evidence(mfds, taxonomy(), min_documents=2)
    row = result[(result.source_field == "product_form") & (result.normalized_value == "분말")].iloc[0]
    assert row.document_count == 2
    assert row.document_ratio == 1.0
    assert row.mapping_status == "CATEGORY_CROSSWALK"
    assert row.evidence_status == "CANDIDATE"


def test_i2710_reference_is_not_assigned_to_a_catalog_product():
    result = build_reference_evidence(pd.DataFrame([{
        "category_reference_name": "유산균", "ingredient_name": "프로바이오틱스",
        "main_functionality": "배변활동", "daily_intake_min": "1", "daily_intake_max": "2",
        "unit": "g", "caution": "주의",
    }]), taxonomy())
    assert result.loc[0, "source"] == "MFDS_I2710"
    assert result.loc[0, "evidence_scope"] == "OFFICIAL_REFERENCE_NOT_CATALOG_FACT"
    assert result.loc[0, "category_id"] == "health-functional-food:probiotics"
