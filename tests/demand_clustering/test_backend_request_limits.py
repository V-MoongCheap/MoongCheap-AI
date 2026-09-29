"""Offline wire-limit, aggregation and partial-failure regression checks."""

import json
from copy import deepcopy
from functools import partial
from pathlib import Path

import pytest
import requests
from jsonschema import Draft202012Validator, ValidationError

from moongcheap_ai.demand_clustering import backend_board_plan, backend_plan_client
from moongcheap_ai.demand_clustering.backend_board_plan import (
    post_board_assignment_plan,
)
from moongcheap_ai.demand_clustering.backend_plan_client import (
    post_substitute_board_admission_plan,
)
from moongcheap_ai.demand_clustering.batch_execution import (
    execute_demand_clustering_batch,
)
from moongcheap_ai.demand_clustering.evaluation.backend_requests import (
    build_backend_plan_request_bundle,
    build_board_plan_request_bundle_from_simulation,
)
from moongcheap_ai.demand_clustering.postgres_reader import ClusteringInputBatch

from .test_batch_execution import NOW, TwoReadInputReader, board, demand


def formation_plan(existing_count=0, new_count=0):
    return {
        "schemaVersion": backend_board_plan.BOARD_PLAN_SCHEMA_VERSION,
        "plannedAt": NOW.isoformat(),
        "ruleVersion": "board-formation-v1",
        "existingBoardAssignments": [
            {"demandBoardId": i + 1, "demandIds": [i + 1]}
            for i in range(existing_count)
        ],
        "newBoards": [
            {
                "clientBoardKey": f"new-board:{i + 1}",
                "catalogId": i + 1000,
                "priceMin": 10001,
                "priceMax": 20000,
                "demandIds": list(range(10000 + i * 5, 10005 + i * 5)),
            }
            for i in range(new_count)
        ],
    }


def substitute_plan(count=0):
    return {
        "schemaVersion": backend_plan_client.PLAN_SCHEMA_VERSION,
        "plannedAt": NOW.isoformat(),
        "ruleVersion": "substitute-admission-v2",
        "proposals": [
            {
                "demandId": i + 1,
                "expectedOriginalCatalogId": 1,
                "substituteCatalogId": 2,
                "demandBoardId": 31,
            }
            for i in range(count)
        ],
    }


class Response:
    ok = True
    status_code = 200
    text = ""

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def response_payload(request):
    if "proposals" in request:
        ids = [row["demandId"] for row in request["proposals"]]
        return {
            "status": "APPLIED",
            "appliedCount": sum(i % 3 == 0 for i in ids),
            "alreadyAppliedCount": sum(i % 3 == 1 for i in ids),
            "staleRejectedCount": sum(i % 3 == 2 for i in ids),
        }
    existing = request["existingBoardAssignments"]
    return {
        "status": "APPLIED",
        "existingAssignments": {
            "appliedCount": sum(
                len(row["demandIds"]) for row in existing if row["demandBoardId"] % 2
            ),
            "staleCount": sum(
                len(row["demandIds"])
                for row in existing
                if not row["demandBoardId"] % 2
            ),
        },
        # A valid Backend response need not follow request order.
        "newBoards": [
            {
                "clientBoardKey": row["clientBoardKey"],
                "demandBoardId": row["catalogId"] + 50000
                if row["catalogId"] % 3
                else None,
                "status": "CREATED" if row["catalogId"] % 3 else "STALE_REJECTED",
            }
            for row in reversed(request["newBoards"])
        ],
    }


def post_for(kind):
    return (
        post_board_assignment_plan
        if kind == "formation"
        else post_substitute_board_admission_plan
    )


def assert_wire_schema(kind, request):
    filename = (
        "demand_board_assignment_plan_v01.schema.json"
        if kind == "formation"
        else "substitute_offer_plan_v01.schema.json"
    )
    schema = json.loads((Path("docs/contracts") / filename).read_text())
    Draft202012Validator(schema).validate(request)


@pytest.mark.parametrize(
    "existing_count,new_count",
    [
        (0, 0),
        (1, 1),
        (49, 49),
        (50, 50),
        (51, 51),
        (112, 3),
        (3, 112),
        (0, 51),
        (51, 0),
        (100, 101),
    ],
)
def test_formation_limits_each_array_without_losing_metadata_or_board_keys(
    existing_count, new_count
):
    plan = formation_plan(existing_count, new_count)
    original = deepcopy(plan)
    calls = []

    def http_post(url, **kwargs):
        assert url == "https://backend.example/custom-formation"
        assert kwargs["timeout"] == 7
        assert kwargs["headers"]["X-Internal-Api-Key"] == "test-key"
        assert kwargs["allow_redirects"] is False
        request = kwargs["json"]
        assert_wire_schema("formation", request)
        calls.append(deepcopy(request))
        return Response(response_payload(request))

    result = post_board_assignment_plan(
        "https://backend.example",
        "test-key",
        plan,
        endpoint="/custom-formation",
        timeout_seconds=7,
        http_post=http_post,
    )

    assert len(calls) == max(1, (existing_count + 49) // 50, (new_count + 49) // 50)
    for field in ("existingBoardAssignments", "newBoards"):
        assert [row for request in calls for row in request[field]] == plan[field]
    assert all(
        request[key] == plan[key]
        for request in calls
        for key in ("schemaVersion", "plannedAt", "ruleVersion")
    )
    assert plan == original
    expected = response_payload(plan)
    assert result.status == "APPLIED"
    assert (
        result.existing_applied_demand_count
        == expected["existingAssignments"]["appliedCount"]
    )
    assert (
        result.existing_stale_rejected_count
        == expected["existingAssignments"]["staleCount"]
    )
    assert {
        row.client_board_key: (row.demand_board_id, row.status)
        for row in result.new_boards
    } == {
        row["clientBoardKey"]: (row["demandBoardId"], row["status"])
        for row in expected["newBoards"]
    }


def test_formation_limit_counts_board_objects_not_nested_demand_ids():
    plan = formation_plan(1, 1)
    plan["existingBoardAssignments"][0]["demandIds"] = list(range(1, 62))
    plan["newBoards"][0]["demandIds"] = list(range(100, 161))
    calls = []

    def http_post(url, **kwargs):
        calls.append(kwargs["json"])
        assert_wire_schema("formation", kwargs["json"])
        return Response(response_payload(kwargs["json"]))

    post_board_assignment_plan(
        "https://backend.example", "test-key", plan, http_post=http_post
    )
    assert calls == [plan]


@pytest.mark.parametrize("count", [0, 1, 49, 50, 51, 100, 101, 112])
def test_substitution_uses_announced_50_limit_and_sums_all_outcome_types(count):
    plan = substitute_plan(count)
    original = deepcopy(plan)
    calls = []

    def http_post(url, **kwargs):
        assert url == "https://backend.example/custom-substitution"
        assert kwargs["timeout"] == 9
        assert kwargs["headers"]["X-Internal-Api-Key"] == "test-key"
        assert kwargs["allow_redirects"] is False
        request = kwargs["json"]
        assert_wire_schema("substitution", request)
        calls.append(deepcopy(request))
        return Response(response_payload(request))

    result = post_substitute_board_admission_plan(
        "https://backend.example",
        "test-key",
        plan,
        endpoint="/custom-substitution",
        timeout_seconds=9,
        http_post=http_post,
    )
    assert len(calls) == max(1, (count + 49) // 50)
    assert [row for request in calls for row in request["proposals"]] == plan[
        "proposals"
    ]
    assert all(
        request[key] == plan[key]
        for request in calls
        for key in ("schemaVersion", "plannedAt", "ruleVersion")
    )
    expected = response_payload(plan)
    assert result.status == "APPLIED"
    assert result.applied_count == expected["appliedCount"]
    assert result.already_applied_count == expected["alreadyAppliedCount"]
    assert result.stale_rejected_count == expected["staleRejectedCount"]
    assert plan == original


@pytest.mark.parametrize(
    "field", ["existingBoardAssignments", "newBoards", "proposals"]
)
def test_wire_schemas_reject_51_top_level_objects(field):
    kind = "substitution" if field == "proposals" else "formation"
    plan = (
        substitute_plan(51)
        if kind == "substitution"
        else formation_plan(
            51 if field == "existingBoardAssignments" else 0,
            51 if field == "newBoards" else 0,
        )
    )
    with pytest.raises(ValidationError, match="too long"):
        assert_wire_schema(kind, plan)


@pytest.mark.parametrize(
    "case",
    [
        "existing_demand",
        "board_id",
        "client_key",
        "new_demand",
        "invalid_price",
        "proposal",
    ],
)
def test_entire_plan_is_validated_before_any_chunk_is_sent(case):
    plan = formation_plan(51, 51)
    kind = "formation"
    if case == "existing_demand":
        plan["existingBoardAssignments"][-1]["demandIds"] = [1]
    elif case == "board_id":
        plan["existingBoardAssignments"][-1]["demandBoardId"] = 1
    elif case == "client_key":
        plan["newBoards"][-1]["clientBoardKey"] = "new-board:1"
    elif case == "new_demand":
        plan["newBoards"][-1]["demandIds"][0] = 1
    elif case == "invalid_price":
        plan["newBoards"][-1]["priceMax"] = -1
    else:
        kind = "substitution"
        plan = substitute_plan(51)
        plan["proposals"][-1]["demandId"] = 1

    def must_not_post(*args, **kwargs):
        pytest.fail("invalid later chunks must prevent the first HTTP mutation")

    with pytest.raises(ValueError):
        post_for(kind)(
            "https://backend.example", "test-key", plan, http_post=must_not_post
        )


@pytest.mark.parametrize("kind", ["formation", "substitution"])
@pytest.mark.parametrize(
    "failure", ["timeout", "http_error", "redirect", "json", "counts"]
)
def test_second_chunk_failure_stops_without_retry_or_sending_third_chunk(kind, failure):
    plan = formation_plan(101, 101) if kind == "formation" else substitute_plan(101)
    calls = []

    def http_post(url, **kwargs):
        calls.append(deepcopy(kwargs["json"]))
        payload = response_payload(kwargs["json"])
        if len(calls) == 2:
            if failure == "timeout":
                raise requests.Timeout("lost response")
            if failure == "json":
                return Response([])
            if failure == "counts":
                if kind == "formation":
                    payload["existingAssignments"]["appliedCount"] += 1
                else:
                    payload["appliedCount"] += 1
            else:
                response = Response(payload)
                response.status_code = 500 if failure == "http_error" else 307
                response.ok = failure == "redirect"
                return response
        return Response(payload)

    with pytest.raises((requests.Timeout, RuntimeError, ValueError)):
        post_for(kind)("https://backend.example", "test-key", plan, http_post=http_post)
    assert len(calls) == 2


def test_formation_response_cannot_return_a_key_from_a_different_chunk():
    calls = []

    def http_post(url, **kwargs):
        calls.append(kwargs["json"])
        payload = response_payload(kwargs["json"])
        if len(calls) == 2:
            payload["newBoards"][0]["clientBoardKey"] = "new-board:1"
        return Response(payload)

    with pytest.raises(ValueError, match="unknown or duplicate"):
        post_board_assignment_plan(
            "https://backend.example",
            "test-key",
            formation_plan(0, 101),
            http_post=http_post,
        )
    assert len(calls) == 2


def test_limits_are_independent_named_settings(monkeypatch):
    monkeypatch.setattr(backend_board_plan, "MAX_EXISTING_BOARD_ASSIGNMENTS", 2)
    monkeypatch.setattr(backend_board_plan, "MAX_NEW_BOARDS", 3)
    monkeypatch.setattr(backend_plan_client, "MAX_SUBSTITUTE_PROPOSALS", 4)
    requests_to_send = list(
        backend_board_plan.iter_board_assignment_requests(formation_plan(5, 8))
    )
    assert [
        (len(row["existingBoardAssignments"]), len(row["newBoards"]))
        for row in requests_to_send
    ] == [
        (2, 3),
        (2, 3),
        (1, 2),
    ]
    assert [
        len(row["proposals"])
        for row in backend_plan_client.iter_substitute_offer_requests(
            substitute_plan(9)
        )
    ] == [4, 4, 1]


def test_offline_substitution_bundle_obeys_the_same_wire_limit():
    proposals = [
        {
            "demandId": i + 1,
            "originalCatalogId": 1,
            "substituteCatalogId": 2,
            "demandBoardId": 31,
            "batchId": "hourly-1",
            "offeredAt": NOW.isoformat(),
        }
        for i in range(112)
    ]
    bundle = build_backend_plan_request_bundle(
        {
            "schemaVersion": "part-c-demand-board-hourly-simulation.v0.4",
            "batchTimeline": [{"batchId": "hourly-1", "plannedAt": NOW.isoformat()}],
            "substituteAdmissionPlan": {
                "schemaVersion": "substitute-board-admission-plan.v0.1",
                "ruleVersion": "substitute-admission-v2",
                "proposals": proposals,
            },
        }
    )
    assert bundle["requestCount"] == 3
    assert bundle["proposalCount"] == 112
    assert [len(row["proposals"]) for row in bundle["requests"]] == [50, 50, 12]
    for request in bundle["requests"]:
        assert_wire_schema("substitution", request)


def test_offline_formation_bundle_keeps_global_client_keys_when_split():
    plan = formation_plan(0, 51)
    boards = [
        {
            "demandBoardId": i + 1,
            "catalogId": row["catalogId"],
            "priceMin": row["priceMin"],
            "priceMax": row["priceMax"],
            "createdAt": NOW.isoformat(),
            "directDemandIds": row["demandIds"],
        }
        for i, row in enumerate(plan["newBoards"])
    ]
    bundle = build_board_plan_request_bundle_from_simulation(
        {
            "schemaVersion": "part-c-demand-board-hourly-simulation.v0.4",
            "simulationPolicy": {"minParticipants": 5},
            "summary": {"directAssignedDemandCount": 255},
            "batchTimeline": [
                {
                    "batchId": "hourly-1",
                    "plannedAt": NOW.isoformat(),
                    "existingBoardAssignedCount": 0,
                    "newBoardIds": list(range(1, 52)),
                    "newBoardAssignedCount": 255,
                }
            ],
            "demandBoards": boards,
            "substituteAdmissionPlan": {"ruleVersion": "rules-v1"},
        }
    )
    assert bundle["requestCount"] == 2
    assert bundle["newBoardCount"] == 51
    assert bundle["directAssignedDemandCount"] == 255
    assert [len(row["newBoards"]) for row in bundle["requests"]] == [50, 1]
    assert [
        row["clientBoardKey"]
        for request in bundle["requests"]
        for row in request["newBoards"]
    ] == [row["clientBoardKey"] for row in bundle["simulationBoardMapping"]]
    for request in bundle["requests"]:
        assert_wire_schema("formation", request)


@pytest.mark.parametrize("failure_stage", [None, "formation", "substitution"])
def test_batch_finishes_all_formation_chunks_before_refresh_and_substitution(
    failure_stage,
):
    calls = []
    existing_boards = tuple(board(100 + i, 1000 + i, 10001, 20000) for i in range(51))
    existing_demands = tuple(demand(i + 1, 1000 + i, 10001, 20000) for i in range(51))
    new_demands = tuple(
        demand(1000 + i * 5 + j, 2000 + i, 10001, 20000)
        for i in range(51)
        for j in range(5)
    )
    leftovers = tuple(demand(10000 + i, 50000 + i, 10001, 20000) for i in range(112))
    created_boards = tuple(board(9001 + i, 2000 + i, 10001, 20000) for i in range(51))
    reader = TwoReadInputReader(
        ClusteringInputBatch(
            existing_demands + new_demands + leftovers, existing_boards
        ),
        ClusteringInputBatch(leftovers, existing_boards + created_boards),
        calls,
    )

    def http_post(url, **kwargs):
        stage = "formation" if url.endswith("formation-plans") else "substitution"
        calls.append(stage)
        if failure_stage == stage and calls.count(stage) == 2:
            response = Response({})
            response.ok = False
            response.status_code = 500
            return response
        request = kwargs["json"]
        assert_wire_schema(stage, request)
        if stage == "formation":
            return Response(
                {
                    "status": "APPLIED",
                    "existingAssignments": {
                        "appliedCount": sum(
                            len(row["demandIds"])
                            for row in request["existingBoardAssignments"]
                        ),
                        "staleCount": 0,
                    },
                    "newBoards": [
                        {
                            "clientBoardKey": row["clientBoardKey"],
                            "demandBoardId": row["catalogId"] + 7001,
                            "status": "CREATED",
                        }
                        for row in request["newBoards"]
                    ],
                }
            )
        return Response(
            {
                "status": "APPLIED",
                "appliedCount": len(request["proposals"]),
                "alreadyAppliedCount": 0,
                "staleRejectedCount": 0,
            }
        )

    def planner(inputs, *, as_of):
        calls.append("planner")
        assert as_of == NOW
        assert inputs.demands == leftovers
        return [
            {
                "demandId": row.id,
                "originalCatalogId": row.catalog_id,
                "substituteCatalogId": 2000,
                "demandBoardId": 9001,
            }
            for row in inputs.demands
        ]

    run = partial(
        execute_demand_clustering_batch,
        reader,
        planner,
        backend_base_url="https://backend.example",
        internal_key="test-key",
        planned_at=NOW,
        formation_rule_version="board-formation-v1",
        substitute_rule_version="substitute-admission-v2",
        formation_plan_poster=partial(post_board_assignment_plan, http_post=http_post),
        substitute_plan_poster=partial(
            post_substitute_board_admission_plan, http_post=http_post
        ),
    )
    if failure_stage:
        with pytest.raises(RuntimeError, match="HTTP 500"):
            run()
        expected = ["read", "formation", "formation"]
        if failure_stage == "substitution":
            expected += ["read", "planner", "substitution", "substitution"]
        assert calls == expected
    else:
        result = run()
        assert calls == [
            "read",
            "formation",
            "formation",
            "read",
            "planner",
            "substitution",
            "substitution",
            "substitution",
        ]
        assert result.formation_result.existing_applied_demand_count == 51
        assert len(result.formed_board_ids_by_client_key) == 51
        assert len(result.formation_attempted_demand_ids) == 306
        assert result.substitute_result.applied_count == 112
