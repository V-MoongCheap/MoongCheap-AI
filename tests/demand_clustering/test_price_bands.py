import unittest

from moongcheap_ai.demand_clustering import (
    PRICE_BANDS,
    PriceBand,
    find_price_band_for_range,
    find_price_band_for_value,
)


class PriceBandsTest(unittest.TestCase):
    def test_defines_the_seven_confirmed_price_choices_in_order(self) -> None:
        expected = [
            (0, 0, 5_000, "5,000원 이하"),
            (1, 5_001, 10_000, "1만원 이하"),
            (2, 10_001, 20_000, "2만원 이하"),
            (3, 20_001, 30_000, "3만원 이하"),
            (4, 30_001, 50_000, "5만원 이하"),
            (5, 50_001, 100_000, "10만원 이하"),
            (6, 100_001, 999_999, "10만원 초과"),
        ]

        actual = [
            (
                band.index,
                band.lower_bound,
                band.upper_bound,
                band.display_name,
            )
            for band in PRICE_BANDS
        ]

        self.assertEqual(actual, expected)

    def test_exports_each_band_exactly_once(self) -> None:
        self.assertEqual(len(PRICE_BANDS), 7)
        self.assertEqual(len(set(PRICE_BANDS)), 7)
        self.assertEqual(PRICE_BANDS, tuple(PriceBand))

    def test_maps_values_to_one_unambiguous_band(self) -> None:
        self.assertIs(find_price_band_for_value(5_000), PriceBand.UP_TO_5_000)
        self.assertIs(
            find_price_band_for_value(5_001),
            PriceBand.FROM_5_001_TO_10_000,
        )
        self.assertIs(
            find_price_band_for_value(999_999),
            PriceBand.FROM_100_001_TO_999_999,
        )

    def test_maps_only_exact_confirmed_ranges_to_a_band(self) -> None:
        self.assertIs(
            find_price_band_for_range(10_001, 20_000),
            PriceBand.FROM_10_001_TO_20_000,
        )

        with self.assertRaisesRegex(ValueError, "confirmed price band"):
            find_price_band_for_range(15_000, 20_000)

    def test_rejects_values_outside_the_confirmed_mapping(self) -> None:
        for price in (-1, 1_000_000):
            with self.subTest(price=price):
                with self.assertRaisesRegex(ValueError, "0 and 999999"):
                    find_price_band_for_value(price)


if __name__ == "__main__":
    unittest.main()
