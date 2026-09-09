"""Select one existing alternative-catalog board for user confirmation.

This module consumes the normalized service demand-requirement result.  It is a
pure planning boundary: it neither updates a demand nor increments a board's
confirmed participant count.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..demand_constraints import DemandRequirementResult, FacetConstraint
from .input_models import DemandBoardInput, DemandInput


ALLOWED_REQUIREMENT_MODES = {"STRUCTURED", "SEMANTIC_TEXT", "NONE"}


@dataclass(frozen=True, slots=True)
class SubstituteDemandInput:
    """A Backend demand joined with its catalog and normalized requirement data."""

    id: int
    catalog_id: int
    category_id: str
    taxonomy_version: str
    desired_price_min: int
    desired_price_max: int
    quantity: int
    is_substitutable: bool
    requirement: DemandRequirementResult
    status: str
    desire_end_at: datetime

    @classmethod
    def from_demand(
        cls,
        demand: DemandInput,
        *,
        category_id: str,
        taxonomy_version: str,
        requirement: DemandRequirementResult,
    ) -> SubstituteDemandInput:
        required = {
            "desired_price_min": demand.desired_price_min,
            "desired_price_max": demand.desired_price_max,
            "quantity": demand.quantity,
            "desire_end_at": demand.desire_end_at,
        }
        missing = sorted(name for name, value in required.items() if value is None)
        if missing:
            raise ValueError(f"substitute demand fields are unresolved: {missing}")
        return cls(
            id=demand.id,
            catalog_id=demand.catalog_id,
            category_id=category_id,
            taxonomy_version=taxonomy_version,
            desired_price_min=int(demand.desired_price_min),
            desired_price_max=int(demand.desired_price_max),
            quantity=int(demand.quantity),
            is_substitutable=demand.is_substitutable is True,
            requirement=requirement,
            status=str(demand.status or ""),
            desire_end_at=demand.desire_end_at,
        )

    def __post_init__(self) -> None:
        if not self.category_id.strip() or not self.taxonomy_version.strip():
            raise ValueError("category_id and taxonomy_version must not be empty")
        if self.desired_price_min < 0 or self.desired_price_max < 0:
            raise ValueError("desired prices must not be negative")
        if self.desired_price_min > self.desired_price_max:
            raise ValueError("desired price min must not exceed max")
        if not 1 <= self.quantity <= 99:
            raise ValueError("quantity must be between 1 and 99")
        if (
            self.desire_end_at.tzinfo is None
            or self.desire_end_at.utcoffset() is None
        ):
            raise ValueError("desire_end_at must include timezone information")


@dataclass(frozen=True, slots=True)
class SubstituteBoardCandidateInput:
    """An active-board row joined with immutable catalog profile fields."""

    id: int
    catalog_id: int
    category_id: str
    taxonomy_version: str
    price_min: int
    price_max: int
    participant_count: int
    facet_values: Mapping[str, int]
    sale_end_at: datetime
    status: str
    semantic_text: str = ""

    @classmethod
    def from_board(
        cls,
        board: DemandBoardInput,
        *,
        category_id: str,
        taxonomy_version: str,
        facet_values: Mapping[str, int],
        semantic_text: str = "",
    ) -> SubstituteBoardCandidateInput:
        required = {
            "price_min": board.price_min,
            "price_max": board.price_max,
        }
        missing = sorted(name for name, value in required.items() if value is None)
        if missing:
            raise ValueError(f"substitute board fields are unresolved: {missing}")
        return cls(
            id=board.id,
            catalog_id=board.catalog_id,
            category_id=category_id,
            taxonomy_version=taxonomy_version,
            price_min=int(board.price_min),
            price_max=int(board.price_max),
            participant_count=board.participant_count,
            facet_values=dict(facet_values),
            sale_end_at=board.sale_end_at,
            status=board.status,
            semantic_text=semantic_text,
        )

    def __post_init__(self) -> None:
        if not self.category_id.strip() or not self.taxonomy_version.strip():
            raise ValueError("category_id and taxonomy_version must not be empty")
        if self.price_min < 0 or self.price_max < 0:
            raise ValueError("board prices must not be negative")
        if self.price_min > self.price_max:
            raise ValueError("board price min must not exceed max")
        if self.participant_count < 0:
            raise ValueError("participant_count must not be negative")
        if self.sale_end_at.tzinfo is None or self.sale_end_at.utcoffset() is None:
            raise ValueError("sale_end_at must include timezone information")


@dataclass(frozen=True, slots=True)
class RejectedSubstituteBoard:
    demand_board_id: int
    catalog_id: int
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "demandBoardId": self.demand_board_id,
            "catalogId": self.catalog_id,
            "reasonCodes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class RankedSubstituteBoard:
    demand_board_id: int
    catalog_id: int
    rank: int
    structured_preference_matched: int
    structured_preference_total: int
    structured_preference_score: float
    text_similarity_score: float | None
    participant_count: int
    matched_preferences: tuple[str, ...]
    unmatched_preferences: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "demandBoardId": self.demand_board_id,
            "catalogId": self.catalog_id,
            "rank": self.rank,
            "structuredPreferenceMatched": self.structured_preference_matched,
            "structuredPreferenceTotal": self.structured_preference_total,
            "structuredPreferenceScore": self.structured_preference_score,
            "textSimilarityScore": self.text_similarity_score,
            "participantCount": self.participant_count,
            "matchedPreferences": list(self.matched_preferences),
            "unmatchedPreferences": list(self.unmatched_preferences),
        }


@dataclass(frozen=True, slots=True)
class SubstituteBoardAdmissionDecision:
    demand_id: int
    status: str
    reason_codes: tuple[str, ...]
    ranked_boards: tuple[RankedSubstituteBoard, ...]
    rejected_boards: tuple[RejectedSubstituteBoard, ...]

    @property
    def selected_board(self) -> RankedSubstituteBoard | None:
        return self.ranked_boards[0] if self.ranked_boards else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "demandId": self.demand_id,
            "status": self.status,
            "reasonCodes": list(self.reason_codes),
            "selectedBoard": (
                self.selected_board.to_dict()
                if self.selected_board is not None
                else None
            ),
            "rankedBoards": [item.to_dict() for item in self.ranked_boards],
            "rejectedBoards": [item.to_dict() for item in self.rejected_boards],
        }


CodeCanonicalizer = Callable[[str, str, int], int | tuple[int, object | None]]
TextSimilarityScorer = Callable[[str, str], float]


def character_ngram_cosine_similarity(left: str, right: str) -> float:
    """Return a dependency-free lexical baseline for scorer contract tests."""

    def grams(text: str) -> Counter[str]:
        normalized = re.sub(
            r"\s+",
            " ",
            unicodedata.normalize("NFKC", text).casefold(),
        ).strip()
        compact = re.sub(r"\s+", "", normalized)
        if not compact:
            return Counter()
        if len(compact) == 1:
            return Counter((compact,))
        return Counter(
            compact[index : index + 2]
            for index in range(len(compact) - 1)
        )

    left_grams = grams(left)
    right_grams = grams(right)
    if not left_grams or not right_grams:
        return 0.0
    numerator = sum(
        count * right_grams.get(token, 0)
        for token, count in left_grams.items()
    )
    left_norm = math.sqrt(sum(count * count for count in left_grams.values()))
    right_norm = math.sqrt(sum(count * count for count in right_grams.values()))
    return round(numerator / (left_norm * right_norm), 6)


def _canonical_code(
    canonicalizer: CodeCanonicalizer | None,
    category_id: str,
    facet_name: str,
    value_code: int,
) -> int:
    if canonicalizer is None:
        return value_code
    result = canonicalizer(category_id, facet_name, value_code)
    return int(result[0] if isinstance(result, tuple) else result)


def _facet_matches(
    signal: FacetConstraint,
    demand: SubstituteDemandInput,
    candidate: SubstituteBoardCandidateInput,
    canonicalizer: CodeCanonicalizer | None,
) -> bool | None:
    actual = candidate.facet_values.get(signal.facet_name)
    if actual in {None, 0}:
        return None
    expected_code = _canonical_code(
        canonicalizer,
        demand.category_id,
        signal.facet_name,
        signal.value_code,
    )
    actual_code = _canonical_code(
        canonicalizer,
        demand.category_id,
        signal.facet_name,
        int(actual),
    )
    return actual_code == expected_code


def _validate_requirement(
    demand: SubstituteDemandInput,
    canonicalizer: CodeCanonicalizer | None,
) -> tuple[str, ...]:
    mode = demand.requirement.effective_requirement_mode
    if mode not in ALLOWED_REQUIREMENT_MODES:
        raise ValueError(f"unknown effective requirement mode: {mode}")
    if mode != "STRUCTURED":
        return ()

    must_by_facet: dict[str, set[int]] = {}
    excludes: set[tuple[str, int]] = set()
    for item in demand.requirement.constraints:
        if item.constraint_type not in {"MUST", "PREFER", "EXCLUDE"}:
            raise ValueError(f"unknown constraint type: {item.constraint_type}")
        code = _canonical_code(
            canonicalizer,
            demand.category_id,
            item.facet_name,
            item.value_code,
        )
        if item.constraint_type == "MUST":
            must_by_facet.setdefault(item.facet_name, set()).add(code)
        elif item.constraint_type == "EXCLUDE":
            excludes.add((item.facet_name, code))

    reasons = []
    if any(len(codes) > 1 for codes in must_by_facet.values()):
        reasons.append("CONFLICTING_MUST_VALUES")
    if any(
        (facet_name, code) in excludes
        for facet_name, codes in must_by_facet.items()
        for code in codes
    ):
        reasons.append("MUST_EXCLUDE_CONFLICT")
    return tuple(reasons)


def select_substitute_board_candidate(
    demand: SubstituteDemandInput,
    candidates: Iterable[SubstituteBoardCandidateInput],
    *,
    as_of: datetime,
    canonicalize_value_code: CodeCanonicalizer | None = None,
    text_similarity_scorer: TextSimilarityScorer | None = None,
) -> SubstituteBoardAdmissionDecision:
    """Rank existing alternative-catalog boards and expose one top candidate.

    The ordinary same-catalog assignment path must run before this function.
    A returned candidate is only a proposal and is not a confirmed assignment.
    """

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must include timezone information")
    candidate_rows = tuple(candidates)
    candidate_ids = [item.id for item in candidate_rows]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("duplicate demand board id")

    if not demand.is_substitutable:
        return SubstituteBoardAdmissionDecision(
            demand.id,
            "NOT_ELIGIBLE",
            ("SUBSTITUTION_NOT_CONSENTED",),
            (),
            (),
        )
    if demand.status != "UNASSIGNED":
        return SubstituteBoardAdmissionDecision(
            demand.id,
            "NOT_ELIGIBLE",
            ("DEMAND_NOT_UNASSIGNED",),
            (),
            (),
        )
    if demand.desire_end_at <= as_of:
        return SubstituteBoardAdmissionDecision(
            demand.id,
            "NOT_ELIGIBLE",
            ("DEMAND_EXPIRED",),
            (),
            (),
        )

    invalid_signal = _validate_requirement(demand, canonicalize_value_code)
    if invalid_signal:
        return SubstituteBoardAdmissionDecision(
            demand.id,
            "INVALID_REQUIREMENT_SIGNAL",
            invalid_signal,
            (),
            (),
        )

    requirement = demand.requirement
    if requirement.effective_requirement_mode == "STRUCTURED":
        constraints = requirement.constraints
        preference_groups = requirement.preference_groups
    else:
        constraints = ()
        preference_groups = ()
    musts = tuple(item for item in constraints if item.constraint_type == "MUST")
    excludes = tuple(
        item for item in constraints if item.constraint_type == "EXCLUDE"
    )
    preferences = tuple(
        item for item in constraints if item.constraint_type == "PREFER"
    )
    semantic_preferences = (
        requirement.semantic_preferences
        if requirement.effective_requirement_mode == "SEMANTIC_TEXT"
        else ()
    )

    eligible: list[
        tuple[
            SubstituteBoardCandidateInput,
            int,
            int,
            float,
            float | None,
            tuple[str, ...],
            tuple[str, ...],
        ]
    ] = []
    rejected: list[RejectedSubstituteBoard] = []

    for candidate in candidate_rows:
        reasons: list[str] = []
        if candidate.catalog_id == demand.catalog_id:
            reasons.append("SAME_AS_ORIGINAL_CATALOG")
        if candidate.category_id != demand.category_id:
            reasons.append("CATEGORY_MISMATCH")
        if candidate.taxonomy_version != demand.taxonomy_version:
            reasons.append("TAXONOMY_VERSION_MISMATCH")
        if candidate.status != "GB_GATHERING":
            reasons.append("BOARD_NOT_GATHERING")
        if candidate.sale_end_at <= as_of:
            reasons.append("BOARD_NOT_ACTIVE")
        if candidate.price_max > demand.desired_price_max:
            reasons.append("PRICE_MAX_EXCEEDS_DEMAND")

        for item in musts:
            matched = _facet_matches(
                item,
                demand,
                candidate,
                canonicalize_value_code,
            )
            if matched is None:
                reasons.append(f"UNKNOWN_MUST_FACET:{item.facet_name}")
            elif not matched:
                reasons.append(f"MUST_MISMATCH:{item.facet_name}")
        for item in excludes:
            matched = _facet_matches(
                item,
                demand,
                candidate,
                canonicalize_value_code,
            )
            if matched is None:
                reasons.append(f"UNKNOWN_EXCLUDE_FACET:{item.facet_name}")
            elif matched:
                reasons.append(f"EXCLUDED_VALUE:{item.facet_name}")

        if reasons:
            rejected.append(RejectedSubstituteBoard(
                candidate.id,
                candidate.catalog_id,
                tuple(dict.fromkeys(reasons)),
            ))
            continue

        matched_preferences = []
        unmatched_preferences = []
        for item in preferences:
            label = f"{item.facet_name}:{item.value}"
            if _facet_matches(
                item,
                demand,
                candidate,
                canonicalize_value_code,
            ):
                matched_preferences.append(label)
            else:
                unmatched_preferences.append(label)

        for group in preference_groups:
            if group.operator != "ANY_OF" or group.aggregation != "MAX":
                raise ValueError("only ANY_OF + MAX preference groups are supported")
            group_matched = any(
                _facet_matches(
                    item,
                    demand,
                    candidate,
                    canonicalize_value_code,
                )
                is True
                for item in group.members
            )
            label = f"{group.group_id}:ANY_OF_MAX"
            if group_matched:
                matched_preferences.append(label)
            else:
                unmatched_preferences.append(label)

        structured_total = len(preferences) + len(preference_groups)
        structured_matched = len(matched_preferences)
        structured_score = (
            round(structured_matched / structured_total, 6)
            if structured_total
            else 0.0
        )

        text_score = None
        if (
            semantic_preferences
            and text_similarity_scorer is not None
            and candidate.semantic_text.strip()
        ):
            scores = tuple(
                float(text_similarity_scorer(text, candidate.semantic_text))
                for text in semantic_preferences
            )
            if any(
                not math.isfinite(score) or not 0.0 <= score <= 1.0
                for score in scores
            ):
                raise ValueError("text similarity score must be between 0 and 1")
            text_score = round(max(scores), 6)

        eligible.append((
            candidate,
            structured_matched,
            structured_total,
            structured_score,
            text_score,
            tuple(matched_preferences),
            tuple(unmatched_preferences),
        ))

    eligible.sort(key=lambda row: (
        -row[1],
        -row[3],
        -(row[4] is not None),
        -(row[4] if row[4] is not None else 0.0),
        -row[0].participant_count,
        row[0].id,
    ))
    ranked = tuple(
        RankedSubstituteBoard(
            demand_board_id=row[0].id,
            catalog_id=row[0].catalog_id,
            rank=index,
            structured_preference_matched=row[1],
            structured_preference_total=row[2],
            structured_preference_score=row[3],
            text_similarity_score=row[4],
            participant_count=row[0].participant_count,
            matched_preferences=row[5],
            unmatched_preferences=row[6],
        )
        for index, row in enumerate(eligible, 1)
    )
    return SubstituteBoardAdmissionDecision(
        demand_id=demand.id,
        status="CANDIDATE_SELECTED" if ranked else "NO_COMPATIBLE_BOARD",
        reason_codes=() if ranked else ("NO_COMPATIBLE_BOARD",),
        ranked_boards=ranked,
        rejected_boards=tuple(sorted(rejected, key=lambda item: item.demand_board_id)),
    )


def build_substitute_board_admission_plan(
    items: Iterable[tuple[SubstituteDemandInput, SubstituteBoardAdmissionDecision]],
    *,
    batch_id: str,
    planned_at: datetime,
    rule_version: str,
    text_scorer_version: str | None = None,
) -> dict[str, Any]:
    """Build the persistence-neutral one-candidate Backend handoff."""

    if not batch_id.strip():
        raise ValueError("batch_id must not be empty")
    if not rule_version.strip():
        raise ValueError("rule_version must not be empty")
    if planned_at.tzinfo is None or planned_at.utcoffset() is None:
        raise ValueError("planned_at must include timezone information")

    item_rows = tuple(items)
    proposals = []
    not_eligible = []
    unmatched = []
    seen_demand_ids: set[int] = set()
    for demand, result in sorted(item_rows, key=lambda item: item[0].id):
        if demand.id in seen_demand_ids:
            raise ValueError(f"duplicate demand id: {demand.id}")
        seen_demand_ids.add(demand.id)
        if result.demand_id != demand.id:
            raise ValueError("demand/result id mismatch")

        selected = result.selected_board
        if result.status == "CANDIDATE_SELECTED" and selected is not None:
            if not demand.is_substitutable or demand.status != "UNASSIGNED":
                raise ValueError("selected demand is not eligible for a proposal")
            if selected.catalog_id == demand.catalog_id:
                raise ValueError("substitute catalog must differ from original catalog")
            proposals.append({
                "demandId": demand.id,
                "action": "PROPOSE_SUBSTITUTE_BOARD_ADMISSION",
                "fromStatus": "UNASSIGNED",
                "proposedStatus": "SUBSTITUTE_OFFERED",
                "originalCatalogId": demand.catalog_id,
                "substituteCatalogId": selected.catalog_id,
                "demandBoardId": selected.demand_board_id,
                "quantityToCarry": demand.quantity,
                "requiresUserConfirmation": True,
                "participantCountDeltaOnProposal": 0,
                "participantCountDeltaOnAccept": 1,
                "onAcceptStatus": "ASSIGNED",
                "onRejectStatus": "UNASSIGNED",
                "clearDemandBoardIdOnReject": True,
                "requirementStatus": demand.requirement.status,
                "effectiveRequirementMode": (
                    demand.requirement.effective_requirement_mode
                ),
                "rankEvidence": selected.to_dict(),
            })
        elif selected is not None:
            raise ValueError("only CANDIDATE_SELECTED may contain ranked boards")
        elif result.status == "CANDIDATE_SELECTED":
            raise ValueError("selected result must contain at least one ranked board")
        elif result.status == "NOT_ELIGIBLE":
            not_eligible.append({
                "demandId": demand.id,
                "reasonCodes": list(result.reason_codes),
            })
        else:
            unmatched.append({
                "demandId": demand.id,
                "reasonCodes": list(result.reason_codes),
            })

    return {
        "schemaVersion": "substitute-board-admission-plan.v0.1",
        "batchId": batch_id,
        "plannedAt": planned_at.isoformat(),
        "ruleVersion": rule_version,
        "textScorerVersion": text_scorer_version,
        "proposals": proposals,
        "notEligible": not_eligible,
        "unmatched": unmatched,
        "stateContract": {
            "proposal": "UNASSIGNED_TO_SUBSTITUTE_OFFERED",
            "accept": "SUBSTITUTE_OFFERED_TO_ASSIGNED",
            "reject": "SUBSTITUTE_OFFERED_TO_UNASSIGNED",
            "proposalIncrementsParticipantCount": False,
        },
    }
