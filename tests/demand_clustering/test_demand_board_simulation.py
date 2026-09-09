from __future__ import annotations

from datetime import datetime, timezone

from scripts.demand.simulate_demand_board_handoff import (
    PROFILE_ORIGIN,
    PRICE_ORIGIN,
    _stable_index,
    build_part_c_board_snapshot,
    build_synthetic_catalog_profiles,
    requirement_from_v046_row,
    simulate_demand_board_handoff,
    simulated_price_band,
)


AS_OF = datetime(2026, 9, 6, tzinfo=timezone.utc)
CATEGORY = "health-functional-food:test"
TAXONOMY = {
    "version": "v2.1",
    "categories": [
        {
            "category_id": CATEGORY,
            "facets": [
                {
                    "name": "product_form",
                    "order": 1,
                    "values": [
                        {"code": 0, "value": "ALL"},
                        {"code": 1, "value": "분말"},
                        {"code": 2, "value": "정"},
                    ],
                },
                {
                    "name": "daily_frequency",
                    "order": 2,
                    "values": [
                        {"code": 0, "value": "ALL"},
                        {"code": 1, "value": "1일 1회"},
                        {"code": 2, "value": "1일 2회"},
                    ],
                },
            ],
        }
    ],
}


def source_id_for_band(index: int, *, offset: int = 0) -> str:
    found = []
    candidate = 1
    while len(found) <= offset:
        source_id = f"synthetic-test-demand-{candidate:05d}"
        if simulated_price_band(source_id).index == index:
            found.append(source_id)
        candidate += 1
    return found[offset]


def row(
    source_demand_id: str,
    catalog_id: int,
    *,
    is_substitutable: bool = True,
    status: str = "NONE",
    mode: str = "NONE",
    constraints: str = "[]",
    groups: str = "[]",
    semantic: str = "[]",
) -> dict[str, str]:
    return {
        "demand_id": source_demand_id,
        "product_reference": str(catalog_id),
        "category_id": CATEGORY,
        "taxonomy_version": "v2.1",
        "label": "0-0",
        "quantity": "2",
        "is_substitutable": str(is_substitutable),
        "desired_price_min": "10000",
        "desired_price_max": "30000",
        "constraint_status": status,
        "constraints": constraints,
        "constraint_warnings": "[]",
        "constraint_clauses": "[]",
        "constraint_interpretation_method": "TEST",
        "preference_groups": groups,
        "free_text_preferences": semantic,
        "constraint_diagnostic_code": "",
        "effective_constraint_mode": mode,
    }


def test_stable_index_and_price_band_are_reproducible() -> None:
    assert _stable_index("same-key", 7) == _stable_index("same-key", 7)
    source_id = "synthetic-test-demand-1"
    assert simulated_price_band(source_id) is simulated_price_band(source_id)


def test_catalog_profiles_do_not_consume_demand_labels_or_constraints() -> None:
    first = row("D1", 100, constraints="[]")
    second = row(
        "D2",
        100,
        status="PARSED",
        mode="STRUCTURED",
        constraints=(
            '[{"facet_name":"product_form","value_code":2,'
            '"value":"정","constraint_type":"MUST"}]'
        ),
    )
    first["label"] = "1-1"
    second["label"] = "2-2"

    profiles = build_synthetic_catalog_profiles((first, second), TAXONOMY)

    assert list(profiles) == [100]
    assert profiles[100]["profileOrigin"] == PROFILE_ORIGIN
    assert set(profiles[100]["facetValues"]) == {
        "product_form",
        "daily_frequency",
    }


def test_v046_row_deserializes_structured_group_and_semantic_modes() -> None:
    structured = row(
        "D1",
        100,
        status="PARSED",
        mode="STRUCTURED",
        constraints=(
            '[{"facet_name":"product_form","value_code":1,'
            '"value":"분말","constraint_type":"PREFER"}]'
        ),
        groups=(
            '[{"group_id":"g1","operator":"ANY_OF","aggregation":"MAX",'
            '"members":[{"facet_name":"daily_frequency","value_code":1,'
            '"value":"1일 1회","constraint_type":"PREFER"},'
            '{"facet_name":"daily_frequency","value_code":2,'
            '"value":"1일 2회","constraint_type":"PREFER"}]}]'
        ),
    )
    passthrough = row(
        "D2",
        101,
        status="PASSTHROUGH",
        mode="SEMANTIC_TEXT",
        semantic='["딸기맛"]',
    )

    parsed = requirement_from_v046_row(structured)
    semantic = requirement_from_v046_row(passthrough)

    assert parsed.constraints[0].constraint_type == "PREFER"
    assert parsed.preference_groups[0].operator == "ANY_OF"
    assert semantic.semantic_preferences == ("딸기맛",)


def test_end_to_end_simulation_separates_assignment_offer_and_opt_out() -> None:
    direct_a = row(source_id_for_band(0, offset=0), 201)
    direct_b = row(source_id_for_band(0, offset=1), 201)
    substitute = row(source_id_for_band(6, offset=0), 100)
    opted_out = row(
        source_id_for_band(6, offset=1),
        101,
        is_substitutable=False,
        status="NOT_APPLICABLE",
    )

    output = simulate_demand_board_handoff(
        (direct_a, direct_b, substitute, opted_out),
        TAXONOMY,
        as_of=AS_OF,
        min_participants=2,
    )

    assert output["dataClassification"] == (
        "SYNTHETIC_MECHANICS_ONLY_NOT_PRODUCT_FACT"
    )
    assert output["simulationPolicy"]["priceOrigin"] == PRICE_ORIGIN
    assert output["summary"] == {
        "sourceDemandCount": 4,
        "catalogProfileCount": 3,
        "sourcePriceContractViolationCount": 4,
        "demandBoardCount": 1,
        "directAssignedDemandCount": 2,
        "substituteProposalCount": 1,
        "substitutionNotEligibleCount": 1,
        "unmatchedDemandCount": 0,
        "reviewQueueCount": 0,
        "requirementStatusCounts": {"NONE": 3, "NOT_APPLICABLE": 1},
        "effectiveRequirementModeCounts": {"NONE": 4},
    }

    board = output["demandBoards"][0]
    assert board["participantCount"] == 2
    assert board["pendingSubstituteOfferCount"] == 1
    assert len(board["directDemandIds"]) == 2
    assert len(board["pendingSubstituteDemandIds"]) == 1

    statuses = {
        item["sourceDemandId"]: item for item in output["demandStates"]
    }
    assert statuses[substitute["demand_id"]]["status"] == "SUBSTITUTE_OFFERED"
    assert statuses[opted_out["demand_id"]]["status"] == "UNASSIGNED"
    assert statuses[opted_out["demand_id"]]["reasonCodes"] == [
        "SUBSTITUTION_NOT_CONSENTED"
    ]

    snapshot = build_part_c_board_snapshot(output)
    assert snapshot["schemaVersion"] == "part-c-demand-board-snapshot.v0.1"
    assert snapshot["demandBoards"] == output["demandBoards"]
    assert "demandStates" not in snapshot
    assert "substituteAdmissionPlan" not in snapshot
    assert "catalogProfiles" not in snapshot
