import json

import pandas as pd

from moongcheap_ai.data_foundation.backend_contract import validate_backend_response
from moongcheap_ai.data_foundation.labeling import taxonomy_from_category_facet_rows
from moongcheap_ai.data_foundation.runtime_job import _first_env, run_batch


def test_runtime_accepts_cloud_develop_model2_environment_aliases() -> None:
    source = {
        "A_MODEL2_FALLBACK_ENABLED": "true",
        "A_MODEL2_FALLBACK_MODEL": "qwen2.5:3b",
        "A_MODEL2_OLLAMA_BASE_URL": "http://127.0.0.1:11434",
    }

    assert _first_env(source, "A_LLM_ENABLED", "A_MODEL2_FALLBACK_ENABLED") == "true"
    assert _first_env(source, "A_LLM_MODEL", "A_MODEL2_FALLBACK_MODEL") == "qwen2.5:3b"
    assert _first_env(source, "A_LLM_ENDPOINT", "A_MODEL2_OLLAMA_BASE_URL") == "http://127.0.0.1:11434"


def test_label_runtime_builds_backend_payload(tmp_path) -> None:
    taxonomy = {
        "categories": [
            {
                "category_id": "c1",
                "facets": [
                    {
                        "name": "form",
                        "order": 1,
                        "values": [
                            {"code": 0, "value": "ALL"},
                            {"code": 1, "value": "분말", "aliases": ["가루"]},
                        ],
                    }
                ],
            }
        ]
    }
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(taxonomy, ensure_ascii=False), encoding="utf-8")
    demands = pd.DataFrame(
        [
            {
                "demand_id": "1",
                "catalog_id": "10",
                "category_id": "c1",
                "extra_requirement": "가루",
                "quantity": "1",
                "is_substitutable": "False",
            }
        ]
    )
    labeled, payload = run_batch(
        demands, path, processed_at="2026-01-01T00:00:00+00:00"
    )
    assert labeled.loc[0, "label"] == "1"
    assert payload["results"][0]["demandId"] == 1


def test_runtime_job_uses_part_a_policy_when_rules_are_provided(tmp_path) -> None:
    taxonomy = {
        "categories": [
            {
                "category_id": "c1",
                "facets": [
                    {
                        "name": "functional_ingredients",
                        "order": 1,
                        "values": [
                            {"code": 0, "value": "ALL"},
                            {"code": 1, "value": "오메가-3"},
                        ],
                    }
                ],
            }
        ]
    }
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(taxonomy, ensure_ascii=False), encoding="utf-8")
    demands = pd.DataFrame(
        [
            {
                "demand_id": "1",
                "catalog_id": "10",
                "category_id": "c1",
                "extra_requirement": "오메가3 함유 제품을 원해요.",
                "is_substitutable": "true",
            }
        ]
    )

    labeled, _ = run_batch(
        demands,
        path,
        rules_path=__import__("pathlib").Path("config/demand_constraint_rules.json"),
        processed_at="2026-01-01T00:00:00+00:00",
    )

    assert labeled.loc[0, "label"] == "1"
    assert labeled.loc[0, "label_status"] == "LABELED"


def test_backend_response_requires_accepted_status() -> None:
    validate_backend_response({"status": "ACCEPTED", "acceptedCount": 1}, 1)


def test_runtime_does_not_label_or_submit_unknown_category(tmp_path) -> None:
    taxonomy = {
        "categories": [
            {
                "category_id": "c1",
                "facets": [
                    {
                        "name": "form",
                        "order": 1,
                        "values": [
                            {"code": 0, "value": "ALL"},
                            {"code": 1, "value": "분말"},
                        ],
                    }
                ],
            }
        ]
    }
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(taxonomy, ensure_ascii=False), encoding="utf-8")
    demands = pd.DataFrame(
        [
            {
                "demand_id": "1",
                "catalog_id": "10",
                "category_id": "unknown",
                "extra_requirement": "분말",
            }
        ]
    )

    labeled, payload = run_batch(
        demands, path, processed_at="2026-01-01T00:00:00+00:00"
    )

    assert labeled.loc[0, "label_status"] == "REVIEW"
    assert labeled.loc[0, "label"] == ""
    assert payload["results"] == []


def test_runtime_job_uses_part_a_parser_for_explicit_requirement() -> None:
    root = __import__("pathlib").Path(".")
    demands = pd.DataFrame([{
        "demand_id": "1",
        "catalog_id": "catalog-1",
        "category_id": "health-functional-food:omega_fatty_acid",
        "extra_requirement": "오메가3 함유 제품을 원해요.",
        "is_substitutable": "true",
    }])

    labeled, payload = run_batch(
        demands,
        root / "config/facet_taxonomy_v2_2.json",
        alias_registry_path=root / "config/model1_aliases_reviewed_v2.json",
        compatibility_alias_registry_path=root / "config/demand_constraint_aliases.json",
        processed_at="2026-01-01T00:00:00+00:00",
    )

    assert labeled.loc[0, "label"] == "0-2-0"
    assert labeled.loc[0, "label_status"] == "LABELED"
    assert payload["results"][0]["label"] == "0-2-0"


def test_empty_runtime_batch_is_a_successful_noop(tmp_path) -> None:
    taxonomy = {
        "categories": [{"category_id": "c1", "facets": []}],
    }
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(taxonomy), encoding="utf-8")

    labeled, payload = run_batch(
        pd.DataFrame(
            columns=["demand_id", "catalog_id", "category_id", "extra_requirement"]
        ),
        path,
        processed_at="2026-01-01T00:00:00+00:00",
    )

    assert labeled.empty
    assert payload["results"] == []
    assert payload["processedAt"] == "2026-01-01T00:00:00+00:00"


def test_taxonomy_can_be_built_from_database_category_facet() -> None:
    frame = pd.DataFrame(
        [
            {
                "category_id": "health-functional-food:probiotics",
                "category_facet": json.dumps(
                    {
                        "category_id": "health-functional-food:probiotics",
                        "facets": [
                            {
                                "name": "product_form",
                                "order": 1,
                                "values": [
                                    {"code": 0, "value": "ALL"},
                                    {"code": 1, "value": "캡슐"},
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            }
        ]
    )

    payload = taxonomy_from_category_facet_rows(frame)

    assert payload["version"] == "backend-category-facet"
    assert (
        payload["categories"][0]["category_id"] == "health-functional-food:probiotics"
    )
