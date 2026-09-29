"""Part A-only extensions for the shared demand input policy.

The base policy is used by Part B and remains unchanged.  This subclass adds
the stricter Part A routing for explicit requirement frames and broader
conflict diagnostics without changing B's parser behavior.
"""

from __future__ import annotations

import re
from dataclasses import replace

from ..demand_constraints.input_policy import (
    ConstraintInputPolicy,
    DemandRequirementResult,
)
from ..demand_constraints.classifier import normalize
from ..demand_constraints.extractor import ExtractionResult
from ..demand_constraints.facet_matcher import MatchedFacet


class PartAConstraintInputPolicy(ConstraintInputPolicy):
    """A-specific policy layered on top of the stable shared policy."""

    @staticmethod
    def _explicit_requirement_type(text: str) -> str | None:
        normalized = normalize(text)
        if re.search(r"(?:피하|제외|금지|말고|없는\s*제품|포함되지\s*않)", normalized):
            return "EXCLUDE"
        if re.search(r"(?:꼭|반드시|무조건)", normalized):
            return "MUST"
        if "가능하면" in normalized or re.search(r"(?:선호|좋겠|좋을|우선)", normalized):
            return "PREFER"
        if re.search(r"(?:원해요|원합니다|필요해요|찾아|원하는)", normalized):
            return "MUST"
        return None

    @staticmethod
    def _compact_value(value: str) -> str:
        value = re.sub(r"\([^)]*\)", "", value)
        return re.sub(r"[\s\-_/·,]", "", normalize(value))

    def _explicit_requirement_facets(
        self, category_id: str, text: str
    ) -> tuple[MatchedFacet, ...]:
        compact_text = self._compact_value(text)
        candidates: list[MatchedFacet] = []
        category_key = self._category_key(category_id)
        for facet_values in self.matcher.values.get(category_key, {}).values():
            for candidate in facet_values:
                value = candidate.value.removesuffix(" 제품")
                compact_value = self._compact_value(value)
                components = [
                    self._compact_value(part)
                    for part in re.split(r",|/|또는|혹은|및|와|과", value)
                    if self._compact_value(part)
                ]
                found = bool(
                    compact_value
                    and (len(compact_value) > 1 or "형태" in normalize(text))
                    and (
                        compact_value in compact_text
                        or len(components) > 1
                        and all(component in compact_text for component in components)
                    )
                )
                frequency = re.fullmatch(r"1일\s*([0-9０-９]+)회", candidate.value)
                if frequency:
                    number = frequency.group(1).translate(
                        str.maketrans("０１２３４５６７８９", "0123456789")
                    )
                    korean_number = {
                        "1": "한", "2": "두", "3": "세", "4": "네", "5": "다섯"
                    }.get(number, number)
                    found = bool(
                        re.search(
                            rf"(?:1일|하루)(?:에)?\s*(?:{number}|{korean_number})\s*(?:회|번)",
                            normalize(text),
                        )
                    )
                if "오메가-3" in candidate.value and re.search(r"오메가\s*3", normalize(text)):
                    found = True
                if found:
                    candidates.append(candidate)

        by_facet: dict[str, list[MatchedFacet]] = {}
        for candidate in candidates:
            by_facet.setdefault(candidate.facet_name, []).append(candidate)
        selected: list[MatchedFacet] = []
        for values in by_facet.values():
            unique = {item.value_code: item for item in values}
            ranked = sorted(
                unique.values(),
                key=lambda item: (
                    len(self._compact_value(item.value.removesuffix(" 제품"))),
                    -item.value_code,
                ),
                reverse=True,
            )
            if ranked:
                selected.append(ranked[0])
        return tuple(sorted(selected, key=lambda item: (item.facet_name, item.value_code)))

    def _explicit_requirement_result(
        self, category_id: str, text: str
    ) -> ExtractionResult | None:
        normalized = normalize(text)
        has_negative = bool(
            re.search(r"(?:피하|제외|금지|말고|없는\s*제품|포함되지\s*않)", normalized)
        )
        has_positive = bool(
            re.search(r"(?:원해요|원합니다|필요해요|찾아|원하는|꼭|반드시|무조건|포함해)", normalized)
        )
        if has_negative and has_positive:
            return None
        requirement_type = self._explicit_requirement_type(text)
        if requirement_type is None:
            return None
        facets = self._explicit_requirement_facets(category_id, text)
        if not facets:
            return None
        parsed = self._preference_result(
            category_id,
            text,
            facets,
            polarity_source=f"EXPLICIT_{requirement_type}_FRAME",
            modality_scope="EXPLICIT_REQUIREMENT_FRAME",
        )
        constraints = tuple(
            replace(item, constraint_type=requirement_type)
            for item in parsed.constraints
        )
        return replace(parsed, constraints=constraints)

    @staticmethod
    def _conflict_branches(text: str) -> tuple[str, str] | None:
        value = text.strip()
        match = re.fullmatch(
            r"(.+?)이면서\s+(.+?)인\s+제품으로\s+부탁(?:해요|드립니다)[.!?]?",
            value,
        )
        if match:
            return match.group(1), match.group(2)
        match = re.fullmatch(
            r"(.+?)(?:이어야|여야)\s*하지만,?\s*(?:동시에\s*)?(.+?)(?:이어야|여야)\s*(?:해요|합니다)?[.!?]?",
            value,
        )
        if match:
            return match.group(1), match.group(2)
        match = re.fullmatch(
            r"(.+?)(?:이어야|여야)\s*하지만,?\s*(?:동시에\s*)?(.+?)(?:피하고\s*싶어(?:요|해요|합니다)?)[.!?]?",
            value,
        )
        return (
            (match.group(1), f"{match.group(2)} 피하고 싶어요")
            if match
            else None
        )

    def _branch_constraint_type(self, text: str) -> str:
        """Return the branch polarity used only for A conflict diagnostics."""
        explicit = self._explicit_requirement_type(text)
        if explicit is not None:
            return explicit
        if re.search(r"(?:이어야|여야)", normalize(text)):
            return "MUST"
        return "MUST"

    @staticmethod
    def _values_conflict(
        left_code: int,
        right_code: int,
        left_type: str,
        right_type: str,
    ) -> bool:
        if left_code == right_code:
            return {left_type, right_type} == {"MUST", "EXCLUDE"}
        return left_type != "EXCLUDE" and right_type != "EXCLUDE"

    @staticmethod
    def _conjunction_match(text: str) -> re.Match[str] | None:
        # Keep the shared policy's match contract for its original sentence
        # shape.  The additional A-only shapes are handled by
        # ``resolved_conflict`` before delegating to the shared policy.
        return re.fullmatch(
            r"(.+?)이면서\s+(.+?)인\s+제품으로\s+부탁(?:해요|드립니다)[.!?]?",
            text.strip(),
        )

    def conflict_warnings(self, category_id: str, text: str) -> tuple[str, ...]:
        branches = self._conflict_branches(text)
        if branches is None:
            return ()
        left = self._branch_facets(category_id, branches[0])
        right = self._branch_facets(category_id, branches[1])
        left_type = self._branch_constraint_type(branches[0])
        right_type = self._branch_constraint_type(branches[1])
        conflicts = {
            (left_item.facet_name, left_item.value_code, right_item.value_code)
            for left_item in left
            for right_item in right
            if left_item.facet_name == right_item.facet_name
            and self._values_conflict(
                left_item.value_code,
                right_item.value_code,
                left_type,
                right_type,
            )
        }
        return tuple(
            f"CONFLICTING_VALUES:{facet}:{left_code}:{right_code}"
            for facet, left_code, right_code in sorted(conflicts)
        )

    def resolved_conflict(self, category_id: str, text: str):
        branches = self._conflict_branches(text)
        if branches is None:
            return (), (), ()
        left, left_equivalences = self._resolved_branch_facets(category_id, branches[0])
        right, right_equivalences = self._resolved_branch_facets(category_id, branches[1])
        left_type = self._branch_constraint_type(branches[0])
        right_type = self._branch_constraint_type(branches[1])
        equivalences = self._dedupe_equivalences((*left_equivalences, *right_equivalences))
        conflicts = {
            (left_item.facet_name, left_item.value_code, right_item.value_code)
            for left_item in left
            for right_item in right
            if left_item.facet_name == right_item.facet_name
            and self._values_conflict(
                left_item.value_code,
                right_item.value_code,
                left_type,
                right_type,
            )
        }
        warnings = tuple(
            f"CONFLICTING_VALUES:{facet}:{left_code}:{right_code}"
            for facet, left_code, right_code in sorted(conflicts)
        )
        return warnings, tuple(dict.fromkeys((*left, *right))), equivalences

    def interpret(self, category_id: str, text: str, *, is_substitutable: bool):
        value = text.strip()
        if value and is_substitutable and self.classifier.input_channel_typed_nonblocking_states:
            branches = self._conflict_branches(value)
            if branches is not None:
                left, left_equivalences = self._resolved_branch_facets(category_id, branches[0])
                right, right_equivalences = self._resolved_branch_facets(category_id, branches[1])
                left_type = self._branch_constraint_type(branches[0])
                right_type = self._branch_constraint_type(branches[1])
                branch_conflicts = {
                    (left_item.facet_name, left_item.value_code, right_item.value_code)
                    for left_item in left
                    for right_item in right
                    if left_item.facet_name == right_item.facet_name
                    and self._values_conflict(
                        left_item.value_code,
                        right_item.value_code,
                        left_type,
                        right_type,
                    )
                }
                if not branch_conflicts and left and right:
                    facets = tuple(dict.fromkeys((*left, *right)))
                    parsed = self._preference_result(
                        category_id,
                        value,
                        facets,
                        polarity_source="A_BRANCH_POLARITY",
                        modality_scope="EXPLICIT_REQUIREMENT_FRAME",
                    )
                    types = {
                        (item.facet_name, item.value_code): left_type
                        for item in left
                    }
                    types.update({
                        (item.facet_name, item.value_code): right_type
                        for item in right
                    })
                    constraints = tuple(
                        replace(
                            item,
                            constraint_type=types.get(
                                (item.facet_name, item.value_code),
                                item.constraint_type,
                            ),
                        )
                        for item in parsed.constraints
                    )
                    return DemandRequirementResult(
                        status="PARSED",
                        constraints=constraints,
                        warnings=(),
                        clauses=(value,),
                        interpretation_method="A_BRANCH_POLARITY",
                        effective_requirement_mode="STRUCTURED",
                        taxonomy_equivalences=self._dedupe_equivalences(
                            (*left_equivalences, *right_equivalences)
                        ),
                    )
            conflict, _, equivalences = self.resolved_conflict(category_id, value)
            if conflict:
                return DemandRequirementResult(
                    status="CONFLICT",
                    constraints=(),
                    warnings=conflict,
                    clauses=(value,),
                    interpretation_method="TYPED_CONFLICT_STATE",
                    effective_requirement_mode="NONE",
                    diagnostic_code="CONFLICTING_SAME_FACET_VALUES",
                    taxonomy_equivalences=equivalences,
                )
        result = super().interpret(
            category_id,
            text,
            is_substitutable=is_substitutable,
        )
        baseline = self.extractor.extract(category_id, value) if value else None
        safe_review = baseline is not None and baseline.status == "REVIEW" and all(
            warning.startswith(("PREDICATE_EVENT_UNRESOLVED:", "NO_FACET_CONSTRAINT_EXTRACTED"))
            for warning in baseline.warnings
        )
        explicit = None
        if value and safe_review:
            explicit = self._explicit_requirement_result(category_id, value)
        if explicit is None:
            return result
        return replace(
            result,
            status=explicit.status,
            constraints=explicit.constraints,
            warnings=explicit.warnings,
            clauses=explicit.clauses,
            interpretation_method="EXPLICIT_REQUIREMENT_FRAME",
            effective_requirement_mode="STRUCTURED",
        )
