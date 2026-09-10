import json

import pandas as pd

from moongcheap_ai.data_foundation.part_a_runtime import run_part_a_batch
from moongcheap_ai.demand_constraints.service import DemandConstraintParser


def _fixtures(tmp_path):
    taxonomy = {
        "version": "v2.2",
        "categories": [{"category_id": "c1", "facets": [
            {"facet_id": 1, "name": "product_form", "order": 1, "values": [
                {"code": 0, "value": "ALL"},
                {"code": 1, "value": "\ucea1\uc290", "aliases": ["\ucea1\uc290\ud615"]},
                {"code": 2, "value": "\ubd84\ub9d0"},
            ]},
        ]}],
    }
    taxonomy_path = tmp_path / "taxonomy.json"
    taxonomy_path.write_text(json.dumps(taxonomy, ensure_ascii=False), encoding="utf-8")
    rules_path = __import__("pathlib").Path("config/demand_constraint_rules.json")
    alias_path = tmp_path / "aliases.json"
    alias_path.write_text(json.dumps({"aliases": []}, ensure_ascii=False), encoding="utf-8")
    return taxonomy_path, rules_path, alias_path


def test_part_a_returns_backend_contract_without_clustering(tmp_path):
    taxonomy, rules, aliases = _fixtures(tmp_path)
    demands = pd.DataFrame([
        {"demand_id": "1", "catalog_id": "p1", "category_id": "c1", "extra_requirement": "\uac00\ub2a5\ud558\uba74 \ucea1\uc290\uc778 \uc81c\ud488\uc73c\ub85c \ubd80\ud0c1\ud574\uc694.", "is_substitutable": "true"},
        {"demand_id": "2", "catalog_id": "p1", "category_id": "c1", "extra_requirement": "", "is_substitutable": "false"},
        {"demand_id": "3", "catalog_id": "p1", "category_id": "c1", "extra_requirement": "\ub538\uae30\ub9db \uc81c\ud488\uc774\uba74 \uc88b\uaca0\uc5b4\uc694.", "is_substitutable": "true"},
        {"demand_id": "4", "catalog_id": "p1", "category_id": "c1", "extra_requirement": "\ubd84\ub9d0 \ub610\ub294 \ucea1\uc290\ub3c4 \uad1c\ucc2e\uc544\uc694.", "is_substitutable": "true"},
    ])
    result, summary = run_part_a_batch(demands, taxonomy, rules, aliases)
    assert list(result["status"]) == ["PARSED", "NOT_APPLICABLE", "PASSTHROUGH", "PARSED"]
    constraints = json.loads(result.loc[0, "constraints"])
    assert constraints[0]["facetKey"] == "product_form"
    assert constraints[0]["valueCode"] == 1
    assert result.loc[2, "effectiveRequirementMode"] == "SEMANTIC_TEXT"
    assert len(json.loads(result.loc[3, "preferenceGroups"])) == 1
    assert summary["externalLlmCalls"] == 0
    assert summary["clustering"] == "NOT_PERFORMED"


def test_part_a_isolates_parser_failure_and_preserves_backend_ids(tmp_path, monkeypatch):
    taxonomy, rules, aliases = _fixtures(tmp_path)
    demands = pd.DataFrame([
        {
            "demand_id": str(index),
            "catalog_id": str(100 + index),
            "category_id": "c1",
            "extra_requirement": "캡슐",
            "is_substitutable": "true",
        }
        for index in range(10)
    ])
    class FailingParser:
        calls = 0

        def interpret(self, category_id, requirement, *, is_substitutable):
            self.calls += 1
            if self.calls == 5:
                raise ValueError("fixture parser failure")
            return type("Result", (), {
                "to_dict": lambda self: {
                    "status": "PARSED",
                    "effective_requirement_mode": "STRUCTURED",
                    "constraints": [],
                    "warnings": [],
                    "diagnostic_code": None,
                    "interpretation_method": "fixture",
                    "preference_groups": [],
                    "semantic_preferences": [],
                }
            })()

    monkeypatch.setattr(
        "moongcheap_ai.data_foundation.part_a_runtime.DemandConstraintParser.from_taxonomy",
        classmethod(lambda cls, *args, **kwargs: FailingParser()),
    )
    result, summary = run_part_a_batch(demands, taxonomy, rules, aliases)
    assert len(result) == 10
    assert result.loc[0, "demandId"] == "0"
    assert result.loc[0, "categoryId"] == "c1"
    assert result.loc[4, "status"] == "REVIEW"
    assert result.loc[4, "processed_at"] == ""
    assert summary["parserExceptionCount"] == 1
    assert summary["externalLlmCalls"] == 0


def test_v22_category_local_alias_maps_powder_to_korean_value():
    taxonomy = json.loads(__import__("pathlib").Path("config/facet_taxonomy_v2_2.json").read_text(encoding="utf-8"))
    parser = DemandConstraintParser.from_taxonomy(
        taxonomy,
        rules_path="config/demand_constraint_rules.json",
        aliases_path="config/model1_aliases_reviewed_v2.json",
    )
    result = parser.interpret(
        "health-functional-food:probiotics",
        "가루",
        is_substitutable=True,
    )
    assert result.status == "PARSED"
    assert result.constraints[0].facet_name == "product_form"
    assert result.constraints[0].value == "분말"
    assert result.constraints[0].value_code == 1
