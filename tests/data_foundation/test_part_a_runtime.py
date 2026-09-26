import json

import pandas as pd

from moongcheap_ai.data_foundation.part_a_runtime import run_part_a_batch
from moongcheap_ai.data_foundation.runtime_job import run_batch
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
        {"demand_id": "2", "catalog_id": "p1", "category_id": "c1", "extra_requirement": "분말", "is_substitutable": "false"},
        {"demand_id": "3", "catalog_id": "p1", "category_id": "c1", "extra_requirement": "\ub538\uae30\ub9db \uc81c\ud488\uc774\uba74 \uc88b\uaca0\uc5b4\uc694.", "is_substitutable": "true"},
        {"demand_id": "4", "catalog_id": "p1", "category_id": "c1", "extra_requirement": "\ubd84\ub9d0 \ub610\ub294 \ucea1\uc290\ub3c4 \uad1c\ucc2e\uc544\uc694.", "is_substitutable": "true"},
    ])
    result, summary = run_part_a_batch(demands, taxonomy, rules, aliases)
    assert list(result["status"]) == ["PARSED", "PARSED", "PASSTHROUGH", "PARSED"]
    assert json.loads(result.loc[1, "constraints"])[0]["valueCode"] == 2
    constraints = json.loads(result.loc[0, "constraints"])
    assert constraints[0]["facetKey"] == "product_form"
    assert constraints[0]["valueCode"] == 1
    assert result.loc[2, "effectiveRequirementMode"] == "SEMANTIC_TEXT"
    assert result.loc[2, "processed_at"] == ""
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


def test_part_a_prevalidates_category_before_parser_and_keeps_invalid_rows_pending(tmp_path, monkeypatch):
    taxonomy, rules, aliases = _fixtures(tmp_path)

    class ParserMustNotBeCalled:
        calls = 0

        def interpret(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("parser must not be called for an invalid category")

    parser = ParserMustNotBeCalled()
    monkeypatch.setattr(
        "moongcheap_ai.data_foundation.part_a_runtime.DemandConstraintParser.from_taxonomy",
        classmethod(lambda cls, *args, **kwargs: parser),
    )
    demands = pd.DataFrame([
        {"demand_id": "missing", "catalog_id": "p1", "extra_requirement": "캡슐"},
        {"demand_id": "unknown", "catalog_id": "p2", "category_id": "not-in-taxonomy", "extra_requirement": "캡슐"},
    ])

    result, summary = run_part_a_batch(demands, taxonomy, rules, aliases, processed_at="2026-09-10T00:00:00+00:00")

    assert parser.calls == 0
    assert list(result["status"]) == ["REVIEW", "REVIEW"]
    assert list(result["diagnostic_code"]) == ["CATEGORY_MISSING", "CATEGORY_NOT_IN_TAXONOMY"]
    assert list(result["processed_at"]) == ["", ""]
    assert set(result.loc[0, ["effectiveRequirementMode", "preferenceGroups", "passthroughText"]].index) == {
        "effectiveRequirementMode", "preferenceGroups", "passthroughText"
    }
    assert result.loc[0, "effectiveRequirementMode"] == "NONE"
    assert result.loc[0, "preferenceGroups"] == "[]"
    assert pd.isna(result.loc[0, "passthroughText"])
    assert summary["categoryPrevalidationFailureCount"] == 2


def test_part_a_rejects_invalid_substitution_consent_before_parser(tmp_path, monkeypatch):
    taxonomy, rules, aliases = _fixtures(tmp_path)

    class ParserMustNotBeCalled:
        def interpret(self, *args, **kwargs):
            raise AssertionError("parser must not be called for invalid input")

    monkeypatch.setattr(
        "moongcheap_ai.data_foundation.part_a_runtime.DemandConstraintParser.from_taxonomy",
        classmethod(lambda cls, *args, **kwargs: ParserMustNotBeCalled()),
    )
    demands = pd.DataFrame([{
        "demand_id": "invalid-bool",
        "catalog_id": "p1",
        "category_id": "c1",
        "extra_requirement": "캡슐",
        "is_substitutable": "maybe",
    }])

    result, _ = run_part_a_batch(demands, taxonomy, rules, aliases)

    assert result.loc[0, "status"] == "REVIEW"
    assert result.loc[0, "diagnostic_code"] == "INVALID_IS_SUBSTITUTABLE"
    assert result.loc[0, "processed_at"] == ""
    assert result.loc[0, "effectiveRequirementMode"] == "NONE"
    assert result.loc[0, "preferenceGroups"] == "[]"
    assert pd.isna(result.loc[0, "passthroughText"])


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


def test_part_a_runtime_uses_compatibility_aliases_for_explicit_requirement() -> None:
    root = __import__("pathlib").Path(".")
    demands = pd.DataFrame([{
        "demand_id": "omega", "catalog_id": "catalog-1",
        "category_id": "health-functional-food:omega_fatty_acid",
        "extra_requirement": "오메가3 함유 제품을 원해요.",
        "is_substitutable": "true",
    }])

    result, _ = run_part_a_batch(
        demands,
        root / "config/facet_taxonomy_v2_2.json",
        root / "config/demand_constraint_rules.json",
        root / "config/model1_aliases_reviewed_v2.json",
        compatibility_alias_registry_path=root / "config/demand_constraint_aliases.json",
    )

    assert result.loc[0, "status"] == "PARSED"
    assert result.loc[0, "label"] == "0-2-0"
    constraint = json.loads(result.loc[0, "constraints"])[0]
    assert constraint["constraintType"] == "MUST"


def test_runtime_job_uses_qwen_only_for_unresolved_rows(tmp_path, monkeypatch):
    taxonomy, rules, aliases = _fixtures(tmp_path)
    calls = []

    class FakeQwen:
        call_count = 0

        def __init__(self, model, *, endpoint, timeout):
            assert model == "qwen-test"
            assert endpoint == "http://ollama.test"
            assert timeout == 7

        def classify(self, rows, loader):
            calls.append(rows)
            self.call_count += 1
            return {rows[0]["demand_id"]: {"product_form": {"code": 1}}}

    monkeypatch.setattr("moongcheap_ai.data_foundation.runtime_job.OllamaDemandLabeler", FakeQwen)
    demands = pd.DataFrame([
        {"demand_id": "parsed", "catalog_id": "p1", "category_id": "c1", "extra_requirement": "캡슐", "is_substitutable": "true"},
        {"demand_id": "fallback", "catalog_id": "p1", "category_id": "c1", "extra_requirement": "딸기맛", "is_substitutable": "true"},
    ])

    result, _ = run_batch(
        demands, taxonomy, alias_registry_path=aliases, rules_path=rules,
        model2_fallback_enabled=True, model2_fallback_model="qwen-test",
        model2_fallback_endpoint="http://ollama.test", model2_fallback_timeout=7,
    )

    assert len(calls) == 1
    assert calls[0][0]["demand_id"] == "fallback"
    assert result.set_index("demand_id").loc["parsed", "interpretation_method"] != "RULE_FIRST_QWEN_FALLBACK"
    assert result.set_index("demand_id").loc["fallback", "status"] == "PARSED"
    assert result.set_index("demand_id").loc["fallback", "label"] == "1"
    assert result.set_index("demand_id").loc["fallback", "fallback_status"] == "ACCEPTED"


def test_runtime_job_keeps_unavailable_qwen_rows_in_review(tmp_path, monkeypatch):
    taxonomy, rules, aliases = _fixtures(tmp_path)

    class UnavailableQwen:
        call_count = 0

        def __init__(self, *args, **kwargs):
            pass

        def classify(self, rows, loader):
            from moongcheap_ai.data_foundation.demand_label_comparison import LLMLabelingError
            raise LLMLabelingError("ollama unavailable")

    monkeypatch.setattr("moongcheap_ai.data_foundation.runtime_job.OllamaDemandLabeler", UnavailableQwen)
    demands = pd.DataFrame([{
        "demand_id": "fallback", "catalog_id": "p1", "category_id": "c1",
        "extra_requirement": "딸기맛", "is_substitutable": "true",
    }])
    result, payload = run_batch(
        demands, taxonomy, alias_registry_path=aliases, rules_path=rules,
        model2_fallback_enabled=True,
    )
    assert result.loc[0, "status"] == "REVIEW"
    assert result.loc[0, "label_status"] == "REVIEW"
    assert result.loc[0, "fallback_status"] == "UNAVAILABLE"
    assert payload["results"] == []
