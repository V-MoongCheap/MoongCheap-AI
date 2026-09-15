from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace

from .extractor import (
    ConstraintExtractor,
    ConstraintProof,
    ExtractionResult,
    FacetConstraint,
    SpeakerScope,
)
from .classifier import normalize
from .facet_matcher import KiwiFacetMatcher, MatchedFacet


@dataclass(frozen=True)
class PreferenceGroup:
    group_id: str
    operator: str
    aggregation: str
    members: tuple[FacetConstraint, ...]


@dataclass(frozen=True)
class TaxonomyEquivalence:
    category_id: str
    facet_name: str
    normalized_value: str
    canonical_value_code: int
    canonical_value: str
    equivalent_value_codes: tuple[int, ...]
    equivalent_values: tuple[str, ...]


@dataclass(frozen=True)
class DemandRequirementResult:
    """Demand-level normalization result consumed before board formation.

    Diagnostic states remain observable, but this object neither routes a
    demand nor represents a seller-matching decision.
    """

    status: str
    constraints: tuple[FacetConstraint, ...]
    warnings: tuple[str, ...]
    clauses: tuple[str, ...]
    interpretation_method: str
    preference_groups: tuple[PreferenceGroup, ...] = ()
    semantic_preferences: tuple[str, ...] = ()
    diagnostic_code: str | None = None
    taxonomy_equivalences: tuple[TaxonomyEquivalence, ...] = ()
    effective_requirement_mode: str = "NONE"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "constraints": [asdict(item) for item in self.constraints],
            "warnings": list(self.warnings),
            "clauses": list(self.clauses),
            "interpretation_method": self.interpretation_method,
            "preference_groups": [asdict(item) for item in self.preference_groups],
            "semantic_preferences": list(self.semantic_preferences),
            "diagnostic_code": self.diagnostic_code,
            "taxonomy_equivalences": [
                asdict(item) for item in self.taxonomy_equivalences
            ],
            "effective_requirement_mode": self.effective_requirement_mode,
        }


class ConstraintInputPolicy:
    """Normalize the optional requirement field around the frozen parser."""

    def __init__(
        self,
        matcher: KiwiFacetMatcher,
        extractor: ConstraintExtractor,
    ) -> None:
        self.matcher = matcher
        self.extractor = extractor
        self.classifier = extractor.classifier
        self._equivalence_by_surface: dict[
            tuple[str, str, str], TaxonomyEquivalence
        ] = {}
        self._equivalence_by_code: dict[
            tuple[str, str, int], TaxonomyEquivalence
        ] = {}
        self._canonical_facet: dict[
            tuple[str, str, str], MatchedFacet
        ] = {}
        for group in matcher.normalized_duplicate_groups:
            category_id = group["category_id"]
            facet_name = group["facet_name"]
            normalized_value = group["normalized_value"]
            candidates = tuple(
                candidate
                for candidate in matcher.values[category_id][facet_name]
                if normalize(candidate.value) == normalized_value
            )
            canonical = min(
                candidates,
                key=lambda item: (
                    normalize(item.value) != item.value.casefold().strip(),
                    item.value_code,
                ),
            )
            equivalence = TaxonomyEquivalence(
                category_id=category_id,
                facet_name=facet_name,
                normalized_value=normalized_value,
                canonical_value_code=canonical.value_code,
                canonical_value=canonical.value,
                equivalent_value_codes=tuple(
                    sorted(item.value_code for item in candidates)
                ),
                equivalent_values=tuple(
                    item.value
                    for item in sorted(candidates, key=lambda item: item.value_code)
                ),
            )
            surface_key = (category_id, facet_name, normalized_value)
            self._equivalence_by_surface[surface_key] = equivalence
            self._canonical_facet[surface_key] = canonical
            for candidate in candidates:
                self._equivalence_by_code[
                    (category_id, facet_name, candidate.value_code)
                ] = equivalence

    def _category_key(self, category_id: str) -> str:
        """Resolve taxonomy adapters that provide a root-category fallback."""

        resolver = getattr(self.matcher, "_category_key", None)
        if callable(resolver):
            return str(resolver(category_id))
        return category_id

    def canonicalize_value_code(
        self,
        category_id: str,
        facet_name: str,
        value_code: int,
    ) -> tuple[int, TaxonomyEquivalence | None]:
        """Normalize a taxonomy code consistently at downstream boundaries."""

        category_key = self._category_key(category_id)
        equivalence = self._equivalence_by_code.get(
            (category_key, facet_name, value_code)
        )
        if equivalence is None:
            return value_code, None
        return equivalence.canonical_value_code, equivalence

    def taxonomy_equivalence_groups(self) -> tuple[TaxonomyEquivalence, ...]:
        return tuple(
            self._equivalence_by_surface[key]
            for key in sorted(self._equivalence_by_surface)
        )

    def exact_matches(
        self, category_id: str, text: str
    ) -> tuple[MatchedFacet, ...]:
        value = text.strip()
        if not value:
            return ()
        category_key = self._category_key(category_id)
        normalized_value = normalize(value)
        exact = set()
        for candidates in self.matcher.values.get(category_key, {}).values():
            for candidate in candidates:
                surfaces = (
                    candidate.value,
                    *self.matcher.aliases[
                        (category_key, candidate.facet_name, candidate.value_code)
                    ],
                )
                if any(normalize(surface) == normalized_value for surface in surfaces):
                    exact.add(candidate)
        return tuple(sorted(exact, key=lambda item: (item.facet_name, item.value_code)))

    def unique_exact_match(self, category_id: str, text: str) -> MatchedFacet | None:
        exact = self.exact_matches(category_id, text)
        if len(exact) != 1:
            return None
        return exact[0]

    def resolved_exact_match(
        self, category_id: str, text: str
    ) -> tuple[MatchedFacet | None, TaxonomyEquivalence | None]:
        exact = self.exact_matches(category_id, text)
        if len(exact) == 1:
            return exact[0], None
        if not exact:
            return None, None
        facet_names = {item.facet_name for item in exact}
        normalized_values = {normalize(item.value) for item in exact}
        if len(facet_names) != 1 or len(normalized_values) != 1:
            return None, None
        facet_name = next(iter(facet_names))
        normalized_value = next(iter(normalized_values))
        key = (self._category_key(category_id), facet_name, normalized_value)
        equivalence = self._equivalence_by_surface.get(key)
        if equivalence is None:
            return None, None
        return self._canonical_facet[key], equivalence

    @staticmethod
    def _dedupe_equivalences(
        equivalences: tuple[TaxonomyEquivalence, ...]
    ) -> tuple[TaxonomyEquivalence, ...]:
        by_key = {
            (item.category_id, item.facet_name, item.normalized_value): item
            for item in equivalences
        }
        return tuple(by_key[key] for key in sorted(by_key))

    def equivalences_in_text(
        self, category_id: str, text: str
    ) -> tuple[TaxonomyEquivalence, ...]:
        category_key = self._category_key(category_id)
        grouped: dict[tuple[int, int, str], set[MatchedFacet]] = {}
        for occurrence in self.matcher.occurrences(category_id, text):
            key = (
                occurrence.start,
                occurrence.end,
                occurrence.facet.facet_name,
            )
            grouped.setdefault(key, set()).add(occurrence.facet)
        equivalences = []
        for candidates in grouped.values():
            if len(candidates) < 2:
                continue
            normalized_values = {normalize(item.value) for item in candidates}
            if len(normalized_values) != 1:
                continue
            candidate = next(iter(candidates))
            equivalence = self._equivalence_by_surface.get((
                category_key,
                candidate.facet_name,
                next(iter(normalized_values)),
            ))
            if equivalence is not None:
                equivalences.append(equivalence)
        return self._dedupe_equivalences(tuple(equivalences))

    def resolved_sentence_facets(
        self, category_id: str, text: str
    ) -> tuple[tuple[MatchedFacet, ...], tuple[TaxonomyEquivalence, ...]]:
        matched = self.matcher.match(category_id, text)
        equivalences = self.equivalences_in_text(category_id, text)
        equivalence_facets = {item.facet_name for item in equivalences}
        ambiguous_facets = {
            warning.split(":", 1)[1].strip()
            for warning in matched.warnings
            if warning.startswith("ambiguous values for facet:")
        }
        if ambiguous_facets - equivalence_facets:
            return (), ()

        facets = list(matched.facets)
        for equivalence in equivalences:
            key = (
                equivalence.category_id,
                equivalence.facet_name,
                equivalence.normalized_value,
            )
            canonical = self._canonical_facet[key]
            if canonical not in facets:
                facets.append(canonical)
        by_facet: dict[str, set[int]] = {}
        for facet in facets:
            by_facet.setdefault(facet.facet_name, set()).add(facet.value_code)
        if any(len(value_codes) > 1 for value_codes in by_facet.values()):
            return (), ()
        return tuple(facets), equivalences

    def short_composite_matches(
        self, category_id: str, text: str
    ) -> tuple[MatchedFacet, ...]:
        """Return predicate-free values only when the whole input is explained.

        Multiple values for one facet are deliberately rejected because a flat
        PREFER list cannot prove whether they are AND, OR, or a correction.
        """

        value = text.strip()
        if not value or len(value) > 80:
            return ()
        matched = self.matcher.match(category_id, value)
        if matched.warnings or len(matched.facets) < 2:
            return ()
        facet_names = [facet.facet_name for facet in matched.facets]
        if len(set(facet_names)) != len(facet_names):
            return ()

        occurrences = self.matcher.occurrences(category_id, value)
        spans = []
        for facet in matched.facets:
            candidates = [
                occurrence
                for occurrence in occurrences
                if occurrence.facet == facet
            ]
            if not candidates:
                return ()
            occurrence = max(candidates, key=lambda item: item.end - item.start)
            spans.append((occurrence.start, occurrence.end))

        explained = [False] * len(value)
        for start, end in spans:
            for index in range(start, end):
                explained[index] = True
        remainder = "".join(
            character
            for index, character in enumerate(value)
            if not explained[index]
        )
        remainder = re.sub(r"[\s,;/+·&]+", "", remainder)
        remainder = re.sub(r"(?:그리고|및|와|과)", "", remainder)
        if remainder:
            return ()
        return matched.facets

    @staticmethod
    def _soft_preference_frame(text: str) -> bool:
        value = text.strip()
        unsafe = re.compile(
            r"(?:\s또는\s|\s혹은\s|중\s*하나|제외|배제|빼|피하|말고|"
            r"가능하면\s*(?:반드시|무조건|꼭)|(?:반드시|무조건|꼭)[^.!?]{0,24}만)"
        )
        if unsafe.search(value):
            return False
        patterns = (
            re.compile(r"^가능하면\s+.+(?:인\s+)?제품으로\s+부탁(?:해요|드립니다|드려요)[.!?]?$"),
            re.compile(r"^.+\s+제품이면\s+좋겠(?:어요|습니다)[.!?]?$"),
            re.compile(r"(?:^|[.!?]\s*).+\s+조건을?\s+만족하면\s+좋겠(?:어요|습니다)[.!?]?$"),
        )
        return any(pattern.search(value) for pattern in patterns)

    def soft_preference_matches(
        self, category_id: str, text: str
    ) -> tuple[MatchedFacet, ...]:
        if not self._soft_preference_frame(text):
            return ()
        matched = self.matcher.match(category_id, text)
        if matched.warnings:
            return ()
        facets = list(matched.facets)

        # Kiwi can read a one-syllable product form such as `환인` as part of an
        # inflected word instead of a standalone noun. The narrow UI template
        # exposes its payload boundary, so compare that payload as an exact
        # codebook value without relaxing sentence-internal one-character rules.
        paraphrase = re.fullmatch(
            r"가능하면\s+(.+?)\s+제품으로\s+부탁(?:해요|드립니다|드려요)[.!?]?",
            text.strip(),
        )
        if paraphrase:
            payload = paraphrase.group(1).strip()
            exact = self.unique_exact_match(category_id, payload)
            if exact is None and payload.endswith("인"):
                exact = self.unique_exact_match(category_id, payload[:-1])
            if exact is not None and exact not in facets:
                facets.append(exact)
        return tuple(facets)

    def resolved_soft_preference_matches(
        self, category_id: str, text: str
    ) -> tuple[tuple[MatchedFacet, ...], tuple[TaxonomyEquivalence, ...]]:
        if not self._soft_preference_frame(text):
            return (), ()
        facets, equivalences = self.resolved_sentence_facets(category_id, text)
        facets = list(facets)

        paraphrase = re.fullmatch(
            r"가능하면\s+(.+?)\s+제품으로\s+부탁(?:해요|드립니다|드려요)[.!?]?",
            text.strip(),
        )
        if paraphrase:
            payload = paraphrase.group(1).strip()
            exact, equivalence = self.resolved_exact_match(category_id, payload)
            if exact is None and payload.endswith("인"):
                exact, equivalence = self.resolved_exact_match(
                    category_id, payload[:-1]
                )
            if exact is not None and exact not in facets:
                facets.append(exact)
            if equivalence is not None:
                equivalences = self._dedupe_equivalences(
                    (*equivalences, equivalence)
                )
        return tuple(facets), equivalences

    def _preference_result(
        self,
        category_id: str,
        text: str,
        facets: tuple[MatchedFacet, ...],
        *,
        polarity_source: str,
        modality_scope: str,
    ) -> ExtractionResult:
        occurrences = self.matcher.occurrences(category_id, text)
        constraints = []
        for facet in facets:
            occurrence = next(
                (item for item in occurrences if item.facet == facet),
                None,
            )
            taxonomy_span = (
                (occurrence.start, occurrence.end)
                if occurrence is not None
                else (
                    (literal_start, literal_start + len(facet.value))
                    if (literal_start := text.find(facet.value)) >= 0
                    else (0, len(text))
                )
            )
            proof = ConstraintProof(
                taxonomy_span=taxonomy_span,
                predicate_span=(len(text), len(text)),
                argument_role="NAMED_VALUE",
                set_operation="RANK_NAMED",
                polarity_source=polarity_source,
                modality_scope=modality_scope,
                final_state_order=len(text),
                speaker_scope=SpeakerScope(
                    owner="USER",
                    acceptance="ACCEPTED_BY_INPUT_CONTRACT",
                    evidence_span=(0, len(text)),
                    tail_proof_source="OPTIONAL_SUBSTITUTE_CONDITION_FIELD",
                ),
            )
            constraints.append(FacetConstraint(
                facet_name=facet.facet_name,
                value_code=facet.value_code,
                value=facet.value,
                constraint_type="PREFER",
                evidence_clause=text,
                proof=proof,
            ))
        return ExtractionResult(
            status="PARSED",
            constraints=tuple(constraints),
            warnings=(),
            clauses=(text,),
        )

    @staticmethod
    def _requirement_type(text: str) -> str | None:
        """Classify the small, explicit requirement clauses used by the UI.

        The frozen extractor intentionally rejects ambiguous prose.  These
        clauses are still deterministic: the user names a taxonomy value and
        attaches one of the explicit requirement markers to it.
        """

        value = text.strip()
        if re.search(
            r"(?:제외|금지|빼|없는\s*제품|안\s*들어간|포함되지\s*않은|피하고)",
            value,
        ):
            return "EXCLUDE"
        if re.search(
            r"(?:선호|좋겠|좋을|중요하게\s*보|중요하게\s*봐|먼저\s*보|먼저\s*봐|우선|있으면\s*좋)",
            value,
        ):
            return "PREFER"
        if re.search(r"(?:필수|반드시|꼭|무조건|이어야|여야)", value):
            return "MUST"
        if re.search(r"포함된\s*제품을\s*찾", value):
            return "MUST"
        return None

    def _typed_requirement_result(
        self,
        category_id: str,
        text: str,
        facets: tuple[MatchedFacet, ...],
        constraint_type: str,
    ) -> ExtractionResult:
        base = self._preference_result(
            category_id,
            text,
            facets,
            polarity_source=f"EXPLICIT_{constraint_type}_FRAME",
            modality_scope="EXPLICIT_REQUIREMENT_FRAME",
        )
        operation = {
            "MUST": "KEEP_NAMED",
            "PREFER": "RANK_NAMED",
            "EXCLUDE": "REMOVE_NAMED",
        }[constraint_type]
        constraints = tuple(
            replace(
                item,
                constraint_type=constraint_type,
                proof=(
                    replace(item.proof, set_operation=operation)
                    if item.proof is not None
                    else None
                ),
            )
            for item in base.constraints
        )
        return replace(base, constraints=constraints)

    def _explicit_requirement_result(
        self, category_id: str, text: str
    ) -> ExtractionResult | None:
        """Parse explicit value + marker clauses rejected by older proof rules."""

        normalized = text.strip().rstrip(".!?")
        if re.search(
            r"(?:반드시|필수|꼭)\s*포함하고.{0,40}같은\s*조합.{0,12}제외",
            normalized,
        ):
            return ExtractionResult(
                status="CONFLICT",
                constraints=(),
                warnings=("CONFLICTING_EXPLICIT_REQUIREMENTS",),
                clauses=(text,),
            )
        separator = (
            r"\s*(?:이고|이며|그리고)\s*"
            if re.search(r"(?:이고|이며|그리고)", normalized)
            else r"\s*,\s*"
        )
        clauses = [
            item.strip()
            for item in re.split(separator, normalized)
            if item.strip()
        ]
        typed: list[tuple[str, MatchedFacet]] = []
        for clause in clauses:
            requirement_type = self._requirement_type(clause)
            if requirement_type is None:
                continue
            facets, _ = self.resolved_sentence_facets(category_id, clause)
            if not facets:
                # Product-labelled values are often mentioned without the
                # taxonomy suffix, e.g. ``원료명이 포함된 제품`` versus the
                # canonical ``원료명 제품``. Keep this fallback limited to
                # explicit requirement clauses.
                normalized_clause = normalize(clause)
                loose: list[MatchedFacet] = []
                for facet_values in self.matcher.values.get(category_id, {}).values():
                    for facet in facet_values:
                        candidates = (
                            normalize(facet.value),
                            re.sub(r"\s*제품$", "", normalize(facet.value)),
                        )
                        if any(
                            len(candidate) > 1 and candidate in normalized_clause
                            for candidate in candidates
                        ):
                            loose.append(facet)
                facets = tuple(dict.fromkeys(loose))
            for facet in facets:
                typed.append((requirement_type, facet))
        if not typed:
            return None

        by_value: dict[tuple[str, int], set[str]] = {}
        for requirement_type, facet in typed:
            by_value.setdefault((facet.facet_name, facet.value_code), set()).add(
                requirement_type
            )
        if any({"MUST", "EXCLUDE"} <= types for types in by_value.values()):
            return ExtractionResult(
                status="CONFLICT",
                constraints=(),
                warnings=("CONFLICTING_EXPLICIT_REQUIREMENTS",),
                clauses=(text,),
            )
        if (
            any(requirement_type == "MUST" for requirement_type, _ in typed)
            and re.search(r"(?:다른|같은)\s+[^.!?]{0,20}제외", text)
        ):
            return ExtractionResult(
                status="CONFLICT",
                constraints=(),
                warnings=("CONFLICTING_EXPLICIT_REQUIREMENTS",),
                clauses=(text,),
            )

        constraints: list[FacetConstraint] = []
        for requirement_type, facet in typed:
            result = self._typed_requirement_result(
                category_id, text, (facet,), requirement_type
            )
            constraints.extend(result.constraints)
        return ExtractionResult(
            status="PARSED",
            constraints=tuple(constraints),
            warnings=(),
            clauses=(text,),
        )

    def _explicit_any_of_group(
        self, category_id: str, text: str
    ) -> PreferenceGroup | None:
        normalized = text.strip().rstrip(".!?")
        if not re.search(r"(?:또는|혹은)", normalized):
            return None
        branches = [
            item.strip()
            for item in re.split(r"\s*(?:또는|혹은)\s*", normalized, maxsplit=1)
        ]
        if len(branches) != 2:
            return None
        right = re.sub(r"\s*(?:중\s*)?하나면?.*$", "", branches[1]).strip()
        members: list[FacetConstraint] = []
        for branch in (branches[0], right):
            facet, _ = self.resolved_exact_match(category_id, branch)
            if facet is None:
                matched, _ = self.resolved_sentence_facets(category_id, branch)
                if len(matched) == 1:
                    facet = matched[0]
            if facet is None:
                return None
            members.extend(
                self._typed_requirement_result(
                    category_id,
                    text,
                    (facet,),
                    "PREFER",
                ).constraints
            )
        return PreferenceGroup(
            group_id="alternative-preference-1",
            operator="ANY_OF",
            aggregation="MAX",
            members=tuple(members),
        )

    @staticmethod
    def _consumer_experience_passthrough(text: str) -> bool:
        return bool(
            re.search(r"(?:휴대|삼키|포장|개별\s*포장|보관|맛|향|소화|속|섞)", text)
            and re.search(r"(?:편하|좋겠|좋을|원하|바라|싶)", text)
            and not re.search(
                r"(?:필수|반드시|꼭|제외|금지|없는\s*제품|포함|선택)", text
            )
        )

    def alternative_preference_group(
        self, category_id: str, text: str
    ) -> PreferenceGroup | None:
        match = re.fullmatch(
            r"(.+?)\s+(?:또는|혹은)\s+(.+?)(?:도)?\s+"
            r"괜찮(?:아요|습니다)[.!?]?",
            text.strip(),
        )
        if match is None:
            return None
        left = self.unique_exact_match(category_id, match.group(1))
        right = self.unique_exact_match(category_id, match.group(2))
        if left is None or right is None or left == right:
            return None
        members = self._preference_result(
            category_id,
            text,
            (left, right),
            polarity_source="EXPLICIT_ALTERNATIVE_ACCEPTANCE",
            modality_scope="SOFT_PREFERENCE_ANY_OF",
        ).constraints
        return PreferenceGroup(
            group_id="alternative-preference-1",
            operator="ANY_OF",
            aggregation="MAX",
            members=members,
        )

    def resolved_alternative_preference_group(
        self, category_id: str, text: str
    ) -> tuple[PreferenceGroup | None, tuple[TaxonomyEquivalence, ...]]:
        match = re.fullmatch(
            r"(.+?)\s+(?:또는|혹은)\s+(.+?)(?:도)?\s+"
            r"괜찮(?:아요|습니다)[.!?]?",
            text.strip(),
        )
        if match is None:
            return None, ()
        left, left_equivalence = self.resolved_exact_match(
            category_id, match.group(1)
        )
        right, right_equivalence = self.resolved_exact_match(
            category_id, match.group(2)
        )
        if left is None or right is None or left == right:
            return None, ()
        equivalences = self._dedupe_equivalences(tuple(
            item
            for item in (left_equivalence, right_equivalence)
            if item is not None
        ))
        members = self._preference_result(
            category_id,
            text,
            (left, right),
            polarity_source="EXPLICIT_ALTERNATIVE_ACCEPTANCE",
            modality_scope="SOFT_PREFERENCE_ANY_OF",
        ).constraints
        return PreferenceGroup(
            group_id="alternative-preference-1",
            operator="ANY_OF",
            aggregation="MAX",
            members=members,
        ), equivalences

    def _branch_facets(
        self, category_id: str, text: str
    ) -> tuple[MatchedFacet, ...]:
        exact = self.unique_exact_match(category_id, text)
        if exact is not None:
            return (exact,)
        composite = self.short_composite_matches(category_id, text)
        if composite:
            return composite
        # Retain facets that are individually unambiguous even when another
        # facet in the same branch has a taxonomy-code collision.
        return self.matcher.match(category_id, text).facets

    def conflict_warnings(self, category_id: str, text: str) -> tuple[str, ...]:
        match = re.fullmatch(
            r"(.+?)이면서\s+(.+?)인\s+제품으로\s+부탁(?:해요|드립니다)[.!?]?",
            text.strip(),
        )
        if match is None:
            return ()
        left = self._branch_facets(category_id, match.group(1))
        right = self._branch_facets(category_id, match.group(2))
        conflicts = {
            (left_item.facet_name, left_item.value_code, right_item.value_code)
            for left_item in left
            for right_item in right
            if left_item.facet_name == right_item.facet_name
            and left_item.value_code != right_item.value_code
        }
        return tuple(
            f"CONFLICTING_VALUES:{facet_name}:{left_code}:{right_code}"
            for facet_name, left_code, right_code in sorted(conflicts)
        )

    @staticmethod
    def _conjunction_match(text: str) -> re.Match[str] | None:
        return re.fullmatch(
            r"(.+?)이면서\s+(.+?)인\s+제품으로\s+부탁(?:해요|드립니다)[.!?]?",
            text.strip(),
        )

    def _resolved_branch_facets(
        self, category_id: str, text: str
    ) -> tuple[tuple[MatchedFacet, ...], tuple[TaxonomyEquivalence, ...]]:
        exact, equivalence = self.resolved_exact_match(category_id, text)
        if exact is not None:
            return (exact,), ((equivalence,) if equivalence is not None else ())
        return self.resolved_sentence_facets(category_id, text)

    def resolved_conflict(
        self, category_id: str, text: str
    ) -> tuple[
        tuple[str, ...],
        tuple[MatchedFacet, ...],
        tuple[TaxonomyEquivalence, ...],
    ]:
        match = self._conjunction_match(text)
        if match is None:
            return (), (), ()
        left, left_equivalences = self._resolved_branch_facets(
            category_id, match.group(1)
        )
        right, right_equivalences = self._resolved_branch_facets(
            category_id, match.group(2)
        )
        equivalences = self._dedupe_equivalences(
            (*left_equivalences, *right_equivalences)
        )
        conflicts = {
            (left_item.facet_name, left_item.value_code, right_item.value_code)
            for left_item in left
            for right_item in right
            if left_item.facet_name == right_item.facet_name
            and left_item.value_code != right_item.value_code
        }
        warnings = tuple(
            f"CONFLICTING_VALUES:{facet_name}:{left_code}:{right_code}"
            for facet_name, left_code, right_code in sorted(conflicts)
        )
        combined = tuple(dict.fromkeys((*left, *right)))
        return warnings, combined, equivalences

    def has_taxonomy_code_collision(self, category_id: str, text: str) -> bool:
        grouped: dict[tuple[int, int, str], set[int]] = {}
        for occurrence in self.matcher.occurrences(category_id, text):
            key = (
                occurrence.start,
                occurrence.end,
                occurrence.facet.facet_name,
            )
            grouped.setdefault(key, set()).add(occurrence.facet.value_code)
        return any(len(value_codes) > 1 for value_codes in grouped.values())

    def lexical_aversion_result(
        self, category_id: str, text: str
    ) -> ExtractionResult | None:
        match = re.fullmatch(
            r"(.+?)(?:은|는|을|를)\s+피하고\s+싶(?:어요|습니다)[.!?]?",
            text.strip(),
        )
        if match is None:
            return None
        facet = self.unique_exact_match(category_id, match.group(1))
        if facet is None:
            return None
        predicate_start = text.find("피하고")
        proof = ConstraintProof(
            taxonomy_span=(0, len(match.group(1))),
            predicate_span=(predicate_start, predicate_start + len("피하고")),
            argument_role="NAMED_VALUE",
            set_operation="REMOVE_NAMED",
            polarity_source="EXPLICIT_AVERSION_PREDICATE",
            modality_scope="USER_AVERSION",
            final_state_order=predicate_start,
            speaker_scope=SpeakerScope(
                owner="USER",
                acceptance="EXPLICIT",
                evidence_span=(0, len(text)),
                tail_proof_source="DIRECT_USER_AVERSION",
            ),
        )
        return ExtractionResult(
            status="PARSED",
            constraints=(FacetConstraint(
                facet_name=facet.facet_name,
                value_code=facet.value_code,
                value=facet.value,
                constraint_type="EXCLUDE",
                evidence_clause=text,
                proof=proof,
            ),),
            warnings=(),
            clauses=(text,),
        )

    def resolved_lexical_aversion_result(
        self, category_id: str, text: str
    ) -> tuple[ExtractionResult | None, tuple[TaxonomyEquivalence, ...]]:
        match = re.fullmatch(
            r"(.+?)(?:은|는|을|를)\s+피하고\s+싶(?:어요|습니다)[.!?]?",
            text.strip(),
        )
        if match is None:
            return None, ()
        facet, equivalence = self.resolved_exact_match(
            category_id, match.group(1)
        )
        if facet is None:
            return None, ()
        predicate_start = text.find("피하고")
        proof = ConstraintProof(
            taxonomy_span=(0, len(match.group(1))),
            predicate_span=(predicate_start, predicate_start + len("피하고")),
            argument_role="NAMED_VALUE",
            set_operation="REMOVE_NAMED",
            polarity_source="EXPLICIT_AVERSION_PREDICATE",
            modality_scope="USER_AVERSION",
            final_state_order=predicate_start,
            speaker_scope=SpeakerScope(
                owner="USER",
                acceptance="EXPLICIT",
                evidence_span=(0, len(text)),
                tail_proof_source="DIRECT_USER_AVERSION",
            ),
        )
        result = ExtractionResult(
            status="PARSED",
            constraints=(FacetConstraint(
                facet_name=facet.facet_name,
                value_code=facet.value_code,
                value=facet.value,
                constraint_type="EXCLUDE",
                evidence_clause=text,
                proof=proof,
            ),),
            warnings=(),
            clauses=(text,),
        )
        return result, ((equivalence,) if equivalence is not None else ())

    @staticmethod
    def _channel_preference(text: str, facet: MatchedFacet) -> ExtractionResult:
        value = text.strip()
        proof = ConstraintProof(
            taxonomy_span=(0, len(value)),
            predicate_span=(len(value), len(value)),
            argument_role="NAMED_VALUE",
            set_operation="RANK_NAMED",
            polarity_source="INPUT_CHANNEL_DEFAULT_PREFER",
            modality_scope="UI_POLICY_DEFAULT",
            final_state_order=len(value),
            speaker_scope=SpeakerScope(
                owner="USER",
                acceptance="ACCEPTED_BY_INPUT_CONTRACT",
                evidence_span=(0, len(value)),
                tail_proof_source="OPTIONAL_SUBSTITUTE_CONDITION_FIELD",
            ),
        )
        return ExtractionResult(
            status="PARSED",
            constraints=(FacetConstraint(
                facet_name=facet.facet_name,
                value_code=facet.value_code,
                value=facet.value,
                constraint_type="PREFER",
                evidence_clause=value,
                proof=proof,
            ),),
            warnings=(),
            clauses=(value,),
        )

    def interpret(
        self,
        category_id: str,
        text: str,
        *,
        is_substitutable: bool,
    ) -> DemandRequirementResult:
        value = text.strip()
        if (
            not is_substitutable
            and self.classifier.ignore_requirement_when_substitution_disabled
        ):
            return DemandRequirementResult(
                status="NOT_APPLICABLE",
                constraints=(),
                warnings=(),
                clauses=(),
                interpretation_method="IGNORED_SUBSTITUTION_DISABLED",
                effective_requirement_mode="NONE",
            )
        if not value:
            return DemandRequirementResult(
                status="NONE",
                constraints=(),
                warnings=(),
                clauses=(),
                interpretation_method="NO_REQUIREMENT",
                effective_requirement_mode="NONE",
            )

        baseline = self.extractor.extract(category_id, value)
        interpreted = baseline
        method = "V042_LANGUAGE_PROOF"
        taxonomy_equivalences: tuple[TaxonomyEquivalence, ...] = ()
        preference_groups: tuple[PreferenceGroup, ...] = ()
        semantic_preferences: tuple[str, ...] = ()
        # These explicit input-channel forms carry enough user intent to be
        # structured even when the older sentence-proof extractor declines
        # them. Consumer-experience wording remains semantic text instead of
        # being forced into a product facet.
        if self._consumer_experience_passthrough(value):
            interpreted = ExtractionResult("PASSTHROUGH", (), (), (value,))
            semantic_preferences = (value,)
            method = "CONSUMER_EXPERIENCE_PASSTHROUGH"
        elif baseline.status == "REVIEW" and (
            explicit_group := self._explicit_any_of_group(category_id, value)
        ):
            interpreted = ExtractionResult("PARSED", (), (), (value,))
            preference_groups = (explicit_group,)
            method = "EXPLICIT_ALTERNATIVE_PREFERENCE_GROUP"
        elif explicit_result := self._explicit_requirement_result(category_id, value):
            # A conflict must override a parsed removal from the legacy
            # extractor. Other explicit recovery is only applied when the
            # legacy proof gate returned REVIEW; this preserves established
            # behavior for already-covered fixtures.
            reported_or_negated = re.search(
                r"(?:말고|하지\s*말고|라고|말씀|선생님|의사|누가|들었)",
                value,
            )
            direct_exclusion = re.search(
                r"(?:없는\s*제품|안\s*들어간.*(?:찾|골라|선택))", value
            )
            recoverable_frame = re.search(
                r"(?:포함\s*여부를\s*(?:중요하게|먼저)\s*(?:보|봐)|"
                r"포함은\s*(?:필수|선호)|"
                r"포함된\s*제품을\s*찾)",
                value,
            )
            simple_conflict = (
                explicit_result.status == "CONFLICT"
                and (
                    re.search(
                        r"(?:필수|반드시|꼭).{0,30}포함.{0,30}(?:제외|금지)",
                        value,
                    )
                    or re.search(r"(?:다른|같은)\s+[^.!?]{0,20}제외", value)
                )
                and not re.search(
                    r"(?:가능하면|생각해보니|최종|빼지\s*말|비교|결정|추천|말씀|선생님)",
                    value,
                )
            )
            if (
                simple_conflict
                or (
                    baseline.status == "REVIEW"
                    and not reported_or_negated
                    and recoverable_frame
                )
                or (explicit_result.status == "PARSED" and direct_exclusion)
            ):
                interpreted = explicit_result
                method = "EXPLICIT_REQUIREMENT_FRAME"
        if self.classifier.input_channel_default_prefer_exact_value:
            if self.classifier.input_channel_equivalent_taxonomy_codes:
                exact, equivalence = self.resolved_exact_match(category_id, value)
                if equivalence is not None:
                    taxonomy_equivalences = (equivalence,)
            else:
                exact = self.unique_exact_match(category_id, value)
            if exact is not None:
                interpreted = self._channel_preference(value, exact)
                method = "UI_DEFAULT_PREFER_EXACT_VALUE"
        if method == "V042_LANGUAGE_PROOF" and (
            self.classifier.input_channel_default_prefer_short_composite
        ) and (
            composite := self.short_composite_matches(category_id, value)
        ):
            interpreted = self._preference_result(
                category_id,
                value,
                composite,
                polarity_source="INPUT_CHANNEL_DEFAULT_PREFER",
                modality_scope="UI_POLICY_SHORT_COMPOSITE",
            )
            method = "UI_DEFAULT_PREFER_SHORT_COMPOSITE"
        if method == "V042_LANGUAGE_PROOF" and (
            self.classifier.input_channel_soft_preference_frame
        ):
            if self.classifier.input_channel_equivalent_taxonomy_codes:
                soft_facets, soft_equivalences = (
                    self.resolved_soft_preference_matches(category_id, value)
                )
            else:
                soft_facets = self.soft_preference_matches(category_id, value)
                soft_equivalences = ()
            if soft_facets:
                interpreted = self._preference_result(
                    category_id,
                    value,
                    soft_facets,
                    polarity_source="EXPLICIT_SOFT_PREFERENCE_FRAME",
                    modality_scope="SOFT_PREFERENCE",
                )
                taxonomy_equivalences = self._dedupe_equivalences(
                    (*taxonomy_equivalences, *soft_equivalences)
                )
                method = "EXPLICIT_SOFT_PREFERENCE_FRAME"

        diagnostic_code = None
        if interpreted.status == "REVIEW" and self.classifier.input_channel_lexical_aversion_frame:
            if self.classifier.input_channel_equivalent_taxonomy_codes:
                aversion, aversion_equivalences = (
                    self.resolved_lexical_aversion_result(category_id, value)
                )
            else:
                aversion = self.lexical_aversion_result(category_id, value)
                aversion_equivalences = ()
            if aversion is not None:
                interpreted = aversion
                taxonomy_equivalences = self._dedupe_equivalences(
                    (*taxonomy_equivalences, *aversion_equivalences)
                )
                method = "EXPLICIT_LEXICAL_AVERSION_FRAME"
        if (
            interpreted.status == "REVIEW"
            and self.classifier.input_channel_alternative_preference_group
        ):
            if self.classifier.input_channel_equivalent_taxonomy_codes:
                preference_group, group_equivalences = (
                    self.resolved_alternative_preference_group(category_id, value)
                )
            else:
                preference_group = self.alternative_preference_group(category_id, value)
                group_equivalences = ()
            if preference_group is not None:
                interpreted = ExtractionResult("PARSED", (), (), (value,))
                preference_groups = (preference_group,)
                taxonomy_equivalences = self._dedupe_equivalences(
                    (*taxonomy_equivalences, *group_equivalences)
                )
                method = "EXPLICIT_ALTERNATIVE_PREFERENCE_GROUP"
        if (
            interpreted.status == "REVIEW"
            and self.classifier.input_channel_typed_nonblocking_states
        ):
            combined_facets: tuple[MatchedFacet, ...] = ()
            if self.classifier.input_channel_equivalent_taxonomy_codes:
                conflict, combined_facets, conflict_equivalences = (
                    self.resolved_conflict(category_id, value)
                )
                taxonomy_equivalences = self._dedupe_equivalences(
                    (*taxonomy_equivalences, *conflict_equivalences)
                )
            else:
                conflict = self.conflict_warnings(category_id, value)
            if conflict:
                interpreted = ExtractionResult("CONFLICT", (), conflict, (value,))
                diagnostic_code = "CONFLICTING_SAME_FACET_VALUES"
                method = "TYPED_CONFLICT_STATE"
            elif (
                self.classifier.input_channel_equivalent_taxonomy_codes
                and self._conjunction_match(value) is not None
                and combined_facets
                and conflict_equivalences
            ):
                interpreted = self._preference_result(
                    category_id,
                    value,
                    combined_facets,
                    polarity_source="EQUIVALENT_CODE_REDUNDANT_CONJUNCTION",
                    modality_scope="UI_POLICY_CONJUNCTION",
                )
                method = "EQUIVALENT_CODE_REDUNDANT_CONJUNCTION"
            elif self.has_taxonomy_code_collision(category_id, value) or any(
                warning.startswith("ambiguous values for facet:")
                for warning in interpreted.warnings
            ):
                interpreted = ExtractionResult(
                    "TAXONOMY_AMBIGUOUS",
                    (),
                    interpreted.warnings,
                    interpreted.clauses,
                )
                diagnostic_code = "NORMALIZED_VALUE_CODE_COLLISION"
                method = "TYPED_TAXONOMY_AMBIGUITY"
            elif (
                self._soft_preference_frame(value)
                and not self.matcher.match(category_id, value).facets
            ):
                interpreted = ExtractionResult("PASSTHROUGH", (), (), (value,))
                semantic_preferences = (value,)
                method = "FREE_TEXT_PREFERENCE_PASSTHROUGH"

        if interpreted.status == "PARSED":
            effective_requirement_mode = "STRUCTURED"
        elif interpreted.status == "PASSTHROUGH":
            effective_requirement_mode = "SEMANTIC_TEXT"
        else:
            # Conflict, taxonomy ambiguity, and unexpected REVIEW remain
            # diagnostic only. They must not block board formation or create a
            # requirement signal that downstream code might accidentally score.
            effective_requirement_mode = "NONE"

        return DemandRequirementResult(
            status=interpreted.status,
            constraints=interpreted.constraints,
            warnings=interpreted.warnings,
            clauses=interpreted.clauses,
            interpretation_method=method,
            preference_groups=preference_groups,
            semantic_preferences=semantic_preferences,
            diagnostic_code=diagnostic_code,
            taxonomy_equivalences=taxonomy_equivalences,
            effective_requirement_mode=effective_requirement_mode,
        )
