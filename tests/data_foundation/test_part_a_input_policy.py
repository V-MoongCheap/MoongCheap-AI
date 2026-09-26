from __future__ import annotations

import json
from pathlib import Path

from moongcheap_ai.data_foundation.part_a_input_policy import PartAConstraintInputPolicy
from moongcheap_ai.demand_constraints import DemandConstraintParser


ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests/demand_constraints/fixtures"


def _parser() -> DemandConstraintParser:
    taxonomy = json.loads((FIXTURES / "v042_taxonomy.json").read_text(encoding="utf-8"))
    return DemandConstraintParser.from_taxonomy(
        taxonomy,
        rules_path=ROOT / "config/demand_constraint_rules.json",
        aliases_path=ROOT / "config/demand_constraint_aliases.json",
        policy_cls=PartAConstraintInputPolicy,
    )


def test_part_a_preserves_clause_polarity() -> None:
    result = _parser().interpret(
        "health-functional-food:protein",
        "분말은 반드시 포함하고 하루 2회는 선호해요.",
        is_substitutable=True,
    )

    assert {(item.value, item.constraint_type) for item in result.constraints} == {
        ("분말", "MUST"),
        ("1일 2회", "PREFER"),
    }


def test_part_a_preserves_exclusion_next_to_preference() -> None:
    result = _parser().interpret(
        "health-functional-food:protein",
        "분말 형태는 피하고 하루 두 번 섭취는 선호해요.",
        is_substitutable=True,
    )

    assert {(item.value, item.constraint_type) for item in result.constraints} == {
        ("분말", "EXCLUDE"),
        ("1일 2회", "PREFER"),
    }


def test_part_a_does_not_call_must_and_exclude_different_values_conflict() -> None:
    result = _parser().interpret(
        "health-functional-food:protein",
        "분말 형태여야 하지만, 동시에 정 형태는 피하고 싶어요.",
        is_substitutable=True,
    )

    assert result.status != "CONFLICT"
    assert {(item.value, item.constraint_type) for item in result.constraints} == {
        ("분말", "MUST"),
        ("정", "EXCLUDE"),
    }
