from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from moongcheap_ai.demand_constraints import (
    DemandConstraintParser,
    parse_demand_constraints,
)


ROOT = Path(__file__).parents[2]
FIXTURES = Path(__file__).parent / "fixtures"
RULES = ROOT / "config/demand_constraint_rules.json"
ALIASES = ROOT / "config/demand_constraint_aliases.json"
TAXONOMY = FIXTURES / "v042_taxonomy.json"


@pytest.fixture(scope="module")
def parser() -> DemandConstraintParser:
    taxonomy = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    return DemandConstraintParser.from_taxonomy(
        taxonomy,
        rules_path=RULES,
        aliases_path=ALIASES,
    )


def test_substitution_opt_out_ignores_only_the_optional_requirement(
    parser: DemandConstraintParser,
) -> None:
    result = parser.interpret(
        "health-functional-food:protein",
        "분말은 반드시 제외해주세요.",
        is_substitutable=False,
    )

    assert result.status == "NOT_APPLICABLE"
    assert result.effective_requirement_mode == "NONE"
    assert result.constraints == ()
    assert "route" not in result.to_dict()


def test_empty_opt_in_has_no_requirement_signal(
    parser: DemandConstraintParser,
) -> None:
    result = parser.interpret(
        "health-functional-food:protein",
        " ",
        is_substitutable=True,
    )

    assert result.status == "NONE"
    assert result.effective_requirement_mode == "NONE"


@pytest.mark.parametrize(
    ("text", "expected_values"),
    [
        ("분말", {"분말"}),
        ("정제", {"정"}),
        ("분말 1일 2회", {"분말", "1일 2회"}),
        ("가능하면 분말인 제품으로 부탁해요.", {"분말"}),
    ],
)
def test_input_contract_promotes_safe_preferences(
    parser: DemandConstraintParser,
    text: str,
    expected_values: set[str],
) -> None:
    result = parser.interpret(
        "health-functional-food:protein",
        text,
        is_substitutable=True,
    )

    assert result.status == "PARSED"
    assert result.effective_requirement_mode == "STRUCTURED"
    assert {item.value for item in result.constraints} == expected_values
    assert {item.constraint_type for item in result.constraints} == {"PREFER"}


def test_alternatives_are_preserved_as_any_of_max(
    parser: DemandConstraintParser,
) -> None:
    result = parser.interpret(
        "health-functional-food:protein",
        "분말 또는 정도 괜찮아요.",
        is_substitutable=True,
    )

    assert result.status == "PARSED"
    assert result.constraints == ()
    assert result.effective_requirement_mode == "STRUCTURED"
    assert len(result.preference_groups) == 1
    group = result.preference_groups[0]
    assert group.operator == "ANY_OF"
    assert group.aggregation == "MAX"
    assert {item.value for item in group.members} == {"분말", "정"}


def test_out_of_taxonomy_preference_is_a_semantic_signal(
    parser: DemandConstraintParser,
) -> None:
    text = "딸기맛 제품이면 좋겠어요."
    result = parser.interpret(
        "health-functional-food:protein",
        text,
        is_substitutable=True,
    )

    assert result.status == "PASSTHROUGH"
    assert result.effective_requirement_mode == "SEMANTIC_TEXT"
    assert result.semantic_preferences == (text,)


def test_conflict_is_diagnostic_but_has_no_effective_signal(
    parser: DemandConstraintParser,
) -> None:
    result = parser.interpret(
        "health-functional-food:protein",
        "분말이면서 정인 제품으로 부탁해요.",
        is_substitutable=True,
    )

    assert result.status == "CONFLICT"
    assert result.diagnostic_code == "CONFLICTING_SAME_FACET_VALUES"
    assert result.effective_requirement_mode == "NONE"
    assert result.constraints == ()


def test_lexical_aversion_is_an_exclusion(
    parser: DemandConstraintParser,
) -> None:
    result = parser.interpret(
        "health-functional-food:omega_fatty_acid",
        "필수 지방산은 피하고 싶어요.",
        is_substitutable=True,
    )

    assert result.status == "PARSED"
    assert {(item.value, item.constraint_type) for item in result.constraints} == {
        ("필수 지방산", "EXCLUDE")
    }


def test_equivalent_taxonomy_codes_resolve_to_a_canonical_code(
    parser: DemandConstraintParser,
) -> None:
    result = parser.interpret(
        "health-functional-food:vitamin_mineral",
        "１일 1회",
        is_substitutable=True,
    )

    assert result.status == "PARSED"
    assert result.constraints[0].value_code == 1
    assert result.taxonomy_equivalences[0].equivalent_value_codes == (1, 8)
    assert result.effective_requirement_mode == "STRUCTURED"

    canonical_code, equivalence = parser.canonicalize_value_code(
        "health-functional-food:vitamin_mineral",
        "daily_frequency",
        8,
    )
    assert canonical_code == 1
    assert equivalence is not None
    assert equivalence.equivalent_value_codes == (1, 8)


def test_batch_contract_serializes_board_preprocessing_signals(
    parser: DemandConstraintParser,
) -> None:
    source = pd.DataFrame([
        {
            "demand_id": "D1",
            "category_id": "health-functional-food:protein",
            "extra_requirement": "분말",
            "is_substitutable": True,
        },
        {
            "demand_id": "D2",
            "category_id": "health-functional-food:protein",
            "extra_requirement": "딸기맛 제품이면 좋겠어요.",
            "is_substitutable": True,
        },
        {
            "demand_id": "D3",
            "category_id": "health-functional-food:protein",
            "extra_requirement": "분말이면서 정인 제품으로 부탁해요.",
            "is_substitutable": True,
        },
        {
            "demand_id": "D4",
            "category_id": "health-functional-food:protein",
            "extra_requirement": "분말은 반드시 제외해주세요.",
            "is_substitutable": False,
        },
    ])

    result = parse_demand_constraints(source, parser).set_index("demand_id")

    assert result.loc["D1", "constraint_status"] == "PARSED"
    assert result.loc["D1", "effective_requirement_mode"] == "STRUCTURED"
    assert result.loc["D2", "constraint_status"] == "PASSTHROUGH"
    assert json.loads(result.loc["D2", "semantic_preferences"]) == [
        "딸기맛 제품이면 좋겠어요."
    ]
    assert result.loc["D3", "constraint_status"] == "CONFLICT"
    assert result.loc["D3", "effective_requirement_mode"] == "NONE"
    assert result.loc["D4", "constraint_status"] == "NOT_APPLICABLE"
    assert result.loc["D4", "effective_requirement_mode"] == "NONE"
    assert json.loads(result.loc["D4", "constraints"]) == []
    assert not any("route" in column for column in result.columns)


def test_invalid_present_substitution_consent_is_rejected(
    parser: DemandConstraintParser,
) -> None:
    source = pd.DataFrame([{
        "demand_id": "D1",
        "category_id": "health-functional-food:protein",
        "extra_requirement": "분말",
        "is_substitutable": "maybe",
    }])

    with pytest.raises(ValueError, match="invalid is_substitutable"):
        parse_demand_constraints(source, parser)
