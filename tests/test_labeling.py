import pandas as pd
import pytest

from moongcheap_ai.data_foundation.labeling import TaxonomyLoader, TaxonomyValidationError, build_product_facet_map, label_demands
from moongcheap_ai.data_foundation.facet_codebook import build_clustering_input, load_codebook
from moongcheap_ai.data_foundation.demand_label_comparison import _apply_model_result, _normalise_model_facet_values


TAXONOMY = {"categories": [{"category_id": "C1", "facets": [{"name": "sugar_type", "order": 1, "values": [
    {"code": 0, "value": "ALL", "aliases": []}, {"code": 2, "value": "sugar_free", "aliases": ["무설탕"]}
]}]}]}


def test_loader_matches_alias_and_defaults_all() -> None:
    loader = TaxonomyLoader(TAXONOMY)
    matched, warnings = loader.resolve("C1", "무설탕으로")
    assert matched["sugar_type"]["code"] == 2
    assert not warnings
    all_values, _ = loader.resolve("C1", "")
    assert all_values["sugar_type"]["code"] == 0


def test_batch_keeps_required_output_columns() -> None:
    loader = TaxonomyLoader(TAXONOMY)
    result = label_demands(pd.DataFrame([{"demand_id": "D1", "catalog_id": "P1", "category_id": "C1", "extra_requirement": "무설탕으로", "desired_quantity": "2"}]), loader)
    assert result.iloc[0]["label"] == "2"
    assert result.iloc[0]["label_status"] == "LABELED"
    assert result.iloc[0]["quantity"] == "2"


def test_duplicate_value_codes_are_rejected() -> None:
    invalid = {"categories": [{"category_id": "C1", "facets": [{"name": "f", "values": [{"code": 0}, {"code": 0}]}]}]}
    with pytest.raises(TaxonomyValidationError):
        TaxonomyLoader(invalid)


def test_non_contiguous_facet_orders_are_rejected() -> None:
    invalid = {"categories": [{"category_id": "C1", "facets": [
        {"name": "a", "order": 1, "values": [{"code": 0}]},
        {"name": "b", "order": 3, "values": [{"code": 0}]},
    ]}]}
    with pytest.raises(TaxonomyValidationError):
        TaxonomyLoader(invalid)


def test_unmatched_requirement_is_recorded_as_unresolved() -> None:
    loader = TaxonomyLoader(TAXONOMY)
    result = label_demands(pd.DataFrame([{
        "demand_id": "D3", "catalog_id": "P3", "category_id": "C1",
        "extra_requirement": "카페인 함량이 낮은 제품",
    }]), loader)
    assert result.iloc[0]["label_status"] == "LABELED_WITH_REVIEW"
    assert "카페인 함량이 낮은 제품" in result.iloc[0]["unresolved_items"]


def test_no_requirement_phrase_defaults_to_all_without_review() -> None:
    loader = TaxonomyLoader(TAXONOMY)
    result = label_demands(pd.DataFrame([{
        "demand_id": "D4", "catalog_id": "P4", "category_id": "C1",
        "extra_requirement": "조건 없음",
    }]), loader)
    assert result.iloc[0]["label"] == "0"
    assert result.iloc[0]["label_status"] == "LABELED"


def test_batch_can_resolve_category_through_catalog_id() -> None:
    loader = TaxonomyLoader(TAXONOMY)
    result = label_demands(pd.DataFrame([{"demand_id": "D2", "catalog_id": "P2", "extra_requirement": "무설탕"}]), loader, {"P2": "C1"})
    assert result.iloc[0]["label"] == "2"


def test_product_facets_are_defaults_and_extra_requirement_wins() -> None:
    loader = TaxonomyLoader({"categories": [{"category_id": "C1", "facets": [
        {"name": "form", "order": 1, "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "정제"}, {"code": 2, "value": "분말"}]},
        {"name": "sugar", "order": 2, "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "무설탕"}, {"code": 2, "value": "당류"}]},
    ]}]})
    facets = build_product_facet_map(pd.DataFrame([{
        "source_product_id": "P1", "facet_name": "old_form_name", "source_field": "form", "value": "정제", "mapping_status": "MAPPED",
    }]))
    result = label_demands(pd.DataFrame([{
        "demand_id": "D1", "catalog_id": "catalog-seed-P1", "category_id": "C1", "extra_requirement": "분말",
        "is_substitutable": False,
    }]), loader, product_facet_map=facets)
    assert '"form":{"code":2' in result.loc[0, "facet_values"]
    assert '"sugar":{"code":0' in result.loc[0, "facet_values"]


def test_codebook_and_clustering_vector_keep_facet_identity(tmp_path) -> None:
    taxonomy_path = tmp_path / "taxonomy.json"
    taxonomy_path.write_text(__import__("json").dumps({"categories": [{"category_id": "C1", "facets": [
        {"name": "form", "order": 1, "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "정제"}]},
    ]}]}), encoding="utf-8")
    codebook = load_codebook(taxonomy_path)
    result = build_clustering_input(pd.DataFrame([{
        "demand_id": "D1", "catalog_id": "P1", "category_id": "C1", "label": "1",
        "facet_values": '{"form":{"code":1,"value":"정제"}}', "is_substitutable": "false",
        "desired_price_min": "0", "desired_price_max": "10000", "quantity": "1",
    }]), codebook)
    assert result.loc[0, "facet_label"] == "1"
    assert result.loc[0, "facet_1_form_code"] == 1
    assert result.loc[0, "taxonomy_version"] == "v2.1"


def test_llm_result_is_limited_to_taxonomy_codes() -> None:
    loader = TaxonomyLoader({"categories": [{"category_id": "C1", "facets": [
        {"name": "form", "order": 1, "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "정제"}]},
    ]}]})
    row = pd.Series({"category_id": "C1"})
    values, warnings = _apply_model_result(row, {"form": 99}, loader)
    assert values["form"]["code"] == 0
    assert warnings


def test_llm_numeric_facet_key_is_resolved_by_position() -> None:
    loader = TaxonomyLoader({"categories": [{"category_id": "C1", "facets": [
        {"name": "form", "order": 1, "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "정제"}]},
    ]}]})
    row = pd.Series({"category_id": "C1"})
    values, warnings = _apply_model_result(row, {" facet_0 ": 1}, loader)
    assert values["form"]["code"] == 1
    assert not warnings


def test_model_single_facet_object_is_converted_to_mapping() -> None:
    result = _normalise_model_facet_values({"facet_name": "form", "value": "정제"})
    assert result == {"form": {"value": "정제"}}


def test_llm_empty_or_category_prefixed_facet_is_safe() -> None:
    loader = TaxonomyLoader({"categories": [{"category_id": "C1", "facets": [
        {"name": "form", "order": 1, "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "정제"}]},
    ]}]})
    row = pd.Series({"category_id": "C1"})
    values, warnings = _apply_model_result(row, {"health:C1:form": 1, "form": None}, loader)
    assert values["form"]["code"] == 1
    assert not warnings


def test_hybrid_model_override_keeps_unmentioned_product_defaults() -> None:
    loader = TaxonomyLoader({"categories": [{"category_id": "C1", "facets": [
        {"name": "form", "order": 1, "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "정제"}, {"code": 2, "value": "분말"}]},
        {"name": "sugar", "order": 2, "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "무설탕"}]},
    ]}]})
    row = pd.Series({"category_id": "C1"})
    values, warnings = _apply_model_result(row, {"sugar": 1}, loader, [{"facet_name": "form", "value": "정제", "mapping_status": "MAPPED"}])
    assert values["form"]["code"] == 1
    assert values["sugar"]["code"] == 1
    assert not warnings
