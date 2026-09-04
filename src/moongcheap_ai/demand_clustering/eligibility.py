"""Eligibility checks for labeled demands entering clustering."""

from __future__ import annotations

from datetime import datetime, timedelta

from .input_models import DemandInput


UNASSIGNED_CLUSTERING_WINDOW = timedelta(days=2)


def is_ready_for_clustering(demand: DemandInput, *, as_of: datetime) -> bool:
    """Return whether a demand is ready to enter the clustering step.

    ``UNASSIGNED`` comes from the Backend status reference, while ``label`` and
    ``processed_at`` are the current hand-off contract with the labeling part.
    These are input-selection assumptions, not state-transition rules. The
    function neither reads from nor writes to the database.
    """

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must include timezone information")

    has_label = demand.label is not None and bool(demand.label.strip())
    is_not_expired = demand.desire_end_at is None or demand.desire_end_at > as_of
    is_within_clustering_window = (
        demand.created_at + UNASSIGNED_CLUSTERING_WINDOW > as_of
    )

    return (
        demand.status == "UNASSIGNED"
        and demand.demand_board_id is None
        and has_label
        and demand.processed_at is not None
        and is_not_expired
        and is_within_clustering_window
    )
