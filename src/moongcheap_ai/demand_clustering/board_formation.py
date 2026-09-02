"""Deterministic plans for forming new demand boards."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from .eligibility import is_ready_for_clustering
from .input_models import DemandInput
from .price_bands import PRICE_BANDS, PriceBand, find_price_band_for_range


@dataclass(frozen=True, slots=True)
class NewDemandBoardPlan:
    """Pure clustering output to be persisted by an owning adapter."""

    catalog_id: int
    demand_ids: tuple[int, ...]
    participant_count: int
    member_band_min_index: int
    member_band_max_index: int
    price_band_index: int
    price_min: int
    price_max: int


def _validate_min_participants(min_participants: int) -> None:
    if isinstance(min_participants, bool) or not isinstance(min_participants, int):
        raise TypeError("min_participants must be an integer")
    if min_participants < 1:
        raise ValueError("min_participants must be positive")


def _new_board_plan(
    catalog_id: int,
    members: Iterable[tuple[DemandInput, PriceBand]],
    *,
    price_band: PriceBand,
) -> NewDemandBoardPlan:
    member_rows = tuple(members)
    member_band_indexes = tuple(band.index for _, band in member_rows)
    member_band_min_index = min(member_band_indexes)
    member_band_max_index = max(member_band_indexes)

    if member_band_max_index - member_band_min_index > 1:
        raise ValueError("a board must span at most two adjacent price bands")
    if price_band.index != member_band_min_index:
        raise ValueError("board price must use the lowest member price band")

    return NewDemandBoardPlan(
        catalog_id=catalog_id,
        demand_ids=tuple(sorted(demand.id for demand, _ in member_rows)),
        participant_count=len(member_rows),
        member_band_min_index=member_band_min_index,
        member_band_max_index=member_band_max_index,
        price_band_index=price_band.index,
        price_min=price_band.lower_bound,
        price_max=price_band.upper_bound,
    )


def plan_new_demand_boards(
    demands: Iterable[DemandInput],
    *,
    as_of: datetime,
    min_participants: int,
) -> tuple[NewDemandBoardPlan, ...]:
    """Plan new boards from eligible demands using high-to-low band windows.

    Callers should first remove demands assigned to compatible existing boards.
    Within each catalog, adjacent windows are evaluated from ``[5, 6]`` down
    to ``[0, 1]``. A two-band board requires a participant threshold and at
    least as many members in the lower band as in the upper band. If that pair
    cannot form, an upper-band-only board may form. Assigned demands are
    removed before the next lower window is evaluated.

    Missing price bounds remain unplanned. Noncanonical, non-null demand price
    ranges raise an error because buyers must select exactly one confirmed band.
    """

    _validate_min_participants(min_participants)
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must include timezone information")

    demands_by_catalog_and_band: dict[
        int,
        dict[int, list[tuple[DemandInput, PriceBand]]],
    ] = defaultdict(lambda: defaultdict(list))
    seen_demand_ids: set[int] = set()

    for demand in demands:
        if demand.id in seen_demand_ids:
            raise ValueError(f"duplicate demand id: {demand.id}")
        seen_demand_ids.add(demand.id)

        if not is_ready_for_clustering(demand, as_of=as_of):
            continue
        if demand.desired_price_min is None or demand.desired_price_max is None:
            continue

        band = find_price_band_for_range(
            demand.desired_price_min,
            demand.desired_price_max,
        )
        demands_by_catalog_and_band[demand.catalog_id][band.index].append(
            (demand, band)
        )

    plans: list[NewDemandBoardPlan] = []

    for catalog_id in sorted(demands_by_catalog_and_band):
        members_by_band = demands_by_catalog_and_band[catalog_id]

        for upper_index in range(len(PRICE_BANDS) - 1, 0, -1):
            lower_index = upper_index - 1
            lower_members = members_by_band[lower_index]
            upper_members = members_by_band[upper_index]

            pair_can_form = (
                bool(lower_members)
                and bool(upper_members)
                and len(lower_members) + len(upper_members) >= min_participants
                and len(lower_members) >= len(upper_members)
            )

            if pair_can_form:
                plans.append(
                    _new_board_plan(
                        catalog_id,
                        (*lower_members, *upper_members),
                        price_band=PRICE_BANDS[lower_index],
                    )
                )
                lower_members.clear()
                upper_members.clear()
            elif len(upper_members) >= min_participants:
                plans.append(
                    _new_board_plan(
                        catalog_id,
                        upper_members,
                        price_band=PRICE_BANDS[upper_index],
                    )
                )
                upper_members.clear()

        lowest_band_members = members_by_band[0]
        if len(lowest_band_members) >= min_participants:
            plans.append(
                _new_board_plan(
                    catalog_id,
                    lowest_band_members,
                    price_band=PRICE_BANDS[0],
                )
            )
            lowest_band_members.clear()

    return tuple(plans)
