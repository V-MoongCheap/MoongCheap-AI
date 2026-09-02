import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from moongcheap_ai.demand_clustering import (
    PRICE_BANDS,
    DemandBoardInput,
    DemandInput,
    plan_demand_clustering_batch,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "erd_v2_input.json"


class BatchPlannerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.base_demand = DemandInput.from_mapping(fixture["demands"][0])
        cls.base_board = DemandBoardInput.from_mapping(
            fixture["demand_boards"][0]
        )
        cls.as_of = datetime.fromisoformat("2026-08-28T12:00:00+09:00")

    def demands_in_band(
        self,
        band_index: int,
        count: int,
        *,
        first_id: int,
        catalog_id: int = 2001,
    ) -> list[DemandInput]:
        band = PRICE_BANDS[band_index]
        return [
            replace(
                self.base_demand,
                id=first_id + offset,
                catalog_id=catalog_id,
                desired_price_min=band.lower_bound,
                desired_price_max=band.upper_bound,
            )
            for offset in range(count)
        ]

    def board_in_band(
        self,
        band_index: int,
        *,
        board_id: int,
        catalog_id: int = 2001,
    ) -> DemandBoardInput:
        band = PRICE_BANDS[band_index]
        return replace(
            self.base_board,
            id=board_id,
            catalog_id=catalog_id,
            price_min=band.lower_bound,
            price_max=band.upper_bound,
        )

    def test_assigns_exact_matches_before_planning_new_boards(self) -> None:
        existing_band_demands = self.demands_in_band(
            2, 2, first_id=200
        )
        new_board_demands = [
            *self.demands_in_band(3, 3, first_id=300),
            *self.demands_in_band(4, 2, first_id=400),
        ]

        plan = plan_demand_clustering_batch(
            reversed([*existing_band_demands, *new_board_demands]),
            [self.board_in_band(2, board_id=3001)],
            as_of=self.as_of,
            min_participants=5,
        )

        self.assertEqual(len(plan.existing_board_assignments), 1)
        self.assertEqual(
            plan.existing_board_assignments[0].demand_board_id,
            3001,
        )
        self.assertEqual(
            plan.existing_board_assignments[0].demand_ids,
            (200, 201),
        )
        self.assertEqual(
            plan.existing_board_assignments[0].participant_count_delta,
            2,
        )
        self.assertEqual(len(plan.new_board_plans), 1)
        self.assertEqual(
            plan.new_board_plans[0].demand_ids,
            (300, 301, 302, 400, 401),
        )
        self.assertEqual(plan.new_board_plans[0].price_band_index, 3)

    def test_adjacent_band_does_not_automatically_join_existing_board(self) -> None:
        demands = self.demands_in_band(3, 5, first_id=300)

        plan = plan_demand_clustering_batch(
            demands,
            [self.board_in_band(2, board_id=3001)],
            as_of=self.as_of,
            min_participants=5,
        )

        self.assertEqual(plan.existing_board_assignments, ())
        self.assertEqual(len(plan.new_board_plans), 1)
        self.assertEqual(plan.new_board_plans[0].price_band_index, 3)

    def test_rejects_duplicate_existing_boards(self) -> None:
        latest_board = replace(
            self.board_in_band(2, board_id=3003),
            created_at=self.base_board.created_at + timedelta(hours=1),
        )
        earliest_high_id = self.board_in_band(2, board_id=3002)
        earliest_low_id = self.board_in_band(2, board_id=3001)

        with self.assertRaisesRegex(ValueError, "multiple active demand boards"):
            plan_demand_clustering_batch(
                self.demands_in_band(2, 1, first_id=200),
                [latest_board, earliest_high_id, earliest_low_id],
                as_of=self.as_of,
                min_participants=5,
            )

    def test_expired_board_does_not_absorb_new_board_members(self) -> None:
        expired_board = replace(
            self.board_in_band(2, board_id=3001),
            sale_end_at=self.as_of,
        )

        plan = plan_demand_clustering_batch(
            self.demands_in_band(2, 5, first_id=200),
            [expired_board],
            as_of=self.as_of,
            min_participants=5,
        )

        self.assertEqual(plan.existing_board_assignments, ())
        self.assertEqual(len(plan.new_board_plans), 1)
        self.assertEqual(plan.new_board_plans[0].price_band_index, 2)

    def test_rejects_duplicate_input_ids(self) -> None:
        demand = self.demands_in_band(2, 1, first_id=200)[0]
        board = self.board_in_band(2, board_id=3001)

        with self.assertRaisesRegex(ValueError, "duplicate demand id"):
            plan_demand_clustering_batch(
                [demand, demand],
                [board],
                as_of=self.as_of,
                min_participants=5,
            )

        with self.assertRaisesRegex(ValueError, "duplicate demand board id"):
            plan_demand_clustering_batch(
                [demand],
                [board, board],
                as_of=self.as_of,
                min_participants=5,
            )


if __name__ == "__main__":
    unittest.main()
