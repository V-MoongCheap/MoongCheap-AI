import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from moongcheap_ai.demand_clustering import (
    DemandBoardInput,
    DemandInput,
    find_clustering_board_candidates,
    find_price_band_compatible_boards,
    find_same_catalog_gathering_boards,
    select_clustering_board_candidate,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "erd_v2_input.json"


class CandidateFinderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.demand = DemandInput.from_mapping(fixture["demands"][0])
        cls.boards = [
            DemandBoardInput.from_mapping(row) for row in fixture["demand_boards"]
        ]
        cls.as_of = datetime.fromisoformat("2026-08-28T12:00:00+09:00")

    def test_returns_only_gathering_boards_with_same_catalog(self) -> None:
        candidates = find_same_catalog_gathering_boards(self.demand, self.boards)

        self.assertEqual([board.id for board in candidates], [3001, 3004])

    def test_returns_candidates_when_demand_is_ready(self) -> None:
        candidates = find_clustering_board_candidates(
            self.demand,
            self.boards,
            as_of=self.as_of,
        )

        self.assertEqual([board.id for board in candidates], [3001])

    def test_returns_only_boards_with_the_exact_price_band(self) -> None:
        compatible_board = self.boards[0]
        unresolved_board = self.boards[1]
        lower_priced_board = replace(
            compatible_board,
            id=3005,
            price_min=5_001,
            price_max=10_000,
        )
        distant_board = replace(
            compatible_board,
            id=3006,
            price_min=30_001,
            price_max=50_000,
        )

        candidates = find_price_band_compatible_boards(
            self.demand,
            [
                unresolved_board,
                distant_board,
                lower_priced_board,
                compatible_board,
            ],
        )

        self.assertEqual([board.id for board in candidates], [3001])

    def test_excludes_a_board_at_its_sale_deadline(self) -> None:
        expired_board = replace(
            self.boards[0],
            id=3005,
            sale_end_at=self.as_of,
        )

        candidates = find_clustering_board_candidates(
            self.demand,
            [expired_board],
            as_of=self.as_of,
        )

        self.assertEqual(candidates, ())

    def test_rejects_duplicate_active_boards_for_the_same_band(self) -> None:
        latest = replace(
            self.boards[0],
            id=3009,
            created_at=self.boards[0].created_at + timedelta(hours=1),
        )
        earliest_high_id = replace(self.boards[0], id=3008)
        earliest_low_id = replace(self.boards[0], id=3007)

        with self.assertRaisesRegex(ValueError, "multiple active demand boards"):
            select_clustering_board_candidate(
                self.demand,
                [latest, earliest_high_id, earliest_low_id],
                as_of=self.as_of,
            )

    def test_returns_no_candidates_when_demand_is_not_ready(self) -> None:
        assigned_demand = replace(self.demand, status="ASSIGNED")

        candidates = find_clustering_board_candidates(
            assigned_demand,
            self.boards,
            as_of=self.as_of,
        )

        self.assertEqual(candidates, ())

    def test_returns_candidates_in_stable_id_order(self) -> None:
        candidates = find_same_catalog_gathering_boards(
            self.demand,
            reversed(self.boards),
        )

        self.assertEqual([board.id for board in candidates], [3001, 3004])


if __name__ == "__main__":
    unittest.main()
