import json
import unittest
from datetime import timedelta
from pathlib import Path

from moongcheap_ai.demand_clustering import DemandBoardInput, DemandInput


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "erd_v2_input.json"


class InputModelsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_loads_erd_v2_shaped_inputs_without_applying_policy(self) -> None:
        demands = [DemandInput.from_mapping(row) for row in self.fixture["demands"]]
        boards = [
            DemandBoardInput.from_mapping(row)
            for row in self.fixture["demand_boards"]
        ]

        self.assertEqual(demands[0].catalog_id, boards[0].catalog_id)
        self.assertEqual(demands[0].status, "UNASSIGNED")
        self.assertEqual(boards[0].status, "GB_GATHERING")
        self.assertEqual(demands[0].created_at.utcoffset(), timedelta(hours=9))
        self.assertEqual(demands[0].processed_at.utcoffset(), timedelta(hours=9))
        self.assertEqual(boards[0].created_at.utcoffset(), timedelta(hours=9))
        self.assertEqual(boards[0].sale_end_at.utcoffset(), timedelta(hours=9))

    def test_preserves_nullable_demand_fields_from_erd_v2(self) -> None:
        demand = DemandInput.from_mapping(self.fixture["demands"][1])

        self.assertIsNone(demand.desired_price_min)
        self.assertIsNone(demand.desired_price_max)
        self.assertIsNone(demand.quantity)
        self.assertIsNone(demand.is_substitutable)
        self.assertIsNone(demand.status)
        self.assertIsNone(demand.label)
        self.assertIsNone(demand.desire_end_at)
        self.assertIsNone(demand.processed_at)
        self.assertEqual(demand.created_at.utcoffset(), timedelta(0))

    def test_rejects_timestamp_without_timezone(self) -> None:
        row = dict(self.fixture["demands"][0])
        row["created_at"] = "2026-08-27T12:00:00"

        with self.assertRaisesRegex(ValueError, "timezone"):
            DemandInput.from_mapping(row)

    def test_rejects_board_timestamp_without_timezone(self) -> None:
        row = dict(self.fixture["demand_boards"][0])
        row["sale_end_at"] = "2026-09-01T12:00:00"

        with self.assertRaisesRegex(ValueError, "timezone"):
            DemandBoardInput.from_mapping(row)


if __name__ == "__main__":
    unittest.main()
