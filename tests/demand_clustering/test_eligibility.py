import json
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from moongcheap_ai.demand_clustering import (
    DemandInput,
    is_ready_for_clustering,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "erd_v2_input.json"


class EligibilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.demand = DemandInput.from_mapping(fixture["demands"][0])
        cls.as_of = datetime.fromisoformat("2026-08-28T12:00:00+09:00")

    def test_accepts_labeled_unassigned_demand_before_deadline(self) -> None:
        self.assertTrue(is_ready_for_clustering(self.demand, as_of=self.as_of))

    def test_accepts_demand_without_optional_deadline(self) -> None:
        demand = replace(self.demand, desire_end_at=None)

        self.assertTrue(is_ready_for_clustering(demand, as_of=self.as_of))

    def test_rejects_ineligible_demands(self) -> None:
        ineligible_cases = {
            "not unassigned": replace(self.demand, status="ASSIGNED"),
            "already linked": replace(self.demand, demand_board_id=3001),
            "missing label": replace(self.demand, label=None),
            "blank label": replace(self.demand, label="   "),
            "labeling incomplete": replace(self.demand, processed_at=None),
            "deadline reached": replace(self.demand, desire_end_at=self.as_of),
        }

        for case_name, demand in ineligible_cases.items():
            with self.subTest(case=case_name):
                self.assertFalse(is_ready_for_clustering(demand, as_of=self.as_of))

    def test_rejects_as_of_without_timezone(self) -> None:
        naive_as_of = datetime.fromisoformat("2026-08-28T12:00:00")

        with self.assertRaisesRegex(ValueError, "timezone"):
            is_ready_for_clustering(self.demand, as_of=naive_as_of)

    def test_rejects_demand_at_the_two_day_unassigned_cutoff(self) -> None:
        cutoff = datetime.fromisoformat("2026-08-29T12:00:00+09:00")

        self.assertFalse(is_ready_for_clustering(self.demand, as_of=cutoff))


if __name__ == "__main__":
    unittest.main()
