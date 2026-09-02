"""Policy-minimal demand board candidate lookup."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from .eligibility import is_ready_for_clustering
from .input_models import DemandBoardInput, DemandInput
from .price_compatibility import evaluate_price_band_compatibility


def find_same_catalog_gathering_boards(
    demand: DemandInput,
    boards: Iterable[DemandBoardInput],
) -> tuple[DemandBoardInput, ...]:
    """Return GB_GATHERING boards with the same catalog ID in stable ID order.

    This function does not decide whether the demand is eligible or compatible
    with a board. Facet, price, quantity, substitution, and assignment policies
    are deliberately outside this first candidate lookup.
    """

    candidates = (
        board
        for board in boards
        if (
            board.catalog_id == demand.catalog_id
            and board.status == "GB_GATHERING"
        )
    )
    return tuple(sorted(candidates, key=lambda board: board.id))


def find_clustering_board_candidates(
    demand: DemandInput,
    boards: Iterable[DemandBoardInput],
    *,
    as_of: datetime,
) -> tuple[DemandBoardInput, ...]:
    """Return active same-catalog boards with the exact demand price band.

    An unresolved price-band comparison is excluded from automatic clustering.
    This function does not evaluate facet, quantity, or substitution
    compatibility and does not perform database writes or state transitions.
    """

    if not is_ready_for_clustering(demand, as_of=as_of):
        return ()

    catalog_candidates = find_same_catalog_gathering_boards(demand, boards)
    active_candidates = (
        board for board in catalog_candidates if board.sale_end_at > as_of
    )
    return find_price_band_compatible_boards(demand, active_candidates)


def select_clustering_board_candidate(
    demand: DemandInput,
    boards: Iterable[DemandBoardInput],
    *,
    as_of: datetime,
) -> DemandBoardInput | None:
    """Return the sole compatible board and reject invariant violations.

    The owning persistence adapter should prevent multiple active boards for
    one catalog and price band. Failing fast prevents legacy or concurrent
    duplicates from being hidden behind an arbitrary automatic assignment.
    """

    candidates = find_clustering_board_candidates(
        demand,
        boards,
        as_of=as_of,
    )
    if len(candidates) > 1:
        raise ValueError(
            "multiple active demand boards for one catalog and price band"
        )
    return candidates[0] if candidates else None


def find_price_band_compatible_boards(
    demand: DemandInput,
    boards: Iterable[DemandBoardInput],
) -> tuple[DemandBoardInput, ...]:
    """Return boards whose fixed price band exactly matches the demand.

    ``False`` and unresolved ``None`` results are excluded. The caller remains
    responsible for catalog, status, and demand-eligibility filtering.
    """

    return tuple(
        board
        for board in boards
        if evaluate_price_band_compatibility(demand, board) is True
    )
