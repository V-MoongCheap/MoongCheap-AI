from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold()).strip()


@dataclass(frozen=True)
class Classification:
    constraint_type: str
    matched_markers: dict[str, tuple[str, ...]]
    reason: str


class ConstraintClassifier:
    """Human-reviewed deterministic rules; no API call occurs here."""

    def __init__(self, config: dict, use_kiwi: bool = True) -> None:
        self.default = config["default_when_facet_is_explicit"]
        self.rules = {
            kind: tuple(normalize(marker) for marker in markers)
            for kind, markers in config["rules"].items()
        }
        self.review_patterns = tuple(normalize(x) for x in config["review_patterns"])
        special = config["special_cases"]
        self.positive_double_negative = tuple(normalize(x) for x in special["positive_double_negative"])
        self.positive_double_negative_regexes = tuple(
            re.compile(pattern) for pattern in special.get("positive_double_negative_regexes", ())
        )
        self.numeric_range = re.compile(special["numeric_range_regex"])
        leading_preference_regex = special.get("leading_preference_regex")
        self.leading_preference = re.compile(leading_preference_regex) if leading_preference_regex else None
        polite_exclusion_regex = special.get("polite_exclusion_regex")
        self.polite_exclusion = re.compile(polite_exclusion_regex) if polite_exclusion_regex else None
        self.split_soft_punctuation = special.get("split_soft_punctuation", True)
        self.review_unmarked_explicit_facet = special.get("review_unmarked_explicit_facet", False)
        self.unmarked_direct_request_regexes = tuple(
            re.compile(pattern)
            for pattern in special.get("unmarked_direct_request_regexes", ())
        )
        self.ambiguous_modality_regexes = tuple(
            re.compile(pattern)
            for pattern in special.get("ambiguous_modality_regexes", ())
        )
        self.prefer_over_value_only_must = special.get("prefer_over_value_only_must", False)
        self.morphological_direct_request = special.get("morphological_direct_request", False)
        self.morphological_conditional_preference = special.get(
            "morphological_conditional_preference", False
        )
        self.semantic_exclusion_regexes = tuple(
            re.compile(pattern)
            for pattern in special.get("semantic_exclusion_regexes", ())
        )
        self.ranking_preference_regexes = tuple(
            re.compile(pattern)
            for pattern in special.get("ranking_preference_regexes", ())
        )
        self.non_final_action_guard = special.get("non_final_action_guard", False)
        self.local_relation_scope = special.get("local_relation_scope", False)
        self.reported_context_guard = special.get("reported_context_guard", False)
        self.final_commitment_guard = special.get("final_commitment_guard", False)
        self.facet_event_state_machine = special.get("facet_event_state_machine", False)
        self.predicate_span_event_ordering = special.get(
            "predicate_span_event_ordering", False
        )
        self.morphological_predicate_events = special.get(
            "morphological_predicate_events", False
        )
        self.predicate_argument_temporal_scope = special.get(
            "predicate_argument_temporal_scope", False
        )
        self.referential_complement_temporal_resolution = special.get(
            "referential_complement_temporal_resolution", False
        )
        self.typed_reference_event_roles = special.get(
            "typed_reference_event_roles", False
        )
        self.facet_predicate_ledger = special.get(
            "facet_predicate_ledger", False
        )
        self.facet_relation_events = special.get(
            "facet_relation_events", False
        )
        self.facet_set_algebra = special.get(
            "facet_set_algebra", False
        )
        self.predicate_frame_scoping = special.get(
            "predicate_frame_scoping", False
        )
        self.unified_predicate_frame_ledger = special.get(
            "unified_predicate_frame_ledger", False
        )
        self.proof_carrying_constraint_gate = special.get(
            "proof_carrying_constraint_gate", False
        )
        self.typed_filter_operation = special.get(
            "typed_filter_operation", False
        )
        self.speaker_scope_guard = special.get(
            "speaker_scope_guard", False
        )
        self.request_provenance_firewall = special.get(
            "request_provenance_firewall", False
        )
        self.explicit_filter_result_guard = special.get(
            "explicit_filter_result_guard", False
        )
        self.reported_segment_user_tail = special.get(
            "reported_segment_user_tail", False
        )
        self.strong_tail_commitment_guard = special.get(
            "strong_tail_commitment_guard", False
        )
        self.kiwi_quotation_segment_boundary = special.get(
            "kiwi_quotation_segment_boundary", False
        )
        self.minimal_complete_user_tail = special.get(
            "minimal_complete_user_tail", False
        )
        self.proof_ordered_tail_commitment = special.get(
            "proof_ordered_tail_commitment", False
        )
        self.typed_korean_ending_roles = special.get(
            "typed_korean_ending_roles", False
        )
        self.minimal_proven_user_span = special.get(
            "minimal_proven_user_span", False
        )
        self.typed_user_tail_modality = special.get(
            "typed_user_tail_modality", False
        )
        self.kiwi_reported_ending_role_v2 = special.get(
            "kiwi_reported_ending_role_v2", False
        )
        self.ep_ef_commitment_sequence = special.get(
            "ep_ef_commitment_sequence", False
        )
        self.explicit_user_tail_owner_boundary = special.get(
            "explicit_user_tail_owner_boundary", False
        )
        self.token_aligned_unresolved_modality = special.get(
            "token_aligned_unresolved_modality", False
        )
        self.ending_frame_question_scope = special.get(
            "ending_frame_question_scope", False
        )
        self.facet_strength_modifier = special.get(
            "facet_strength_modifier", False
        )
        self.occurrence_predicate_proof = special.get(
            "occurrence_predicate_proof", False
        )
        self.occurrence_bound_strength_modifier = special.get(
            "occurrence_bound_strength_modifier", False
        )
        self.typed_action_evidence = special.get(
            "typed_action_evidence", False
        )
        self.negative_preference_guard = special.get(
            "negative_preference_guard", False
        )
        self.nearest_occurrence_strength_binding = special.get(
            "nearest_occurrence_strength_binding", False
        )
        self.expanded_negative_preference_relation = special.get(
            "expanded_negative_preference_relation", False
        )
        self.coordinated_action_evidence = special.get(
            "coordinated_action_evidence", False
        )
        self.typed_inclusion_action_evidence = special.get(
            "typed_inclusion_action_evidence", False
        )
        self.negative_preference_state_carry = special.get(
            "negative_preference_state_carry", False
        )
        self.typed_negated_removal_final_action = special.get(
            "typed_negated_removal_final_action", False
        )
        self.expanded_negative_state_predicates = special.get(
            "expanded_negative_state_predicates", False
        )
        self.ambiguous_negated_removal_target_guard = special.get(
            "ambiguous_negated_removal_target_guard", False
        )
        self.negative_comparative_state_guard = special.get(
            "negative_comparative_state_guard", False
        )
        self.expanded_ambiguous_negative_target_forms = special.get(
            "expanded_ambiguous_negative_target_forms", False
        )
        self.explicit_final_hard_positive_termination = special.get(
            "explicit_final_hard_positive_termination", False
        )
        self.nominal_inclusion_prohibition = special.get(
            "nominal_inclusion_prohibition", False
        )
        self.nominal_inclusion_prohibition_frame = special.get(
            "nominal_inclusion_prohibition_frame", False
        )
        self.expanded_alternative_deliberation_action = special.get(
            "expanded_alternative_deliberation_action", False
        )
        self.input_channel_default_prefer_exact_value = special.get(
            "input_channel_default_prefer_exact_value", False
        )
        self.ignore_requirement_when_substitution_disabled = special.get(
            "ignore_requirement_when_substitution_disabled", False
        )
        self.diagnostic_review_non_blocking = special.get(
            "diagnostic_review_non_blocking", False
        )
        self.input_channel_default_prefer_short_composite = special.get(
            "input_channel_default_prefer_short_composite", False
        )
        self.input_channel_soft_preference_frame = special.get(
            "input_channel_soft_preference_frame", False
        )
        self.input_channel_alternative_preference_group = special.get(
            "input_channel_alternative_preference_group", False
        )
        self.input_channel_typed_nonblocking_states = special.get(
            "input_channel_typed_nonblocking_states", False
        )
        self.input_channel_lexical_aversion_frame = special.get(
            "input_channel_lexical_aversion_frame", False
        )
        self.input_channel_equivalent_taxonomy_codes = special.get(
            "input_channel_equivalent_taxonomy_codes", False
        )
        self.input_channel_conflict_effective_none = special.get(
            "input_channel_conflict_effective_none", False
        )
        self.positive_double_negative_priority_regexes = tuple(
            re.compile(pattern)
            for pattern in special.get("positive_double_negative_priority_regexes", ())
        )
        self.kiwi = None
        if use_kiwi:
            try:
                from kiwipiepy import Kiwi

                self.kiwi = Kiwi()
            except ImportError:
                pass

    @classmethod
    def from_path(cls, path: str | Path, use_kiwi: bool = True) -> "ConstraintClassifier":
        def load_config(config_path: Path, stack: tuple[Path, ...] = ()) -> dict:
            resolved = config_path.resolve()
            if resolved in stack:
                chain = " -> ".join(str(item) for item in (*stack, resolved))
                raise ValueError(f"Circular rule config inheritance: {chain}")
            config = json.loads(config_path.read_text(encoding="utf-8"))
            extends = config.pop("extends", None)
            if not extends:
                return config
            base = load_config(config_path.parent / extends, (*stack, resolved))
            for key, override in config.items():
                if isinstance(override, dict) and isinstance(base.get(key), dict):
                    base[key] = {**base[key], **override}
                else:
                    base[key] = override
            return base

        config = load_config(Path(path))
        return cls(config, use_kiwi=use_kiwi)

    def _marker_matches(self, value: str, marker: str) -> bool:
        # '만' is productive Korean grammar. Substring matching confuses 웬만하면/오랜만/그만.
        if marker == "만" and self.kiwi is not None:
            return any(token.form == "만" and token.tag == "JX" for token in self.kiwi.tokenize(value))
        return marker in value

    def is_positive_double_negative(self, text: str) -> bool:
        value = normalize(text)
        return any(pattern in value for pattern in self.positive_double_negative) or any(
            pattern.search(value) for pattern in self.positive_double_negative_regexes
        )

    def is_morphological_direct_request(self, text: str) -> bool:
        """Recognize a finalized selection action from Kiwi lemmas and endings.

        This deliberately requires a sentence-final ending and rejects speculative,
        cancelled, or unfinished actions.  It generalizes inflections such as
        `고를게요/고르겠습니다` without treating every bare facet as MUST.
        """
        if not self.morphological_direct_request or self.kiwi is None:
            return False
        tokens = self.kiwi.tokenize(text)
        forms = [token.form for token in tokens]
        blocking_forms = {
            "모르", "아니", "취소", "관두", "고민", "망설이", "보류", "미정",
            "아직", "못", "않",
        }
        if any(form in blocking_forms for form in forms):
            return False
        if any(
            forms[index] == "수" and index + 1 < len(forms) and forms[index + 1] == "도"
            for index in range(len(forms))
        ):
            return False
        if any("ㄹ까" in form or "을까" in form or form == "려고" for form in forms):
            return False

        action_nouns = {
            "구매", "주문", "결제", "선택", "결정", "추천", "부탁", "확정", "진행", "검색",
        }
        action_verbs = {"찾", "고르", "사", "보이"}
        has_action = any(
            token.form in action_nouns
            or token.form in action_verbs
            or token.form.startswith("찾")
            for token in tokens
        )
        if not has_action:
            return False
        final_endings = [token for token in tokens if token.tag == "EF"]
        if not final_endings:
            return False
        return True

    def is_non_final_selection_context(self, text: str) -> bool:
        """Detect a selection action cancelled or left unresolved anywhere in the sentence."""
        if not self.non_final_action_guard or self.kiwi is None:
            return False
        tokens = self.kiwi.tokenize(text)
        forms = [token.form for token in tokens]
        action_nouns = {
            "구매", "주문", "결제", "선택", "결정", "추천", "검색", "확정",
            "필터링", "필터",
        }
        has_action = any(
            form in action_nouns
            or form in {"찾", "고르", "사", "보이", "그만두", "걷어내", "걸러내"}
            or form.startswith("찾")
            for form in forms
        )
        if not has_action:
            return False
        blockers = {
            "모르", "아니", "취소", "관두", "그만두", "고민", "망설이", "보류", "미정",
            "아직", "못",
        }
        if any(form in blockers for form in forms):
            return True
        if any(
            forms[index] == "수" and index + 1 < len(forms) and forms[index + 1] == "도"
            for index in range(len(forms))
        ):
            return True
        return any(
            "ㄹ까" in form or "을까" in form or form in {"려다", "려고"}
            for form in forms
        )

    def is_morphological_conditional_preference(self, text: str) -> bool:
        """Treat an otherwise direct action under a conditional/wish as PREFER."""
        if not self.morphological_conditional_preference or self.kiwi is None:
            return False
        tokens = self.kiwi.tokenize(text)
        forms = [token.form for token in tokens]
        conditional_endings = {"면", "으면", "다면", "라면"}
        has_conditional = any(
            token.tag == "EC"
            and (token.form in conditional_endings or token.form.endswith("다면"))
            for token in tokens
        )
        blockers = {
            "모르", "아니", "취소", "관두", "그만두", "고민", "보류", "미정", "아직", "못",
        }
        return (
            has_conditional
            and any(token.tag == "EF" for token in tokens)
            and not any(form in blockers for form in forms)
        )

    def classify(self, text: str, matched_values: tuple[str, ...] = ()) -> Classification:
        value = normalize(text)
        # A taxonomy value can contain modality-looking words, e.g. '필수 지방산'.
        # Remove known facet spans before searching for constraint markers.
        marker_context = value
        for matched_value in sorted((normalize(x) for x in matched_values), key=len, reverse=True):
            if matched_value:
                # Keep adjacent particles attached to a natural Korean noun so Kiwi still
                # tags `만` as JX, while modality-looking words inside the facet disappear.
                marker_context = marker_context.replace(matched_value, "대상")
        matched = {
            kind: tuple(marker for marker in markers if self._marker_matches(marker_context, marker))
            for kind, markers in self.rules.items()
        }
        matched = {kind: markers for kind, markers in matched.items() if markers}
        if self.leading_preference is not None and self.leading_preference.search(marker_context):
            matched["PREFER"] = (*matched.get("PREFER", ()), "<LEADING_CONDITIONAL>")

        if any(pattern.search(marker_context) for pattern in self.positive_double_negative_priority_regexes):
            return Classification("MUST", matched, "PRIORITY_POSITIVE_DOUBLE_NEGATIVE")
        if any(pattern in marker_context for pattern in self.review_patterns):
            return Classification("REVIEW", matched, "KNOWN_AMBIGUOUS_PATTERN")
        if any(pattern.search(marker_context) for pattern in self.ambiguous_modality_regexes):
            return Classification("REVIEW", matched, "AMBIGUOUS_MODALITY_PATTERN")
        if self.numeric_range.search(marker_context):
            return Classification("REVIEW", matched, "RANGE_NEEDS_NORMALIZATION")
        if self.is_positive_double_negative(marker_context):
            return Classification("MUST", matched, "POSITIVE_DOUBLE_NEGATIVE_EXCEPTION")
        if any(pattern.search(marker_context) for pattern in self.semantic_exclusion_regexes):
            return Classification("EXCLUDE", matched, "SEMANTIC_EXCLUSION_PATTERN")
        if any(pattern.search(marker_context) for pattern in self.ranking_preference_regexes):
            return Classification("PREFER", matched, "RANKING_PREFERENCE_PATTERN")
        # In `무조건 빼`, `반드시 제외`, or `한 번만 ... 제외`, the MUST-like
        # token intensifies/narrows the rejected value; it does not make that value required.
        exclusion_scoped_must = {"반드시", "무조건", "꼭", "만"}
        if set(matched) == {"MUST", "EXCLUDE"} and set(matched["MUST"]) <= exclusion_scoped_must:
            return Classification("EXCLUDE", matched, "EXCLUDE_WITH_INTENSIFIER_OR_VALUE_SCOPE")
        if (
            set(matched) == {"PREFER", "EXCLUDE"}
            and self.polite_exclusion is not None
            and self.polite_exclusion.search(marker_context)
        ):
            return Classification("EXCLUDE", matched, "POLITE_EXCLUSION_REQUEST")
        if (
            self.prefer_over_value_only_must
            and set(matched) == {"MUST", "PREFER"}
            and set(matched["MUST"]) <= {"만"}
        ):
            return Classification("PREFER", matched, "PREFERENCE_WITH_VALUE_ONLY_SCOPE")
        if len(matched) > 1:
            return Classification("REVIEW", matched, "CONFLICTING_MARKERS_OR_MULTIPLE_CLAUSES")
        if matched:
            kind = next(iter(matched))
            return Classification(kind, matched, f"MATCHED_{kind}_MARKER")
        # A bare facet mention is still ambiguous, but an utterance that ends in a
        # concrete selection action is a direct order.  Regexes deliberately run
        # after ambiguity/conflict checks and are anchored by configuration so
        # trailing cancellation or hedging cannot become an automatic MUST.
        if matched_values and any(
            pattern.search(marker_context)
            for pattern in self.unmarked_direct_request_regexes
        ):
            return Classification("MUST", {}, "UNMARKED_DIRECT_SELECTION_REQUEST")
        if matched_values and self.is_morphological_conditional_preference(marker_context):
            return Classification("PREFER", {}, "MORPHOLOGICAL_CONDITIONAL_SELECTION")
        if matched_values and self.is_morphological_direct_request(marker_context):
            return Classification("MUST", {}, "MORPHOLOGICAL_DIRECT_SELECTION_REQUEST")
        if self.review_unmarked_explicit_facet:
            return Classification("REVIEW", {}, "UNMARKED_EXPLICIT_FACET")
        return Classification(self.default, {}, "EXPLICIT_FACET_DEFAULT")
