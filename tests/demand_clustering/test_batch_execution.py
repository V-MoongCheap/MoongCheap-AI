from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from moongcheap_ai.demand_clustering.backend_board_plan import (
    BackendBoardPlanApplyResult,
    FormedDemandBoardResult,
)
from moongcheap_ai.demand_clustering.backend_plan_client import (
    BackendPlanApplyResult,
)
from moongcheap_ai.demand_clustering.batch_execution import (
    execute_demand_clustering_batch,
)
from moongcheap_ai.demand_clustering.input_models import (
    DemandBoardInput,
    DemandInput,
)
from moongcheap_ai.demand_clustering.postgres_reader import ClusteringInputBatch


NOW = datetime.fromisoformat("2026-09-07T12:00:00+09:00")


def demand(
    demand_id: int,
    catalog_id: int,
    price_min: int,
    price_max: int,
    *,
    substitutable: bool = True,
) -> DemandInput:
    return DemandInput(
        id=demand_id,
        catalog_id=catalog_id,
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW - timedelta(hours=1),
        desired_price_min=price_min,
        desired_price_max=price_max,
        quantity=1,
        is_substitutable=substitutable,
        status="UNASSIGNED",
        desire_end_at=NOW + timedelta(days=1),
    )


def board(
    board_id: int,
    catalog_id: int,
    price_min: int,
    price_max: int,
) -> DemandBoardInput:
    return DemandBoardInput(
        id=board_id,
        catalog_id=catalog_id,
        participant_count=5,
        price_min=price_min,
        price_max=price_max,
        status="GB_GATHERING",
        created_at=NOW - timedelta(hours=1),
        sale_end_at=NOW + timedelta(days=2),
    )


class TwoReadInputReader:
    def __init__(
        self,
        initial: ClusteringInputBatch,
        refreshed: ClusteringInputBatch,
        calls: list[str],
    ) -> None:
        self._batches = iter((initial, refreshed))
        self._calls = calls

    def read(self, *, as_of: datetime) -> ClusteringInputBatch:
        assert as_of == NOW
        self._calls.append("read")
        return next(self._batches)


def input_batches(*, include_created_board: bool = True) -> tuple[
    ClusteringInputBatch,
    ClusteringInputBatch,
]:
    initial_demands = (
        demand(1, 101, 10_001, 20_000),
        *(demand(item, 202, 20_001, 30_000) for item in range(2, 7)),
        demand(7, 303, 10_001, 20_000),
        demand(8, 404, 10_001, 20_000, substitutable=False),
    )
    initial_boards = (board(31, 101, 10_001, 20_000),)
    refreshed_boards = initial_boards
    if include_created_board:
        refreshed_boards += (board(9001, 202, 20_001, 30_000),)
    refreshed_demands = (
        demand(7, 303, 10_001, 20_000),
        demand(8, 404, 10_001, 20_000, substitutable=False),
        demand(9, 505, 10_001, 20_000),
    )
    return (
        ClusteringInputBatch(initial_demands, initial_boards),
        ClusteringInputBatch(refreshed_demands, refreshed_boards),
    )


@pytest.mark.parametrize("existing_assignment_stale", [False, True])
def test_executes_formation_refresh_and_substitution_in_order(
    existing_assignment_stale: bool,
) -> None:
    calls: list[str] = []
    events: list[str] = []
    initial, refreshed = input_batches()
    if existing_assignment_stale:
        refreshed = ClusteringInputBatch(
            (initial.demands[0], *refreshed.demands), refreshed.boards
        )
    reader = TwoReadInputReader(initial, refreshed, calls)

    def post_formation(
        backend_base_url: str,
        internal_key: str,
        request: dict[str, Any],
    ) -> BackendBoardPlanApplyResult:
        calls.append("formation")
        assert backend_base_url == "http://backend:8080"
        assert internal_key == "service-secret"
        assert request["existingBoardAssignments"] == [{
            "demandBoardId": 31,
            "demandIds": [1],
        }]
        assert request["newBoards"][0]["demandIds"] == [2, 3, 4, 5, 6]
        return BackendBoardPlanApplyResult(
            status="APPLIED",
            existing_applied_demand_count=0 if existing_assignment_stale else 1,
            existing_stale_rejected_count=1 if existing_assignment_stale else 0,
            new_boards=(
                FormedDemandBoardResult(
                    request["newBoards"][0]["clientBoardKey"],
                    9001,
                    "CREATED",
                ),
            ),
        )

    def plan_substitutes(
        inputs: ClusteringInputBatch,
        *,
        as_of: datetime,
    ) -> list[dict[str, int]]:
        calls.append("planner")
        assert as_of == NOW
        assert [item.id for item in inputs.demands] == [7]
        assert [item.id for item in inputs.boards] == [31, 9001]
        return [{
            "demandId": 7,
            "originalCatalogId": 303,
            "substituteCatalogId": 202,
            "demandBoardId": 9001,
        }]

    def post_substitutes(
        backend_base_url: str,
        internal_key: str,
        request: dict[str, Any],
    ) -> BackendPlanApplyResult:
        calls.append("substitute")
        assert backend_base_url == "http://backend:8080"
        assert internal_key == "service-secret"
        assert request["proposals"] == [{
            "demandId": 7,
            "expectedOriginalCatalogId": 303,
            "substituteCatalogId": 202,
            "demandBoardId": 9001,
        }]
        return BackendPlanApplyResult(
            status="APPLIED",
            applied_count=1,
            already_applied_count=0,
            stale_rejected_count=0,
        )

    result = execute_demand_clustering_batch(
        reader,
        plan_substitutes,
        backend_base_url="http://backend:8080",
        internal_key="service-secret",
        planned_at=NOW,
        formation_rule_version="board-formation-v1",
        substitute_rule_version="substitute-admission-v1",
        formation_plan_poster=post_formation,
        substitute_plan_poster=post_substitutes,
        event_handler=lambda event, fields: events.append(event),
    )

    assert calls == ["read", "formation", "read", "planner", "substitute"]
    assert result.formation_attempted_demand_ids == (1, 2, 3, 4, 5, 6)
    assert result.substitute_candidate_demand_ids == (7,)
    assert result.formed_board_ids_by_client_key == {
        "new-board:1": 9001,
    }
    assert events == [
        "INPUT_LOADED",
        "FORMATION_PLANNED",
        "FORMATION_APPLIED",
        "INPUT_REFRESHED",
        "SUBSTITUTION_PLANNED",
        "SUBSTITUTION_APPLIED",
    ]


def test_stops_before_substitution_when_created_board_is_not_visible() -> None:
    calls: list[str] = []
    initial, refreshed = input_batches(include_created_board=False)
    reader = TwoReadInputReader(initial, refreshed, calls)

    def post_formation(
        backend_base_url: str,
        internal_key: str,
        request: dict[str, Any],
    ) -> BackendBoardPlanApplyResult:
        calls.append("formation")
        return BackendBoardPlanApplyResult(
            status="APPLIED",
            existing_applied_demand_count=1,
            existing_stale_rejected_count=0,
            new_boards=(
                FormedDemandBoardResult(
                    request["newBoards"][0]["clientBoardKey"],
                    9001,
                    "CREATED",
                ),
            ),
        )

    with pytest.raises(RuntimeError, match="9001"):
        execute_demand_clustering_batch(
            reader,
            lambda inputs, *, as_of: (),
            backend_base_url="http://backend:8080",
            internal_key="service-secret",
            planned_at=NOW,
            formation_rule_version="board-formation-v1",
            substitute_rule_version="substitute-admission-v1",
            formation_plan_poster=post_formation,
        )

    assert calls == ["read", "formation", "read"]


def test_rejects_runtime_threshold_below_backend_minimum() -> None:
    class Reader:
        def read(self, *, as_of: datetime) -> ClusteringInputBatch:
            raise AssertionError("reader must not be called")

    with pytest.raises(ValueError, match="at least 5"):
        execute_demand_clustering_batch(
            Reader(),
            lambda inputs, *, as_of: (),
            backend_base_url="http://backend:8080",
            internal_key="service-secret",
            planned_at=NOW,
            formation_rule_version="board-formation-v1",
            substitute_rule_version="substitute-admission-v1",
            min_participants=4,
        )


@pytest.mark.parametrize(
    ("demand_id", "original_catalog_id", "error_message"),
    [
        (9, 505, "outside the eligible refreshed batch"),
        (7, 303, "previously rejected board"),
    ],
)
def test_invalid_substitute_proposal_stops_before_backend_call(
    demand_id: int,
    original_catalog_id: int,
    error_message: str,
) -> None:
    calls: list[str] = []
    initial, refreshed = input_batches()
    refreshed = ClusteringInputBatch(
        refreshed.demands,
        refreshed.boards,
        rejected_demand_board_pairs=frozenset({(7, 9001)}),
    )
    reader = TwoReadInputReader(initial, refreshed, calls)

    def post_formation(
        backend_base_url: str,
        internal_key: str,
        request: dict[str, Any],
    ) -> BackendBoardPlanApplyResult:
        return BackendBoardPlanApplyResult(
            status="APPLIED",
            existing_applied_demand_count=1,
            existing_stale_rejected_count=0,
            new_boards=(
                FormedDemandBoardResult(
                    request["newBoards"][0]["clientBoardKey"],
                    9001,
                    "CREATED",
                ),
            ),
        )

    def invalid_planner(
        inputs: ClusteringInputBatch,
        *,
        as_of: datetime,
    ) -> list[dict[str, int]]:
        assert inputs.rejected_demand_board_pairs == frozenset({(7, 9001)})
        return [{
            "demandId": demand_id,
            "originalCatalogId": original_catalog_id,
            "substituteCatalogId": 202,
            "demandBoardId": 9001,
        }]

    def unexpected_post_substitutes(*args, **kwargs):
        pytest.fail("invalid proposals must not reach Backend API 2")

    with pytest.raises(ValueError, match=error_message):
        execute_demand_clustering_batch(
            reader,
            invalid_planner,
            backend_base_url="http://backend:8080",
            internal_key="service-secret",
            planned_at=NOW,
            formation_rule_version="board-formation-v1",
            substitute_rule_version="substitute-admission-v1",
            formation_plan_poster=post_formation,
            substitute_plan_poster=unexpected_post_substitutes,
        )
