from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import pytest

from moongcheap_ai.data_foundation.labeling import TaxonomyLoader
from moongcheap_ai.demand_constraints import (
    DemandConstraintParser,
    parse_demand_constraints,
)


ROOT = Path(__file__).parents[2]
FIXTURES = Path(__file__).parent / "fixtures"
RULES = ROOT / "config/demand_constraint_rules.json"
ALIASES = ROOT / "config/demand_constraint_aliases.json"
TAXONOMY = FIXTURES / "v042_taxonomy.json"
EVAL_SET = FIXTURES / "v042_approved_eval.csv"


@pytest.fixture(scope="module")
def taxonomy() -> dict:
    payload = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    TaxonomyLoader(payload)
    return payload


@pytest.fixture(scope="module")
def parser(taxonomy: dict) -> DemandConstraintParser:
    return DemandConstraintParser.from_taxonomy(
        taxonomy,
        rules_path=RULES,
        aliases_path=ALIASES,
    )


def test_rules_are_a_standalone_frozen_configuration() -> None:
    payload = json.loads(RULES.read_text(encoding="utf-8"))

    assert "extends" not in payload
    assert payload["version"] == "demand-requirement-policy-v0.46"
    assert payload["special_cases"]["nominal_inclusion_prohibition_frame"] is True
    assert payload["special_cases"]["input_channel_equivalent_taxonomy_codes"] is True
    assert payload["special_cases"]["input_channel_conflict_effective_none"] is True


def test_integrated_taxonomy_aliases_and_batch_contract(
    parser: DemandConstraintParser,
) -> None:
    source = pd.DataFrame([{
        "demand_id": "D1",
        "catalog_id": "P1",
        "label": "legacy-label-remains-unchanged",
        "extra_requirement": "비오틴은 절대 포함 금지이고, 분말은 꼭 포함해 주세요.",
    }])

    result = parse_demand_constraints(
        source,
        parser,
        {"P1": "health-functional-food:protein"},
    )

    assert result.iloc[0]["category_id"] == "health-functional-food:protein"
    assert result.iloc[0]["constraint_status"] == "PARSED"
    assert result.iloc[0]["label"] == "legacy-label-remains-unchanged"
    constraints = json.loads(result.iloc[0]["constraints"])
    assert {
        (item["value"], item["constraint_type"])
        for item in constraints
    } == {("비오틴", "EXCLUDE"), ("분말", "MUST")}


def test_root_taxonomy_falls_back_for_unknown_category() -> None:
    root_taxonomy = {"facets": [{
        "name": "product_form",
        "order": 1,
        "values": [
            {"code": 0, "value": "ALL", "aliases": []},
            {"code": 1, "value": "캡슐", "aliases": []},
        ],
    }]}
    parser = DemandConstraintParser.from_taxonomy(
        root_taxonomy,
        rules_path=RULES,
        aliases_path=ALIASES,
    )

    result = parser.parse("unknown-category", "캡슐은 꼭 포함해 주세요.")

    assert result.status == "PARSED"
    assert {(item.value, item.constraint_type) for item in result.constraints} == {
        ("캡슐", "MUST")
    }


def test_frozen_independent_evaluation_is_reproduced(
    parser: DemandConstraintParser,
) -> None:
    with EVAL_SET.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    outcomes = []
    for row in rows:
        expected_items = json.loads(row["expected_constraints_json"])
        expected = {
            (item["facet_name"], int(item["value_code"]), item["constraint_type"])
            for item in expected_items
        }
        extraction = parser.parse(row["category_id"], row["extra_requirement"])
        actual = {
            (item.facet_name, item.value_code, item.constraint_type)
            for item in extraction.constraints
        }
        correct = extraction.status == row["expected_status"]
        if row["expected_status"] == "PARSED":
            correct = correct and actual == expected
        outcomes.append((row, extraction, correct))

    auto = [item for item in outcomes if item[1].status == "PARSED"]
    correct_auto = [item for item in auto if item[2]]
    expected_review = [item for item in outcomes if item[0]["expected_status"] == "REVIEW"]
    correct_review = [item for item in expected_review if item[2]]
    failures = [item[0]["sample_id"] for item in outcomes if not item[2]]

    assert len(outcomes) == 129
    assert sum(item[2] for item in outcomes) == 127
    assert len(auto) == 79
    assert len(correct_auto) == 79
    assert len(correct_review) == len(expected_review) == 48
    assert failures == ["openai-NP-046-1", "openai-NP-048-1"]
    assert all(
        item[1].status == "REVIEW"
        for item in outcomes
        if item[0]["sample_id"] in failures
    )
