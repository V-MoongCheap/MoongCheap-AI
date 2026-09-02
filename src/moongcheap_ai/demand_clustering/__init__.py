"""Demand clustering primitives."""

from .board_formation import NewDemandBoardPlan, plan_new_demand_boards
from .batch_planner import (
    DemandClusteringBatchPlan,
    ExistingBoardAssignmentPlan,
    plan_demand_clustering_batch,
)
from .candidate_finder import (
    find_clustering_board_candidates,
    find_price_band_compatible_boards,
    find_same_catalog_gathering_boards,
    select_clustering_board_candidate,
)
from .config import (
    CLUSTER_MIN_PARTICIPANTS_ENV,
    DEFAULT_CLUSTER_MIN_PARTICIPANTS,
    load_min_cluster_participants,
)
from .eligibility import is_ready_for_clustering
from .input_models import DemandBoardInput, DemandInput
from .price_bands import (
    PRICE_BANDS,
    PriceBand,
    find_price_band_for_range,
    find_price_band_for_value,
)
from .price_compatibility import evaluate_price_band_compatibility
from .postgres_reader import (
    CLUSTERING_BOARDS_SQL,
    CLUSTERING_DEMANDS_SQL,
    ClusteringInputBatch,
    PostgreSQLClusteringInputReader,
    PostgreSQLConnection,
)

__all__ = [
    "CLUSTER_MIN_PARTICIPANTS_ENV",
    "CLUSTERING_BOARDS_SQL",
    "CLUSTERING_DEMANDS_SQL",
    "DEFAULT_CLUSTER_MIN_PARTICIPANTS",
    "PRICE_BANDS",
    "ClusteringInputBatch",
    "DemandBoardInput",
    "DemandClusteringBatchPlan",
    "DemandInput",
    "ExistingBoardAssignmentPlan",
    "NewDemandBoardPlan",
    "PriceBand",
    "PostgreSQLClusteringInputReader",
    "PostgreSQLConnection",
    "evaluate_price_band_compatibility",
    "find_clustering_board_candidates",
    "find_price_band_compatible_boards",
    "find_price_band_for_range",
    "find_price_band_for_value",
    "find_same_catalog_gathering_boards",
    "is_ready_for_clustering",
    "load_min_cluster_participants",
    "plan_demand_clustering_batch",
    "plan_new_demand_boards",
    "select_clustering_board_candidate",
]
