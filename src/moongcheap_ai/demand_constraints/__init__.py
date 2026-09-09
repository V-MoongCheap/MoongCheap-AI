"""Deterministic Korean demand-constraint parsing."""

from .classifier import ConstraintClassifier
from .extractor import ConstraintExtractor, ExtractionResult, FacetConstraint
from .facet_matcher import KiwiFacetMatcher
from .input_policy import (
    ConstraintInputPolicy,
    DemandRequirementResult,
    PreferenceGroup,
    TaxonomyEquivalence,
)
from .service import DemandConstraintParser, parse_demand_constraints
from .taxonomy_matcher import TaxonomyFacetMatcher

__all__ = [
    "ConstraintClassifier",
    "ConstraintExtractor",
    "ConstraintInputPolicy",
    "DemandConstraintParser",
    "DemandRequirementResult",
    "ExtractionResult",
    "FacetConstraint",
    "KiwiFacetMatcher",
    "PreferenceGroup",
    "TaxonomyEquivalence",
    "TaxonomyFacetMatcher",
    "parse_demand_constraints",
]
