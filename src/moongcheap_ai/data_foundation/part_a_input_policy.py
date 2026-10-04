"""Part A-only extensions for the shared demand input policy.

The base policy is used by Part B and remains unchanged.  This subclass adds
the stricter Part A routing for explicit requirement frames and broader
conflict diagnostics without changing B's parser behavior.
"""

from __future__ import annotations

import re
from dataclasses import replace

from ..demand_constraints.classifier import normalize
from ..demand_constraints.extractor import ExtractionResult
from ..demand_constraints.facet_matcher import MatchedFacet
from ..demand_constraints.input_policy import (
    ConstraintInputPolicy,
    DemandRequirementResult,
)


class PartAConstraintInputPolicy(ConstraintInputPolicy):
    """A-specific policy layered on top of the stable shared policy."""

    @staticmethod
    def _explicit_requirement_type(text: str) -> str | None:
        normalized = normalize(text)
        if re.search(r"(?:피하|제외|금지|말고|없는\s*제품|포함되지\s*않)", normalized):
            return "EXCLUDE"
        if re.search(r"(?:꼭|반드시|무조건)", normalized):
            return "MUST"
        if "가능하면" in normalized or re.search(
            r"(?:선호|좋겠|좋을|우선)", normalized
        ):
            return "PREFER"
        if re.search(r"(?:원해요|원합니다|필요해요|찾아|원하는)", normalized):
            return "MUST"
        return None

    @staticmethod
    def _compact_value(value: str) -> str:
        # Parenthetical letters/numbers can distinguish atomic values (C/D,
        # concentrations, etc.). Never erase them before evidence matching.
        # Preserve separators too: deleting the comma in "분말, 캡슐" would
        # fabricate a word boundary and hide the first independent value.
        return re.sub(r"\s", "", normalize(value))

    @staticmethod
    def is_non_purchase_context(text: str) -> bool:
        """Conservatively reject role/code instructions and reported examples.

        This guard is A-only. It does not treat harmless product questions as
        attacks, nor remove quoted text and then reinterpret the remainder.
        """
        value = normalize(text)
        return bool(
            re.search(
                r"(?:\[/?(?:system|assistant|developer)\]|<\|(?:im_start|im_end|system|assistant)[^>]*>"
                r"|(?:이전|위의|기존)\s*(?:지시|명령).*?(?:무시|잊)"
                r"|(?:코드|json|스키마|schema|label|라벨).*?(?:변경하라|출력하라|바꿔라)"
                r"|\b(?:drop\s+table|update\s+\w+\s+set|delete\s+from)\b"
                r"|번역(?:만)?\s*(?:해|하)|(?:예시|예문|문서).*?[\"“‘']"
                r"|(?:가격|뜻|의미|정의).*?(?:알려|설명)"
                r"|[\"”’'].*?(?:문서의?\s*예시|예문(?:입니다|이에요))"
                r"|(?:제|내|저의|저는)\s*(?:요청|요구(?:사항)?|조건).*?(?:아닙|없|추가하지)"
                r"|(?:친구|다른\s*사람).*?(?:요청|썼|원해))",
                value,
            )
        )

    def _atomic_mentions(self, category_id: str, text: str) -> tuple[MatchedFacet, ...]:
        """Keep maximal evidence spans per Facet, not nested alias substrings."""
        compact = self._compact_value(text)
        key = self._category_key(category_id)
        matches: list[tuple[int, int, MatchedFacet]] = []
        for name, values in self.matcher.values.get(key, {}).items():
            for candidate in values:
                if candidate.value_code == 0:
                    continue
                surfaces = (
                    candidate.value,
                    *self.matcher.aliases.get((key, name, candidate.value_code), ()),
                )
                if "오메가-3" in candidate.value and not re.search(
                    r"[,/]", candidate.value
                ):
                    surfaces = (*surfaces, "오메가3")
                for surface in surfaces:
                    token = self._compact_value(surface)
                    if len(token) < 2:
                        continue
                    for found in re.finditer(re.escape(token), compact):
                        tail = compact[found.end() :]
                        if (
                            name == "product_form"
                            and tail
                            and re.match(r"[가-힣a-z0-9]", tail)
                            and not re.match(
                                r"(?:은|는|이|가|을|를|로|으로|형태|제형|제품|좀|만|주세요|원해|원합|필요|함유|포함|과|와|및|또는|혹은|대신|보다|거나)",
                                tail,
                            )
                        ):
                            continue
                        matches.append((*found.span(), candidate))
                frequency = re.fullmatch(r"1일\s*([0-9０-９]+)회", candidate.value)
                if frequency:
                    number = normalize(frequency.group(1))
                    korean = {
                        "1": "한",
                        "2": "두",
                        "3": "세",
                        "4": "네",
                        "5": "다섯",
                    }.get(number, number)
                    for found in re.finditer(
                        rf"(?:1일|하루)(?:에)?(?:{number}|{korean})(?:회|번)", compact
                    ):
                        matches.append((*found.span(), candidate))
        kept = {
            candidate
            for start, end, candidate in matches
            if not any(
                (
                    other.facet_name == candidate.facet_name
                    or (
                        candidate.facet_name == "product_form"
                        and other.facet_name == "functional_ingredients"
                    )
                )
                and other_start <= start
                and end <= other_end
                and other_end - other_start > end - start
                for other_start, other_end, other in matches
            )
        }
        return tuple(sorted(kept, key=lambda item: (item.facet_name, item.value_code)))

    def _mentioned_value_codes_by_facet(
        self, category_id: str, text: str
    ) -> dict[str, set[int]]:
        mentioned: dict[str, set[int]] = {}
        for candidate in self._atomic_mentions(category_id, text):
            mentioned.setdefault(candidate.facet_name, set()).add(candidate.value_code)
        return mentioned

    def _has_unresolved_positive_multi_value(
        self, category_id: str, text: str, result: DemandRequirementResult
    ) -> bool:
        """Detect when a positive parse drops another mentioned value in that Facet."""
        mentions = self._mentioned_value_codes_by_facet(category_id, text)
        if any(
            item.constraint_type in {"MUST", "PREFER"} and "," in item.value
            for item in result.constraints
        ):
            return True
        if (
            result.status != "PARSED"
            or result.effective_requirement_mode != "STRUCTURED"
        ):
            return any(len(codes) > 1 for codes in mentions.values())

        positive_codes: dict[str, set[int]] = {}
        excluded_codes: dict[str, set[int]] = {}
        for item in result.constraints:
            target = (
                excluded_codes if item.constraint_type == "EXCLUDE" else positive_codes
            )
            target.setdefault(item.facet_name, set()).add(item.value_code)

        group_codes: dict[str, set[int]] = {}
        for group in result.preference_groups:
            for item in group.members:
                group_codes.setdefault(item.facet_name, set()).add(item.value_code)

        for facet_name, mentioned_codes in mentions.items():
            if len(mentioned_codes) < 2:
                continue
            positives = positive_codes.get(facet_name, set())
            if not positives:
                continue
            if len(positives) > 1 and not positives.issubset(
                group_codes.get(facet_name, set())
            ):
                return True
            represented = (
                positives
                | excluded_codes.get(facet_name, set())
                | group_codes.get(facet_name, set())
            )
            if not mentioned_codes.issubset(represented):
                return True
        return False

    def _explicit_requirement_facets(
        self, category_id: str, text: str
    ) -> tuple[MatchedFacet, ...]:
        candidates = list(self._atomic_mentions(category_id, text))
        # One-character forms need token boundaries rather than substrings.
        candidates.extend(
            occurrence.facet
            for occurrence in self.matcher.occurrences(category_id, text)
            if len(self._compact_value(occurrence.facet.value)) == 1
            and occurrence.end - occurrence.start == 1
        )

        by_facet: dict[str, list[MatchedFacet]] = {}
        for candidate in candidates:
            by_facet.setdefault(candidate.facet_name, []).append(candidate)
        selected: list[MatchedFacet] = []
        for values in by_facet.values():
            unique = {item.value_code: item for item in values}
            # Never select one code arbitrarily from ambiguous or independent
            # same-Facet mentions. The runtime retains the product baseline.
            if len(unique) == 1:
                selected.append(next(iter(unique.values())))
        return tuple(
            sorted(selected, key=lambda item: (item.facet_name, item.value_code))
        )

    def _explicit_requirement_result(
        self, category_id: str, text: str
    ) -> ExtractionResult | None:
        normalized = normalize(text)
        has_negative = bool(
            re.search(r"(?:피하|제외|금지|말고|없는\s*제품|포함되지\s*않)", normalized)
        )
        has_positive = bool(
            re.search(
                r"(?:원해요|원합니다|필요해요|찾아|원하는|꼭|반드시|무조건|포함해)",
                normalized,
            )
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
        return (match.group(1), f"{match.group(2)} 피하고 싶어요") if match else None

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
        right, right_equivalences = self._resolved_branch_facets(
            category_id, branches[1]
        )
        left_type = self._branch_constraint_type(branches[0])
        right_type = self._branch_constraint_type(branches[1])
        equivalences = self._dedupe_equivalences(
            (*left_equivalences, *right_equivalences)
        )
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
        if self.is_non_purchase_context(value):
            return DemandRequirementResult(
                status="REVIEW",
                constraints=(),
                warnings=("NON_PURCHASE_CONTEXT",),
                clauses=(value,),
                interpretation_method="A_PURCHASE_SCOPE_GUARD",
                effective_requirement_mode="NONE",
                diagnostic_code="NON_PURCHASE_CONTEXT",
            )
        if (
            value
            and is_substitutable
            and self.classifier.input_channel_typed_nonblocking_states
        ):
            branches = self._conflict_branches(value)
            if branches is not None:
                left, left_equivalences = self._resolved_branch_facets(
                    category_id, branches[0]
                )
                right, right_equivalences = self._resolved_branch_facets(
                    category_id, branches[1]
                )
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
                        (item.facet_name, item.value_code): left_type for item in left
                    }
                    types.update(
                        {
                            (item.facet_name, item.value_code): right_type
                            for item in right
                        }
                    )
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
        safe_review = (
            baseline is not None
            and baseline.status == "REVIEW"
            and all(
                warning.startswith(
                    ("PREDICATE_EVENT_UNRESOLVED:", "NO_FACET_CONSTRAINT_EXTRACTED")
                )
                for warning in baseline.warnings
            )
        )
        explicit = None
        if value and safe_review:
            explicit = self._explicit_requirement_result(category_id, value)
        if explicit is not None:
            result = replace(
                result,
                status=explicit.status,
                constraints=explicit.constraints,
                warnings=explicit.warnings,
                clauses=explicit.clauses,
                interpretation_method="EXPLICIT_REQUIREMENT_FRAME",
                effective_requirement_mode="STRUCTURED",
            )
        if self._has_unresolved_positive_multi_value(category_id, value, result):
            return replace(
                result,
                status="REVIEW",
                constraints=(),
                preference_groups=(),
                semantic_preferences=(),
                warnings=("MULTIPLE_VALUES_SAME_FACET_UNRESOLVED",),
                interpretation_method="A_MULTI_VALUE_FACET_REVIEW",
                diagnostic_code="MULTIPLE_VALUES_SAME_FACET_UNRESOLVED",
                effective_requirement_mode="NONE",
            )
        return result
