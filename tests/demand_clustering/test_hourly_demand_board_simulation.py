from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.demand.simulate_demand_board_handoff import simulated_price_band
from scripts.demand.simulate_hourly_demand_board_handoff import (
    build_part_c_hourly_board_snapshot,
    simulate_hourly_demand_board_handoff,
    simulated_registration_time,
)

from .test_demand_board_simulation import CATEGORY, TAXONOMY, row


START_AT = datetime(2026, 9, 5, tzinfo=timezone.utc)


def source_id_for_band_and_arrival_half(
    band_index: int,
    *,
    late: bool,
    offset: int = 0,
) -> str:
    found = []
    candidate = 1
    while len(found) <= offset:
        source_id = f"hourly-test-demand-{candidate:05d}"
        registered_at = simulated_registration_time(
            source_id,
            start_at=START_AT,
            arrival_window=timedelta(hours=2),
        )
        is_late = registered_at >= START_AT + timedelta(hours=1)
        if simulated_price_band(source_id).index == band_index and is_late == late:
            found.append(source_id)
        candidate += 1
    return found[offset]


def test_registration_time_is_reproducible_and_within_window() -> None:
    first = simulated_registration_time(
        "D1",
        start_at=START_AT,
        arrival_window=timedelta(hours=24),
    )
    second = simulated_registration_time(
        "D1",
        start_at=START_AT,
        arrival_window=timedelta(hours=24),
    )

    assert first == second
    assert START_AT <= first < START_AT + timedelta(hours=24)


def test_hourly_batches_carry_board_state_and_assign_later_arrival() -> None:
    early_a = row(source_id_for_band_and_arrival_half(0, late=False), 201)
    early_b = row(
        source_id_for_band_and_arrival_half(0, late=False, offset=1),
        201,
    )
    late = row(source_id_for_band_and_arrival_half(0, late=True), 201)

    output = simulate_hourly_demand_board_handoff(
        (early_a, early_b, late),
        TAXONOMY,
        start_at=START_AT,
        arrival_window=timedelta(hours=2),
        batch_interval=timedelta(hours=1),
        min_participants=2,
    )

    assert output["summary"]["batchCount"] == 50
    assert output["summary"]["demandBoardCount"] == 1
    assert output["summary"]["directAssignedDemandCount"] == 3
    assert output["summary"]["finalDemandStatusCounts"] == {"ASSIGNED": 3}
    assert sum(
        item["newlyRegisteredDemandCount"] for item in output["batchTimeline"]
    ) == 3

    board = output["demandBoards"][0]
    assert board["participantCount"] == 3
    assert len(board["directDemandIds"]) == 3
    assert output["batchTimeline"][0]["newBoardAssignedCount"] == 2
    assert output["batchTimeline"][1]["existingBoardAssignedCount"] == 1


def test_hourly_snapshot_keeps_policy_and_timeline_but_not_demand_details() -> None:
    first = row(source_id_for_band_and_arrival_half(0, late=False), 201)
    second = row(
        source_id_for_band_and_arrival_half(0, late=False, offset=1),
        201,
    )
    output = simulate_hourly_demand_board_handoff(
        (first, second),
        TAXONOMY,
        start_at=START_AT,
        arrival_window=timedelta(hours=2),
        batch_interval=timedelta(hours=1),
        min_participants=2,
    )

    snapshot = build_part_c_hourly_board_snapshot(output)

    assert snapshot["schemaVersion"] == "part-c-demand-board-snapshot.v0.2"
    assert snapshot["simulationPolicy"]["batchIntervalMinutes"] == 60
    assert snapshot["batchTimeline"] == output["batchTimeline"]
    assert "demandStates" not in snapshot
    assert "substituteAdmissionPlan" not in snapshot
    assert snapshot["demandBoards"][0]["categoryId"] == CATEGORY
