"""Pure orchestration for one deterministic demand-clustering batch."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from .board_formation import NewDemandBoardPlan, plan_new_demand_boards
from .candidate_finder import select_clustering_board_candidate
from .input_models import DemandBoardInput, DemandInput


@dataclass(frozen=True, slots=True)
class ExistingBoardAssignmentPlan:
    """Demands to assign atomically to one already-gathering board."""

    demand_board_id: int
    demand_ids: tuple[int, ...]
    participant_count_delta: int


@dataclass(frozen=True, slots=True)
class DemandClusteringBatchPlan:
    """All persistence-neutral decisions made by one clustering batch."""

    existing_board_assignments: tuple[ExistingBoardAssignmentPlan, ...]
    new_board_plans: tuple[NewDemandBoardPlan, ...]


def _reject_duplicate_ids(
    rows: Iterable[DemandInput | DemandBoardInput],
    *,
    entity_name: str,
) -> None:
    seen_ids: set[int] = set()
    for row in rows:
        if row.id in seen_ids:
            raise ValueError(f"duplicate {entity_name} id: {row.id}")
        seen_ids.add(row.id)


def plan_demand_clustering_batch(
    demands: Iterable[DemandInput],
    boards: Iterable[DemandBoardInput],
    *,
    as_of: datetime,
    min_participants: int,
) -> DemandClusteringBatchPlan:
    """Plan existing-board assignments before forming any new boards.

    An eligible demand automatically joins only an active board with the same
    catalog and exact price band. Duplicate compatible boards violate the
    active-board uniqueness invariant and stop planning. Remaining demands
    enter the high-to-low sliding-window new-board planner.

    This function does not write to PostgreSQL or change demand state. The
    persistence adapter remains responsible for locks, guarded updates, and
    preventing duplicate active boards.
    """

    demand_rows = tuple(demands)
    board_rows = tuple(boards)
    _reject_duplicate_ids(demand_rows, entity_name="demand")
    _reject_duplicate_ids(board_rows, entity_name="demand board")

    demand_ids_by_existing_board: dict[int, list[int]] = defaultdict(list)
    demands_for_new_boards: list[DemandInput] = []

    for demand in sorted(demand_rows, key=lambda row: row.id):
        selected_board = select_clustering_board_candidate(
            demand,
            board_rows,
            as_of=as_of,
        )
        if selected_board is None:
            demands_for_new_boards.append(demand)
            continue

        demand_ids_by_existing_board[selected_board.id].append(demand.id)

    existing_board_assignments = tuple(
        ExistingBoardAssignmentPlan(
            demand_board_id=demand_board_id,
            demand_ids=tuple(demand_ids),
            participant_count_delta=len(demand_ids),
        )
        for demand_board_id, demand_ids in sorted(
            demand_ids_by_existing_board.items()
        )
    )
    new_board_plans = plan_new_demand_boards(
        demands_for_new_boards,
        as_of=as_of,
        min_participants=min_participants,
    )

    return DemandClusteringBatchPlan(
        existing_board_assignments=existing_board_assignments,
        new_board_plans=new_board_plans,
    )
