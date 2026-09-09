"""Runtime and domain API for demand clustering.

Offline tooling is imported explicitly from the evaluation subpackage.
"""

from .board_formation import NewDemandBoardPlan, plan_new_demand_boards
from .batch_planner import (
    DemandClusteringBatchPlan,
    ExistingBoardAssignmentPlan,
    plan_demand_clustering_batch,
)
from .backend_board_plan import (
    BOARD_PLAN_ENDPOINT_PROPOSAL,
    BOARD_PLAN_SCHEMA_VERSION,
    BackendBoardPlanApplyResult,
    FormedDemandBoardResult,
    build_board_assignment_plan,
    post_board_assignment_plan,
    validate_board_assignment_plan_contract,
)
from .backend_plan_client import (
    PLAN_ENDPOINT,
    BackendPlanApplyResult,
    build_substitute_offer_plan_request,
    post_substitute_board_admission_plan,
    validate_backend_plan_contract,
)
from .batch_execution import (
    ClusteringInputReader,
    DemandClusteringBatchExecutionResult,
    SubstituteProposalPlanner,
    execute_demand_clustering_batch,
)
from .candidate_finder import (
    find_clustering_board_candidates,
    find_price_band_compatible_boards,
    find_same_catalog_gathering_boards,
    select_clustering_board_candidate,
)
from .claim_containment_index import (
    ClaimContainmentLookup,
    IdentityClaimContainmentIndex,
)
from .config import (
    CLUSTER_MIN_PARTICIPANTS_ENV,
    DEFAULT_CLUSTER_MIN_PARTICIPANTS,
    MIN_CLUSTER_PARTICIPANTS,
    load_min_cluster_participants,
)
from .eligibility import is_ready_for_clustering
from .e5_runtime_scorer import (
    E5RuntimeScorerConfig,
    E5RuntimeTextSimilarityScorer,
)
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
from .product_substitution import (
    BoundedProductCandidateRanking,
    FunctionCoverageResolver,
    ProductCandidateRanking,
    ProductPairAssessment,
    ProductPairFeatures,
    RankedProductCandidate,
    RetrievedProductCandidate,
    SubstituteProductProfile,
    assess_substitute_product_pair,
    rank_bounded_substitute_product_candidates,
    rank_substitute_product_candidates,
)
from .function_relation_registry import (
    FunctionCoverageRelationRegistry,
    FunctionCoverageResolution,
    function_relation_registry_from_payload,
    load_function_relation_registry,
)
from .substitute_admission import (
    RankedSubstituteBoard,
    RejectedSubstituteBoard,
    SubstituteBoardAdmissionDecision,
    SubstituteBoardCandidateInput,
    SubstituteDemandInput,
    build_substitute_board_admission_plan,
    character_ngram_cosine_similarity,
    select_substitute_board_candidate,
)
from .substitute_proposal_planner import (
    ClaimIndexedSubstituteProposalPlanner,
    RuntimeCatalogProfile,
    SkippedSubstituteDemand,
    SubstituteProposalPlanningResult,
    build_runtime_catalog_profiles,
)
__all__ = [
    "CLUSTER_MIN_PARTICIPANTS_ENV",
    "CLUSTERING_BOARDS_SQL",
    "CLUSTERING_DEMANDS_SQL",
    "DEFAULT_CLUSTER_MIN_PARTICIPANTS",
    "MIN_CLUSTER_PARTICIPANTS",
    "PRICE_BANDS",
    "PLAN_ENDPOINT",
    "BoundedProductCandidateRanking",
    "BOARD_PLAN_ENDPOINT_PROPOSAL",
    "BOARD_PLAN_SCHEMA_VERSION",
    "BackendBoardPlanApplyResult",
    "BackendPlanApplyResult",
    "ClusteringInputReader",
    "ClusteringInputBatch",
    "ClaimContainmentLookup",
    "ClaimIndexedSubstituteProposalPlanner",
    "DemandBoardInput",
    "DemandClusteringBatchPlan",
    "DemandInput",
    "DemandClusteringBatchExecutionResult",
    "E5RuntimeScorerConfig",
    "E5RuntimeTextSimilarityScorer",
    "ExistingBoardAssignmentPlan",
    "FunctionCoverageRelationRegistry",
    "FunctionCoverageResolution",
    "FunctionCoverageResolver",
    "IdentityClaimContainmentIndex",
    "FormedDemandBoardResult",
    "NewDemandBoardPlan",
    "PriceBand",
    "PostgreSQLClusteringInputReader",
    "PostgreSQLConnection",
    "ProductCandidateRanking",
    "ProductPairAssessment",
    "ProductPairFeatures",
    "RankedSubstituteBoard",
    "RankedProductCandidate",
    "RetrievedProductCandidate",
    "RejectedSubstituteBoard",
    "RuntimeCatalogProfile",
    "SubstituteBoardAdmissionDecision",
    "SubstituteBoardCandidateInput",
    "SubstituteDemandInput",
    "SubstituteProposalPlanner",
    "SubstituteProposalPlanningResult",
    "SubstituteProductProfile",
    "SkippedSubstituteDemand",
    "assess_substitute_product_pair",
    "build_board_assignment_plan",
    "build_substitute_board_admission_plan",
    "build_substitute_offer_plan_request",
    "build_runtime_catalog_profiles",
    "character_ngram_cosine_similarity",
    "evaluate_price_band_compatibility",
    "execute_demand_clustering_batch",
    "find_clustering_board_candidates",
    "find_price_band_compatible_boards",
    "find_price_band_for_range",
    "find_price_band_for_value",
    "find_same_catalog_gathering_boards",
    "function_relation_registry_from_payload",
    "is_ready_for_clustering",
    "load_min_cluster_participants",
    "load_function_relation_registry",
    "plan_demand_clustering_batch",
    "plan_new_demand_boards",
    "post_board_assignment_plan",
    "post_substitute_board_admission_plan",
    "rank_bounded_substitute_product_candidates",
    "rank_substitute_product_candidates",
    "select_clustering_board_candidate",
    "select_substitute_board_candidate",
    "validate_backend_plan_contract",
    "validate_board_assignment_plan_contract",
]
