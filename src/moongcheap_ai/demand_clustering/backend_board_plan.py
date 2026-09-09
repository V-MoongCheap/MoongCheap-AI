"""Contract builder for Backend-owned direct board creation and assignment."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

import requests

from .backend_http import (
    aware_datetime as _aware_datetime,
    exact_fields as _exact_fields,
    nonnegative_int as _nonnegative_int,
    nonnegative_int as _price,
    positive_int as _positive_int,
    post_plan_json,
    required_fields as _required_fields,
)
from .batch_planner import DemandClusteringBatchPlan
from .config import MIN_CLUSTER_PARTICIPANTS
from .input_models import DemandBoardInput, DemandInput


BOARD_PLAN_SCHEMA_VERSION = "demand-board-assignment-plan.v0.1"
BOARD_PLAN_ENDPOINT_PROPOSAL = (
    "/api/demand-boards/internal/formation-plans"
)
PLAN_FIELDS = {
    "schemaVersion",
    "plannedAt",
    "ruleVersion",
    "existingBoardAssignments",
    "newBoards",
}
EXISTING_ASSIGNMENT_FIELDS = {
    "demandBoardId",
    "demandIds",
}
NEW_BOARD_FIELDS = {
    "clientBoardKey",
    "catalogId",
    "priceMin",
    "priceMax",
    "demandIds",
}


@dataclass(frozen=True, slots=True)
class FormedDemandBoardResult:
    client_board_key: str
    demand_board_id: int | None
    status: str


@dataclass(frozen=True, slots=True)
class BackendBoardPlanApplyResult:
    status: str
    existing_applied_demand_count: int
    existing_stale_rejected_count: int
    new_boards: tuple[FormedDemandBoardResult, ...]


def _demand_ids(value: object, context: str) -> list[int]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{context} must be a nonempty array")
    result = [_positive_int(item, context) for item in value]
    if len(result) != len(set(result)):
        raise ValueError(f"{context} contains duplicate demand IDs")
    return result


def validate_board_assignment_plan_contract(plan: Mapping[str, Any]) -> None:
    """Validate the minimal Backend mutation request without doing DML."""

    _exact_fields(plan, PLAN_FIELDS, "plan")
    if plan.get("schemaVersion") != BOARD_PLAN_SCHEMA_VERSION:
        raise ValueError("unsupported demand board assignment plan schema")
    rule_version = plan["ruleVersion"]
    if (
        not isinstance(rule_version, str)
        or not rule_version.strip()
        or len(rule_version) > 200
    ):
        raise ValueError("ruleVersion must be a nonempty string of at most 200 characters")
    _aware_datetime(plan["plannedAt"], "plannedAt")
    if not isinstance(plan["existingBoardAssignments"], list):
        raise ValueError("existingBoardAssignments must be an array")
    if not isinstance(plan["newBoards"], list):
        raise ValueError("newBoards must be an array")

    seen_demand_ids: set[int] = set()
    seen_board_ids: set[int] = set()
    for index, assignment in enumerate(plan["existingBoardAssignments"]):
        context = f"existingBoardAssignments[{index}]"
        if not isinstance(assignment, Mapping):
            raise ValueError(f"{context} must be a JSON object")
        _exact_fields(assignment, EXISTING_ASSIGNMENT_FIELDS, context)
        board_id = _positive_int(
            assignment["demandBoardId"], f"{context}.demandBoardId"
        )
        if board_id in seen_board_ids:
            raise ValueError(f"duplicate demandBoardId: {board_id}")
        seen_board_ids.add(board_id)
        demand_ids = _demand_ids(assignment["demandIds"], f"{context}.demandIds")
        for demand_id in demand_ids:
            if demand_id in seen_demand_ids:
                raise ValueError(f"duplicate demandId: {demand_id}")
            seen_demand_ids.add(demand_id)

    seen_client_keys: set[str] = set()
    for index, board in enumerate(plan["newBoards"]):
        context = f"newBoards[{index}]"
        if not isinstance(board, Mapping):
            raise ValueError(f"{context} must be a JSON object")
        _exact_fields(board, NEW_BOARD_FIELDS, context)
        client_key = board["clientBoardKey"]
        if (
            not isinstance(client_key, str)
            or not client_key.strip()
            or len(client_key) > 160
            or client_key in seen_client_keys
        ):
            raise ValueError(f"{context}.clientBoardKey is invalid or duplicate")
        seen_client_keys.add(client_key)
        _positive_int(board["catalogId"], f"{context}.catalogId")
        price_min = _price(board["priceMin"], f"{context}.priceMin")
        price_max = _price(board["priceMax"], f"{context}.priceMax")
        if price_min > price_max:
            raise ValueError(f"{context} price range is invalid")
        demand_ids = _demand_ids(board["demandIds"], f"{context}.demandIds")
        if len(demand_ids) < MIN_CLUSTER_PARTICIPANTS:
            raise ValueError(
                f"{context}.demandIds must contain at least "
                f"{MIN_CLUSTER_PARTICIPANTS} demand IDs"
            )
        for demand_id in demand_ids:
            if demand_id in seen_demand_ids:
                raise ValueError(f"duplicate demandId: {demand_id}")
            seen_demand_ids.add(demand_id)


def build_board_assignment_plan(
    batch_plan: DemandClusteringBatchPlan,
    demands: Iterable[DemandInput],
    boards: Iterable[DemandBoardInput],
    *,
    planned_at: datetime,
    rule_version: str,
    min_participants: int,
) -> dict[str, Any]:
    """Translate clustering decisions into the minimal Backend mutation DTO."""

    if planned_at.tzinfo is None or planned_at.utcoffset() is None:
        raise ValueError("planned_at must include timezone information")
    _positive_int(min_participants, "min_participants")
    demand_rows = tuple(demands)
    board_rows = tuple(boards)
    demand_by_id = {row.id: row for row in demand_rows}
    board_by_id = {row.id: row for row in board_rows}
    if len(demand_by_id) != len(demand_rows):
        raise ValueError("demands contain duplicate IDs")
    if len(board_by_id) != len(board_rows):
        raise ValueError("boards contain duplicate IDs")

    existing_assignments = []
    for assignment in batch_plan.existing_board_assignments:
        board = board_by_id.get(assignment.demand_board_id)
        if board is None:
            raise ValueError(f"unknown demand board: {assignment.demand_board_id}")
        if board.price_min is None or board.price_max is None:
            raise ValueError("existing assignment board price must be resolved")
        for demand_id in assignment.demand_ids:
            demand = demand_by_id.get(demand_id)
            if demand is None:
                raise ValueError(f"unknown demand: {demand_id}")
            if demand.catalog_id != board.catalog_id:
                raise ValueError("existing assignment catalog mismatch")
            if (
                demand.desired_price_min != board.price_min
                or demand.desired_price_max != board.price_max
            ):
                raise ValueError("existing assignment price range mismatch")
        existing_assignments.append({
            "demandBoardId": board.id,
            "demandIds": list(assignment.demand_ids),
        })

    new_boards = []
    for index, board_plan in enumerate(batch_plan.new_board_plans, start=1):
        if len(board_plan.demand_ids) < min_participants:
            raise ValueError("new board has fewer than minParticipants")
        for demand_id in board_plan.demand_ids:
            demand = demand_by_id.get(demand_id)
            if demand is None:
                raise ValueError(f"unknown demand: {demand_id}")
            if demand.catalog_id != board_plan.catalog_id:
                raise ValueError("new board catalog mismatch")
        new_boards.append({
            "clientBoardKey": f"new-board:{index}",
            "catalogId": board_plan.catalog_id,
            "priceMin": board_plan.price_min,
            "priceMax": board_plan.price_max,
            "demandIds": list(board_plan.demand_ids),
        })

    result = {
        "schemaVersion": BOARD_PLAN_SCHEMA_VERSION,
        "plannedAt": planned_at.isoformat(),
        "ruleVersion": rule_version,
        "existingBoardAssignments": existing_assignments,
        "newBoards": new_boards,
    }
    validate_board_assignment_plan_contract(result)
    return result


def post_board_assignment_plan(
    backend_base_url: str,
    internal_key: str,
    plan: Mapping[str, Any],
    *,
    endpoint: str = BOARD_PLAN_ENDPOINT_PROPOSAL,
    timeout_seconds: int = 15,
    http_post: Callable[..., Any] = requests.post,
) -> BackendBoardPlanApplyResult:
    """Submit one formation plan and validate the current application result.

    ``endpoint`` defaults to the agreed internal formation route.
    This client never writes to PostgreSQL directly.
    """

    validate_board_assignment_plan_contract(plan)
    payload = post_plan_json(
        backend_base_url,
        internal_key,
        plan,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        http_post=http_post,
        context="Backend demand-board formation plan apply",
    )
    _required_fields(
        payload,
        {"status", "existingAssignments", "newBoards"},
        "Backend formation response",
    )
    status = payload.get("status")
    if status != "APPLIED":
        raise ValueError(f"unknown Backend formation status: {status}")

    existing = payload.get("existingAssignments")
    if not isinstance(existing, Mapping):
        raise ValueError("Backend existingAssignments must be a JSON object")
    _required_fields(
        existing,
        {"appliedCount", "staleCount"},
        "Backend existingAssignments",
    )
    existing_applied = _nonnegative_int(
        existing.get("appliedCount"),
        "Backend existingAssignments.appliedCount",
    )
    existing_stale = _nonnegative_int(
        existing.get("staleCount"),
        "Backend existingAssignments.staleCount",
    )
    expected_existing_planned = sum(
        len(item["demandIds"])
        for item in plan["existingBoardAssignments"]
    )
    if existing_applied + existing_stale != expected_existing_planned:
        raise ValueError("Backend existing assignment counts do not add up")

    raw_new_boards = payload.get("newBoards")
    if not isinstance(raw_new_boards, list):
        raise ValueError("Backend newBoards must be a JSON array")
    requested_new_boards = {
        item["clientBoardKey"]: item
        for item in plan["newBoards"]
    }
    formed_boards = []
    seen_client_keys: set[str] = set()
    for index, item in enumerate(raw_new_boards):
        context = f"Backend newBoards[{index}]"
        if not isinstance(item, Mapping):
            raise ValueError(f"{context} must be a JSON object")
        _required_fields(
            item,
            {"clientBoardKey", "demandBoardId", "status"},
            context,
        )
        client_board_key = item.get("clientBoardKey")
        if (
            not isinstance(client_board_key, str)
            or client_board_key not in requested_new_boards
            or client_board_key in seen_client_keys
        ):
            raise ValueError(f"{context}.clientBoardKey is unknown or duplicate")
        seen_client_keys.add(client_board_key)
        board_status = item.get("status")
        if board_status not in {"CREATED", "STALE_REJECTED"}:
            raise ValueError(f"{context}.status is invalid")
        raw_board_id = item.get("demandBoardId")
        if board_status == "STALE_REJECTED":
            if raw_board_id is not None:
                raise ValueError(
                    f"{context} stale rejection must not return a board ID"
                )
            board_id = None
        else:
            board_id = _positive_int(raw_board_id, f"{context}.demandBoardId")
        formed_boards.append(FormedDemandBoardResult(
            client_board_key=client_board_key,
            demand_board_id=board_id,
            status=board_status,
        ))
    if seen_client_keys != set(requested_new_boards):
        raise ValueError("Backend formation response is missing a planned new board")

    return BackendBoardPlanApplyResult(
        status=status,
        existing_applied_demand_count=existing_applied,
        existing_stale_rejected_count=existing_stale,
        new_boards=tuple(formed_boards),
    )
