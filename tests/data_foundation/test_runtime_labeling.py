import json

import pandas as pd

from moongcheap_ai.data_foundation.backend_contract import build_label_result_payload, validate_backend_response
from moongcheap_ai.data_foundation.runtime_job import run_batch


def test_label_runtime_builds_backend_payload(tmp_path) -> None:
    taxonomy = {
        "categories": [{"category_id": "c1", "facets": [{"name": "form", "order": 1, "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "분말", "aliases": ["가루"]}]}]}]
    }
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(taxonomy, ensure_ascii=False), encoding="utf-8")
    demands = pd.DataFrame([{"demand_id": "1", "catalog_id": "10", "category_id": "c1", "extra_requirement": "가루", "quantity": "1", "is_substitutable": "False"}])
    labeled, payload = run_batch(demands, path, processed_at="2026-01-01T00:00:00+00:00")
    assert labeled.loc[0, "label"] == "1"
    assert payload["results"][0]["demandId"] == 1


def test_backend_response_requires_accepted_status() -> None:
    validate_backend_response({"status": "ACCEPTED", "acceptedCount": 1}, 1)


def test_runtime_does_not_label_or_submit_unknown_category(tmp_path) -> None:
    taxonomy = {
        "categories": [{"category_id": "c1", "facets": [{"name": "form", "order": 1, "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "분말"}]}]}]
    }
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(taxonomy, ensure_ascii=False), encoding="utf-8")
    demands = pd.DataFrame([{
        "demand_id": "1",
        "catalog_id": "10",
        "category_id": "unknown",
        "extra_requirement": "분말",
    }])

    labeled, payload = run_batch(demands, path, processed_at="2026-01-01T00:00:00+00:00")

    assert labeled.loc[0, "label_status"] == "REVIEW"
    assert labeled.loc[0, "label"] == ""
    assert payload["results"] == []
