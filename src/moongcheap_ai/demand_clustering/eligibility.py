"""Eligibility checks for labeled demands entering clustering."""

from __future__ import annotations

from datetime import datetime, timedelta

from .input_models import DemandInput


UNASSIGNED_CLUSTERING_WINDOW = timedelta(days=2)


def is_ready_for_clustering(demand: DemandInput, *, as_of: datetime) -> bool:
    """Return whether a raw Backend demand may enter clustering.

    Part A ``label`` and ``processed_at`` values are optional metadata rather
    than runtime prerequisites. Typed constraints are derived from the raw
    ``extra_requirement`` inside the AI batch when substitution is relevant.
    The function neither reads from nor writes to the database.
    """

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must include timezone information")

    is_not_expired = demand.desire_end_at is None or demand.desire_end_at > as_of
    is_within_clustering_window = (
        demand.created_at + UNASSIGNED_CLUSTERING_WINDOW > as_of
    )

    return (
        demand.status == "UNASSIGNED"
        and demand.demand_board_id is None
        and is_not_expired
        and is_within_clustering_window
    )
