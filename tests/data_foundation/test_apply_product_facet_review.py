from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts.data.apply_product_facet_review import apply


def _write_taxonomy(path) -> None:
    path.write_text(json.dumps({"categories": [{"category_id": "c1", "facets": [{
        "name": "daily_frequency", "values": [
            {"code": 0, "value": "ALL"}, {"code": 1, "value": "1일 1회"}
        ],
    }]}]}), encoding="utf-8")


def test_apply_only_validated_edit_and_preserves_uncertain_rows(tmp_path) -> None:
    mapping = tmp_path / "mapping.csv"
    review = tmp_path / "review.csv"
    taxonomy = tmp_path / "taxonomy.json"
    output = tmp_path / "output.csv"
    report = tmp_path / "report.json"
    pd.DataFrame([
        {"catalog_id": "p1", "category_id": "c1", "facet_name": "daily_frequency", "value": "", "value_code": "", "mapping_status": "AMBIGUOUS", "mapping_reason": "MULTIPLE"},
        {"catalog_id": "p2", "category_id": "c1", "facet_name": "daily_frequency", "value": "", "value_code": "", "mapping_status": "UNKNOWN", "mapping_reason": "NO_VALUE"},
    ]).to_csv(mapping, index=False, encoding="utf-8-sig")
    pd.DataFrame([
        {"catalog_id": "p1", "category_id": "c1", "facet_name": "daily_frequency", "review_decision": "EDIT", "reviewed_value": "1일 1회", "reviewed_code": "1"},
        {"catalog_id": "p2", "category_id": "c1", "facet_name": "daily_frequency", "review_decision": "UNCERTAIN", "reviewed_value": "", "reviewed_code": ""},
    ]).to_csv(review, index=False, encoding="utf-8-sig")
    _write_taxonomy(taxonomy)

    summary = apply(mapping, review, taxonomy, output, report)

    result = pd.read_csv(output, dtype=str).fillna("").set_index("catalog_id")
    assert summary["applied_edit_rows"] == 1
    assert result.loc["p1", "mapping_status"] == "MAPPED"
    assert result.loc["p1", "value"] == "1일 1회"
    assert result.loc["p2", "mapping_status"] == "UNKNOWN"
    assert json.loads(report.read_text(encoding="utf-8"))["uncertain_rows_preserved"] == 1


def test_apply_rejects_edit_not_present_in_taxonomy(tmp_path) -> None:
    mapping = tmp_path / "mapping.csv"
    review = tmp_path / "review.csv"
    taxonomy = tmp_path / "taxonomy.json"
    pd.DataFrame([{
        "catalog_id": "p1", "category_id": "c1", "facet_name": "daily_frequency", "value": "", "value_code": "", "mapping_status": "UNKNOWN", "mapping_reason": "NO_VALUE",
    }]).to_csv(mapping, index=False, encoding="utf-8-sig")
    pd.DataFrame([{
        "catalog_id": "p1", "category_id": "c1", "facet_name": "daily_frequency", "review_decision": "EDIT", "reviewed_value": "2일 1회", "reviewed_code": "9",
    }]).to_csv(review, index=False, encoding="utf-8-sig")
    _write_taxonomy(taxonomy)

    with pytest.raises(ValueError, match="absent from taxonomy"):
        apply(mapping, review, taxonomy, tmp_path / "output.csv", tmp_path / "report.json")
