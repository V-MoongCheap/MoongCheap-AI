from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from moongcheap_ai.demand_clustering import (
    DemandBoardInput,
    DemandInput,
    SubstituteBoardCandidateInput,
    SubstituteDemandInput,
    build_substitute_board_admission_plan,
    character_ngram_cosine_similarity,
    select_substitute_board_candidate,
)
from moongcheap_ai.demand_constraints import (
    DemandConstraintParser,
    DemandRequirementResult,
    FacetConstraint,
    PreferenceGroup,
)


AS_OF = datetime(2026, 9, 5, tzinfo=timezone.utc)
CATEGORY = "health-functional-food:protein"
ROOT = Path(__file__).parents[2]


def constraint(
    facet_name: str,
    value_code: int,
    value: str,
    constraint_type: str,
) -> FacetConstraint:
    return FacetConstraint(
        facet_name=facet_name,
        value_code=value_code,
        value=value,
        constraint_type=constraint_type,
        evidence_clause=value,
    )


def requirement(
    *,
    status: str = "NONE",
    mode: str = "NONE",
    constraints: tuple[FacetConstraint, ...] = (),
    groups: tuple[PreferenceGroup, ...] = (),
    semantic: tuple[str, ...] = (),
) -> DemandRequirementResult:
    return DemandRequirementResult(
        status=status,
        constraints=constraints,
        warnings=(),
        clauses=(),
        interpretation_method="TEST",
        preference_groups=groups,
        semantic_preferences=semantic,
        effective_requirement_mode=mode,
    )


def demand(**overrides: object) -> SubstituteDemandInput:
    values: dict[str, object] = {
        "id": 9001,
        "catalog_id": 100,
        "category_id": CATEGORY,
        "taxonomy_version": "v2.1",
        "desired_price_min": 10_001,
        "desired_price_max": 20_000,
        "quantity": 3,
        "is_substitutable": True,
        "requirement": requirement(),
        "status": "UNASSIGNED",
        "desire_end_at": AS_OF + timedelta(days=10),
    }
    values.update(overrides)
    return SubstituteDemandInput(**values)  # type: ignore[arg-type]


def board(
    board_id: int,
    catalog_id: int,
    **overrides: object,
) -> SubstituteBoardCandidateInput:
    values: dict[str, object] = {
        "id": board_id,
        "catalog_id": catalog_id,
        "category_id": CATEGORY,
        "taxonomy_version": "v2.1",
        "price_min": 10_001,
        "price_max": 20_000,
        "participant_count": 5,
        "facet_values": {
            "product_form": 2,
            "daily_frequency": 1,
            "functional_ingredients": 3,
        },
        "sale_end_at": AS_OF + timedelta(days=5),
        "status": "GB_GATHERING",
        "semantic_text": "초콜릿맛 단백질 분말",
    }
    values.update(overrides)
    return SubstituteBoardCandidateInput(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"is_substitutable": False}, "SUBSTITUTION_NOT_CONSENTED"),
        ({"status": "ASSIGNED"}, "DEMAND_NOT_UNASSIGNED"),
        ({"desire_end_at": AS_OF}, "DEMAND_EXPIRED"),
    ],
)
def test_requires_live_consented_unassigned_demand(
    overrides: dict[str, object],
    reason: str,
) -> None:
    result = select_substitute_board_candidate(
        demand(**overrides),
        (board(1, 201),),
        as_of=AS_OF,
    )

    assert result.status == "NOT_ELIGIBLE"
    assert result.reason_codes == (reason,)


def test_must_and_exclude_are_hard_gates_including_unknown_facets() -> None:
    signal = requirement(
        status="PARSED",
        mode="STRUCTURED",
        constraints=(
            constraint("daily_frequency", 2, "1일 2회", "MUST"),
            constraint("product_form", 1, "정", "EXCLUDE"),
        ),
    )
    candidates = (
        board(1, 201, facet_values={"daily_frequency": 1, "product_form": 2}),
        board(2, 202, facet_values={"daily_frequency": 2, "product_form": 1}),
        board(3, 203, facet_values={"product_form": 2}),
        board(4, 204, facet_values={"daily_frequency": 2}),
    )

    result = select_substitute_board_candidate(
        demand(requirement=signal),
        candidates,
        as_of=AS_OF,
    )
    reasons = {
        reason
        for rejected in result.rejected_boards
        for reason in rejected.reason_codes
    }

    assert result.status == "NO_COMPATIBLE_BOARD"
    assert {
        "MUST_MISMATCH:daily_frequency",
        "EXCLUDED_VALUE:product_form",
        "UNKNOWN_MUST_FACET:daily_frequency",
        "UNKNOWN_EXCLUDE_FACET:product_form",
    }.issubset(reasons)


def test_preference_ranks_but_does_not_filter() -> None:
    signal = requirement(
        status="PARSED",
        mode="STRUCTURED",
        constraints=(
            constraint("functional_ingredients", 3, "유청단백", "PREFER"),
        ),
    )
    preferred = board(
        1,
        201,
        participant_count=2,
        facet_values={"functional_ingredients": 3},
    )
    popular = board(
        2,
        202,
        participant_count=20,
        facet_values={"functional_ingredients": 4},
    )

    result = select_substitute_board_candidate(
        demand(requirement=signal),
        (popular, preferred),
        as_of=AS_OF,
    )

    assert [item.demand_board_id for item in result.ranked_boards] == [1, 2]
    assert result.ranked_boards[0].structured_preference_score == 1.0
    assert result.ranked_boards[1].structured_preference_score == 0.0


def test_any_of_max_group_is_one_preference_unit() -> None:
    group = PreferenceGroup(
        group_id="frequency-choice",
        operator="ANY_OF",
        aggregation="MAX",
        members=(
            constraint("daily_frequency", 1, "1일 1회", "PREFER"),
            constraint("daily_frequency", 2, "1일 2회", "PREFER"),
        ),
    )
    signal = requirement(
        status="PARSED",
        mode="STRUCTURED",
        constraints=(constraint("product_form", 2, "분말", "PREFER"),),
        groups=(group,),
    )

    result = select_substitute_board_candidate(
        demand(requirement=signal),
        (
            board(1, 201, facet_values={"product_form": 2, "daily_frequency": 2}),
            board(2, 202, facet_values={"product_form": 2, "daily_frequency": 3}),
        ),
        as_of=AS_OF,
    )

    assert result.ranked_boards[0].structured_preference_matched == 2
    assert result.ranked_boards[0].structured_preference_total == 2
    assert result.ranked_boards[1].structured_preference_score == 0.5


def test_passthrough_uses_injected_text_scorer() -> None:
    signal = requirement(
        status="PASSTHROUGH",
        mode="SEMANTIC_TEXT",
        semantic=("딸기맛",),
    )
    strawberry = board(
        1,
        201,
        participant_count=1,
        semantic_text="달콤한 딸기맛 단백질 분말",
    )
    chocolate = board(
        2,
        202,
        participant_count=10,
        semantic_text="진한 초콜릿맛 단백질 분말",
    )

    result = select_substitute_board_candidate(
        demand(requirement=signal),
        (chocolate, strawberry),
        as_of=AS_OF,
        text_similarity_scorer=character_ngram_cosine_similarity,
    )

    assert result.selected_board is not None
    assert result.selected_board.demand_board_id == 1
    assert result.selected_board.text_similarity_score is not None


def test_conflict_effective_none_is_nonblocking() -> None:
    signal = requirement(status="CONFLICT", mode="NONE")

    result = select_substitute_board_candidate(
        demand(requirement=signal),
        (board(1, 201, participant_count=2), board(2, 202, participant_count=10)),
        as_of=AS_OF,
    )

    assert result.status == "CANDIDATE_SELECTED"
    assert result.selected_board is not None
    assert result.selected_board.demand_board_id == 2


def test_v46_canonicalizer_is_applied_to_candidate_codes() -> None:
    signal = requirement(
        status="PARSED",
        mode="STRUCTURED",
        constraints=(constraint("daily_frequency", 1, "1일 1회", "MUST"),),
    )

    def canonicalize(
        _category_id: str,
        facet_name: str,
        value_code: int,
    ) -> tuple[int, object | None]:
        if facet_name == "daily_frequency" and value_code == 8:
            return 1, {"equivalent": (1, 8)}
        return value_code, None

    result = select_substitute_board_candidate(
        demand(requirement=signal),
        (board(1, 201, facet_values={"daily_frequency": 8}),),
        as_of=AS_OF,
        canonicalize_value_code=canonicalize,
    )

    assert result.status == "CANDIDATE_SELECTED"


def test_candidate_gates_allow_a_cheaper_board() -> None:
    candidates = (
        board(1, 100),
        board(2, 202, category_id="health-functional-food:eye_health"),
        board(3, 203, taxonomy_version="v2.0"),
        board(4, 204, status="GB_CLOSED"),
        board(5, 205, sale_end_at=AS_OF),
        board(6, 206, price_min=20_001, price_max=30_000),
        board(7, 207, price_min=0, price_max=10_000),
    )

    result = select_substitute_board_candidate(demand(), candidates, as_of=AS_OF)
    rejected = {
        item.demand_board_id: set(item.reason_codes)
        for item in result.rejected_boards
    }

    assert result.selected_board is not None
    assert result.selected_board.demand_board_id == 7
    assert "SAME_AS_ORIGINAL_CATALOG" in rejected[1]
    assert "CATEGORY_MISMATCH" in rejected[2]
    assert "TAXONOMY_VERSION_MISMATCH" in rejected[3]
    assert "BOARD_NOT_GATHERING" in rejected[4]
    assert "BOARD_NOT_ACTIVE" in rejected[5]
    assert "PRICE_MAX_EXCEEDS_DEMAND" in rejected[6]


def test_input_adapters_join_backend_rows_with_catalog_profile() -> None:
    raw_demand = DemandInput(
        id=1,
        catalog_id=100,
        created_at=AS_OF,
        updated_at=AS_OF,
        desired_price_min=10_001,
        desired_price_max=20_000,
        quantity=2,
        is_substitutable=True,
        status="UNASSIGNED",
        desire_end_at=AS_OF + timedelta(days=7),
    )
    raw_board = DemandBoardInput(
        id=2,
        catalog_id=200,
        participant_count=5,
        created_at=AS_OF,
        sale_end_at=AS_OF + timedelta(days=5),
        price_min=10_001,
        price_max=20_000,
    )

    joined_demand = SubstituteDemandInput.from_demand(
        raw_demand,
        category_id=CATEGORY,
        taxonomy_version="v2.1",
        requirement=requirement(),
    )
    joined_board = SubstituteBoardCandidateInput.from_board(
        raw_board,
        category_id=CATEGORY,
        taxonomy_version="v2.1",
        facet_values={"product_form": 2},
        semantic_text="분말 단백질",
    )

    assert joined_demand.quantity == 2
    assert joined_board.facet_values == {"product_form": 2}


def test_plan_prefills_board_and_counts_participant_only_after_acceptance() -> None:
    item = demand(quantity=4)
    result = select_substitute_board_candidate(
        item,
        (board(1, 201), board(2, 202)),
        as_of=AS_OF,
    )

    plan = build_substitute_board_admission_plan(
        ((item, result),),
        batch_id="admission-batch-1",
        planned_at=AS_OF,
        rule_version="service-requirement+substitute-admission",
    )

    assert "reviewRequired" not in plan
    assert len(plan["proposals"]) == 1
    proposal = plan["proposals"][0]
    assert proposal["proposedStatus"] == "SUBSTITUTE_OFFERED"
    assert proposal["demandBoardId"] == 1
    assert proposal["quantityToCarry"] == 4
    assert proposal["participantCountDeltaOnProposal"] == 0
    assert proposal["participantCountDeltaOnAccept"] == 1
    assert proposal["onAcceptStatus"] == "ASSIGNED"
    assert proposal["onRejectStatus"] == "UNASSIGNED"
    assert proposal["clearDemandBoardIdOnReject"] is True
    assert plan["stateContract"]["reject"] == (
        "SUBSTITUTE_OFFERED_TO_UNASSIGNED"
    )


def test_real_v46_parser_result_flows_directly_into_admission() -> None:
    taxonomy = json.loads(
        (
            ROOT
            / "tests/demand_constraints/fixtures/v042_taxonomy.json"
        ).read_text(encoding="utf-8")
    )
    parser = DemandConstraintParser.from_taxonomy(
        taxonomy,
        rules_path=ROOT / "config/demand_constraint_rules.json",
        aliases_path=ROOT / "config/demand_constraint_aliases.json",
    )
    parsed = parser.interpret(CATEGORY, "분말", is_substitutable=True)

    result = select_substitute_board_candidate(
        demand(requirement=parsed),
        (
            board(1, 201, facet_values={"product_form": 1}),
            board(2, 202, facet_values={"product_form": 2}),
        ),
        as_of=AS_OF,
        canonicalize_value_code=parser.canonicalize_value_code,
    )

    assert parsed.status == "PARSED"
    assert parsed.effective_requirement_mode == "STRUCTURED"
    assert result.selected_board is not None
    assert result.selected_board.demand_board_id == 1
