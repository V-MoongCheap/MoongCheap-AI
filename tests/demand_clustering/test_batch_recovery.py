"""A failed invocation is abandoned; the next one plans from current DB state."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from functools import partial
from types import SimpleNamespace

import pytest
import requests

from moongcheap_ai.demand_clustering.backend_board_plan import post_board_assignment_plan
from moongcheap_ai.demand_clustering.backend_plan_client import (
    post_substitute_board_admission_plan,
)
from moongcheap_ai.demand_clustering.batch_execution import execute_demand_clustering_batch
from moongcheap_ai.demand_clustering.eligibility import is_ready_for_clustering
from moongcheap_ai.demand_clustering.postgres_reader import ClusteringInputBatch

from .test_batch_execution import NOW, board, demand, input_batches


class BackendState:
    """Test double for committed Backend state, not a Backend implementation."""

    def __init__(self, failure_stage=None, failure_position=None):
        initial, _ = input_batches()
        self.demands = {row.id: row for row in initial.demands}
        self.demands[7] = replace(
            self.demands[7], desired_price_min=20_001, desired_price_max=30_000
        )
        self.boards = {row.id: row for row in initial.boards}
        self.failure_stage = failure_stage
        self.failure_position = failure_position
        self.requests = {"formation": [], "substitution": []}
        self.reads = []
        self.planner_inputs = []

    def read(self, *, as_of):
        result = ClusteringInputBatch(
            tuple(
                row for row in self.demands.values()
                if is_ready_for_clustering(row, as_of=as_of)
            ),
            tuple(
                row for row in self.boards.values()
                if row.status == "GB_GATHERING" and row.sale_end_at > as_of
            ),
        )
        self.reads.append((as_of, result))
        return result

    def plan(self, inputs, *, as_of):
        self.planner_inputs.append(tuple(row.id for row in inputs.demands))
        candidates = [row for row in inputs.boards if row.catalog_id == 202]
        if not candidates:
            return []
        target = candidates[0]
        return [
            {
                "demandId": row.id,
                "originalCatalogId": row.catalog_id,
                "substituteCatalogId": target.catalog_id,
                "demandBoardId": target.id,
            }
            for row in inputs.demands
            if row.catalog_id != target.catalog_id
            and row.desired_price_max >= target.price_max
        ]

    def _maybe_fail(self, stage, position):
        if (stage, position) == (self.failure_stage, self.failure_position):
            self.failure_stage = None
            raise requests.Timeout(f"{stage} failure {position} commit")

    def _assign(self, demand_id, board_id):
        self.demands[demand_id] = replace(
            self.demands[demand_id], status="ASSIGNED", demand_board_id=board_id
        )

    def post(self, url, *, json, headers, **kwargs):
        stage = "formation" if url.endswith("/formation-plans") else "substitution"
        assert "batchId" not in json
        assert headers["X-Internal-Key"] == "test-internal-key"
        assert "Authorization" not in headers
        assert kwargs["allow_redirects"] is False
        self.requests[stage].append(deepcopy(json))
        self._maybe_fail(stage, "before")
        result = {"status": "APPLIED"}
        if stage == "formation":
            applied = 0
            for item in json["existingBoardAssignments"]:
                for demand_id in item["demandIds"]:
                    assert self.demands[demand_id].status == "UNASSIGNED"
                    self._assign(demand_id, item["demandBoardId"])
                    target = self.boards[item["demandBoardId"]]
                    self.boards[target.id] = replace(
                        target, participant_count=target.participant_count + 1
                    )
                    applied += 1
            new_boards = []
            for item in json["newBoards"]:
                assert all(
                    self.demands[demand_id].status == "UNASSIGNED"
                    for demand_id in item["demandIds"]
                )
                board_id = max(9000, *self.boards) + 1
                self.boards[board_id] = replace(
                    board(board_id, item["catalogId"], item["priceMin"], item["priceMax"]),
                    participant_count=len(item["demandIds"]),
                )
                for demand_id in item["demandIds"]:
                    self._assign(demand_id, board_id)
                new_boards.append({
                    "clientBoardKey": item["clientBoardKey"],
                    "demandBoardId": board_id,
                    "status": "CREATED",
                })
            result.update({
                "existingAssignments": {"appliedCount": applied, "staleCount": 0},
                "newBoards": new_boards,
            })
        else:
            for item in json["proposals"]:
                row = self.demands[item["demandId"]]
                assert row.status == "UNASSIGNED"
                self.demands[row.id] = replace(
                    row, status="SUBSTITUTE_OFFERED",
                    demand_board_id=item["demandBoardId"],
                )
            result.update({
                "appliedCount": len(json["proposals"]),
                "alreadyAppliedCount": 0,
                "staleRejectedCount": 0,
            })
        self._maybe_fail(stage, "after")
        return SimpleNamespace(ok=True, status_code=200, json=lambda: result)


def run_batch(backend, *, as_of=NOW):
    return execute_demand_clustering_batch(
        backend,
        backend.plan,
        backend_base_url="http://backend:8080",
        internal_key="test-internal-key",
        planned_at=as_of,
        formation_rule_version="formation-v1",
        substitute_rule_version="substitution-v1",
        formation_plan_poster=partial(post_board_assignment_plan, http_post=backend.post),
        substitute_plan_poster=partial(
            post_substitute_board_admission_plan, http_post=backend.post
        ),
    )


@pytest.mark.parametrize("stage", ["formation", "substitution"])
@pytest.mark.parametrize("position", ["before", "after"])
def test_failure_is_not_retried_and_next_batch_reads_current_state(stage, position):
    backend = BackendState(stage, position)
    with pytest.raises(requests.Timeout):
        run_batch(backend)

    assert len(backend.requests[stage]) == 1
    if stage == "formation":
        assert backend.requests["substitution"] == []
        assert len(backend.reads) == 1
    else:
        assert len(backend.reads) == 2

    # Newly arrived demands must participate in the next original-product pass.
    backend.demands[9] = demand(9, 101, 10_001, 20_000)
    read_count = len(backend.reads)
    next_time = NOW + timedelta(hours=1)
    result = run_batch(backend, as_of=next_time)

    assert len(backend.reads) == read_count + 2
    assert backend.reads[read_count][0] == next_time
    assert 9 in result.formation_attempted_demand_ids
    assert backend.demands[9].status == "ASSIGNED"
    assert len(backend.boards) == 2
    assert backend.boards[31].participant_count == 7
    assert backend.boards[9001].participant_count == 5
    assert backend.demands[7].status == "SUBSTITUTE_OFFERED"
    assert result.formation_request["plannedAt"] == next_time.isoformat()

    if stage == "substitution" and position == "after":
        assert result.substitute_candidate_demand_ids == ()
        assert result.substitute_request["proposals"] == []
    else:
        assert result.substitute_candidate_demand_ids == (7,)


def test_rejection_after_lost_response_reenters_original_product_path():
    backend = BackendState("substitution", "after")
    with pytest.raises(requests.Timeout):
        run_batch(backend)
    assert backend.demands[7].status == "SUBSTITUTE_OFFERED"

    # Backend handles rejection; a matching original-product board then appears.
    backend.demands[7] = replace(
        backend.demands[7], status="UNASSIGNED", demand_board_id=None
    )
    backend.boards[9002] = board(9002, 303, 20_001, 30_000)
    result = run_batch(backend, as_of=NOW + timedelta(hours=1))

    assert result.formation_request["existingBoardAssignments"] == [{
        "demandBoardId": 9002, "demandIds": [7],
    }]
    assert result.substitute_request["proposals"] == []
    assert backend.demands[7].status == "ASSIGNED"
    assert backend.demands[7].demand_board_id == 9002


def test_fresh_planning_can_still_select_a_previously_rejected_board():
    backend = BackendState("substitution", "after")
    with pytest.raises(requests.Timeout):
        run_batch(backend)
    backend.demands[7] = replace(
        backend.demands[7], status="UNASSIGNED", demand_board_id=None
    )
    result = run_batch(backend, as_of=NOW + timedelta(hours=1))

    assert backend.planner_inputs == [(7,), (7,)]
    assert result.substitute_request["proposals"][0]["demandBoardId"] == 9001
    assert backend.boards[9001].participant_count == 5


@pytest.mark.parametrize("status", ["ASSIGNED", "CANCELED", "EXPIRED"])
def test_next_batch_does_not_reoffer_a_demand_whose_state_changed(status):
    backend = BackendState("substitution", "after")
    with pytest.raises(requests.Timeout):
        run_batch(backend)
    backend.demands[7] = replace(backend.demands[7], status=status)

    result = run_batch(backend, as_of=NOW + timedelta(hours=1))

    assert 7 not in result.substitute_candidate_demand_ids
    assert result.substitute_request["proposals"] == []


def test_next_batch_excludes_a_rejected_demand_that_expired_while_waiting():
    backend = BackendState("substitution", "after")
    with pytest.raises(requests.Timeout):
        run_batch(backend)
    backend.demands[7] = replace(
        backend.demands[7], status="UNASSIGNED", demand_board_id=None,
        desire_end_at=NOW + timedelta(minutes=30),
    )

    result = run_batch(backend, as_of=NOW + timedelta(hours=1))

    assert 7 not in result.substitute_candidate_demand_ids
    assert result.substitute_request["proposals"] == []
