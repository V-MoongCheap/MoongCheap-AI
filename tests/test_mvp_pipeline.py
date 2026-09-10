from __future__ import annotations

import json

import pandas as pd

from moongcheap_ai.mvp_pipeline import run_local_e2e


def _write_fixture(tmp_path):
    taxonomy = {
        "version": "v2.2",
        "categories": [{"category_id": "c1", "facets": [
            {"name": "product_form", "order": 1, "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "tablet", "aliases": ["정제"]}]},
            {"name": "daily_frequency", "order": 2, "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "1일 1회"}]},
        ]}],
    }
    taxonomy_path = tmp_path / "taxonomy.json"
    taxonomy_path.write_text(json.dumps(taxonomy, ensure_ascii=False), encoding="utf-8")
    registry_path = tmp_path / "aliases.json"
    registry_path.write_text(json.dumps({"version": "aliases-v2", "aliases": [{"facet_name": "product_form", "canonical_value": "tablet", "surfaces": ["알약"], "category_local_values": {"c1": {"code": 1, "value": "tablet"}}}]}, ensure_ascii=False), encoding="utf-8")
    demand_path = tmp_path / "demands.csv"
    pd.DataFrame([
        {"demand_id": "1", "catalog_id": "p1", "category_id": "c1", "extra_requirement": "알약", "quantity": "2", "is_substitutable": "false", "processed_at": ""},
        {"demand_id": "2", "catalog_id": "p1", "category_id": "c1", "extra_requirement": "", "quantity": "1", "is_substitutable": "true", "processed_at": "2026-01-01T00:00:00+00:00"},
    ]).to_csv(demand_path, index=False)
    return taxonomy_path, registry_path, demand_path


def test_local_e2e_uses_v22_alias_and_skips_processed_rows(tmp_path):
    taxonomy, registry, demands = _write_fixture(tmp_path)
    result = run_local_e2e(demands, tmp_path / "out", taxonomy_path=taxonomy, alias_registry_path=registry)
    assert result["taxonomy_version"] == "v2.2"
    assert result["labeling"]["skipped"] == 1
    assert result["labeling"]["alias_hits"] == 1
    assert result["clustering"]["processed"] == 1
    labeled = pd.read_csv(tmp_path / "out/demand_labeled_v2_2.csv", dtype=str)
    assert labeled.loc[0, "label"] == "1-0"

