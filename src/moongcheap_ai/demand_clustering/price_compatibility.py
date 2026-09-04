"""Price-band compatibility primitives for demand clustering."""

from __future__ import annotations

from .input_models import DemandBoardInput, DemandInput
from .price_bands import find_price_band_for_range


def _validate_range(
    lower_bound: int | None,
    upper_bound: int | None,
    *,
    field_prefix: str,
) -> None:
    if (
        lower_bound is not None
        and upper_bound is not None
        and lower_bound > upper_bound
    ):
        raise ValueError(
            f"{field_prefix}_min must not exceed {field_prefix}_max"
        )


def evaluate_price_band_compatibility(
    demand: DemandInput,
    board: DemandBoardInput,
) -> bool | None:
    """Return whether a demand exactly matches a board's fixed price band.

    Adjacent bands may be combined only while forming a new board. Automatic
    assignment to an existing board requires the same canonical band. Missing
    bounds remain unresolved.
    """

    demand_min = demand.desired_price_min
    demand_max = demand.desired_price_max
    board_min = board.price_min
    board_max = board.price_max

    _validate_range(
        demand_min,
        demand_max,
        field_prefix="demand desired_price",
    )
    _validate_range(board_min, board_max, field_prefix="board price")

    if (
        demand_min is None
        or demand_max is None
        or board_min is None
        or board_max is None
    ):
        return None

    demand_band = find_price_band_for_range(demand_min, demand_max)
    board_band = find_price_band_for_range(board_min, board_max)
    return demand_band.index == board_band.index
