from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from moongcheap_ai.demand_clustering.evaluation.backend_requests import (
    build_board_plan_request_bundle_from_simulation,
)
from moongcheap_ai.demand_clustering.backend_board_plan import (
    BOARD_PLAN_ENDPOINT_PROPOSAL,
    build_board_assignment_plan,
    post_board_assignment_plan,
    validate_board_assignment_plan_contract,
)
from moongcheap_ai.demand_clustering.batch_planner import (
    DemandClusteringBatchPlan,
    ExistingBoardAssignmentPlan,
)
from moongcheap_ai.demand_clustering.board_formation import NewDemandBoardPlan
from moongcheap_ai.demand_clustering.input_models import DemandBoardInput, DemandInput


NOW = datetime.fromisoformat("2026-09-06T12:00:00+09:00")


def demand(demand_id: int, catalog_id: int, price_min: int, price_max: int) -> DemandInput:
    return DemandInput(
        id=demand_id,
        catalog_id=catalog_id,
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW - timedelta(hours=1),
        desired_price_min=price_min,
        desired_price_max=price_max,
        quantity=1,
        is_substitutable=False,
        status="UNASSIGNED",
        label="ready",
        desire_end_at=NOW + timedelta(days=1),
        processed_at=NOW - timedelta(minutes=1),
    )


def board() -> DemandBoardInput:
    return DemandBoardInput(
        id=31,
        catalog_id=101,
        participant_count=2,
        price_min=10_001,
        price_max=20_000,
        status="GB_GATHERING",
        created_at=NOW - timedelta(days=1),
        sale_end_at=NOW + timedelta(days=2),
    )


def formation_plan() -> dict[str, object]:
    return {
        "schemaVersion": "demand-board-assignment-plan.v0.1",
        "plannedAt": "2026-09-07T12:00:00+09:00",
        "ruleVersion": "board-formation-v1",
        "existingBoardAssignments": [{
            "demandBoardId": 31,
            "demandIds": [1],
        }],
        "newBoards": [{
            "clientBoardKey": "new-board:1",
            "catalogId": 202,
            "priceMin": 20_001,
            "priceMax": 30_000,
            "demandIds": [2, 3, 4, 5, 6],
        }],
    }


class FormationResponse:
    ok = True
    status_code = 200
    text = ""

    def json(self) -> dict[str, object]:
        return {
            "status": "APPLIED",
            "existingAssignments": {
                "appliedCount": 1,
                "staleCount": 0,
            },
            "newBoards": [{
                "clientBoardKey": "new-board:1",
                "demandBoardId": 9001,
                "status": "CREATED",
            }],
        }


def test_builds_backend_owned_direct_assignment_plan() -> None:
    demands = (
        demand(1, 101, 10_001, 20_000),
        demand(2, 202, 20_001, 30_000),
        demand(3, 202, 30_001, 50_000),
        demand(4, 202, 20_001, 30_000),
        demand(5, 202, 20_001, 30_000),
        demand(6, 202, 20_001, 30_000),
    )
    batch = DemandClusteringBatchPlan(
        existing_board_assignments=(
            ExistingBoardAssignmentPlan(31, (1,), 1),
        ),
        new_board_plans=(
            NewDemandBoardPlan(
                catalog_id=202,
                demand_ids=(2, 3, 4, 5, 6),
                participant_count=5,
                member_band_min_index=3,
                member_band_max_index=4,
                price_band_index=3,
                price_min=20_001,
                price_max=30_000,
            ),
        ),
    )

    result = build_board_assignment_plan(
        batch,
        demands,
        (board(),),
        planned_at=NOW,
        rule_version="board-formation-v1",
        min_participants=5,
    )

    assert result["existingBoardAssignments"][0]["demandIds"] == [1]
    assert result["newBoards"][0]["demandIds"] == [2, 3, 4, 5, 6]
    assert "stateContract" not in result
    assert "saleEndAt" not in result["newBoards"][0]
    validate_board_assignment_plan_contract(result)

    schema_path = Path("docs/contracts/demand_board_assignment_plan_v01.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)


def test_posts_formation_plan_and_validates_backend_result() -> None:
    captured: dict[str, object] = {}

    def http_post(url: str, **kwargs: object) -> FormationResponse:
        captured["url"] = url
        captured.update(kwargs)
        return FormationResponse()

    result = post_board_assignment_plan(
        "http://backend:8080/",
        "secret",
        formation_plan(),
        http_post=http_post,
    )

    assert captured["url"] == "http://backend:8080" + BOARD_PLAN_ENDPOINT_PROPOSAL
    assert captured["headers"]["X-Internal-Key"] == "secret"
    assert "Authorization" not in captured["headers"]
    assert captured["json"] == formation_plan()
    assert result.status == "APPLIED"
    assert result.existing_applied_demand_count == 1
    assert result.new_boards[0].demand_board_id == 9001


def test_formation_endpoint_can_be_injected_after_backend_negotiation() -> None:
    captured: dict[str, object] = {}

    def http_post(url: str, **kwargs: object) -> FormationResponse:
        captured["url"] = url
        return FormationResponse()

    post_board_assignment_plan(
        "http://backend:8080",
        "secret",
        formation_plan(),
        endpoint="/negotiated/formation-plans",
        http_post=http_post,
    )

    assert captured["url"] == "http://backend:8080/negotiated/formation-plans"


def test_rejects_formation_response_with_wrong_existing_counts() -> None:
    class InvalidFormationResponse(FormationResponse):
        def json(self) -> dict[str, object]:
            payload = super().json()
            payload["existingAssignments"]["appliedCount"] = 0
            return payload

    with pytest.raises(ValueError, match="counts do not add up"):
        post_board_assignment_plan(
            "http://backend:8080",
            "secret",
            formation_plan(),
            http_post=lambda *args, **kwargs: InvalidFormationResponse(),
        )


def test_rejects_same_demand_in_existing_and_new_assignment() -> None:
    plan = {
        "schemaVersion": "demand-board-assignment-plan.v0.1",
        "plannedAt": NOW.isoformat(),
        "ruleVersion": "rules-v1",
        "existingBoardAssignments": [{
            "demandBoardId": 31,
            "demandIds": [1],
        }],
        "newBoards": [{
            "clientBoardKey": "batch-1:new-board:1",
            "catalogId": 202,
            "priceMin": 20_001,
            "priceMax": 30_000,
            "demandIds": [1, 2, 3, 4, 5],
        }],
    }

    with pytest.raises(ValueError, match="duplicate demandId"):
        validate_board_assignment_plan_contract(plan)


def test_rejects_new_board_below_minimum_participants() -> None:
    plan = DemandClusteringBatchPlan(
        existing_board_assignments=(),
        new_board_plans=(
            NewDemandBoardPlan(
                catalog_id=202,
                demand_ids=(1,),
                participant_count=1,
                member_band_min_index=3,
                member_band_max_index=3,
                price_band_index=3,
                price_min=20_001,
                price_max=30_000,
            ),
        ),
    )

    with pytest.raises(ValueError, match="fewer than minParticipants"):
        build_board_assignment_plan(
            plan,
            (demand(1, 202, 20_001, 30_000),),
            (),
            planned_at=NOW,
            rule_version="rules-v1",
            min_participants=5,
        )


def test_contract_rejects_new_board_below_five_demands() -> None:
    invalid = formation_plan()
    invalid["newBoards"][0]["demandIds"] = [2, 3, 4, 5]

    with pytest.raises(ValueError, match="at least 5"):
        validate_board_assignment_plan_contract(invalid)


def test_builds_new_board_requests_from_hourly_simulation() -> None:
    simulation = {
        "schemaVersion": "part-c-demand-board-hourly-simulation.v0.4",
        "simulationPolicy": {"minParticipants": 5},
        "summary": {"directAssignedDemandCount": 5},
        "batchTimeline": [{
            "batchId": "hourly-1",
            "plannedAt": "2026-09-06T12:00:00+09:00",
            "existingBoardAssignedCount": 0,
            "newBoardIds": [1001],
            "newBoardAssignedCount": 5,
        }],
        "demandBoards": [{
            "demandBoardId": 1001,
            "catalogId": 101,
            "priceMin": 10_001,
            "priceMax": 20_000,
            "createdAt": "2026-09-06T12:00:00+09:00",
            "saleEndAt": "2026-09-11T12:00:00+09:00",
            "directDemandIds": [1, 2, 3, 4, 5],
        }],
        "substituteAdmissionPlan": {"ruleVersion": "rules-v1"},
    }

    bundle = build_board_plan_request_bundle_from_simulation(simulation)

    assert bundle["requestCount"] == 1
    assert bundle["newBoardCount"] == 1
    assert bundle["directAssignedDemandCount"] == 5
    assert bundle["simulationBoardMapping"] == [{
        "simulationDemandBoardId": 1001,
        "batchId": "hourly-1",
        "clientBoardKey": "new-board:1",
    }]
    validate_board_assignment_plan_contract(bundle["requests"][0])


def test_formation_response_allows_additional_backend_metadata() -> None:
    class ExtendedFormationResponse(FormationResponse):
        def json(self) -> dict[str, object]:
            payload = super().json()
            payload["processedAt"] = NOW.isoformat()
            payload["existingAssignments"]["diagnostic"] = "optional"
            payload["newBoards"][0]["diagnostic"] = "optional"
            return payload

    result = post_board_assignment_plan(
        "http://backend:8080",
        "secret",
        formation_plan(),
        http_post=lambda *args, **kwargs: ExtendedFormationResponse(),
    )

    assert result.new_boards[0].demand_board_id == 9001
