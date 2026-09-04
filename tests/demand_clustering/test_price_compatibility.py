import json
import unittest
from dataclasses import replace
from pathlib import Path

from moongcheap_ai.demand_clustering import (
    DemandBoardInput,
    DemandInput,
    evaluate_price_band_compatibility,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "erd_v2_input.json"


class PriceCompatibilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.demand = DemandInput.from_mapping(fixture["demands"][0])
        cls.board = DemandBoardInput.from_mapping(fixture["demand_boards"][0])

    def test_accepts_the_same_band(self) -> None:
        self.assertIs(
            evaluate_price_band_compatibility(self.demand, self.board),
            True,
        )

    def test_rejects_a_demand_one_band_above_the_board_price(self) -> None:
        lower_priced_board = replace(
            self.board,
            price_min=5_001,
            price_max=10_000,
        )

        self.assertIs(
            evaluate_price_band_compatibility(self.demand, lower_priced_board),
            False,
        )

    def test_rejects_a_band_two_indexes_away(self) -> None:
        distant_board = replace(
            self.board,
            price_min=30_001,
            price_max=50_000,
        )

        self.assertIs(
            evaluate_price_band_compatibility(self.demand, distant_board),
            False,
        )

    def test_rejects_a_lower_band_that_would_shift_the_board_price(self) -> None:
        demand_in_lower_band = replace(
            self.demand,
            desired_price_min=5_001,
            desired_price_max=10_000,
        )

        self.assertIs(
            evaluate_price_band_compatibility(
                demand_in_lower_band,
                self.board,
            ),
            False,
        )

    def test_rejects_a_noncanonical_board_range(self) -> None:
        board = replace(
            self.board,
            price_min=15_000,
            price_max=25_000,
        )

        with self.assertRaisesRegex(ValueError, "confirmed price band"):
            evaluate_price_band_compatibility(self.demand, board)

    def test_supports_the_finite_highest_band(self) -> None:
        highest_band_demand = replace(
            self.demand,
            desired_price_min=100_001,
            desired_price_max=999_999,
        )
        highest_band_board = replace(
            self.board,
            price_min=100_001,
            price_max=999_999,
        )

        self.assertIs(
            evaluate_price_band_compatibility(
                highest_band_demand,
                highest_band_board,
            ),
            True,
        )

    def test_returns_unresolved_for_a_missing_range_bound(self) -> None:
        cases = (
            (replace(self.demand, desired_price_min=None), self.board),
            (replace(self.demand, desired_price_max=None), self.board),
            (self.demand, replace(self.board, price_min=None)),
            (self.demand, replace(self.board, price_max=None)),
        )

        for demand, board in cases:
            with self.subTest(demand=demand, board=board):
                self.assertIsNone(
                    evaluate_price_band_compatibility(demand, board)
                )

    def test_rejects_a_noncanonical_demand_range(self) -> None:
        demand = replace(
            self.demand,
            desired_price_min=15_000,
            desired_price_max=20_000,
        )

        with self.assertRaisesRegex(ValueError, "confirmed price band"):
            evaluate_price_band_compatibility(demand, self.board)

    def test_rejects_inverted_ranges(self) -> None:
        inverted_demand = replace(
            self.demand,
            desired_price_min=20_000,
            desired_price_max=10_001,
        )
        inverted_board = replace(self.board, price_min=20_000, price_max=10_001)

        with self.assertRaisesRegex(ValueError, "desired_price_min"):
            evaluate_price_band_compatibility(inverted_demand, self.board)
        with self.assertRaisesRegex(ValueError, "price_min"):
            evaluate_price_band_compatibility(self.demand, inverted_board)


if __name__ == "__main__":
    unittest.main()
