"""Execute one read-only-planning / Backend-mutation clustering cycle."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .backend_board_plan import (
    BackendBoardPlanApplyResult,
    build_board_assignment_plan,
    post_board_assignment_plan,
)
from .backend_plan_client import (
    BackendPlanApplyResult,
    build_substitute_offer_plan_request,
    post_substitute_board_admission_plan,
)
from .batch_planner import plan_demand_clustering_batch
from .config import MIN_CLUSTER_PARTICIPANTS
from .postgres_reader import ClusteringInputBatch


class ClusteringInputReader(Protocol):
    """Read the current eligible demands and active boards without DML."""

    def read(self, *, as_of: datetime) -> ClusteringInputBatch: ...


class SubstituteProposalPlanner(Protocol):
    """Build rich AI proposal rows from a freshly read candidate batch."""

    def __call__(
        self,
        inputs: ClusteringInputBatch,
        *,
        as_of: datetime,
    ) -> Iterable[Mapping[str, Any]]: ...


FormationPlanPoster = Callable[..., BackendBoardPlanApplyResult]
SubstitutePlanPoster = Callable[..., BackendPlanApplyResult]
ClusteringInputValidator = Callable[[ClusteringInputBatch], None]
BatchEventHandler = Callable[[str, Mapping[str, Any]], None]


def _emit(
    handler: BatchEventHandler | None,
    event: str,
    **fields: Any,
) -> None:
    if handler is not None:
        handler(event, fields)


@dataclass(frozen=True, slots=True)
class DemandClusteringBatchExecutionResult:
    """Observable result of one ordered Backend integration cycle."""

    initial_demand_count: int
    formation_attempted_demand_ids: tuple[int, ...]
    refreshed_demand_count: int
    substitute_candidate_demand_ids: tuple[int, ...]
    formed_board_ids_by_client_key: Mapping[str, int]
    formation_request: Mapping[str, Any]
    formation_result: BackendBoardPlanApplyResult
    substitute_request: Mapping[str, Any]
    substitute_result: BackendPlanApplyResult


def _formation_attempted_demand_ids(
    request: Mapping[str, Any],
) -> frozenset[int]:
    demand_ids = {
        int(demand_id)
        for assignment in request["existingBoardAssignments"]
        for demand_id in assignment["demandIds"]
    }
    demand_ids.update(
        int(demand_id)
        for board in request["newBoards"]
        for demand_id in board["demandIds"]
    )
    return frozenset(demand_ids)


def _formed_board_mapping(
    result: BackendBoardPlanApplyResult,
) -> dict[str, int]:
    return {
        item.client_board_key: item.demand_board_id
        for item in result.new_boards
        if item.demand_board_id is not None
    }


def _validate_substitute_proposals(
    proposals: tuple[Mapping[str, Any], ...],
    inputs: ClusteringInputBatch,
) -> None:
    demand_by_id = {demand.id: demand for demand in inputs.demands}
    board_by_id = {board.id: board for board in inputs.boards}
    for index, proposal in enumerate(proposals):
        if not isinstance(proposal, Mapping):
            raise ValueError(f"substitute proposal {index} must be a mapping")
        demand_id = proposal.get("demandId")
        demand = demand_by_id.get(demand_id)
        if demand is None:
            raise ValueError(
                "substitute proposal references a demand outside the eligible "
                f"refreshed batch: {demand_id}"
            )
        if proposal.get("originalCatalogId") != demand.catalog_id:
            raise ValueError(
                f"substitute proposal original catalog mismatch: {demand_id}"
            )
        board_id = proposal.get("demandBoardId")
        board = board_by_id.get(board_id)
        if board is None:
            raise ValueError(
                f"substitute proposal references an inactive board: {board_id}"
            )
        if (demand_id, board_id) in inputs.rejected_demand_board_pairs:
            raise ValueError(
                "substitute proposal references a previously rejected board: "
                f"demand {demand_id}, board {board_id}"
            )
        if proposal.get("substituteCatalogId") != board.catalog_id:
            raise ValueError(f"substitute proposal board catalog mismatch: {board_id}")


def execute_demand_clustering_batch(
    input_reader: ClusteringInputReader,
    substitute_proposal_planner: SubstituteProposalPlanner,
    *,
    backend_base_url: str,
    internal_key: str,
    planned_at: datetime,
    formation_rule_version: str,
    substitute_rule_version: str,
    min_participants: int = MIN_CLUSTER_PARTICIPANTS,
    formation_plan_poster: FormationPlanPoster = post_board_assignment_plan,
    substitute_plan_poster: SubstitutePlanPoster = (
        post_substitute_board_admission_plan
    ),
    input_validator: ClusteringInputValidator | None = None,
    event_handler: BatchEventHandler | None = None,
) -> DemandClusteringBatchExecutionResult:
    """Read current state, run API 1 once, refresh, then run API 2 once.

    Failures stop this invocation. No request is persisted or retried: the next
    scheduled invocation starts with a fresh PostgreSQL snapshot and replans.

    Demands sent to API 1 are never reconsidered for a substitute offer in
    the same invocation, even when Backend reports them as stale. Demands that
    arrive between the first and second reads also wait for the next batch so
    that the original-catalog path always runs before substitution.
    """

    if planned_at.tzinfo is None or planned_at.utcoffset() is None:
        raise ValueError("planned_at must include timezone information")
    if min_participants < MIN_CLUSTER_PARTICIPANTS:
        raise ValueError(
            f"min_participants must be at least {MIN_CLUSTER_PARTICIPANTS}"
        )

    initial = input_reader.read(as_of=planned_at)
    if input_validator is not None:
        input_validator(initial)
    _emit(
        event_handler,
        "INPUT_LOADED",
        demandCount=len(initial.demands),
        boardCount=len(initial.boards),
    )
    clustering_plan = plan_demand_clustering_batch(
        initial.demands,
        initial.boards,
        as_of=planned_at,
        min_participants=min_participants,
    )
    formation_request = build_board_assignment_plan(
        clustering_plan,
        initial.demands,
        initial.boards,
        planned_at=planned_at,
        rule_version=formation_rule_version,
        min_participants=min_participants,
    )
    formation_attempted_ids = _formation_attempted_demand_ids(formation_request)
    _emit(
        event_handler,
        "FORMATION_PLANNED",
        attemptedDemandCount=len(formation_attempted_ids),
        existingBoardAssignmentCount=len(formation_request["existingBoardAssignments"]),
        newBoardCount=len(formation_request["newBoards"]),
    )
    formation_result = formation_plan_poster(
        backend_base_url,
        internal_key,
        formation_request,
    )
    _emit(
        event_handler,
        "FORMATION_APPLIED",
        status=formation_result.status,
        existingAppliedCount=formation_result.existing_applied_demand_count,
        existingStaleCount=formation_result.existing_stale_rejected_count,
        newBoardResultCount=len(formation_result.new_boards),
    )

    formed_board_mapping = _formed_board_mapping(formation_result)
    refreshed = input_reader.read(as_of=planned_at)
    _emit(
        event_handler,
        "INPUT_REFRESHED",
        demandCount=len(refreshed.demands),
        boardCount=len(refreshed.boards),
    )
    missing_formed_board_ids = set(formed_board_mapping.values()) - {
        board.id for board in refreshed.boards
    }
    if missing_formed_board_ids:
        raise RuntimeError(
            "Backend-created gathering boards are missing from the refreshed "
            f"PostgreSQL input: {sorted(missing_formed_board_ids)}"
        )

    initial_demand_ids = {demand.id for demand in initial.demands}
    substitute_inputs = ClusteringInputBatch(
        demands=tuple(
            demand
            for demand in refreshed.demands
            if (
                demand.id in initial_demand_ids
                and demand.id not in formation_attempted_ids
                and demand.is_substitutable is True
            )
        ),
        boards=refreshed.boards,
        rejected_demand_board_pairs=refreshed.rejected_demand_board_pairs,
    )
    if input_validator is not None:
        input_validator(substitute_inputs)
    rich_proposals = tuple(
        substitute_proposal_planner(substitute_inputs, as_of=planned_at)
    )
    _validate_substitute_proposals(rich_proposals, substitute_inputs)
    substitute_request = build_substitute_offer_plan_request(
        rich_proposals,
        planned_at=planned_at,
        rule_version=substitute_rule_version,
    )
    _emit(
        event_handler,
        "SUBSTITUTION_PLANNED",
        candidateDemandCount=len(substitute_inputs.demands),
        proposalCount=len(substitute_request["proposals"]),
    )
    substitute_result = substitute_plan_poster(
        backend_base_url,
        internal_key,
        substitute_request,
    )
    _emit(
        event_handler,
        "SUBSTITUTION_APPLIED",
        status=substitute_result.status,
        appliedCount=substitute_result.applied_count,
        alreadyAppliedCount=substitute_result.already_applied_count,
        staleRejectedCount=substitute_result.stale_rejected_count,
    )

    return DemandClusteringBatchExecutionResult(
        initial_demand_count=len(initial.demands),
        formation_attempted_demand_ids=tuple(sorted(formation_attempted_ids)),
        refreshed_demand_count=len(refreshed.demands),
        substitute_candidate_demand_ids=tuple(
            demand.id for demand in substitute_inputs.demands
        ),
        formed_board_ids_by_client_key=formed_board_mapping,
        formation_request=formation_request,
        formation_result=formation_result,
        substitute_request=substitute_request,
        substitute_result=substitute_result,
    )
