"""Application-facing service for typed demand-constraint parsing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .classifier import ConstraintClassifier
from .extractor import ConstraintExtractor, ExtractionResult
from .input_policy import (
    ConstraintInputPolicy,
    DemandRequirementResult,
    TaxonomyEquivalence,
)
from .taxonomy_matcher import TaxonomyFacetMatcher


@dataclass(frozen=True, slots=True)
class DemandConstraintParser:
    """Parse and normalize a demand's Korean requirement without a model call."""

    extractor: ConstraintExtractor
    input_policy: ConstraintInputPolicy

    @classmethod
    def from_taxonomy(
        cls,
        taxonomy: Mapping[str, Any],
        *,
        rules_path: str | Path,
        aliases_path: str | Path | None = None,
    ) -> DemandConstraintParser:
        matcher = TaxonomyFacetMatcher(taxonomy, aliases_path)
        classifier = ConstraintClassifier.from_path(rules_path)
        extractor = ConstraintExtractor(matcher, classifier)
        return cls(extractor, ConstraintInputPolicy(matcher, extractor))

    def parse(self, category_id: str, extra_requirement: str) -> ExtractionResult:
        """Return the frozen language-only result for evaluation compatibility."""

        return self.extractor.extract(category_id, extra_requirement)

    def interpret(
        self,
        category_id: str,
        extra_requirement: str,
        *,
        is_substitutable: bool,
    ) -> DemandRequirementResult:
        """Apply the v0.46 input contract before demand-board formation."""

        return self.input_policy.interpret(
            category_id,
            extra_requirement,
            is_substitutable=is_substitutable,
        )

    def canonicalize_value_code(
        self,
        category_id: str,
        facet_name: str,
        value_code: int,
    ) -> tuple[int, TaxonomyEquivalence | None]:
        return self.input_policy.canonicalize_value_code(
            category_id, facet_name, value_code
        )

    def taxonomy_equivalence_groups(self) -> tuple[TaxonomyEquivalence, ...]:
        return self.input_policy.taxonomy_equivalence_groups()


def _substitution_consent(value: Any) -> bool:
    """Parse a present consent field; blank means that consent was not given."""

    if value is None or (not isinstance(value, (list, tuple, dict)) and pd.isna(value)):
        return False
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().casefold()
    if normalized in {"true", "1", "1.0", "y", "yes", "동의"}:
        return True
    if normalized in {"false", "0", "0.0", "n", "no", "", "미동의"}:
        return False
    raise ValueError(f"invalid is_substitutable value: {value!r}")


def parse_demand_constraints(
    frame: pd.DataFrame,
    parser: DemandConstraintParser,
    catalog_category_map: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Append v0.46 demand-level requirement signals without changing labels.

    A legacy frame without ``is_substitutable`` is treated as opted in so the
    previous parser batch contract remains usable. When the column exists, a
    blank value means that substitution consent was not given.
    """

    rows: list[dict[str, Any]] = []
    has_substitution_consent = "is_substitutable" in frame.columns
    for _, demand in frame.iterrows():
        category_id = demand.get("category_id", "") or demand.get("kan_code", "")
        if not category_id and catalog_category_map:
            category_id = catalog_category_map.get(str(demand.get("catalog_id", "")), "")
        requirement = str(demand.get("extra_requirement", "") or "").strip()
        is_substitutable = (
            _substitution_consent(demand.get("is_substitutable"))
            if has_substitution_consent
            else True
        )
        result = parser.interpret(
            str(category_id or ""),
            requirement,
            is_substitutable=is_substitutable,
        )
        payload = result.to_dict()

        row = demand.to_dict()
        row.update({
            "category_id": str(category_id or ""),
            "constraint_status": payload["status"],
            "constraints": json.dumps(
                payload["constraints"], ensure_ascii=False, separators=(",", ":")
            ),
            "constraint_warnings": json.dumps(
                payload["warnings"], ensure_ascii=False, separators=(",", ":")
            ),
            "constraint_clauses": json.dumps(
                payload["clauses"], ensure_ascii=False, separators=(",", ":")
            ),
            "constraint_interpretation_method": payload["interpretation_method"],
            "effective_requirement_mode": payload["effective_requirement_mode"],
            "constraint_preference_groups": json.dumps(
                payload["preference_groups"],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "semantic_preferences": json.dumps(
                payload["semantic_preferences"],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "constraint_diagnostic_code": payload["diagnostic_code"],
            "taxonomy_equivalences": json.dumps(
                payload["taxonomy_equivalences"],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        })
        rows.append(row)
    return pd.DataFrame(rows)
