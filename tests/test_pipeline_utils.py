import json
from pathlib import Path

import pandas as pd

from moongcheap_ai.facet import repeated_terms, taxonomy_v0
from moongcheap_ai.catalog import normalize_barcode, normalize_name, resolve_identity, source_category_path_from_file
from moongcheap_ai.category import build_aihub_category_hierarchy
from moongcheap_ai.labeling import label_demand
from moongcheap_ai.preprocess import category_path, clean_title


def test_clean_title_removes_html_and_normalizes():
    assert clean_title(" <b>비타민&nbsp;C</b>  1000㎎ ") == "비타민 C 1000mg"


def test_product_name_normalization_keeps_quantity_and_model():
    assert normalize_name("상품 X-500 500ml x 24개") == "상품 X-500 500ml x 24개"


def test_barcode_keeps_leading_zero_and_normalizes_formatting():
    assert normalize_barcode(" 0123-4567 ") == "01234567"


def test_aihub_source_path_recovers_nested_category():
    path = r"F:\data\logistics_product\01_가공식품\15_건강식품\01150101_x\item.json"
    assert source_category_path_from_file(path) == "01_가공식품 > 15_건강식품"


def test_aihub_category_hierarchy_preserves_parent_path(tmp_path):
    frame = pd.DataFrame({"source_category_path": ["01_가공식품 > 15_건강식품"], "kan_code": ["01150101"]})
    build_aihub_category_hierarchy(frame, tmp_path / "category.csv")
    result = pd.read_csv(tmp_path / "category.csv")
    assert list(result["depth"]) == [1, 2]
    assert result.iloc[1]["parent_category_key"] == "AIHUB:01_가공식품"


def test_same_name_different_barcode_is_not_merged():
    frame = pd.DataFrame([
        {"barcode": "01234567", "barcode_valid": True, "product_name_normalized": "같은 상품", "kan_code": "A"},
        {"barcode": "01234568", "barcode_valid": True, "product_name_normalized": "같은 상품", "kan_code": "A"},
    ])
    resolved, _ = resolve_identity(frame)
    assert resolved["catalog_seed_id"].nunique() == 2


def test_category_path_ignores_empty_levels():
    assert category_path({"category1": "식품", "category2": "", "category3": "건강"}) == "식품 > 건강"


def test_repeated_terms_counts_documents_not_tokens():
    frame = pd.DataFrame({"name": ["분말 비타민", "분말 유산균", "분말 홍삼"], "main_functionality": ["", "", ""]})
    result = repeated_terms(frame, ["name"], min_documents=2, min_ratio=0)
    assert int(result.loc[result.term == "분말", "document_count"].iloc[0]) == 3


def test_taxonomy_is_deterministic_and_all_is_zero():
    terms = pd.DataFrame([{"term": "분말", "document_count": 3}, {"term": "캡슐", "document_count": 2}])
    first = taxonomy_v0("SEED", "x", terms)
    second = taxonomy_v0("SEED", "x", terms)
    assert first == second
    assert first["facets"][0]["values"][0]["code"] == 0


def test_demand_labeling_defaults_to_all_and_does_not_write_db():
    taxonomy = {"facets": [{"name": "form", "values": [{"code": 0, "value": "ALL", "aliases": []}, {"code": 1, "value": "powder", "aliases": ["분말"]}]}]}
    assert label_demand(1, 2, "분말", taxonomy)["label"] == "1"
    assert label_demand(1, 2, "", taxonomy)["label"] == "0"
