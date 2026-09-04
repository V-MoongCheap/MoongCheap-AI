import json
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from moongcheap_ai.demand_clustering import (
    PRICE_BANDS,
    DemandInput,
    plan_new_demand_boards,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "erd_v2_input.json"


class BoardFormationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.base_demand = DemandInput.from_mapping(fixture["demands"][0])
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

    def test_forms_adjacent_bands_when_lower_band_has_at_least_as_many(self) -> None:
        demands = [
            *self.demands_in_band(2, 3, first_id=200),
            *self.demands_in_band(3, 2, first_id=300),
        ]

        plans = plan_new_demand_boards(
            reversed(demands),
            as_of=self.as_of,
            min_participants=5,
        )

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].demand_ids, (200, 201, 202, 300, 301))
        self.assertEqual(plans[0].participant_count, 5)
        self.assertEqual(plans[0].member_band_min_index, 2)
        self.assertEqual(plans[0].member_band_max_index, 3)
        self.assertEqual(plans[0].price_band_index, 2)
        self.assertEqual(plans[0].price_min, 10_001)
        self.assertEqual(plans[0].price_max, 20_000)

    def test_uses_the_higher_band_alone_when_lower_band_is_a_minority(self) -> None:
        lower_demands = self.demands_in_band(2, 2, first_id=200)
        upper_demands = self.demands_in_band(3, 5, first_id=300)

        plans = plan_new_demand_boards(
            [*lower_demands, *upper_demands],
            as_of=self.as_of,
            min_participants=5,
        )

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].demand_ids, (300, 301, 302, 303, 304))
        self.assertEqual(plans[0].member_band_min_index, 3)
        self.assertEqual(plans[0].member_band_max_index, 3)
        self.assertEqual(plans[0].price_band_index, 3)
        self.assertEqual(plans[0].price_min, 20_001)
        self.assertEqual(plans[0].price_max, 30_000)

    def test_forms_multiple_boards_and_removes_assigned_demands(self) -> None:
        demands = [
            *self.demands_in_band(4, 6, first_id=400),
            *self.demands_in_band(3, 2, first_id=300),
            *self.demands_in_band(2, 3, first_id=200),
        ]

        plans = plan_new_demand_boards(
            demands,
            as_of=self.as_of,
            min_participants=5,
        )

        self.assertEqual([plan.price_band_index for plan in plans], [4, 2])
        self.assertEqual(
            plans[0].demand_ids,
            (400, 401, 402, 403, 404, 405),
        )
        self.assertEqual(plans[1].demand_ids, (200, 201, 202, 300, 301))

    def test_prefers_the_higher_window_when_windows_overlap(self) -> None:
        demands = [
            *self.demands_in_band(2, 3, first_id=200),
            *self.demands_in_band(3, 3, first_id=300),
            *self.demands_in_band(4, 3, first_id=400),
        ]

        plans = plan_new_demand_boards(
            demands,
            as_of=self.as_of,
            min_participants=5,
        )

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].price_band_index, 3)
        self.assertEqual(
            plans[0].demand_ids,
            (300, 301, 302, 400, 401, 402),
        )

    def test_forms_a_single_lowest_band_board(self) -> None:
        demands = self.demands_in_band(0, 5, first_id=100)

        plans = plan_new_demand_boards(
            demands,
            as_of=self.as_of,
            min_participants=5,
        )

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].price_band_index, 0)
        self.assertEqual(plans[0].price_min, 0)
        self.assertEqual(plans[0].price_max, 5_000)

    def test_groups_catalogs_independently_in_stable_order(self) -> None:
        demands = [
            *self.demands_in_band(1, 5, first_id=300, catalog_id=3000),
            *self.demands_in_band(1, 5, first_id=200, catalog_id=2000),
        ]

        plans = plan_new_demand_boards(
            reversed(demands),
            as_of=self.as_of,
            min_participants=5,
        )

        self.assertEqual([plan.catalog_id for plan in plans], [2000, 3000])

    def test_does_not_plan_unready_or_unresolved_demands(self) -> None:
        ready_demands = self.demands_in_band(2, 4, first_id=200)
        assigned_demand = replace(
            self.demands_in_band(2, 1, first_id=300)[0],
            status="ASSIGNED",
        )
        unresolved_demand = replace(
            self.demands_in_band(2, 1, first_id=400)[0],
            desired_price_min=None,
        )

        plans = plan_new_demand_boards(
            [*ready_demands, assigned_demand, unresolved_demand],
            as_of=self.as_of,
            min_participants=5,
        )

        self.assertEqual(plans, ())

    def test_rejects_invalid_threshold_and_duplicate_ids(self) -> None:
        demand = self.demands_in_band(2, 1, first_id=200)[0]

        for invalid_threshold in (0, -1):
            with self.subTest(min_participants=invalid_threshold):
                with self.assertRaisesRegex(ValueError, "positive"):
                    plan_new_demand_boards(
                        [demand],
                        as_of=self.as_of,
                        min_participants=invalid_threshold,
                    )

        with self.assertRaisesRegex(ValueError, "duplicate demand id"):
            plan_new_demand_boards(
                [demand, demand],
                as_of=self.as_of,
                min_participants=5,
            )

        with self.assertRaisesRegex(TypeError, "integer"):
            plan_new_demand_boards(
                [demand],
                as_of=self.as_of,
                min_participants=True,
            )

    def test_rejects_as_of_without_timezone_even_for_an_empty_batch(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone"):
            plan_new_demand_boards(
                [],
                as_of=datetime.fromisoformat("2026-08-28T12:00:00"),
                min_participants=5,
            )


if __name__ == "__main__":
    unittest.main()
