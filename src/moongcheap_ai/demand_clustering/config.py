"""Runtime configuration adapters for demand clustering."""

from __future__ import annotations

import os
from collections.abc import Mapping


CLUSTER_MIN_PARTICIPANTS_ENV = "CLUSTER_MIN_PARTICIPANTS"
MIN_CLUSTER_PARTICIPANTS = 5
DEFAULT_CLUSTER_MIN_PARTICIPANTS = MIN_CLUSTER_PARTICIPANTS


def load_min_cluster_participants(
    environ: Mapping[str, str] | None = None,
) -> int:
    """Load and validate the ConfigMap-provided cluster threshold."""

    source = os.environ if environ is None else environ
    raw_value = source.get(
        CLUSTER_MIN_PARTICIPANTS_ENV,
        str(DEFAULT_CLUSTER_MIN_PARTICIPANTS),
    )

    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(
            f"{CLUSTER_MIN_PARTICIPANTS_ENV} must be an integer"
        ) from error

    if value < MIN_CLUSTER_PARTICIPANTS:
        raise ValueError(
            f"{CLUSTER_MIN_PARTICIPANTS_ENV} must be at least "
            f"{MIN_CLUSTER_PARTICIPANTS}"
        )
    return value
