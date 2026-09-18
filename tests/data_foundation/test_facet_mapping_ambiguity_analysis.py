from __future__ import annotations

import json

import pandas as pd

from scripts.data.analyze_facet_mapping_ambiguity import analyze


def test_analyze_groups_repeated_ambiguity_and_flags_textual_overlap() -> None:
    evidence = json.dumps([
        {"value_code": 1, "value": "홍삼", "matched_terms": ["홍삼"], "source_fields": ["name"]},
        {"value_code": 2, "value": "홍삼제품", "matched_terms": ["홍삼제품"], "source_fields": ["name"]},
    ], ensure_ascii=False)
    mapping = pd.DataFrame([
        {"catalog_id": "c1", "category_id": "red_ginseng", "facet_name": "functional_ingredients", "mapping_status": "AMBIGUOUS", "candidate_evidence": evidence},
        {"catalog_id": "c2", "category_id": "red_ginseng", "facet_name": "functional_ingredients", "mapping_status": "AMBIGUOUS", "candidate_evidence": evidence},
        {"catalog_id": "c3", "category_id": "red_ginseng", "facet_name": "product_form", "mapping_status": "MAPPED", "candidate_evidence": "[]"},
    ])

    patterns, overlap, summary = analyze(mapping)

    assert summary == {
        "ambiguous_mapping_rows": 2,
        "ambiguity_patterns": 1,
        "taxonomy_overlap_patterns": 1,
        "taxonomy_overlap_mapping_rows": 2,
    }
    assert patterns.loc[0, "catalog_count"] == 2
    assert json.loads(patterns.loc[0, "textual_overlap_pairs"]) == ["홍삼 -> 홍삼제품"]
    assert len(overlap) == 1


def test_analyze_flags_normalized_duplicate_values_as_taxonomy_review() -> None:
    evidence = json.dumps([
        {"value_code": 1, "value": "비타민 D", "matched_terms": ["비타민 D"], "source_fields": ["name"]},
        {"value_code": 2, "value": "비타민D", "matched_terms": ["비타민D"], "source_fields": ["name"]},
    ], ensure_ascii=False)
    mapping = pd.DataFrame([{
        "catalog_id": "c1", "category_id": "vitamin", "facet_name": "functional_ingredients",
        "mapping_status": "AMBIGUOUS", "candidate_evidence": evidence,
    }])

    patterns, overlap, summary = analyze(mapping)

    assert summary["taxonomy_overlap_mapping_rows"] == 1
    assert json.loads(patterns.loc[0, "textual_overlap_pairs"]) == [
        "비타민 D = 비타민D (normalized duplicate)"
    ]
    assert len(overlap) == 1
