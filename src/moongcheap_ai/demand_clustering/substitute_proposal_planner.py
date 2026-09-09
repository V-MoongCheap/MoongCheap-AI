"""Production-facing substitute proposal planner for one refreshed batch."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

import pandas as pd

from ..demand_constraints import DemandConstraintParser, DemandRequirementResult
from .claim_containment_index import IdentityClaimContainmentIndex
from .profile_contract import SUBSTITUTION_EVIDENCE_READY_STATUSES
from .postgres_reader import ClusteringInputBatch
from .substitute_admission import (
    SubstituteBoardAdmissionDecision,
    SubstituteBoardCandidateInput,
    SubstituteDemandInput,
    TextSimilarityScorer,
    select_substitute_board_candidate,
)


RUNTIME_PROFILE_COLUMNS = {
    "catalog_id",
    "product_name",
    "service_category_id",
    "taxonomy_version",
    "product_form",
    "functional_ingredients_json",
    "main_functionality_claim_ids_json",
    "main_functionality_claim_texts_json",
    "intake_method_text",
    "profile_status",
}


@dataclass(frozen=True, slots=True)
class RuntimeCatalogProfile:
    catalog_id: int
    category_id: str
    taxonomy_version: str
    facet_values: Mapping[str, int]
    semantic_text: str


@dataclass(frozen=True, slots=True)
class SkippedSubstituteDemand:
    demand_id: int
    reason_code: str


@dataclass(frozen=True, slots=True)
class SubstituteProposalPlanningResult:
    proposals: tuple[Mapping[str, Any], ...]
    decisions: tuple[SubstituteBoardAdmissionDecision, ...]
    skipped_demands: tuple[SkippedSubstituteDemand, ...]


def _normalized_text(value: object) -> str:
    return re.sub(
        r"\s+",
        "",
        unicodedata.normalize("NFKC", str(value)).casefold(),
    )


def _json_strings(value: object) -> tuple[str, ...]:
    try:
        parsed = json.loads(str(value) or "[]")
    except json.JSONDecodeError as error:
        raise ValueError("profile JSON fields must contain arrays") from error
    if not isinstance(parsed, list):
        raise ValueError("profile JSON fields must contain arrays")
    return tuple(str(item).strip() for item in parsed if str(item).strip())


def _taxonomy_value_indexes(
    taxonomy: Mapping[str, Any],
) -> dict[str, dict[str, dict[str, int]]]:
    indexes: dict[str, dict[str, dict[str, int]]] = {}
    for category in taxonomy.get("categories", ()):
        category_id = str(category["category_id"])
        indexes[category_id] = {}
        for facet in category.get("facets", ()):
            values: dict[str, int] = {}
            for value in facet.get("values", ()):
                code = int(value["code"])
                if code == 0:
                    continue
                normalized = _normalized_text(value["value"])
                values[normalized] = min(code, values.get(normalized, code))
            indexes[category_id][str(facet["name"])] = values
    return indexes


def _mapped_facet_values(
    profile: Mapping[str, Any],
    category_indexes: Mapping[str, Mapping[str, int]],
) -> dict[str, int]:
    mapped: dict[str, int] = {}
    form = _normalized_text(profile["product_form"])
    if form and form in category_indexes.get("product_form", {}):
        mapped["product_form"] = category_indexes["product_form"][form]

    ingredients = _json_strings(profile["functional_ingredients_json"])
    joined_ingredients = _normalized_text(", ".join(ingredients))
    if (
        joined_ingredients
        and joined_ingredients
        in category_indexes.get("functional_ingredients", {})
    ):
        mapped["functional_ingredients"] = category_indexes[
            "functional_ingredients"
        ][joined_ingredients]

    intake = _normalized_text(profile["intake_method_text"])
    frequency_matches = [
        (len(value), code)
        for value, code in category_indexes.get("daily_frequency", {}).items()
        if value and value in intake
    ]
    if frequency_matches:
        mapped["daily_frequency"] = max(frequency_matches)[1]
    return mapped


def build_runtime_catalog_profiles(
    profiles: pd.DataFrame,
    taxonomy: Mapping[str, Any],
) -> dict[int, RuntimeCatalogProfile]:
    """Build immutable board-ranking fields from the MFDS profile artifact."""

    if missing := sorted(RUNTIME_PROFILE_COLUMNS - set(profiles.columns)):
        raise ValueError("profiles missing columns: " + ", ".join(missing))
    normalized = profiles.fillna("").copy()
    if normalized["catalog_id"].astype(str).duplicated().any():
        raise ValueError("profile catalog IDs must be unique")
    taxonomy_indexes = _taxonomy_value_indexes(taxonomy)

    runtime_profiles: dict[int, RuntimeCatalogProfile] = {}
    for row in normalized.to_dict("records"):
        try:
            catalog_id = int(str(row["catalog_id"]).strip())
        except ValueError as error:
            raise ValueError("runtime catalog IDs must be integers") from error
        if catalog_id < 1:
            raise ValueError("runtime catalog IDs must be positive")
        category_id = str(row["service_category_id"]).strip()
        taxonomy_version = str(row["taxonomy_version"]).strip()
        if category_id not in taxonomy_indexes:
            raise ValueError(f"taxonomy is missing category: {category_id}")
        if not taxonomy_version:
            raise ValueError("profile taxonomy versions must not be blank")

        ingredients = _json_strings(row["functional_ingredients_json"])
        functions = _json_strings(
            row["main_functionality_claim_texts_json"]
        )
        semantic_text = "\n".join((
            f"상품명: {row['product_name']}",
            f"서비스 카테고리: {category_id}",
            f"제품 형태: {row['product_form']}",
            "기능성 원료: " + ", ".join(ingredients),
            "공인 기능: " + ", ".join(functions),
            f"섭취 방법: {row['intake_method_text']}",
        ))
        runtime_profiles[catalog_id] = RuntimeCatalogProfile(
            catalog_id=catalog_id,
            category_id=category_id,
            taxonomy_version=taxonomy_version,
            facet_values=_mapped_facet_values(
                row,
                taxonomy_indexes[category_id],
            ),
            semantic_text=semantic_text,
        )
    return runtime_profiles


class ClaimIndexedSubstituteProposalPlanner:
    """Create one Backend-ready proposal per eligible unassigned demand."""

    def __init__(
        self,
        profiles: pd.DataFrame,
        taxonomy: Mapping[str, Any],
        requirement_parser: DemandConstraintParser,
        *,
        text_similarity_scorer: TextSimilarityScorer,
    ) -> None:
        self._claim_index = IdentityClaimContainmentIndex(profiles)
        self._profiles = build_runtime_catalog_profiles(profiles, taxonomy)
        self._requirement_parser = requirement_parser
        self._text_similarity_scorer = text_similarity_scorer

    @property
    def index_summary(self) -> Mapping[str, Any]:
        return self._claim_index.summary

    @property
    def catalog_ids(self) -> frozenset[int]:
        return frozenset(self._profiles)

    def validate_input_profile_coverage(
        self,
        inputs: ClusteringInputBatch,
    ) -> None:
        """Fail before planning when a Backend catalog has no bound profile."""

        input_catalog_ids = {
            item.catalog_id
            for item in (*inputs.demands, *inputs.boards)
        }
        missing = sorted(input_catalog_ids - self.catalog_ids)
        if missing:
            raise ValueError(
                "runtime catalog profiles are missing Backend catalog IDs: "
                + ", ".join(map(str, missing))
            )

    def plan(
        self,
        inputs: ClusteringInputBatch,
        *,
        as_of: datetime,
    ) -> SubstituteProposalPlanningResult:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must include timezone information")
        active_catalog_ids = {
            board.catalog_id
            for board in inputs.boards
            if board.status == "GB_GATHERING" and board.sale_end_at > as_of
        }
        proposals: list[Mapping[str, Any]] = []
        decisions: list[SubstituteBoardAdmissionDecision] = []
        skipped: list[SkippedSubstituteDemand] = []
        prepared_rows: list[
            tuple[
                SubstituteDemandInput,
                DemandRequirementResult,
                tuple[SubstituteBoardCandidateInput, ...],
            ]
        ] = []

        for demand in sorted(inputs.demands, key=lambda item: item.id):
            profile = self._profiles.get(demand.catalog_id)
            lookup = self._claim_index.lookup(
                demand.catalog_id,
                candidate_catalog_ids=active_catalog_ids,
            )
            if (
                profile is None
                or lookup.source_profile_status
                not in SUBSTITUTION_EVIDENCE_READY_STATUSES
            ):
                skipped.append(SkippedSubstituteDemand(
                    demand.id,
                    "SOURCE_FUNCTION_EVIDENCE_NOT_READY",
                ))
                continue

            requirement = self._requirement_parser.interpret(
                profile.category_id,
                demand.extra_requirement or "",
                is_substitutable=demand.is_substitutable is True,
            )
            substitute_demand = SubstituteDemandInput.from_demand(
                demand,
                category_id=profile.category_id,
                taxonomy_version=profile.taxonomy_version,
                requirement=requirement,
            )
            candidate_catalog_ids = set(lookup.candidate_catalog_ids)
            candidates = []
            for board in inputs.boards:
                if (demand.id, board.id) in inputs.rejected_demand_board_pairs:
                    continue
                if str(board.catalog_id) not in candidate_catalog_ids:
                    continue
                candidate_profile = self._profiles[board.catalog_id]
                candidates.append(SubstituteBoardCandidateInput.from_board(
                    board,
                    category_id=candidate_profile.category_id,
                    taxonomy_version=candidate_profile.taxonomy_version,
                    facet_values=candidate_profile.facet_values,
                    semantic_text=candidate_profile.semantic_text,
                ))

            prepared_rows.append((
                substitute_demand,
                requirement,
                tuple(candidates),
            ))

        semantic_queries = tuple(sorted({
            text
            for _, requirement, _ in prepared_rows
            if requirement.effective_requirement_mode == "SEMANTIC_TEXT"
            for text in requirement.semantic_preferences
        }))
        semantic_passages = tuple(sorted({
            candidate.semantic_text
            for _, requirement, candidates in prepared_rows
            if requirement.effective_requirement_mode == "SEMANTIC_TEXT"
            for candidate in candidates
            if candidate.semantic_text.strip()
        }))
        prepare = getattr(self._text_similarity_scorer, "prepare", None)
        if callable(prepare) and semantic_queries and semantic_passages:
            prepare(semantic_queries, semantic_passages)

        for substitute_demand, requirement, candidates in prepared_rows:
            decision = select_substitute_board_candidate(
                substitute_demand,
                candidates,
                as_of=as_of,
                canonicalize_value_code=(
                    self._requirement_parser.canonicalize_value_code
                ),
                text_similarity_scorer=self._text_similarity_scorer,
            )
            decisions.append(decision)
            selected = decision.selected_board
            if selected is None:
                continue
            proposals.append({
                "demandId": substitute_demand.id,
                "originalCatalogId": substitute_demand.catalog_id,
                "substituteCatalogId": selected.catalog_id,
                "demandBoardId": selected.demand_board_id,
                "requirementStatus": requirement.status,
                "effectiveRequirementMode": (
                    requirement.effective_requirement_mode
                ),
                "rankEvidence": selected.to_dict(),
            })

        return SubstituteProposalPlanningResult(
            proposals=tuple(proposals),
            decisions=tuple(decisions),
            skipped_demands=tuple(skipped),
        )

    def __call__(
        self,
        inputs: ClusteringInputBatch,
        *,
        as_of: datetime,
    ) -> tuple[Mapping[str, Any], ...]:
        return self.plan(inputs, as_of=as_of).proposals
