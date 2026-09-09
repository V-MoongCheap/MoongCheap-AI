"""Convert offline simulations into non-sending Backend request bundles.

Simulation batch IDs remain diagnostic metadata, never Backend DTO fields.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from ..backend_board_plan import (
    BOARD_PLAN_SCHEMA_VERSION,
    validate_board_assignment_plan_contract,
)
from ..backend_http import (
    aware_datetime as _aware_datetime,
    positive_int as _positive_int,
)
from ..backend_plan_client import build_substitute_offer_plan_request


SOURCE_PLAN_SCHEMA_VERSION = "substitute-board-admission-plan.v0.1"
BOARD_REQUEST_BUNDLE_SCHEMA_VERSION = (
    "demand-board-assignment-request-bundle.v0.1"
)
REQUEST_BUNDLE_SCHEMA_VERSION = (
    "substitute-offer-request-bundle.v0.1"
)


def build_board_plan_request_bundle_from_simulation(
    simulation: Mapping[str, Any],
) -> dict[str, Any]:
    """Build direct-assignment dry-run requests from a final simulation.

    The current 5,000-row simulation forms new boards but has no later direct
    joins to existing boards. Refuse simulations with such joins because the
    aggregate artifact does not retain their per-batch demand IDs.
    """

    timeline = simulation.get("batchTimeline")
    boards = simulation.get("demandBoards")
    policy = simulation.get("simulationPolicy")
    admission = simulation.get("substituteAdmissionPlan")
    if not isinstance(timeline, list) or not isinstance(boards, list):
        raise ValueError("simulation must contain batchTimeline and demandBoards")
    if not isinstance(policy, Mapping) or not isinstance(admission, Mapping):
        raise ValueError("simulation policy and admission plan are required")

    min_participants = _positive_int(
        policy.get("minParticipants"), "simulationPolicy.minParticipants"
    )
    rule_version = admission.get("ruleVersion")
    if not isinstance(rule_version, str) or not rule_version.strip():
        raise ValueError("simulation ruleVersion must not be empty")
    board_by_id: dict[int, Mapping[str, Any]] = {}
    for board in boards:
        if not isinstance(board, Mapping):
            raise ValueError("demandBoards rows must be JSON objects")
        board_id = _positive_int(board.get("demandBoardId"), "demandBoardId")
        if board_id in board_by_id:
            raise ValueError(f"duplicate simulated demandBoardId: {board_id}")
        board_by_id[board_id] = board

    requests_payload = []
    simulation_board_mapping = []
    seen_board_ids: set[int] = set()
    seen_direct_demand_ids: set[int] = set()
    for timeline_row in timeline:
        if not isinstance(timeline_row, Mapping):
            raise ValueError("batchTimeline rows must be JSON objects")
        if timeline_row.get("existingBoardAssignedCount") != 0:
            raise ValueError(
                "aggregate simulation cannot recover per-batch existing-board demand IDs"
            )
        new_board_ids = timeline_row.get("newBoardIds")
        if not isinstance(new_board_ids, list):
            raise ValueError("batchTimeline.newBoardIds must be an array")
        if timeline_row.get("newBoardCount") not in {None, len(new_board_ids)}:
            raise ValueError("new-board count differs from batch timeline")
        if not new_board_ids:
            continue
        batch_id = timeline_row.get("batchId")
        planned_at = timeline_row.get("plannedAt")
        if not isinstance(batch_id, str) or not batch_id:
            raise ValueError("batchTimeline.batchId must not be empty")
        planned_time = _aware_datetime(planned_at, f"{batch_id}.plannedAt")
        new_boards = []
        for index, raw_board_id in enumerate(new_board_ids, start=1):
            board_id = _positive_int(raw_board_id, f"{batch_id}.newBoardIds")
            if board_id in seen_board_ids:
                raise ValueError(f"simulated board appears in multiple batches: {board_id}")
            seen_board_ids.add(board_id)
            board = board_by_id.get(board_id)
            if board is None:
                raise ValueError(f"batch references unknown simulated board: {board_id}")
            if _aware_datetime(board.get("createdAt"), "board.createdAt") != planned_time:
                raise ValueError("simulated board createdAt does not match its batch")
            direct_ids = board.get("directDemandIds")
            if not isinstance(direct_ids, list):
                raise ValueError("board.directDemandIds must be an array")
            if board.get("participantCount") not in {None, len(direct_ids)}:
                raise ValueError("board participant count differs from direct demands")
            duplicate_direct_ids = seen_direct_demand_ids & set(direct_ids)
            if duplicate_direct_ids:
                raise ValueError(
                    "direct demands appear in multiple boards: "
                    f"{sorted(duplicate_direct_ids)}"
                )
            seen_direct_demand_ids.update(direct_ids)
            client_key = f"new-board:{index}"
            if len(direct_ids) < min_participants:
                raise ValueError(
                    "simulated new board has fewer than minParticipants"
                )
            new_boards.append({
                "clientBoardKey": client_key,
                "catalogId": board.get("catalogId"),
                "priceMin": board.get("priceMin"),
                "priceMax": board.get("priceMax"),
                "demandIds": direct_ids,
            })
            simulation_board_mapping.append({
                "simulationDemandBoardId": board_id,
                "batchId": batch_id,
                "clientBoardKey": client_key,
            })
        request = {
            "schemaVersion": BOARD_PLAN_SCHEMA_VERSION,
            "plannedAt": planned_time.isoformat(),
            "ruleVersion": rule_version,
            "existingBoardAssignments": [],
            "newBoards": new_boards,
        }
        validate_board_assignment_plan_contract(request)
        expected_count = timeline_row.get("newBoardAssignedCount")
        actual_count = sum(len(item["demandIds"]) for item in new_boards)
        if expected_count != actual_count:
            raise ValueError("new-board assigned count differs from batch timeline")
        requests_payload.append(request)

    if seen_board_ids != set(board_by_id):
        raise ValueError("not every simulated board is linked to a creation batch")
    direct_count = sum(
        len(board["directDemandIds"])
        for board in board_by_id.values()
    )
    summary = simulation.get("summary")
    if not isinstance(summary, Mapping):
        raise ValueError("simulation summary is required")
    if direct_count != summary.get("directAssignedDemandCount"):
        raise ValueError("direct assignment count differs from simulation summary")
    if len(board_by_id) != summary.get("demandBoardCount", len(board_by_id)):
        raise ValueError("board count differs from simulation summary")

    return {
        "schemaVersion": BOARD_REQUEST_BUNDLE_SCHEMA_VERSION,
        "sourceSimulationSchema": simulation.get("schemaVersion"),
        "requestCount": len(requests_payload),
        "newBoardCount": len(board_by_id),
        "directAssignedDemandCount": direct_count,
        "simulationBoardMapping": simulation_board_mapping,
        "requests": requests_payload,
    }


def build_backend_plan_request_bundle(
    simulation: Mapping[str, Any],
) -> dict[str, Any]:
    """Convert an aggregate simulation into one-shot hourly API requests.

    Aggregate final diagnostics have no mutation and cannot be attributed to a
    single hourly request, so they remain counts in the bundle manifest. Only
    actual substitute proposals are sent to the Backend.
    """

    admission = simulation.get("substituteAdmissionPlan")
    if not isinstance(admission, Mapping):
        raise ValueError("simulation must contain substituteAdmissionPlan")
    if admission.get("schemaVersion") != SOURCE_PLAN_SCHEMA_VERSION:
        raise ValueError("simulation admission plan schema is unsupported")
    timeline = simulation.get("batchTimeline")
    if not isinstance(timeline, list):
        raise ValueError("simulation must contain batchTimeline")

    planned_at_by_batch: dict[str, str] = {}
    for row in timeline:
        if not isinstance(row, Mapping):
            raise ValueError("batchTimeline rows must be JSON objects")
        batch_id = str(row.get("batchId", ""))
        if not batch_id or batch_id in planned_at_by_batch:
            raise ValueError("batchTimeline contains an invalid or duplicate batchId")
        planned_at = str(row.get("plannedAt", ""))
        _aware_datetime(planned_at, f"batchTimeline[{batch_id}].plannedAt")
        planned_at_by_batch[batch_id] = planned_at

    proposals_by_batch: dict[str, list[dict[str, Any]]] = defaultdict(list)
    proposals = admission.get("proposals")
    if not isinstance(proposals, list):
        raise ValueError("simulation proposals must be an array")
    for proposal in proposals:
        if not isinstance(proposal, Mapping):
            raise ValueError("simulation proposals must be JSON objects")
        batch_id = str(proposal.get("batchId", ""))
        if batch_id not in planned_at_by_batch:
            raise ValueError(f"proposal references unknown batchId: {batch_id}")
        offered_at = str(proposal.get("offeredAt", ""))
        if offered_at != planned_at_by_batch[batch_id]:
            raise ValueError("proposal offeredAt does not match its planned batch")
        proposals_by_batch[batch_id].append(dict(proposal))

    rule_version = admission.get("ruleVersion")
    if not isinstance(rule_version, str):
        raise ValueError("simulation ruleVersion must be a string")
    requests_payload = []
    for batch_id in sorted(
        proposals_by_batch,
        key=lambda value: _aware_datetime(planned_at_by_batch[value], "plannedAt"),
    ):
        request = build_substitute_offer_plan_request(
            proposals_by_batch[batch_id],
            planned_at=planned_at_by_batch[batch_id],
            rule_version=rule_version,
        )
        requests_payload.append(request)

    return {
        "schemaVersion": REQUEST_BUNDLE_SCHEMA_VERSION,
        "sourceSimulationSchema": simulation.get("schemaVersion"),
        "requestCount": len(requests_payload),
        "proposalCount": sum(len(row["proposals"]) for row in requests_payload),
        "diagnosticCounts": {
            "notEligible": len(admission.get("notEligible", [])),
            "unmatched": len(admission.get("unmatched", [])),
        },
        "requests": requests_payload,
    }
