"""Canonical price bands selected by buyers before clustering."""

from __future__ import annotations

from enum import Enum


class PriceBand(Enum):
    """The seven buyer-facing price choices confirmed for the MVP.

    Both bounds are inclusive. Adjacent bands use consecutive integer bounds,
    so every supported price belongs to exactly one band.
    """

    UP_TO_5_000 = (0, 0, 5_000, "5,000원 이하")
    FROM_5_001_TO_10_000 = (1, 5_001, 10_000, "1만원 이하")
    FROM_10_001_TO_20_000 = (2, 10_001, 20_000, "2만원 이하")
    FROM_20_001_TO_30_000 = (3, 20_001, 30_000, "3만원 이하")
    FROM_30_001_TO_50_000 = (4, 30_001, 50_000, "5만원 이하")
    FROM_50_001_TO_100_000 = (5, 50_001, 100_000, "10만원 이하")
    FROM_100_001_TO_999_999 = (6, 100_001, 999_999, "10만원 초과")

    def __init__(
        self,
        index: int,
        lower_bound: int,
        upper_bound: int,
        display_name: str,
    ) -> None:
        self.index = index
        self.lower_bound = lower_bound
        self.upper_bound = upper_bound
        self.display_name = display_name


PRICE_BANDS: tuple[PriceBand, ...] = tuple(PriceBand)


def find_price_band_for_value(price: int) -> PriceBand:
    """Return the single canonical band containing ``price``."""

    for band in PRICE_BANDS:
        if band.lower_bound <= price <= band.upper_bound:
            return band
    raise ValueError("price must be between 0 and 999999")


def find_price_band_for_range(
    lower_bound: int,
    upper_bound: int,
) -> PriceBand:
    """Return the canonical band exactly matching the supplied bounds."""

    for band in PRICE_BANDS:
        if (
            band.lower_bound == lower_bound
            and band.upper_bound == upper_bound
        ):
            return band
    raise ValueError("price range must exactly match a confirmed price band")
