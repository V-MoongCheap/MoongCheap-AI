"""Conservative product-level gate and ranker for substitute-board candidates.

Board state, price, and a demand's natural-language constraints are evaluated
elsewhere.  This module answers the prior question: whether a different catalog
product has enough objective evidence to be considered as a substitute at all.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any


PAIR_DECISIONS = {
    "ELIGIBLE_FOR_SEMANTIC_RANKING",
    "NOT_SUBSTITUTABLE",
    "INSUFFICIENT_EVIDENCE",
}
PROFILE_STATUSES = {"APPROVED", "PROVISIONAL", "INSUFFICIENT_EVIDENCE"}
RECORD_TYPES = {"FINISHED_PRODUCT", "INGREDIENT_MATERIAL", "UNKNOWN"}


def _normalized_values(values: object) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError("profile list fields must be arrays")
    return tuple(
        sorted({str(value).strip() for value in values if str(value).strip()})
    )


@dataclass(frozen=True, slots=True)
class SubstituteProductProfile:
    """Evidence-backed catalog fields used for product substitution."""

    catalog_id: int
    product_name: str
    service_category_id: str
    taxonomy_version: str
    record_type: str
    product_form: str | None
    functional_ingredients: tuple[str, ...]
    main_functionality_codes: tuple[str, ...]
    main_functionality_text: str
    intake_method_text: str
    profile_status: str

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
    ) -> SubstituteProductProfile:
        profile = cls(
            catalog_id=int(value["catalogId"]),
            product_name=str(value["productName"]).strip(),
            service_category_id=str(value["serviceCategoryId"]).strip(),
            taxonomy_version=str(value["taxonomyVersion"]).strip(),
            record_type=str(value["recordType"]).strip(),
            product_form=(
                str(value["productForm"]).strip()
                if value.get("productForm") is not None
                else None
            ),
            functional_ingredients=_normalized_values(
                value["functionalIngredients"]
            ),
            main_functionality_codes=_normalized_values(
                value["mainFunctionalityCodes"]
            ),
            main_functionality_text=str(
                value.get("mainFunctionalityText", "")
            ).strip(),
            intake_method_text=str(
                value.get("intakeMethodText", "")
            ).strip(),
            profile_status=str(value["profileStatus"]).strip(),
        )
        profile._validate()
        return profile

    def _validate(self) -> None:
        if self.catalog_id < 1:
            raise ValueError("catalogId must be positive")
        if not self.product_name:
            raise ValueError("productName must not be empty")
        if not self.service_category_id or not self.taxonomy_version:
            raise ValueError(
                "serviceCategoryId and taxonomyVersion must not be empty"
            )
        if self.record_type not in RECORD_TYPES:
            raise ValueError(f"unknown recordType: {self.record_type}")
        if self.profile_status not in PROFILE_STATUSES:
            raise ValueError(f"unknown profileStatus: {self.profile_status}")

    def semantic_card(self) -> str:
        """Build the stable input text for an injected semantic model."""

        parts = (
            f"상품명: {self.product_name}",
            f"서비스 카테고리: {self.service_category_id}",
            "주기능 코드: " + ", ".join(self.main_functionality_codes),
            f"주기능 원문: {self.main_functionality_text}",
            "기능성 원료: " + ", ".join(self.functional_ingredients),
            f"제품 형태: {self.product_form or ''}",
            f"섭취 방법: {self.intake_method_text}",
        )
        return "\n".join(parts)


@dataclass(frozen=True, slots=True)
class ProductPairFeatures:
    directional_function_coverage: float | None
    ingredient_jaccard: float | None
    product_form_match: bool | None

    @property
    def structured_baseline_score(self) -> float | None:
        if (
            self.directional_function_coverage is None
            or self.ingredient_jaccard is None
        ):
            return None
        return round(
            (self.directional_function_coverage + self.ingredient_jaccard) / 2,
            6,
        )


@dataclass(frozen=True, slots=True)
class ProductPairAssessment:
    source_catalog_id: int
    candidate_catalog_id: int
    decision: str
    reason_codes: tuple[str, ...]
    features: ProductPairFeatures

    def __post_init__(self) -> None:
        if self.decision not in PAIR_DECISIONS:
            raise ValueError(f"unknown pair decision: {self.decision}")

    @property
    def eligible_for_semantic_ranking(self) -> bool:
        return self.decision == "ELIGIBLE_FOR_SEMANTIC_RANKING"


@dataclass(frozen=True, slots=True)
class RankedProductCandidate:
    catalog_id: int
    semantic_score: float
    structured_baseline_score: float
    assessment: ProductPairAssessment


@dataclass(frozen=True, slots=True)
class ProductCandidateRanking:
    ranked_candidates: tuple[RankedProductCandidate, ...]
    rejected_pairs: tuple[ProductPairAssessment, ...]


@dataclass(frozen=True, slots=True)
class RetrievedProductCandidate:
    """One pre-gate candidate returned by a CPU semantic retriever."""

    profile: SubstituteProductProfile
    retrieval_score: float


@dataclass(frozen=True, slots=True)
class BoundedProductCandidateRanking:
    """Result of primary retrieval plus an optional no-survivor fallback."""

    ranked_candidates: tuple[RankedProductCandidate, ...]
    rejected_pairs: tuple[ProductPairAssessment, ...]
    retrieved_candidate_count: int
    retrieval_limit_used: int
    fallback_used: bool

    @property
    def runtime_review_required(self) -> bool:
        return False


SemanticScorer = Callable[[str, str], float]
FunctionCoverageResolver = Callable[[str, str], bool]


def _jaccard(left: set[str], right: set[str]) -> float | None:
    if not left or not right:
        return None
    return round(len(left & right) / len(left | right), 6)


def _pair_features(
    source: SubstituteProductProfile,
    candidate: SubstituteProductProfile,
    function_coverage_resolver: FunctionCoverageResolver | None = None,
) -> ProductPairFeatures:
    source_functions = set(source.main_functionality_codes)
    candidate_functions = set(candidate.main_functionality_codes)
    covered_source_functions = {
        source_code
        for source_code in source_functions
        if any(
            source_code == candidate_code
            or (
                function_coverage_resolver is not None
                and function_coverage_resolver(source_code, candidate_code)
            )
            for candidate_code in candidate_functions
        )
    }
    function_coverage = (
        round(
            len(covered_source_functions) / len(source_functions),
            6,
        )
        if source_functions
        else None
    )
    form_match = (
        source.product_form == candidate.product_form
        if source.product_form and candidate.product_form
        else None
    )
    return ProductPairFeatures(
        directional_function_coverage=function_coverage,
        ingredient_jaccard=_jaccard(
            set(source.functional_ingredients),
            set(candidate.functional_ingredients),
        ),
        product_form_match=form_match,
    )


def assess_substitute_product_pair(
    source: SubstituteProductProfile,
    candidate: SubstituteProductProfile,
    *,
    function_coverage_resolver: FunctionCoverageResolver | None = None,
) -> ProductPairAssessment:
    """Apply evidence and safety gates before any semantic model runs.

    Functional coverage is directional.  A multi-function candidate may replace
    a single-function source, while the reverse is rejected.  An inconclusive
    result means no offer; it never creates a runtime REVIEW state.
    """

    features = _pair_features(source, candidate, function_coverage_resolver)
    if source.catalog_id == candidate.catalog_id:
        return ProductPairAssessment(
            source.catalog_id,
            candidate.catalog_id,
            "NOT_SUBSTITUTABLE",
            ("SAME_CATALOG",),
            features,
        )

    insufficient_reasons = []
    if source.profile_status != "APPROVED":
        insufficient_reasons.append("SOURCE_PROFILE_NOT_APPROVED")
    if candidate.profile_status != "APPROVED":
        insufficient_reasons.append("CANDIDATE_PROFILE_NOT_APPROVED")
    if source.record_type == "UNKNOWN":
        insufficient_reasons.append("SOURCE_RECORD_TYPE_UNKNOWN")
    if candidate.record_type == "UNKNOWN":
        insufficient_reasons.append("CANDIDATE_RECORD_TYPE_UNKNOWN")
    if source.taxonomy_version != candidate.taxonomy_version:
        insufficient_reasons.append("TAXONOMY_VERSION_MISMATCH")
    if not source.main_functionality_codes:
        insufficient_reasons.append("SOURCE_FUNCTIONALITY_MISSING")
    if not candidate.main_functionality_codes:
        insufficient_reasons.append("CANDIDATE_FUNCTIONALITY_MISSING")
    if not source.functional_ingredients:
        insufficient_reasons.append("SOURCE_INGREDIENT_EVIDENCE_MISSING")
    if not candidate.functional_ingredients:
        insufficient_reasons.append("CANDIDATE_INGREDIENT_EVIDENCE_MISSING")
    if insufficient_reasons:
        return ProductPairAssessment(
            source.catalog_id,
            candidate.catalog_id,
            "INSUFFICIENT_EVIDENCE",
            tuple(insufficient_reasons),
            features,
        )

    rejection_reasons = []
    if (
        source.record_type != "FINISHED_PRODUCT"
        or candidate.record_type != "FINISHED_PRODUCT"
    ):
        rejection_reasons.append("NOT_FINISHED_PRODUCT_PAIR")
    if source.service_category_id != candidate.service_category_id:
        rejection_reasons.append("SERVICE_CATEGORY_MISMATCH")
    missing_functions = sorted(
        source_code
        for source_code in set(source.main_functionality_codes)
        if not any(
            source_code == candidate_code
            or (
                function_coverage_resolver is not None
                and function_coverage_resolver(source_code, candidate_code)
            )
            for candidate_code in set(candidate.main_functionality_codes)
        )
    )
    rejection_reasons.extend(
        f"SOURCE_FUNCTION_NOT_COVERED:{code}" for code in missing_functions
    )
    if rejection_reasons:
        return ProductPairAssessment(
            source.catalog_id,
            candidate.catalog_id,
            "NOT_SUBSTITUTABLE",
            tuple(rejection_reasons),
            features,
        )

    return ProductPairAssessment(
        source.catalog_id,
        candidate.catalog_id,
        "ELIGIBLE_FOR_SEMANTIC_RANKING",
        ("SOURCE_FUNCTIONALITY_COVERED",),
        features,
    )


def rank_substitute_product_candidates(
    source: SubstituteProductProfile,
    candidates: Iterable[SubstituteProductProfile],
    *,
    semantic_scorer: SemanticScorer,
    function_coverage_resolver: FunctionCoverageResolver | None = None,
) -> ProductCandidateRanking:
    """Run a semantic scorer only on objective-gate survivors and rank them."""

    ranked = []
    rejected = []
    source_card = source.semantic_card()
    for candidate in candidates:
        assessment = assess_substitute_product_pair(
            source,
            candidate,
            function_coverage_resolver=function_coverage_resolver,
        )
        if not assessment.eligible_for_semantic_ranking:
            rejected.append(assessment)
            continue

        score = float(semantic_scorer(source_card, candidate.semantic_card()))
        if not math.isfinite(score) or not -1.0 <= score <= 1.0:
            raise ValueError(
                "semantic scorer must return a finite score between -1 and 1"
            )
        structured_score = assessment.features.structured_baseline_score
        if structured_score is None:
            raise AssertionError(
                "eligible pair must have a structured baseline score"
            )
        ranked.append(
            RankedProductCandidate(
                catalog_id=candidate.catalog_id,
                semantic_score=round(score, 6),
                structured_baseline_score=structured_score,
                assessment=assessment,
            )
        )

    ranked.sort(
        key=lambda item: (
            -item.semantic_score,
            -item.structured_baseline_score,
            item.catalog_id,
        )
    )
    rejected.sort(key=lambda item: item.candidate_catalog_id)
    return ProductCandidateRanking(tuple(ranked), tuple(rejected))


def rank_bounded_substitute_product_candidates(
    source: SubstituteProductProfile,
    retrieved_candidates: Iterable[RetrievedProductCandidate],
    *,
    function_coverage_resolver: FunctionCoverageResolver,
    primary_limit: int = 10,
    fallback_limit: int = 20,
) -> BoundedProductCandidateRanking:
    """Apply the relation gate after bounded CPU retrieval.

    The fallback window is evaluated only when the primary window has no hard-
    gate survivor. Unknown relations remain ordinary rejections and never
    create a runtime REVIEW state.
    """

    if primary_limit <= 0:
        raise ValueError("primary_limit must be positive")
    if fallback_limit < primary_limit:
        raise ValueError("fallback_limit must be at least primary_limit")
    retrieved = tuple(retrieved_candidates)
    catalog_ids = [item.profile.catalog_id for item in retrieved]
    if len(catalog_ids) != len(set(catalog_ids)):
        raise ValueError("retrieved candidate catalog IDs must be unique")
    for item in retrieved:
        score = float(item.retrieval_score)
        if not math.isfinite(score) or not -1.0 <= score <= 1.0:
            raise ValueError(
                "retrieval score must be finite and between -1 and 1"
            )
    ordered = tuple(sorted(
        retrieved,
        key=lambda item: (-item.retrieval_score, item.profile.catalog_id),
    ))

    def assess_window(
        window: tuple[RetrievedProductCandidate, ...],
    ) -> tuple[list[RankedProductCandidate], list[ProductPairAssessment]]:
        ranked_window = []
        rejected_window = []
        for item in window:
            assessment = assess_substitute_product_pair(
                source,
                item.profile,
                function_coverage_resolver=function_coverage_resolver,
            )
            if not assessment.eligible_for_semantic_ranking:
                rejected_window.append(assessment)
                continue
            structured_score = assessment.features.structured_baseline_score
            if structured_score is None:
                raise AssertionError(
                    "eligible pair must have a structured baseline score"
                )
            ranked_window.append(RankedProductCandidate(
                catalog_id=item.profile.catalog_id,
                semantic_score=round(float(item.retrieval_score), 6),
                structured_baseline_score=structured_score,
                assessment=assessment,
            ))
        return ranked_window, rejected_window

    primary_window = ordered[:primary_limit]
    ranked, rejected = assess_window(primary_window)
    fallback_used = False
    retrieval_limit_used = len(primary_window)
    if not ranked and len(ordered) > primary_limit:
        fallback_window = ordered[primary_limit:fallback_limit]
        fallback_ranked, fallback_rejected = assess_window(fallback_window)
        ranked.extend(fallback_ranked)
        rejected.extend(fallback_rejected)
        fallback_used = bool(fallback_window)
        retrieval_limit_used += len(fallback_window)

    ranked.sort(key=lambda item: (
        -item.semantic_score,
        -item.structured_baseline_score,
        item.catalog_id,
    ))
    rejected.sort(key=lambda item: item.candidate_catalog_id)
    return BoundedProductCandidateRanking(
        ranked_candidates=tuple(ranked),
        rejected_pairs=tuple(rejected),
        retrieved_candidate_count=len(ordered),
        retrieval_limit_used=retrieval_limit_used,
        fallback_used=fallback_used,
    )
