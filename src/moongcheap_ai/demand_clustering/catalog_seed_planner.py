"""Substitute-board planning against the Backend v5 catalog seed.

The Backend owns numeric ``product_catalog.id`` values, while the reviewed v5
seed contains stable source IDs but the current Backend schema does not persist
them.  Runtime binding is therefore an exact join on the Backend-unique product
name.  Missing or edited names disable substitution for that product without
blocking same-catalog board formation.

This production path deliberately does not infer MFDS function claims.  It
uses the v5 leaf category as the candidate gate, preserves the existing Part B
MUST/PREFER/EXCLUDE parser, and derives only taxonomy values that occur
explicitly in the seller product name.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from ..demand_constraints import DemandConstraintParser, DemandRequirementResult
from .postgres_reader import ClusteringInputBatch
from .substitute_admission import (
    SubstituteBoardAdmissionDecision,
    SubstituteBoardCandidateInput,
    SubstituteDemandInput,
    TextSimilarityScorer,
    select_substitute_board_candidate,
)
from .substitute_proposal_planner import (
    SkippedSubstituteDemand,
    SubstituteProposalPlanningResult,
)

CATALOG_SEED_COLUMNS = {
    "catalog_seed_id",
    "source_product_id",
    "name",
    "category_seed_id",
    "source_category_path",
    "source_category_id",
    "status",
}


@dataclass(frozen=True, slots=True)
class RuntimeSeedCatalogProfile:
    """Immutable fields derived from one checked-in v5 seed row."""

    catalog_name: str
    category_seed_id: str
    category_id: str
    taxonomy_version: str
    facet_values: Mapping[str, int]
    semantic_text: str


def _text(value: object) -> str:
    return str(value or "").strip()


def _normalized_text(value: object) -> str:
    return re.sub(
        r"\s+",
        "",
        unicodedata.normalize("NFKC", _text(value)).casefold(),
    )


def _taxonomy_version(taxonomy: Mapping[str, Any]) -> str:
    version = _text(taxonomy.get("version") or taxonomy.get("taxonomy_version"))
    if not version:
        raise ValueError("taxonomy version must not be blank")
    return version


def _taxonomy_categories(
    taxonomy: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    categories = {
        _text(row.get("category_id")): row
        for row in taxonomy.get("categories", ())
        if isinstance(row, Mapping) and _text(row.get("category_id"))
    }
    if not categories:
        raise ValueError("taxonomy must contain categories")
    return categories


def _explicit_name_facets(
    name: str,
    category: Mapping[str, Any],
) -> dict[str, int]:
    """Map only taxonomy values or aliases explicitly visible in a name."""

    normalized_name = _normalized_text(name)
    mapped: dict[str, int] = {}
    for facet in category.get("facets", ()):
        if not isinstance(facet, Mapping):
            continue
        facet_name = _text(facet.get("name"))
        matches: list[tuple[int, int]] = []
        for value in facet.get("values", ()):
            if not isinstance(value, Mapping):
                continue
            code = int(value.get("code", 0))
            if code == 0:
                continue
            surfaces = (
                _text(value.get("value")),
                *(
                    _text(alias)
                    for alias in value.get("aliases", ())
                    if _text(alias)
                ),
            )
            for surface in surfaces:
                normalized_surface = _normalized_text(surface)
                # One-character values such as "정" otherwise match brand
                # names such as "정관장". Require at least two normalized
                # characters; uncertain forms remain unknown and are handled
                # conservatively by the admission gate.
                if (
                    len(normalized_surface) >= 2
                    and normalized_surface in normalized_name
                ):
                    matches.append((len(normalized_surface), code))
        if matches:
            mapped[facet_name] = max(matches, key=lambda item: (item[0], -item[1]))[1]
    return mapped


def build_runtime_seed_catalog(
    seed: pd.DataFrame,
    taxonomy: Mapping[str, Any],
) -> dict[str, RuntimeSeedCatalogProfile]:
    """Validate v5 rows and index them by Backend-unique product name."""

    if missing := sorted(CATALOG_SEED_COLUMNS - set(seed.columns)):
        raise ValueError("catalog seed missing columns: " + ", ".join(missing))
    if seed.empty:
        raise ValueError("catalog seed must not be empty")

    normalized = seed.fillna("").copy()
    normalized["name"] = normalized["name"].astype(str).str.strip()
    if normalized["name"].eq("").any():
        raise ValueError("catalog seed names must not be blank")
    if normalized["name"].duplicated().any():
        raise ValueError("catalog seed names must be unique")
    for column, label in (
        ("catalog_seed_id", "catalog seed IDs"),
        ("source_product_id", "source product IDs"),
    ):
        values = normalized[column].astype(str).str.strip()
        if values.eq("").any() or values.duplicated().any():
            raise ValueError(f"{label} must be nonempty and unique")

    categories = _taxonomy_categories(taxonomy)
    version = _taxonomy_version(taxonomy)
    profiles: dict[str, RuntimeSeedCatalogProfile] = {}
    for row in normalized.to_dict("records"):
        name = _text(row["name"])
        category_seed_id = _text(row["category_seed_id"])
        category_id = _text(row["source_category_id"])
        status = _text(row["status"])
        if not category_seed_id:
            raise ValueError("catalog seed category IDs must not be blank")
        if status not in {"ACTIVE", "INACTIVE"}:
            raise ValueError(f"unsupported catalog seed status: {status}")
        category = categories.get(category_id)
        if category_id and category is None:
            raise ValueError(f"taxonomy is missing category: {category_id}")
        facet_values = (
            _explicit_name_facets(name, category)
            if category is not None
            else {}
        )
        profiles[name] = RuntimeSeedCatalogProfile(
            catalog_name=name,
            category_seed_id=category_seed_id,
            category_id=category_id,
            taxonomy_version=version,
            facet_values=facet_values,
            semantic_text="\n".join((
                f"상품명: {name}",
                f"도매꾹 카테고리: {_text(row['source_category_path'])}",
            )),
        )
    return profiles


class CatalogSeedSubstituteProposalPlanner:
    """Plan opt-in substitutions from the v5 leaf-category catalog contract."""

    def __init__(
        self,
        seed: pd.DataFrame,
        taxonomy: Mapping[str, Any],
        requirement_parser: DemandConstraintParser,
        *,
        text_similarity_scorer: TextSimilarityScorer,
    ) -> None:
        self._profiles = build_runtime_seed_catalog(seed, taxonomy)
        self._requirement_parser = requirement_parser
        self._text_similarity_scorer = text_similarity_scorer

    @property
    def catalog_names(self) -> frozenset[str]:
        return frozenset(self._profiles)

    def plan(
        self,
        inputs: ClusteringInputBatch,
        *,
        as_of: datetime,
    ) -> SubstituteProposalPlanningResult:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must include timezone information")

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
            source = self._profiles.get(_text(demand.catalog_name))
            if source is None:
                skipped.append(SkippedSubstituteDemand(
                    demand.id,
                    "SOURCE_CATALOG_SEED_NOT_FOUND",
                ))
                continue
            if not source.category_id:
                skipped.append(SkippedSubstituteDemand(
                    demand.id,
                    "SOURCE_CATEGORY_NOT_MAPPED",
                ))
                continue

            requirement = self._requirement_parser.interpret(
                source.category_id,
                demand.extra_requirement or "",
                is_substitutable=demand.is_substitutable is True,
            )
            substitute_demand = SubstituteDemandInput.from_demand(
                demand,
                category_id=source.category_id,
                taxonomy_version=source.taxonomy_version,
                requirement=requirement,
            )
            source_ingredient = source.facet_values.get("functional_ingredients")
            candidates = []
            for board in inputs.boards:
                if (demand.id, board.id) in inputs.rejected_demand_board_pairs:
                    continue
                candidate = self._profiles.get(_text(board.catalog_name))
                if candidate is None or not candidate.category_id:
                    continue
                if candidate.category_seed_id != source.category_seed_id:
                    continue
                if candidate.category_id != source.category_id:
                    continue
                if (
                    source_ingredient is not None
                    and candidate.facet_values.get("functional_ingredients")
                    != source_ingredient
                ):
                    continue
                candidates.append(SubstituteBoardCandidateInput.from_board(
                    board,
                    category_id=candidate.category_id,
                    taxonomy_version=candidate.taxonomy_version,
                    facet_values=candidate.facet_values,
                    semantic_text=candidate.semantic_text,
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
